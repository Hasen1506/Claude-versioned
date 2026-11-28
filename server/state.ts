import crypto from "node:crypto";
import type {
  AuthConfig,
  CompanyDoc,
  CompanyMeta,
  Cycle,
  CycleSummary,
  Dataset,
  Me,
  Session,
  User,
  VersionDoc,
  VersionMeta,
} from "./types.ts";

interface StoredUser extends User {
  passwordHash: string;
  salt: string;
}

interface StoredCompany {
  id: string;
  name: string;
  dataset: Dataset;
  revision: number;
  created_at: string;
  updated_at: string;
  updated_by: string;
  members: Map<string, { role: "owner" | "planner" | "viewer"; email: string; name: string }>;
  revisions: Map<number, { dataset: Dataset; at: string; by: string; note: string }>;
  history: { id: number; at: string; by: string; kind: string; summary: string; revision: number | null }[];
}

interface StoredVersion {
  meta: VersionMeta;
  dataset: Dataset;
  log: VersionDoc["log"];
}

const usersByEmail = new Map<string, StoredUser>();
const sessions = new Map<string, { email: string; csrf: string; expiresAt: string }>();
const companies = new Map<string, StoredCompany>();
const versions = new Map<string, StoredVersion>();
const cycles = new Map<string, Cycle>();
const workItemOverrides = new Map<string, { owner?: string; status?: "open" | "acknowledged" | "resolved"; note?: string }>();

function hashPassword(password: string, salt: string): string {
  return crypto.scryptSync(password, salt, 32).toString("hex");
}

function makeId(prefix: string): string {
  return `${prefix}-${crypto.randomBytes(6).toString("hex")}`;
}

export function sha256Of(obj: unknown): string {
  return crypto.createHash("sha256").update(JSON.stringify(obj)).digest("hex");
}

export function getAuthConfig(): AuthConfig {
  const signup = (process.env.SCP_SIGNUP as "open" | "invite" | "closed") || "open";
  const requireSignin = ["1", "true", "yes", "on"].includes((process.env.SCP_REQUIRE_SIGNIN || "").toLowerCase());
  return {
    signup,
    require_signin: requireSignin,
    first_account: usersByEmail.size === 0,
    mail: false,
    sso: null,
    password_min: 12,
  };
}

export function createCsrfToken(): string {
  return crypto.randomBytes(16).toString("hex");
}

export function signUp(email: string, name: string, password: string): { session: Session; token: string } {
  const norm = email.trim().toLowerCase();
  if (!norm || !norm.includes("@")) throw new Error("Enter a valid e-mail address.");
  if (password.length < 12) throw new Error("Password must be at least 12 characters.");
  if (usersByEmail.has(norm)) throw new Error("An account with that e-mail already exists.");
  const salt = crypto.randomBytes(16).toString("hex");
  const user: StoredUser = {
    id: makeId("usr"),
    email: norm,
    name: name.trim() || norm.split("@")[0],
    verified: true,
    two_step: false,
    passwordHash: hashPassword(password, salt),
    salt,
  };
  usersByEmail.set(norm, user);
  return createSessionFor(user);
}

export function signIn(email: string, password: string): { session: Session; token: string } {
  const norm = email.trim().toLowerCase();
  const user = usersByEmail.get(norm);
  if (!user) throw new Error("Wrong e-mail or password.");
  const actual = hashPassword(password, user.salt);
  if (!crypto.timingSafeEqual(Buffer.from(actual, "hex"), Buffer.from(user.passwordHash, "hex"))) {
    throw new Error("Wrong e-mail or password.");
  }
  return createSessionFor(user);
}

function createSessionFor(user: StoredUser): { session: Session; token: string } {
  const token = crypto.randomBytes(24).toString("hex");
  const csrf = createCsrfToken();
  const expiresAt = new Date(Date.now() + 30 * 86_400_000).toISOString();
  sessions.set(token, { email: user.email, csrf, expiresAt });
  const pubUser: User = {
    id: user.id,
    email: user.email,
    name: user.name,
    verified: user.verified,
    two_step: user.two_step,
  };
  return {
    token,
    session: {
      token: "",
      user: pubUser,
      expires_at: expiresAt,
      csrf,
      second_step: "",
    },
  };
}

