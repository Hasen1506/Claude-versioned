import type {
  ProductionUsageInput,
  Comparison, FinanceResult, TowerResult, WorkItem, WorkItemEntry, VersionDoc, VersionMeta, ActualsView, FirmResponse, RollResponse, Dataset, DemandRecord, ExampleInfo, ForecastModels, ForecastResult, InventoryResult, PlacementResponse, PromiseCommitResponse, PromiseResult, ScheduleResult, SopReleaseResponse, SopResult, NetworkView, PlanResult, ReleaseResponse, RuleInfo,
  PlanTrace, ScenarioInfo, ScenarioReport, SchemaError, ValidationResult, ScheduleApplyResponse, LevelPreview, ScheduleCatalogue, ScheduleComparison,
  PurchasingView, CreatePoResponse, PoActionResponse, PoAction, PoActionInput, RequisitionPick, PostAction, CountInput, UsageInput, StockType, SalesOrderChange, SalesOrderResponse,
  SalesView, SalesAction, SalesActionInput, SalesActionResponse,
  AuthConfig, Session, Me, CompanyMeta, CompanyDoc, SaveReport, Member, LogRow, MergeResult, HeldChange, FieldChangeRow, ResetLink,
  User,
  ApiKey, ImportJobs, JobInput, MessageRow, MailInput, MailRow, MailSetup, ReminderSettings,
} from "./types";
import { applyPatch, type Patch } from "../lib/patch";
import { done } from "../lib/guide";

/** Thrown when the engine rejects the dataset shape (HTTP 422). Carries field-level errors. */
export class SchemaRejected extends Error {
  constructor(public errors: SchemaError[]) {
    super(`${errors.length} schema error(s)`);
  }
}

/** Any other refusal: the engine's plain-words reason, its HTTP status and the whole answer (a save conflict says
 *  who saved and when). */
export class ApiError extends Error {
  constructor(message: string, public status: number, public body: Record<string, unknown>) {
    super(message);
  }
}

/** Who is asking and in which company: the store installs this (sign-in and the open server company). */
let authOf: () => { token: string | null; company: string | null } = () => ({ token: null, company: null });
export function setAuth(fn: typeof authOf) { authOf = fn; }

/** Why a change may not be made now (a viewer of the open company), or null: the store installs this, and every
 *  engine call that changes the company is refused before it is sent. */
let writeGuard: () => string | null = () => null;
export function setWriteGuard(fn: typeof writeGuard) { writeGuard = fn; }

/** This browser window, across reloads (a tab keeps its session storage): the server takes a save from the window
 *  whose own save it has not heard back about (a reload during a save) as that window's, not a colleague's. */
export const CLIENT_ID = (() => {
  try {
    let id = sessionStorage.getItem("scp.client");
    if (!id) { id = Math.random().toString(36).slice(2) + Date.now().toString(36); sessionStorage.setItem("scp.client", id); }
    return id;
  } catch {
    return Math.random().toString(36).slice(2);
  }
})();

/** This browser's own random key, kept across reloads and tabs: without an open company the server keeps this
 *  browser's plan versions and worklist under it, never in one space shared by everyone (CV-H06). */
export const BROWSER_KEY = (() => {
  const make = () => {
    const b = new Uint8Array(24);
    (globalThis.crypto ?? window.crypto).getRandomValues(b);
    return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  };
  try {
    let k = localStorage.getItem("scp.browser-key");
    if (!k || k.length < 16) { k = make(); localStorage.setItem("scp.browser-key", k); }
    return k;
  } catch {
    return make();
  }
})();

/** A large answer comes with its lists of records as rows (`{$cols, $rows}`, scp/api/working.py pack_rows): the field
 *  names are not repeated for each of a plan's hundreds of thousands of orders, so the answer is a third as long.
 *  Put them back as records. */
export function unpackRows(x: unknown): unknown {
  if (Array.isArray(x)) {
    for (let i = 0; i < x.length; i++) x[i] = unpackRows(x[i]);
    return x;
  }
  if (x !== null && typeof x === "object") {
    const o = x as Record<string, unknown>;
    const cols = o.$cols, rows = o.$rows;
    if (Array.isArray(cols) && Array.isArray(rows) && Object.keys(o).length === 2) {
      const n = cols.length;
      return (rows as unknown[][]).map((r) => {
        const rec: Record<string, unknown> = {};
        for (let i = 0; i < n; i++) rec[cols[i] as string] = unpackRows(r[i]);
        return rec;
      });
    }
    for (const k of Object.keys(o)) o[k] = unpackRows(o[k]);
    return o;
  }
  return x;
}

