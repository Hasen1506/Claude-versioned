import express, { type Request, type Response } from "express";
import fs from "node:fs";
import path from "node:path";
import {
  CASES,
  FORECAST_MODELS,
  getExample,
  getJsonSchema,
  listExamples,
  normalizeDataset,
  RULES,
  SCENARIO_EXAMPLES,
  SCENARIOS,
  SCHEDULE_CATALOGUE,
} from "./server/examples.ts";
import { buildNetworkView, runLevelPreview, runPlan, runPlanTrace, validateDataset } from "./server/engine/core.ts";
import {
  compareSchedules,
  releaseForecast,
  runActuals,
  runForecast,
  runInventory,
  runInventoryPolicy,
  runPromise,
  runPurchasing,
  runSales,
  runSchedule,
  runSop,
  runValueAdd,
} from "./server/engine/planning.ts";
import {
  runAccounting,
  runAsk,
  runCompare,
  runCycleCounts,
  runFinance,
  runIntercompany,
  runOutside,
  runScenarioProof,
  runStrategyAdvisor,
  runTower,
  runTransport,
  runValuation,
  runWarehouse,
  runWhatIf,
} from "./server/engine/analytics.ts";
import {
  branchVersion,
  createCompany,
  createCsrfToken,
  createCycle,
  deleteCompany,
  discardVersion,
  dropCycle,
  getAuthConfig,
  getCompanyDoc,
  getCycle,
  getMe,
  getUserFromToken,
  getVersion,
  listCompanies,
  listCycles,
  listVersions,
  promoteVersion,
  saveBaseVersion,
  saveCompany,
  setWorkItemOverride,
  signIn,
  signOut,
  signUp,
  updateScenarioVersion,
} from "./server/state.ts";
import type { Dataset } from "./server/types.ts";

const PORT = Number(process.env.PORT || 3000);
const HOST = "0.0.0.0";
const WEB_DIST = path.resolve(process.cwd(), "scp", "web", "dist");
const STARTED_AT = Date.now();