export function getUserFromToken(token: string | null): User | null {
  if (!token) return null;
  const sess = sessions.get(token);
  if (!sess) return null;
  const u = usersByEmail.get(sess.email);
  if (!u) return null;
  return {
    id: u.id,
    email: u.email,
    name: u.name,
    verified: u.verified,
    two_step: u.two_step,
  };
}

export function signOut(token: string | null): void {
  if (token) sessions.delete(token);
}

export function getMe(token: string | null): Me | null {
  const user = getUserFromToken(token);
  if (!user) return null;
  return {
    user,
    companies: listCompanies(user.email),
    invites: [],
  };
}

function companyMeta(c: StoredCompany, email: string): CompanyMeta {
  const member = c.members.get(email);
  const size = Buffer.byteLength(JSON.stringify(c.dataset), "utf-8");
  return {
    id: c.id,
    name: c.name,
    role: member?.role ?? "owner",
    revision: c.revision,
    created_at: c.created_at,
    updated_at: c.updated_at,
    updated_by: c.updated_by,
    size,
    approval: false,
    pending: 0,
    places: [],
    families: [],
    two_step: false,
    needs_two_step: false,
  };
}

export function listCompanies(email: string): CompanyMeta[] {
  const out: CompanyMeta[] = [];
  for (const c of companies.values()) {
    if (c.members.has(email)) out.push(companyMeta(c, email));
  }
  return out;
}

export function createCompany(user: User, dataset: Dataset, note = "created"): CompanyMeta {
  const id = makeId("co");
  const now = new Date().toISOString();
  const c: StoredCompany = {
    id,
    name: dataset.settings?.company_name || "Untitled company",
    dataset,
    revision: 1,
    created_at: now,
    updated_at: now,
    updated_by: user.name,
    members: new Map([[user.email, { role: "owner", email: user.email, name: user.name }]]),
    revisions: new Map([[1, { dataset, at: now, by: user.name, note }]]),
    history: [{ id: 1, at: now, by: user.name, kind: "create", summary: note || "created", revision: 1 }],
  };
  companies.set(id, c);
  return companyMeta(c, user.email);
}

export function getCompanyDoc(id: string, email: string): CompanyDoc | null {
  const c = companies.get(id);
  if (!c || !c.members.has(email)) return null;
  return {
    meta: companyMeta(c, email),
    dataset: c.dataset as unknown as Record<string, unknown>,
  };
}

export function saveCompany(id: string, user: User, dataset: Dataset, baseRevision: number, note = "") {
  const c = companies.get(id);
  if (!c || !c.members.has(user.email)) return null;
  if (baseRevision !== c.revision) {
    return { conflict: true as const, revision: c.revision, updated_by: c.updated_by, updated_at: c.updated_at };
  }
  const now = new Date().toISOString();
  c.revision += 1;
  c.dataset = dataset;
  c.name = dataset.settings?.company_name || c.name;
  c.updated_at = now;
  c.updated_by = user.name;
  c.revisions.set(c.revision, { dataset, at: now, by: user.name, note });
  c.history.unshift({ id: c.history.length + 1, at: now, by: user.name, kind: "save", summary: note || "saved", revision: c.revision });
  return {
    conflict: false as const,
    report: {
      meta: companyMeta(c, user.email),
      saved: true,
      summary: note || "Saved",
      own: true,
      held: null,
      dataset: null,
    },
  };
}

export function deleteCompany(id: string, email: string): boolean {
  const c = companies.get(id);
  if (!c || c.members.get(email)?.role !== "owner") return false;
  companies.delete(id);
  return true;
}