const API_ORIGIN = import.meta.env.VITE_API_ORIGIN || "";
const co = (id: string) => `/api/companies/${encodeURIComponent(id)}`;
/** Where the browser goes to sign in with the company's identity provider. */
export const SSO_START = `${API_ORIGIN}/api/auth/sso/start`;
/** A proof run answers only when it is done; on a small server the generated flow takes minutes. */
export const RUN_TIMEOUT_MS = 15 * 60_000;

/** Roadmap D: the browser's session lives in an HttpOnly cookie the page cannot read. The store keeps only a marker
 *  ("cookie:…", no secret) so it knows it is signed in; a real token there is one kept before the change, which
 *  `adopt` swaps for the cookie once. */
export const COOKIE_SESSION = "cookie:";
export const cookieSession = () => COOKIE_SESSION + Math.random().toString(36).slice(2) + Date.now().toString(36);
const isBearer = (t: string | null) => !!t && !t.startsWith(COOKIE_SESSION);
/** The double-submit token sent back on every change (header X-CSRF-Token = the scp_csrf cookie). */
let csrf: string | null = null;
export function setCsrf(t: string | null | undefined) { if (t) csrf = t; }
function csrfCookie(): string | null {
  try {
    const m = document.cookie.match(/(?:^|;\s*)scp_csrf=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  } catch { return null; }
}
async function csrfToken(): Promise<string | null> {
  const c = csrfCookie();            // same site: the cookie itself (always the current one)
  if (c) return (csrf = c);
  if (csrf) return csrf;
  try {                              // a client served from another site cannot read it: ask
    const r = await fetch(`${API_ORIGIN}/api/auth/csrf`, { credentials: CREDENTIALS });
    if (r.ok) csrf = ((await r.json()) as { csrf: string }).csrf;
  } catch { /* offline: the change is refused and says so */ }
  return csrf;
}
const CREDENTIALS: RequestCredentials = API_ORIGIN ? "include" : "same-origin";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/** `timeoutMs`: give up (and say so) when the engine has not answered by then. */
async function call<T>(path: string, init?: RequestInit, timeoutMs?: number): Promise<T> {
  const ctrl = timeoutMs ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), timeoutMs) : undefined;
  try {
    const who = authOf();
    const unsafe = UNSAFE.has((init?.method ?? "GET").toUpperCase());
    const xsrf = unsafe && who.token && !isBearer(who.token) ? await csrfToken() : null;
    const res = await fetch(`${API_ORIGIN}${path}`, {
      ...init,
      credentials: CREDENTIALS,
      signal: ctrl?.signal ?? init?.signal,
      headers: {
        "Content-Type": "application/json",
        ...(isBearer(who.token) ? { Authorization: `Bearer ${who.token}` } : {}),
        ...(xsrf ? { "X-CSRF-Token": xsrf } : {}),
        ...(who.company ? { "X-Company": who.company } : {}),
        "X-Client": CLIENT_ID,
        "X-Browser-Key": BROWSER_KEY,
        "X-Pack": "rows",
        ...(init?.headers ?? {}),
      },
    });
    if (res.status === 422) {
      const body = await res.json();
      // a refusal in plain words (an address the company does not know) rather than field errors
      if (typeof body.detail === "string") throw new ApiError(body.detail, 422, body);
      throw new SchemaRejected((body.detail ?? []) as SchemaError[]);
    }
    if (!res.ok) {
      let body: Record<string, unknown> = {};
      try {
        body = (await res.json()) as Record<string, unknown>;
      } catch {
        /* not JSON */
      }
      const detail = typeof body.detail === "string" ? body.detail : "";
      throw new ApiError(detail || `${path}: HTTP ${res.status}`, res.status, body);
    }
    let out: unknown;
    try {
      out = await res.json();
    } catch {
      throw new Error("the engine's answer did not arrive whole: it may be larger than this browser can read");
    }
    return (res.headers.get("X-Rows") ? unpackRows(out) : out) as T;
  } catch (e) {
    if (ctrl?.signal.aborted) {
      throw new Error(`no answer after ${Math.round(timeoutMs! / 60_000)} minutes: the engine may be overloaded or restarting`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/** What the engine plans: the dataset without the unfinished records the data check set aside, and a way to put
 *  them back into a dataset the engine returns (a released forecast, committed promises, …), so an engine write
 *  never loses a record the planner is still filling in; `only` puts them back into those lists alone. The store
 *  installs this. */
export interface PlanningView { clean: Dataset; restore: (next: Dataset, only?: string[]) => Dataset }
let planningViewOf: (ds: Dataset) => PlanningView = (ds) => ({ clean: ds, restore: (x) => x });
export function setPlanningView(fn: (ds: Dataset) => PlanningView) { planningViewOf = fn; }
const clean = (ds: Dataset) => planningViewOf(ds).clean;

/** The company kept on the server that a working copy stands for: the save it was made from and what changed since
 *  (none: nothing). Sent in place of the company (Phase S): the server reads its own copy, so a planning call is a
 *  few hundred bytes instead of the whole company, and sets aside unfinished records itself. */
export interface DataRef { revision: number; patch: Patch | null }
let refOf: (ds: Dataset) => DataRef | null = () => null;
let refUnfit: () => void = () => {};
/** The store installs `of` (a reference for its working copy, else null) and `unfit` (the server's copy did not
 *  match: send the company whole until the next save). */
export function setDataRef(of: typeof refOf, unfit: () => void) { refOf = of; refUnfit = unfit; }

/** `ds` as sent: a reference to the server's copy when there is one, else whole (`planning`: without the records
 *  the data check set aside). */
function sent(ds: Dataset, planning: boolean): { data: unknown; ref: boolean } {
  const r = refOf(ds);
  if (r) return { data: { $ref: r.patch ? { revision: r.revision, patch: r.patch } : { revision: r.revision } }, ref: true };
  return { data: planning ? clean(ds) : ds, ref: false };
}

/** POST `body(ds as sent)`; when the server's copy did not fit the reference, again with the company whole. */
async function send<T>(path: string, ds: Dataset, planning: boolean, body: (data: unknown) => unknown): Promise<T> {
  const s = sent(ds, planning);
  try {
    return await call<T>(path, { method: "POST", body: JSON.stringify(body(s.data)) });
  } catch (e) {
    if (!(s.ref && e instanceof ApiError && e.status === 409 && e.body.patch === "unfit")) throw e;
    refUnfit();
    return call<T>(path, { method: "POST", body: JSON.stringify(body(planning ? clean(ds) : ds)) });
  }
}

const post = <T>(path: string, ds: Dataset) => send<T>(path, ds, false, (d) => d);
const planPost = <T>(path: string, ds: Dataset) => send<T>(path, ds, true, (d) => d);

/** An engine answer that changed the company: the company whole, or what changed when it was sent by reference. */
type Changed<T> = Omit<T, "dataset" | "patch"> & { dataset: Dataset };
type ChangeAnswer = { dataset?: Dataset | null; patch?: Record<string, unknown> | null };
function changed<T extends ChangeAnswer>(before: Dataset, out: T): Changed<T> {
  const v = planningViewOf(before);
  const { patch, dataset, ...rest } = out;
  if (patch) {
    const p = patch as unknown as Patch;
    // the records set aside stay in the working copy, except in a list the answer sends whole
    return { ...rest, dataset: v.restore(applyPatch(before, p), Object.keys(p.set ?? {})) } as Changed<T>;
  }
  return { ...rest, dataset: v.restore(dataset as Dataset) } as Changed<T>;
}

/** POST `{ dataset, ...extra }` for a change, and put the set-aside records back into the dataset that comes back. */
async function write<T extends ChangeAnswer>(path: string, dataset: Dataset, extra: Record<string, unknown> = {}): Promise<Changed<T>> {
  const refused = writeGuard();
  if (refused) throw new Error(refused);
  return changed(dataset, await send<T>(path, dataset, true, (d) => ({ dataset: d, ...extra })));
}
const withDataset = <T>(path: string, dataset: Dataset, extra: Record<string, unknown> = {}) =>
  send<T>(path, dataset, true, (d) => ({ dataset: d, ...extra }));

/** What a posting may say besides its action (scp/api/app.py PostRequest). */
export interface PostExtra {
  order?: string; qty?: number | null; date?: string; final?: boolean; usage?: UsageInput[] | null; counts?: CountInput[];
  note?: string; ship_from?: string | null; batch?: string | null; expires_on?: string | null; supplier_batch?: string | null;
  serials?: string[] | null; stock_type?: StockType | null; to_type?: StockType | null; location?: string | null;
  product?: string | null; movement?: string | null; doc?: string | null; nodes?: { location: string; product: string }[] | null;
  block?: boolean; uncounted_zero?: boolean;
}

/** Sign-in calls ask for the session in the HttpOnly cookie (roadmap D) and keep the CSRF token they answer with. */
const COOKIE_PLEASE = { "X-SCP-Session": "cookie" };
async function withCsrf(p: Promise<Session>): Promise<Session> {
  const s = await p;
  setCsrf((s as Session & { csrf?: string | null }).csrf);
  return s;
}

export const api = {
  productionUsage: (dataset: Dataset, order: string, qty: number) =>
    withDataset<ProductionUsageInput[]>("/api/actuals/production-usage", dataset, { order, qty }),
  examples: () => call<ExampleInfo[]>("/api/examples"),
  example: (name: string) => call<Dataset>(`/api/examples/${encodeURIComponent(name)}`),
  schema: () => call<JsonSchema>("/api/schema"),
  rules: () => call<RuleInfo[]>("/api/rules"),
  validate: (ds: Dataset) => post<ValidationResult>("/api/validate", ds),
  network: (ds: Dataset) => post<NetworkView>("/api/network", ds),
  plan: (ds: Dataset) => planPost<PlanResult>("/api/plan?pegging=false", ds),
  /** Part of the plan's requirements and pegging: an order's chain (what it serves and depends on), or one product's
   *  at one place. */
  planTrace: (ds: Dataset, what: { order: string } | { location: string; product: string }) =>
    withDataset<PlanTrace>("/api/plan/trace", ds, what),
  sop: (ds: Dataset) => planPost<SopResult>("/api/sop", ds),
  sopRelease: async (ds: Dataset) => {
    const refused = writeGuard();
    if (refused) throw new Error(refused);
    return changed(ds, await planPost<SopReleaseResponse>("/api/sop/release", ds));
  },
  inventory: (ds: Dataset) => planPost<InventoryResult>("/api/inventory", ds),
  /** Write the multi-echelon recommendation as fixed policies; keys "location|product", null = every stage that differs. */
  applyPlacement: (dataset: Dataset, keys: string[] | null) =>
    write<PlacementResponse>("/api/inventory/apply", dataset, { keys }),
  promise: (ds: Dataset) => planPost<PromiseResult>("/api/promise", ds),
  bop: (ds: Dataset) => planPost<PromiseResult>("/api/promise/bop", ds),
  promiseCheck: (dataset: Dataset, order: DemandRecord) =>
    withDataset<PromiseResult>("/api/promise/check", dataset, { order }).then(done("check")),
  /** The lines of one order checked together, each after the ones before it (N119). */
  promiseCheckLines: (dataset: Dataset, lines: DemandRecord[]) =>
    withDataset<PromiseResult>("/api/promise/check", dataset, { lines }).then(done("check")),
  promiseCommit: (dataset: Dataset, mode: "entry" | "bop") =>
    write<PromiseCommitResponse>("/api/promise/commit", dataset, { mode }),
  /** Detailed schedule; `sequence` (resource → operation keys) fixes the order on those resources and puts a step
   *  listed on an alternative machine there; `hold` = not-before times (clock hours) per order. */
  schedule: (dataset: Dataset, sequence?: Record<string, string[]>, hold?: Record<string, number>) =>
    withDataset<ScheduleResult>("/api/schedule", dataset, { sequence: sequence ?? null, hold: hold ?? null }),
  /** Fix the schedule's dates on its orders (planned ones become dated production orders); `ids` = only these.
   *  Send the shown schedule's sequences and holds: the optimiser may not give the same answer twice. */
  applySchedule: (dataset: Dataset, sequence?: Record<string, string[]>, ids?: string[], hold?: Record<string, number>) =>
    write<ScheduleApplyResponse>("/api/schedule/apply", dataset, { sequence: sequence ?? null, ids: ids ?? null, hold: hold ?? null }),
  /** The scheduling heuristics and profiles (what each does, when to use it). */
  scheduleCatalogue: () => call<ScheduleCatalogue>("/api/schedule/catalogue"),
  /** Every start rule, the local search and the optimiser on the same orders and weights. */
  compareSchedules: (ds: Dataset) => planPost<ScheduleComparison>("/api/schedule/compare", ds),
  /** What planning within machine capacity would move (runs the plan both ways; changes nothing). */
  level: (ds: Dataset) => planPost<LevelPreview>("/api/capacity/level", ds),
  actuals: (dataset: Dataset, asOf?: string) =>
    withDataset<ActualsView>("/api/actuals", dataset, { as_of: asOf ?? null }),
  roll: (dataset: Dataset, asOf: string) =>
    write<RollResponse>("/api/actuals/roll", dataset, { as_of: asOf }),
  /** Post what happened: ship a transfer, receive an order (a production order issues its parts), or count stock. */
  postActual: (dataset: Dataset, action: PostAction, extra: PostExtra = {}) =>
    write<PoActionResponse>("/api/actuals/post", dataset, { action, order: extra.order ?? null, qty: extra.qty ?? null,
      date: extra.date ?? null, final: extra.final ?? false, usage: extra.usage ?? null, counts: extra.counts ?? null, note: extra.note ?? "",
      ship_from: extra.ship_from ?? null, batch: extra.batch ?? null, expires_on: extra.expires_on ?? null,
      supplier_batch: extra.supplier_batch ?? null, serials: extra.serials ?? null, stock_type: extra.stock_type ?? null,
      to_type: extra.to_type ?? null, location: extra.location ?? null, product: extra.product ?? null, movement: extra.movement ?? null,
      doc: extra.doc ?? null, nodes: extra.nodes ?? null, block: extra.block ?? true, uncounted_zero: extra.uncounted_zero ?? false }),
  /** Take a checked customer order (with its promise), change one (promised again), or cancel what is still open. */
  salesOrder: (dataset: Dataset, action: "accept" | "change" | "cancel",
    extra: { order?: DemandRecord; id?: string; changes?: Partial<SalesOrderChange>; date?: string; reason?: string }) =>
    write<SalesOrderResponse>("/api/orders/sales", dataset, { action, order: extra.order ?? null, id: extra.id ?? null,
      changes: extra.changes ?? null, date: extra.date ?? null, reason: extra.reason ?? "" }),
  /** Every sales order, quotation, delivery, invoice and return; what is due to deliver and bill; customers' credit. */
  sales: (ds: Dataset) => planPost<SalesView>("/api/sales", ds),
  /** One order-to-cash step: take an order, quote, deliver, invoice, record a payment, take a return back. */
  salesAct: (dataset: Dataset, action: SalesAction, extra: SalesActionInput = {}) =>
    write<SalesActionResponse>("/api/sales/act", dataset, { action, ...extra }),
  /** Requisitions from the supply plan, every purchase order and the supplier scorecard. */
  purchasing: (ds: Dataset) => planPost<PurchasingView>("/api/purchasing", ds),
  /** Turn requisitions into purchase orders (`lines` = which, on which source; none = everything due now). */
  createPurchaseOrders: (dataset: Dataset, lines?: RequisitionPick[], orderDate?: string) =>
    write<CreatePoResponse>("/api/purchasing/create", dataset, { lines: lines ?? null, order_date: orderDate ?? null }),
  /** A purchase order no requisition asked for: one line on a purchasing source (null date = as soon as it can come). */
  oneOffPo: (dataset: Dataset, sourceId: string, qty: number, dueDate?: string | null) =>
    write<CreatePoResponse>("/api/purchasing/one-off", dataset, { source_id: sourceId, qty, due_date: dueDate || null }),
  /** An action on a purchase order (approve, send, confirm, receive, change, cancel), a scheduling agreement, a
   * supplier invoice (enter, release, pay, cancel) or a return to the supplier. */
  poAction: (dataset: Dataset, action: PoAction, po: string, extra: PoActionInput = {}) =>
    write<PoActionResponse>("/api/purchasing/act", dataset, { action, po, ...extra, lines: extra.lines ?? null,
      date: extra.date ?? null, reference: extra.reference ?? "", note: extra.note ?? "" }),
  /** Firm planned orders into receipts: `ids`, or everything starting within the firm zone; `send` sends the
   * purchase orders it makes at once. */
  firm: (dataset: Dataset, ids?: string[], withinDays?: number, starts?: Record<string, string>, send = false) =>
    write<FirmResponse>("/api/orders/firm", dataset, { ids: ids ?? null, within_days: withinDays ?? null, starts: starts ?? null, send }),
  // ---- sign-in and companies kept on the server (Phase I)
  authConfig: () => call<AuthConfig>("/api/auth/config"),
  signUp: (email: string, name: string, password: string) =>
    withCsrf(call<Session>("/api/auth/signup", { method: "POST", headers: COOKIE_PLEASE, body: JSON.stringify({ email, name, password }) })),
  signIn: (email: string, password: string) =>
    withCsrf(call<Session>("/api/auth/signin", { method: "POST", headers: COOKIE_PLEASE, body: JSON.stringify({ email, password }) })),
  signOut: () => call<{ ok: boolean }>("/api/auth/signout", { method: "POST" }),
  me: () => call<Me>("/api/auth/me"),
  changePassword: (old: string, next: string) =>
    call<{ ok: boolean }>("/api/auth/password", { method: "POST", body: JSON.stringify({ old, new: next }) }),
  companies: () => call<CompanyMeta[]>("/api/companies"),
  createCompany: (dataset: Dataset, note = "") =>
    call<CompanyMeta>("/api/companies", { method: "POST", body: JSON.stringify({ dataset, note }) }),
  company: (id: string) => call<CompanyDoc>(`/api/companies/${encodeURIComponent(id)}`),
  /** Save the working copy, whole (`dataset`) or as what changed since `baseRevision` (`patch`). */
  saveCompany: (id: string, what: { dataset: Dataset } | { patch: Patch }, baseRevision: number, note = "") =>
    call<SaveReport>(`/api/companies/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ ...what, base_revision: baseRevision, note }) }),
  /** Merge the working copy (whole, or a patch on `baseRevision`) with the saves made since. `base` defaults to that
   *  revision as the server keeps it; `choose` says whose version to keep per clash; `preview` saves nothing. */
  mergeCompany: (id: string, o: { base?: Dataset; dataset?: Dataset; patch?: Patch; baseRevision: number; cleanOnly?: boolean;
    choose?: Record<string, "mine" | "theirs">; preview?: boolean }) =>
    call<MergeResult>(`/api/companies/${encodeURIComponent(id)}/merge`, { method: "POST",
      body: JSON.stringify({ base: o.base, dataset: o.dataset, patch: o.patch, base_revision: o.baseRevision, clean_only: !!o.cleanOnly,
        choose: o.choose ?? {}, preview: !!o.preview }) }),
  deleteCompany: (id: string) => call<{ ok: boolean }>(`/api/companies/${encodeURIComponent(id)}`, { method: "DELETE" }),
  companyHistory: (id: string, before?: number) =>
    call<LogRow[]>(`/api/companies/${encodeURIComponent(id)}/history${before ? `?before=${before}` : ""}`),
  companyRevision: (id: string, rev: number) => call<Dataset>(`/api/companies/${encodeURIComponent(id)}/revisions/${rev}`),
  restoreCompany: (id: string, revision: number, baseRevision: number) =>
    call<SaveReport>(`/api/companies/${encodeURIComponent(id)}/restore`, { method: "POST", body: JSON.stringify({ revision, base_revision: baseRevision }) }),
  members: (id: string) => call<Member[]>(`/api/companies/${encodeURIComponent(id)}/members`),
  setMember: (id: string, email: string, role: string, limits?: { places?: string[]; families?: string[] }) =>
    call<Member[]>(`/api/companies/${encodeURIComponent(id)}/members`, { method: "POST", body: JSON.stringify({ email, role, ...limits }) }),
  /** A link for a planner or viewer to set a new password (an owner hands it over). */
  memberResetLink: (id: string, email: string) =>
    call<ResetLink>(`/api/companies/${encodeURIComponent(id)}/members/${encodeURIComponent(email)}/reset`, { method: "POST" }),
  setApproval: (id: string, approval: boolean) =>
    call<CompanyMeta>(`/api/companies/${encodeURIComponent(id)}/approval`, { method: "PUT", body: JSON.stringify({ approval }) }),
  heldChanges: (id: string, status = "pending") => call<HeldChange[]>(`/api/companies/${encodeURIComponent(id)}/held?status=${status}`),
  decideHeld: (id: string, rid: number, decision: "approve" | "reject" | "withdraw", note = "") =>
    call<SaveReport>(`/api/companies/${encodeURIComponent(id)}/held/${rid}`, { method: "POST", body: JSON.stringify({ decision, note }) }),
  /** Change documents: every field changed, newest first; `q` finds records by (part of) their key. */
  changes: (id: string, q = "", list = "", before?: number) =>
    call<FieldChangeRow[]>(`/api/companies/${encodeURIComponent(id)}/changes?q=${encodeURIComponent(q)}&list=${encodeURIComponent(list)}${before ? `&before=${before}` : ""}`),
  resetRequest: (email: string) => call<{ ok: boolean; mail: boolean }>("/api/auth/reset/request", { method: "POST", body: JSON.stringify({ email }) }),
  resetPassword: (token: string, password: string) => withCsrf(call<Session>("/api/auth/reset", { method: "POST", headers: COOKIE_PLEASE, body: JSON.stringify({ token, password }) })),
  /** Once: swap a session token this browser kept in its storage (before roadmap D) for the HttpOnly cookie. */
  adopt: (token: string) => withCsrf(call<Session>("/api/auth/adopt", { method: "POST", headers: { ...COOKIE_PLEASE, Authorization: `Bearer ${token}` } })),
  /** Join a company invited to: with the invitation's link, or by its id once the address is verified (CV-C01). */
  acceptInvite: (o: { token?: string; company?: string }) =>
    call<CompanyMeta>("/api/auth/invites/accept", { method: "POST", body: JSON.stringify({ token: o.token ?? "", company: o.company ?? "" }) }),
  /** Mail a link that confirms the account's address (mail: false when the server sends none). */
  requestEmailCheck: () => call<{ ok: boolean; mail: boolean }>("/api/auth/email/request", { method: "POST" }),
  verifyEmail: (token: string) => call<User>("/api/auth/email/verify", { method: "POST", body: JSON.stringify({ token }) }),
  /** Begin binding the company's sign-on to the signed-in account: the address to open. */
  ssoLink: () => call<{ url: string }>("/api/auth/sso/link", { method: "POST" }),
  removeMember: (id: string, email: string) =>
    call<Member[]>(`/api/companies/${encodeURIComponent(id)}/members/${encodeURIComponent(email)}`, { method: "DELETE" }),

  // Phase Q: keys for other systems, scheduled imports, the message log, e-mail from the server
  keys: (id: string) => call<ApiKey[]>(`${co(id)}/keys`),
  makeKey: (id: string, name: string, role: "planner" | "viewer") =>
    call<ApiKey>(`${co(id)}/keys`, { method: "POST", body: JSON.stringify({ name, role }) }),
  revokeKey: (id: string, kid: string) => call<ApiKey[]>(`${co(id)}/keys/${encodeURIComponent(kid)}`, { method: "DELETE" }),
  imports: (id: string) => call<ImportJobs>(`${co(id)}/imports`),
  saveImport: (id: string, job: JobInput, jid?: string) =>
    call<ImportJobs>(`${co(id)}/imports${jid ? `/${encodeURIComponent(jid)}` : ""}`, { method: jid ? "PUT" : "POST", body: JSON.stringify(job) }),
  removeImport: (id: string, jid: string) => call<ImportJobs>(`${co(id)}/imports/${encodeURIComponent(jid)}`, { method: "DELETE" }),
  runImport: (id: string, jid: string) => call<MessageRow[]>(`${co(id)}/imports/${encodeURIComponent(jid)}/run`, { method: "POST" }, RUN_TIMEOUT_MS),
  messages: (id: string, o: { kind?: string; status?: string; before?: number } = {}) =>
    call<MessageRow[]>(`${co(id)}/messages?kind=${encodeURIComponent(o.kind ?? "")}&status=${encodeURIComponent(o.status ?? "")}${o.before ? `&before=${o.before}` : ""}`),
  mailSetup: (id: string) => call<MailSetup>(`${co(id)}/mail`),
  sendMail: (id: string, m: MailInput) => call<MailRow>(`${co(id)}/mail`, { method: "POST", body: JSON.stringify(m) }),
  mailSent: (id: string, ref = "") => call<MailRow[]>(`${co(id)}/mail/sent?ref=${encodeURIComponent(ref)}`),
  setReminders: (id: string, r: ReminderSettings) => call<MailSetup>(`${co(id)}/mail/reminders`, { method: "PUT", body: JSON.stringify(r) }),
  remindNow: (id: string) => call<MailRow[]>(`${co(id)}/mail/reminders/send`, { method: "POST" }),

  versions: () => call<VersionMeta[]>("/api/versions"),
  version: (id: string) => call<VersionDoc>(`/api/versions/${encodeURIComponent(id)}`),
  saveBase: (dataset: Dataset, name: string, note = "") =>
    call<VersionMeta>("/api/versions", { method: "POST", body: JSON.stringify({ dataset, name, note }) }),
  saveVersion: (id: string, dataset: Dataset) =>
    call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(dataset) }),
  branch: (id: string, name: string, note = "") =>
    call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}/branch`, { method: "POST", body: JSON.stringify({ name, note }) }),
  discard: (id: string) => call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}/discard`, { method: "POST" }),
  promote: (id: string, name?: string) =>
    call<VersionMeta>(`/api/versions/${encodeURIComponent(id)}/promote`, { method: "POST", body: JSON.stringify({ name: name ?? null }) }),
  compareVersions: (a: string, b: string) => call<Comparison>(`/api/versions/${encodeURIComponent(a)}/compare/${encodeURIComponent(b)}`).then(done("whatif")),
  compare: (a: Dataset, b: Dataset, labelA: string, labelB: string) =>
    call<Comparison>("/api/compare", { method: "POST", body: JSON.stringify({ a: clean(a), b: clean(b), label_a: labelA, label_b: labelB }) }).then(done("whatif")),
  finance: (ds: Dataset) => planPost<FinanceResult>("/api/finance", ds),
  tower: (ds: Dataset) => planPost<TowerResult>("/api/tower", ds),
  /** Assign (owner "" = back to the rules), acknowledge / resolve / reopen, or annotate a worklist item. */
  towerItem: (id: string, patch: { owner?: string; status?: "open" | "acknowledged" | "resolved"; note?: string; sla_days?: Record<string, number> }) =>
    call<WorkItem>(`/api/tower/items/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify(patch) }),
  towerHistory: (id: string) => call<WorkItemEntry[]>(`/api/tower/items/${encodeURIComponent(id)}/history`),
  forecastModels: () => call<ForecastModels>("/api/forecast/models"),
  forecast: (ds: Dataset) => planPost<ForecastResult>("/api/forecast", ds),
  release: (dataset: Dataset, keys?: string[]) =>
    write<ReleaseResponse>("/api/forecast/release", dataset, { keys: keys ?? null }),
  /** Proof: end-to-end scenarios with hand-derived answers, run against an isolated in-memory store. */
  scenarios: () => call<ScenarioInfo[]>("/api/scenarios"),
  scenarioDataset: (id: string) => call<Dataset>(`/api/scenarios/${encodeURIComponent(id)}/dataset`),
  runScenario: (id: string) => call<ScenarioReport>(`/api/scenarios/${encodeURIComponent(id)}/run`, { method: "POST" }, RUN_TIMEOUT_MS),
};

// Minimal JSON-schema shape used by the form generator.
export interface JsonSchemaNode {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
  $ref?: string;
  anyOf?: JsonSchemaNode[];
  items?: JsonSchemaNode;
  properties?: Record<string, JsonSchemaNode>;
  required?: string[];
  additionalProperties?: JsonSchemaNode | boolean;
  format?: string;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  "x-unit"?: string;
  "x-ref"?: string;
  "x-multiline"?: boolean;
}

export interface JsonSchema extends JsonSchemaNode {
  $defs: Record<string, JsonSchemaNode>;
}