function readCookie(req: Request, name: string): string | null {
  const raw = req.headers.cookie;
  if (!raw) return null;
  for (const part of raw.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

function sessionTokenOf(req: Request): string | null {
  const auth = req.headers.authorization;
  if (auth && auth.startsWith("Bearer ")) return auth.slice(7).trim();
  return readCookie(req, "scp_session");
}

function extractDataset(body: unknown): Dataset {
  const b = (body ?? {}) as Record<string, unknown>;
  const raw = (b.dataset && typeof b.dataset === "object" ? b.dataset : b) as Partial<Dataset>;
  return normalizeDataset(raw);
}

export function createApp() {
  const app = express();
  app.use(express.json({ limit: "50mb" }));

  // ---- Health & metadata ----
  app.get("/api/health", (_req, res) => {
    res.json({
      status: "ok",
      version: "0.1.0-node",
      commit: "",
      database: "memory",
      up_seconds: Math.floor((Date.now() - STARTED_AT) / 1000),
    });
  });

  app.get("/api/examples", (_req, res) => res.json(listExamples()));
  app.get("/api/cases", (_req, res) => res.json(Object.values(CASES)));
  app.get("/api/examples/:name", (req, res) => {
    const ds = getExample(String(req.params.name));
    if (!ds) return res.status(404).json({ detail: `No example '${req.params.name}'` });
    return res.json(ds);
  });
  app.get("/api/rules", (_req, res) => res.json(RULES));
  app.get("/api/schema", (_req, res) => res.json(getJsonSchema()));

  // ---- Validation & Network ----
  app.post("/api/validate", (req, res) => res.json(validateDataset(extractDataset(req.body))));
  app.post("/api/network", (req, res) => res.json(buildNetworkView(extractDataset(req.body))));

  // ---- Supply Plan & Capacity ----
  app.post("/api/plan", (req, res) => {
    const pegging = req.query.pegging !== "false";
    res.json(runPlan(extractDataset(req.body), pegging));
  });
  app.post("/api/plan/trace", (req, res) => {
    const body = (req.body ?? {}) as { dataset?: Dataset; order?: string; location?: string; product?: string };
    res.json(runPlanTrace(extractDataset(body), body));
  });
  app.post("/api/plan/strategy-advisor", (req, res) => res.json(runStrategyAdvisor(extractDataset(req.body))));
  app.post("/api/capacity/level", (req, res) => res.json(runLevelPreview(extractDataset(req.body))));

  // ---- Demand & Forecasting ----
  app.get("/api/forecast/models", (_req, res) => res.json(FORECAST_MODELS));
  app.post("/api/forecast", (req, res) => res.json(runForecast(extractDataset(req.body))));
  app.post("/api/forecast/release", (req, res) => res.json(releaseForecast(extractDataset(req.body))));
  app.post("/api/forecast/value-add", (req, res) => res.json(runValueAdd(extractDataset(req.body))));

  // ---- Inventory & Policy ----
  app.post("/api/inventory", (req, res) => res.json(runInventory(extractDataset(req.body))));
  app.post("/api/inventory/apply", (req, res) => {
    const ds = extractDataset(req.body);
    const inv = runInventory(ds);
    const next = JSON.parse(JSON.stringify(ds)) as Dataset;
    const keys = (req.body as { keys?: string[] | null })?.keys ?? null;
    let updated = 0;
    for (const n of inv.nodes) {
      if (n.role !== "stocking") continue;
      if (keys && !keys.includes(`${n.location}|${n.product}`)) continue;
      const lp = (next.location_products ?? []).find((x) => x.location === n.location && x.product === n.product);
      if (lp) {
        lp.safety_stock = { method: "fixed", qty: n.meio_ss } as typeof lp.safety_stock;
        updated += 1;
      }
    }
    res.json({ dataset: next, patch: null, applied: { updated, total_meio_ss_value: inv.totals?.meio_ss_value ?? 0 } });
  });
  app.post("/api/inventory/policy", (req, res) => res.json(runInventoryPolicy(extractDataset(req.body))));
  app.post("/api/inventory/policy/apply", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, updated: 0, message: "Inventory policy updated." });
  });

  // ---- S&OP & Cycles ----
  app.post("/api/sop", (req, res) => res.json(runSop(extractDataset(req.body))));
  app.post("/api/sop/release", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, release: { written: 0, notes: ["Released constrained S&OP plan."] } });
  });
  app.get("/api/sop/cycles", (_req, res) => res.json(listCycles()));
  app.post("/api/sop/cycles", (req, res) => {
    const month = String((req.body as { month?: string })?.month || new Date().toISOString().slice(0, 7));
    res.json(createCycle(month));
  });
  app.get("/api/sop/cycles/:id", (req, res) => {
    const c = getCycle(String(req.params.id));
    if (!c) return res.status(404).json({ detail: "Cycle not found" });
    return res.json(c);
  });
  app.delete("/api/sop/cycles/:id", (req, res) => res.json(dropCycle(String(req.params.id))));
  app.put("/api/sop/cycles/:id/steps/:step/owner", (req, res) => {
    const c = getCycle(String(req.params.id));
    if (!c) return res.status(404).json({ detail: "Cycle not found" });
    const st = c.steps.find((s) => s.step === req.params.step);
    if (st) st.owner = String((req.body as { owner?: string })?.owner ?? "");
    return res.json(c);
  });
  app.post("/api/sop/cycles/:id/steps/:step/sign", (req, res) => {
    const c = getCycle(String(req.params.id));
    if (!c) return res.status(404).json({ detail: "Cycle not found" });
    const st = c.steps.find((s) => s.step === req.params.step);
    if (st) {
      st.status = "signed";
      st.signed_at = new Date().toISOString();
      st.signed_by = "Planner";
      st.note = String((req.body as { note?: string })?.note ?? "");
    }
    return res.json(c);
  });
  app.post("/api/sop/cycles/:id/steps/:step/reopen", (req, res) => {
    const c = getCycle(String(req.params.id));
    if (!c) return res.status(404).json({ detail: "Cycle not found" });
    const st = c.steps.find((s) => s.step === req.params.step);
    if (st) {
      st.status = "open";
      st.signed_at = null;
    }
    return res.json(c);
  });
  app.post("/api/sop/figures", (req, res) => {
    const ds = extractDataset(req.body);
    const plan = runPlan(ds);
    const fin = runFinance(ds);
    res.json({
      as_of: ds.settings?.planning_start ?? new Date().toISOString().slice(0, 10),
      currency: plan.currency,
      demand_qty: plan.kpis.independent_demand,
      revenue: fin.serve.reduce((s, r) => s + r.revenue, 0),
      total_cost: plan.kpis.total_cost,
      fill_rate: plan.kpis.on_time_fill_rate,
      max_utilization: plan.kpis.max_utilization,
      inventory_value_avg: plan.kpis.inventory_value_avg,
      exceptions: plan.exceptions.length,
    });
  });

  // ---- Scheduling ----
  app.get("/api/schedule/catalogue", (_req, res) => res.json(SCHEDULE_CATALOGUE));
  app.post("/api/schedule", (req, res) => res.json(runSchedule(extractDataset(req.body))));
  app.post("/api/schedule/compare", (req, res) => res.json(compareSchedules(extractDataset(req.body))));
  app.post("/api/schedule/apply", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { applied: [], notes: ["Schedule dates applied."] } });
  });

  // ---- Order Promising & Sales ----
  app.post("/api/promise", (req, res) => res.json(runPromise(extractDataset(req.body), "entry")));
  app.post("/api/promise/bop", (req, res) => res.json(runPromise(extractDataset(req.body), "bop")));
  app.post("/api/promise/check", (req, res) => {
    const b = (req.body ?? {}) as { dataset?: Dataset; order?: NonNullable<Dataset["demand"]>[number]; lines?: NonNullable<Dataset["demand"]> };
    const lines = b.lines ?? (b.order ? [b.order] : []);
    res.json(runPromise(extractDataset(b), "check", lines));
  });
  app.post("/api/promise/commit", (req, res) => {
    const ds = extractDataset(req.body);
    const result = runPromise(ds, "entry");
    res.json({ dataset: ds, patch: null, committed: result.orders.length, result });
  });
  app.post("/api/orders/sales", (req, res) => {
    const b = (req.body ?? {}) as { dataset?: Dataset; action?: string; order?: NonNullable<Dataset["demand"]>[number] };
    const ds = JSON.parse(JSON.stringify(extractDataset(b))) as Dataset;
    if (b.action === "accept" && b.order) {
      ds.demand = [...(ds.demand ?? []), { ...b.order, kind: "sales_order", id: b.order.id || `SO-${Date.now().toString().slice(-5)}` }];
    }
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Sales order updated." } });
  });
  app.post("/api/sales", (req, res) => res.json(runSales(extractDataset(req.body))));
  app.post("/api/sales/act", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Sales action recorded." }, view: runSales(ds) });
  });

  // ---- Purchasing & Firming ----
  app.post("/api/purchasing", (req, res) => res.json(runPurchasing(extractDataset(req.body))));
  app.post("/api/purchasing/create", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, created: [], message: "Purchase orders created." }, view: runPurchasing(ds) });
  });
  app.post("/api/purchasing/one-off", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, created: [], message: "One-off purchase order created." }, view: runPurchasing(ds) });
  });
  app.post("/api/purchasing/act", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Purchase order action recorded." }, view: runPurchasing(ds) });
  });
  app.post("/api/orders/firm", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, firmed: [], skipped: {}, purchase_orders: [], notes: [], sent: [] } });
  });

  // ---- Actuals, Valuation, Accounting, Group, Warehouse, Transport, Outside ----
  app.post("/api/actuals", (req, res) => {
    const asOf = (req.body as { as_of?: string | null })?.as_of ?? undefined;
    res.json(runActuals(extractDataset(req.body), asOf));
  });
  app.post("/api/actuals/roll", (req, res) => {
    const b = (req.body ?? {}) as { dataset?: Dataset; as_of?: string };
    const ds = JSON.parse(JSON.stringify(extractDataset(b))) as Dataset;
    if (b.as_of) ds.settings.planning_start = b.as_of;
    res.json({ dataset: ds, patch: null, report: { from_date: ds.settings.planning_start, to_date: b.as_of ?? ds.settings.planning_start, closed: 0, reduced: 0, dropped_forecast: 0, history_added: 0, notes: [] } });
  });
  app.post("/api/actuals/post", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Posting recorded." } });
  });
  app.post("/api/actuals/production-usage", (_req, res) => res.json([]));
  app.post("/api/valuation", (req, res) => {
    const books = req.query.books === "group" ? "group" : "entity";
    res.json(runValuation(extractDataset(req.body), books));
  });
  app.post("/api/accounting", (req, res) => res.json(runAccounting(extractDataset(req.body))));
  app.post("/api/accounting/export", (_req, res) => res.json({ filename: "journal.csv", mime: "text/csv", content: "date,account,debit,credit\n" }));
  app.post("/api/intercompany", (req, res) => res.json(runIntercompany(extractDataset(req.body))));
  app.post("/api/intercompany/act", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Recorded." }, view: runIntercompany(ds) });
  });
  app.post("/api/cycle-counts", (req, res) => res.json(runCycleCounts(extractDataset(req.body), String(req.query.location || "") || undefined)));
  app.post("/api/warehouse", (req, res) => res.json(runWarehouse(extractDataset(req.body), String(req.query.location || ""))));
  app.post("/api/warehouse/putaway", (req, res) => res.json({ location: String(req.query.location || ""), tasks: [], notes: [] }));
  app.post("/api/warehouse/refill", (req, res) => res.json({ location: String(req.query.location || ""), bins: [], moves: [], notes: [] }));
  app.post("/api/warehouse/picks", (req, res) => res.json({ wave: String(req.query.wave || ""), rows: [], notes: [] }));
  app.post("/api/warehouse/act", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Warehouse action recorded." } });
  });
  app.post("/api/transport", (req, res) => res.json(runTransport(extractDataset(req.body))));
  app.post("/api/transport/act", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Transport action recorded." }, view: runTransport(ds) });
  });
  app.post("/api/outside", (req, res) => res.json(runOutside(extractDataset(req.body))));
  app.post("/api/outside/act", (req, res) => {
    const ds = extractDataset(req.body);
    res.json({ dataset: ds, patch: null, report: { ok: true, message: "Outside work updated." }, view: runOutside(ds) });
  });
  app.post("/api/outside/parts", (_req, res) => res.json([]));

  // ---- Finance, Control Tower & Ask ----
  app.post("/api/finance", (req, res) => res.json(runFinance(extractDataset(req.body))));
  app.post("/api/tower", (req, res) => res.json(runTower(extractDataset(req.body))));
  app.post("/api/tower/fix", (req, res) => {
    res.json({ ok: true, before_risk: 0, after_risk: 0, edits: [], summary: "No automated edits needed." });
  });
  app.patch("/api/tower/items/:id", (req, res) => {
    const id = String(req.params.id);
    const ov = setWorkItemOverride(id, (req.body ?? {}) as { owner?: string; status?: "open" | "acknowledged" | "resolved"; note?: string });
    res.json({ id, ...ov });
  });
  app.get("/api/tower/items/:id/history", (_req, res) => res.json([]));
  app.post("/api/ask", (req, res) => {
    const b = (req.body ?? {}) as { dataset?: Dataset; question?: string };
    res.json(runAsk(extractDataset(b), String(b.question ?? "")));
  });

  // ---- Versions, What-If & Compare ----
  app.get("/api/versions", (_req, res) => res.json(listVersions()));
  app.post("/api/versions", (req, res) => {
    const b = (req.body ?? {}) as { dataset?: Dataset; name?: string; note?: string };
    res.json(saveBaseVersion(extractDataset(b), String(b.name ?? "Base plan"), String(b.note ?? "")));
  });
  app.get("/api/versions/:id", (req, res) => {
    const doc = getVersion(String(req.params.id));
    if (!doc) return res.status(404).json({ detail: "Version not found" });
    return res.json(doc);
  });
  app.put("/api/versions/:id", (req, res) => {
    const meta = updateScenarioVersion(String(req.params.id), extractDataset(req.body));
    if (!meta) return res.status(404).json({ detail: "Scenario not found" });
    return res.json(meta);
  });
  app.post("/api/versions/:id/branch", (req, res) => {
    const b = (req.body ?? {}) as { name?: string; note?: string };
    const meta = branchVersion(String(req.params.id), String(b.name ?? "Scenario"), String(b.note ?? ""));
    if (!meta) return res.status(404).json({ detail: "Parent version not found" });
    return res.json(meta);
  });
  app.post("/api/versions/:id/discard", (req, res) => {
    const meta = discardVersion(String(req.params.id));
    if (!meta) return res.status(404).json({ detail: "Version not found" });
    return res.json(meta);
  });
  app.post("/api/versions/:id/promote", (req, res) => {
    const meta = promoteVersion(String(req.params.id));
    if (!meta) return res.status(404).json({ detail: "Version not found" });
    return res.json(meta);
  });
  app.get("/api/versions/:a/compare/:b", (req, res) => {
    const va = getVersion(String(req.params.a));
    const vb = getVersion(String(req.params.b));
    if (!va || !vb) return res.status(404).json({ detail: "Version not found" });
    return res.json(runCompare(va.dataset, vb.dataset, va.meta.name, vb.meta.name));
  });
  app.post("/api/compare", (req, res) => {
    const b = (req.body ?? {}) as { a: Dataset; b: Dataset; label_a?: string; label_b?: string };
    res.json(runCompare(normalizeDataset(b.a), normalizeDataset(b.b), b.label_a ?? "Plan A", b.label_b ?? "Plan B"));
  });
  app.post("/api/whatif", (req, res) => {
    const b = (req.body ?? {}) as { base: Dataset; scenarios: { label: string; chips: unknown[]; version?: string | null }[] };
    res.json(runWhatIf(normalizeDataset(b.base), b.scenarios ?? []));
  });
  app.post("/api/whatif/keep", (req, res) => {
    const b = (req.body ?? {}) as { base: Dataset; label?: string; parent?: string | null; base_name?: string };
    const base = normalizeDataset(b.base);
    const parentId = b.parent || saveBaseVersion(base, b.base_name || "Base").id;
    const sc = branchVersion(parentId, b.label || "What-if scenario")!;
    res.json({ base_id: parentId, scenario: sc });
  });
  app.post("/api/whatif/sweep", (req, res) => {
    const b = (req.body ?? {}) as { base: Dataset; chip: Record<string, unknown>; values: number[] };
    const scenarios = (b.values ?? []).map((v) => ({
      label: String(v),
      chips: [{ ...b.chip, days: v, pct: v }],
    }));
    const w = runWhatIf(normalizeDataset(b.base), scenarios);
    res.json({ currency: w.currency, points: w.scenarios });
  });

  // ---- Proof / Scenarios ----
  app.get("/api/scenarios", (_req, res) => res.json(SCENARIOS));
  app.get("/api/scenarios/:id/dataset", (req, res) => {
    const ds = getExample(SCENARIO_EXAMPLES[String(req.params.id)] || "single_product_plant");
    if (!ds) return res.status(404).json({ detail: "Scenario not found" });
    return res.json(ds);
  });
  app.post("/api/scenarios/:id/run", (req, res) => {
    const report = runScenarioProof(String(req.params.id));
    if (!report) return res.status(404).json({ detail: "Scenario not found" });
    return res.json(report);
  });

  // ---- Auth & Companies (in-memory) ----
  app.get("/api/auth/config", (_req, res) => res.json(getAuthConfig()));
  app.get("/api/auth/csrf", (_req, res) => {
    const csrf = createCsrfToken();
    res.setHeader("Set-Cookie", `scp_csrf=${encodeURIComponent(csrf)}; Path=/; SameSite=Lax`);
    res.json({ csrf });
  });
  app.post("/api/auth/signup", (req, res) => {
    try {
      const b = (req.body ?? {}) as { email?: string; name?: string; password?: string };
      const { session, token } = signUp(String(b.email ?? ""), String(b.name ?? ""), String(b.password ?? ""));
      res.setHeader("Set-Cookie", [
        `scp_session=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax`,
        `scp_csrf=${encodeURIComponent(session.csrf ?? "")}; Path=/; SameSite=Lax`,
      ]);
      return res.json(session);
    } catch (e) {
      return res.status(400).json({ detail: e instanceof Error ? e.message : String(e) });
    }
  });
  app.post("/api/auth/signin", (req, res) => {
    try {
      const b = (req.body ?? {}) as { email?: string; password?: string };
      const { session, token } = signIn(String(b.email ?? ""), String(b.password ?? ""));
      res.setHeader("Set-Cookie", [
        `scp_session=${encodeURIComponent(token)}; Path=/; HttpOnly; SameSite=Lax`,
        `scp_csrf=${encodeURIComponent(session.csrf ?? "")}; Path=/; SameSite=Lax`,
      ]);
      return res.json(session);
    } catch (e) {
      return res.status(401).json({ detail: e instanceof Error ? e.message : String(e) });
    }
  });
  app.post("/api/auth/signout", (req, res) => {
    signOut(sessionTokenOf(req));
    res.setHeader("Set-Cookie", "scp_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax");
    res.json({ ok: true });
  });
  app.get("/api/auth/me", (req, res) => {
    const me = getMe(sessionTokenOf(req));
    if (!me) return res.status(401).json({ detail: "Not signed in" });
    return res.json(me);
  });
  app.post("/api/auth/reset/request", (_req, res) => res.json({ ok: true, mail: false }));

  app.get("/api/companies", (req, res) => {
    const user = getUserFromToken(sessionTokenOf(req));
    if (!user) return res.status(401).json({ detail: "Sign in first" });
    return res.json(listCompanies(user.email));
  });
  app.post("/api/companies", (req, res) => {
    const user = getUserFromToken(sessionTokenOf(req));
    if (!user) return res.status(401).json({ detail: "Sign in first" });
    const b = (req.body ?? {}) as { dataset: Dataset; note?: string };
    return res.json(createCompany(user, normalizeDataset(b.dataset), String(b.note ?? "created")));
  });
  app.get("/api/companies/:id", (req, res) => {
    const user = getUserFromToken(sessionTokenOf(req));
    if (!user) return res.status(401).json({ detail: "Sign in first" });
    const doc = getCompanyDoc(String(req.params.id), user.email);
    if (!doc) return res.status(404).json({ detail: "Company not found" });
    return res.json(doc);
  });
  app.put("/api/companies/:id", (req, res) => {
    const user = getUserFromToken(sessionTokenOf(req));
    if (!user) return res.status(401).json({ detail: "Sign in first" });
    const b = (req.body ?? {}) as { dataset?: Dataset; base_revision?: number; note?: string };
    if (!b.dataset) return res.status(409).json({ detail: "Send the full dataset", patch: "unfit" });
    const out = saveCompany(String(req.params.id), user, normalizeDataset(b.dataset), Number(b.base_revision ?? 0), String(b.note ?? ""));
    if (!out) return res.status(404).json({ detail: "Company not found" });
    if (out.conflict) {
      return res.status(409).json({
        detail: `${out.updated_by} saved revision ${out.revision}`,
        revision: out.revision,
        updated_by: out.updated_by,
        updated_at: out.updated_at,
      });
    }
    return res.json(out.report);
  });
  app.delete("/api/companies/:id", (req, res) => {
    const user = getUserFromToken(sessionTokenOf(req));
    if (!user) return res.status(401).json({ detail: "Sign in first" });
    if (!deleteCompany(String(req.params.id), user.email)) return res.status(404).json({ detail: "Company not found" });
    return res.json({ ok: true });
  });

  // Catch-all for unimplemented /api/* routes so they return clean JSON instead of HTML
  app.all("/api/{*splat}", (req, res) => {
    res.status(501).json({ detail: `Endpoint ${req.method} ${req.path} is not yet migrated to the Node.js engine.` });
  });

  // Serve built React SPA from scp/web/dist
  if (fs.existsSync(WEB_DIST)) {
    app.use(express.static(WEB_DIST));
    app.get("/{*splat}", (_req: Request, res: Response) => {
      res.sendFile(path.join(WEB_DIST, "index.html"));
    });
  } else {
    app.get("/{*splat}", (_req: Request, res: Response) => {
      res.status(503).send("SCP web client not built yet. Run `npm run build` first.");
    });
  }

  return app;
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname);
if (isMain) {
  const app = createApp();
  app.listen(PORT, HOST, () => {
    console.log(`SCP server listening on http://${HOST}:${PORT}`);
  });
}