export function listVersions(): VersionMeta[] {
  return [...versions.values()].map((v) => v.meta).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getVersion(id: string): VersionDoc | null {
  const v = versions.get(id);
  if (!v) return null;
  return { meta: v.meta, dataset: v.dataset, log: v.log };
}

export function saveBaseVersion(dataset: Dataset, name: string, note = ""): VersionMeta {
  const id = makeId("v");
  const now = new Date().toISOString();
  const meta: VersionMeta = {
    id,
    name: name || "Base plan",
    kind: "base",
    status: "active",
    parent_id: null,
    company: dataset.settings?.company_name ?? "",
    planning_start: dataset.settings?.planning_start ?? now.slice(0, 10),
    created_at: now,
    updated_at: now,
    note,
    sha256: sha256Of(dataset),
    size: Buffer.byteLength(JSON.stringify(dataset), "utf-8"),
  };
  versions.set(id, { meta, dataset, log: [] });
  return meta;
}

export function branchVersion(parentId: string, name: string, note = ""): VersionMeta | null {
  const parent = versions.get(parentId);
  if (!parent) return null;
  const id = makeId("sc");
  const now = new Date().toISOString();
  const dsCopy = JSON.parse(JSON.stringify(parent.dataset)) as Dataset;
  const meta: VersionMeta = {
    id,
    name: name || "Scenario",
    kind: "scenario",
    status: "active",
    parent_id: parentId,
    company: dsCopy.settings?.company_name ?? "",
    planning_start: dsCopy.settings?.planning_start ?? now.slice(0, 10),
    created_at: now,
    updated_at: now,
    note,
    sha256: sha256Of(dsCopy),
    size: Buffer.byteLength(JSON.stringify(dsCopy), "utf-8"),
  };
  versions.set(id, { meta, dataset: dsCopy, log: [] });
  return meta;
}

export function updateScenarioVersion(id: string, dataset: Dataset): VersionMeta | null {
  const v = versions.get(id);
  if (!v || v.meta.kind !== "scenario") return null;
  v.dataset = dataset;
  v.meta.updated_at = new Date().toISOString();
  v.meta.sha256 = sha256Of(dataset);
  v.meta.size = Buffer.byteLength(JSON.stringify(dataset), "utf-8");
  return v.meta;
}

export function discardVersion(id: string): VersionMeta | null {
  const v = versions.get(id);
  if (!v) return null;
  v.meta.status = "discarded";
  v.meta.updated_at = new Date().toISOString();
  return v.meta;
}

export function promoteVersion(id: string): VersionMeta | null {
  const v = versions.get(id);
  if (!v) return null;
  const base = saveBaseVersion(JSON.parse(JSON.stringify(v.dataset)) as Dataset, v.meta.name, `Promoted from ${v.meta.name}`);
  v.meta.status = "promoted";
  return base;
}

export function getWorkItemOverride(id: string) {
  return workItemOverrides.get(id);
}

export function setWorkItemOverride(id: string, patch: { owner?: string; status?: "open" | "acknowledged" | "resolved"; note?: string }) {
  const prev = workItemOverrides.get(id) ?? {};
  workItemOverrides.set(id, { ...prev, ...patch });
  return workItemOverrides.get(id)!;
}

export function listCycles(): CycleSummary[] {
  return [...cycles.values()].map((c) => {
    const signed = c.steps.filter((s) => s.status === "signed").length;
    const next = c.steps.find((s) => s.status !== "signed")?.step ?? null;
    return {
      id: c.id,
      month: c.month,
      status: next ? "open" : "closed",
      next,
      signed,
    };
  });
}

export function createCycle(month: string): Cycle {
  const id = makeId("cyc");
  const now = new Date().toISOString();
  const c: Cycle = {
    id,
    month: month || now.slice(0, 7),
    status: "open",
    created_at: now,
    created_by: "Planner",
    next: "data",
    steps: [
      { step: "data", label: "Data gathering", owner: "", status: "open", signed_at: null, signed_by: "", note: "", version_id: null, figures: null },
      { step: "demand", label: "Demand review", owner: "", status: "open", signed_at: null, signed_by: "", note: "", version_id: null, figures: null },
      { step: "supply", label: "Supply review", owner: "", status: "open", signed_at: null, signed_by: "", note: "", version_id: null, figures: null },
      { step: "presop", label: "Pre-S&OP", owner: "", status: "open", signed_at: null, signed_by: "", note: "", version_id: null, figures: null },
      { step: "executive", label: "Executive S&OP", owner: "", status: "open", signed_at: null, signed_by: "", note: "", version_id: null, figures: null },
    ],
    log: [],
  };
  cycles.set(id, c);
  return c;
}

export function getCycle(id: string): Cycle | null {
  return cycles.get(id) ?? null;
}

export function dropCycle(id: string): CycleSummary[] {
  cycles.delete(id);
  return listCycles();
}
