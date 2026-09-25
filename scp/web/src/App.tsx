import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Dataset, ExampleInfo } from "./api/types";
import { Badge, Empty, ThemeSwitch } from "./components/ui";
import { pct } from "./lib/format";
import { href, go, useRoute } from "./lib/router";
import { STAGES, stageById } from "./lib/stages";
import { COLLECTIONS, items } from "./model/collections";
import { Demand } from "./pages/Demand";
import { Inventory } from "./pages/Inventory";
import { Sop } from "./pages/Sop";
import { DATA_GROUPS, MasterData } from "./pages/MasterData";
import { Network } from "./pages/Network";
import { Plan } from "./pages/Plan";
import { Readiness } from "./pages/Readiness";
import { isStale, store, useStore, NO_ISSUES, type RunKey } from "./state/store";

export function App() {
  const route = useRoute();
  const ds = useStore((s) => s.dataset);
  useEffect(() => store.restore(), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      const typing = (e.target as HTMLElement)?.closest("input, textarea, select");
      if (!mod || typing) return;
      if (e.key === "z" && !e.shiftKey) { e.preventDefault(); store.undo(); }
      if ((e.key === "z" && e.shiftKey) || e.key === "y") { e.preventDefault(); store.redo(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const page = route[0] ?? "network";
  return (
    <div className="app">
      <TopBar />
      {ds ? <Spine page={page} /> : <div />}
      {ds ? <Sidebar page={page} sub={route[1]} ds={ds} /> : <aside className="sidebar" />}
      <main className="main">
        {!ds ? <div className="content"><Welcome /></div> : page === "data" ? <MasterData route={route} />
          : page === "settings" ? <MasterData route={["data", "settings"]} />
          : page === "readiness" ? <Readiness />
          : page === "demand" ? <Demand route={route} />
          : page === "inventory" ? <Inventory route={route} />
          : page === "sop" ? <Sop route={route} />
          : page === "plan" ? <Plan route={route} />
          : <Network route={route} />}
      </main>
    </div>
  );
}

function TopBar() {
  const ds = useStore((s) => s.dataset);
  const canUndo = useStore((s) => s.canUndo);
  const canRedo = useStore((s) => s.canRedo);
  const engineError = useStore((s) => s.engineError);
  const schemaBad = useStore((s) => s.schemaErrors.length > 0);
  const file = useRef<HTMLInputElement>(null);

  const exportJson = () => {
    if (!ds) return;
    const blob = new Blob([JSON.stringify(ds, null, 1)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(ds.settings.company_name || "network").replace(/[^\w-]+/g, "_")}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <header className="topbar">
      <div className="brand"><span className="brand-mark">S</span>SCP</div>
      {ds && <span className="company" title={ds.settings.company_name}>{ds.settings.company_name}</span>}
      {ds && engineError && <Badge sev="error">Engine unreachable</Badge>}
      {ds && !engineError && schemaBad && <a href={href("readiness")}><Badge sev="error">Invalid values</Badge></a>}
      <span className="spacer" />
      <ThemeSwitch />
      {ds && <>
        <button className="btn ghost icon-btn" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!canUndo} onClick={() => store.undo()}>↶</button>
        <button className="btn ghost icon-btn" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled={!canRedo} onClick={() => store.redo()}>↷</button>
        <button className="btn" onClick={() => file.current?.click()}>Import</button>
        <button className="btn" onClick={exportJson}>Export</button>
        <button className="btn ghost" onClick={() => { if (window.confirm("Close this dataset? Export it first if you want to keep it.")) { store.clear(); go(); } }}>Close</button>
      </>}
      {!ds && <button className="btn" onClick={() => file.current?.click()}>Import JSON</button>}
      <input ref={file} type="file" accept="application/json,.json" hidden onChange={async (e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (!f) return;
        try {
          store.load(JSON.parse(await f.text()) as Dataset);
          go("network");
        } catch {
          window.alert("That file is not valid JSON.");
        }
      }} />
    </header>
  );
}

/** Freshness strip over the planning spine (legacy pipeline ribbon): one chip per stage with its
 *  state — fresh, stale (inputs changed since it ran), blocked, or not run — and its headline number. */
function Spine({ page }: { page: string }) {
  const s = useStore((x) => x);
  const errors = s.validation?.issues.filter((i) => i.severity === "error").length ?? 0;
  const blocked = s.validation?.blocking || s.schemaErrors.length > 0;
  type Chip = { stage: string; state: "fresh" | "stale" | "blocked" | "idle"; val: string };
  const runChip = (key: RunKey, stage: string, val: () => string): Chip => {
    const r = s.runs[key];
    if (blocked && !r.data) return { stage, state: "blocked", val: "blocked by readiness" };
    if (!r.data) return { stage, state: "idle", val: r.running ? "running…" : "not run" };
    return { stage, state: isStale(s, key) ? "stale" : "fresh", val: val() };
  };
  const chips: Chip[] = [
    { stage: "network", state: s.network ? "fresh" : "idle",
      val: s.network ? `${s.network.locations.length} locations · ${s.network.nodes.length} nodes` : "building…" },
    { stage: "readiness", state: blocked ? "blocked" : s.validation ? "fresh" : "idle",
      val: s.schemaErrors.length ? "invalid values" : errors ? `${errors} blocking` : s.validation ? `${s.validation.issues.length} warnings` : "checking…" },
    runChip("forecast", "demand", () => {
      const f = s.runs.forecast.data!;
      return `${f.series.length} series · WAPE ${pct(f.summary.wape, 0)}`;
    }),
    runChip("inventory", "inventory", () => {
      const v = s.runs.inventory.data!;
      return v.ok && v.totals ? `${v.totals.buffers_placed}/${v.totals.stocking_nodes} buffered · −${pct(v.totals.single_cost ? v.totals.saving_vs_single / v.totals.single_cost : 0, 0)}` : "not optimised";
    }),
    runChip("sop", "sop", () => {
      const v = s.runs.sop.data!;
      return v.ok && v.kpis ? `fill ${pct(v.kpis.fill_rate, 1)} · ${v.binding.length} binding` : "not solved";
    }),
    runChip("plan", "plan", () => {
      const p = s.runs.plan.data!;
      return p.ok ? `fill ${pct(p.kpis.on_time_fill_rate, 1)} · ${p.orders.length} orders` : "not planned";
    }),
  ];
  const stale = chips.filter((c) => c.state === "stale").length;
  return (
    <nav className="spine" aria-label="Planning spine">
      <div className="lead">
        <b>PLANNING SPINE</b>
        <span>{stale ? `${stale} stale — re-run` : "status of every stage"}</span>
      </div>
      {chips.map((c) => {
        const st = stageById[c.stage];
        return (
          // remounting a stale chip on every revision replays its pulse: the edit visibly travels the spine
          <a key={c.state === "stale" ? `${c.stage}-${s.revision}` : c.stage} href={href(c.stage)}
            className={`${page === c.stage ? "on" : ""} ${c.state === "stale" ? "pulse" : ""}`} title={`${st.name}: ${c.state}`}>
            <span className={`dot ${c.state}`} aria-hidden />
            <span style={{ minWidth: 0 }}>
              <span className="name">{st.n} {st.name}</span>
              <span className={`val ${c.state === "stale" ? "stale" : ""}`}>{c.state === "stale" ? `stale · ${c.val}` : c.val}</span>
            </span>
          </a>
        );
      })}
    </nav>
  );
}

function Sidebar({ page, sub, ds }: { page: string; sub?: string; ds: Dataset }) {
  const issues = useStore((s) => s.validation?.issues ?? NO_ISSUES);
  const errors = issues.filter((i) => i.severity === "error").length;
  const plan = useStore((s) => s.runs.plan.data);
  const planErr = plan?.exceptions.filter((e) => e.severity === "error").length ?? 0;
  const counts: Record<string, React.ReactNode> = {
    readiness: errors ? <Badge sev="error">{errors}</Badge> : issues.length ? <Badge sev="warning">{issues.length}</Badge> : <Badge sev="ok">{" "}</Badge>,
    plan: planErr ? <Badge sev="error">{planErr}</Badge> : null,
  };
  const item = (to: string[], label: string, active: boolean, n?: string, right?: React.ReactNode) => (
    <a key={to.join("/")} className={`nav-item ${active ? "active" : ""}`} href={href(...to)}>
      {n && <span className="n">{n}</span>}{label}<span className="count">{right}</span>
    </a>
  );
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="nav-section">Planning spine</div>
      {STAGES.map((st) => item([st.id], st.name, page === st.id, st.n, counts[st.id]))}
      {DATA_GROUPS.map((g) => (
        <div key={g}>
          <div className="nav-section">{g}</div>
          {COLLECTIONS.filter((c) => c.group === g).map((c) =>
            item(["data", c.key], c.label, page === "data" && sub === c.key, undefined, <span className="faint">{items(ds, c.key).length}</span>))}
        </div>
      ))}
      <div className="nav-section">Company</div>
      {item(["settings"], "Settings", page === "settings")}
    </nav>
  );
}

function Welcome() {
  const [examples, setExamples] = useState<ExampleInfo[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.examples().then(setExamples).catch((e) => setErr(String(e))); }, []);
  const blank = () => {
    const today = new Date();
    const monday = new Date(today);
    monday.setDate(today.getDate() + ((8 - today.getDay()) % 7 || 7));
    const iso = monday.toISOString().slice(0, 10);
    store.load({
      schema_version: "1",
      settings: { company_name: "My Company", currency: "INR", planning_start: iso, horizon_days: 182, bucket: "week",
        week_start: 0, fx_rates: {}, wacc: 0.12, holding_spread: 0.08, default_service_level: 0.95, default_calendar: "CAL-STD" },
      calendars: [{ id: "CAL-STD", name: "Mon–Sat", workdays: [0, 1, 2, 3, 4, 5], holidays: [] }],
      locations: [], products: [], location_products: [], resources: [], production_sources: [],
      purchasing_sources: [], lanes: [], demand: [], receipts: [], history: [], events: [], npi: [], overrides: [],
    } as unknown as Dataset);
    go("data", "locations");
  };
  return (
    <div style={{ maxWidth: 980, margin: "12px auto" }} className="animate-in">
      <div className="row" style={{ alignItems: "flex-end", gap: 16, marginBottom: 6 }}>
        <span className="stage-head" style={{ padding: 0, border: 0, background: "none" }}><span className="n" style={{ fontSize: 44 }}>00</span></span>
        <h1 style={{ fontSize: 26 }}>Plan your supply chain, end to end</h1>
      </div>
      <p className="muted" style={{ fontSize: 15, maxWidth: 760 }}>
        Model your own network: locations, products, bills of material, routings on machines and labour, suppliers
        and transport lanes. Check it for data defects, forecast demand from history, then plan supply: net requirements
        across every echelon, lot-size, source, schedule on working days, and see capacity, stock and exceptions, with
        every order pegged to the demand it serves.
      </p>
      <div className="grid-2" style={{ marginTop: 20 }}>
        <div className="panel">
          <div className="panel-head"><h3>Start from an example</h3></div>
          <div className="panel-body stack" style={{ gap: 8 }}>
            <p className="muted small" style={{ margin: 0 }}>Fictional companies that exercise every feature. Edit them freely.</p>
            {err && <div className="banner error">Engine unreachable: {err}. Start it with <code>uvicorn scp.api.app:app</code>.</div>}
            {!examples && !err && <div className="faint">Loading…</div>}
            {examples?.map((x) => (
              <button key={x.name} className="btn" style={{ height: "auto", padding: "10px 12px", justifyContent: "flex-start",
                textAlign: "left", whiteSpace: "normal", textTransform: "none", letterSpacing: 0 }}
                onClick={async () => { store.load(await api.example(x.name)); go("network"); }}>
                <div><div style={{ fontSize: 13 }}>{x.title}</div>
                  <div className="faint small" style={{ fontFamily: "var(--mono)", fontWeight: 400 }}>{x.locations} locations · {x.products} products</div></div>
              </button>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><h3>Start your own network</h3></div>
          <div className="panel-body">
            <p className="muted small" style={{ marginTop: 0 }}>An empty dataset with a Mon–Sat calendar. Add locations first, then products,
              sources and lanes; readiness checks guide you.</p>
            <button className="btn accent" onClick={blank}>Create blank network</button>
            <p className="muted small" style={{ marginTop: 16, marginBottom: 0 }}>Or import a dataset JSON exported earlier, using <b>Import JSON</b> at the top.</p>
          </div>
        </div>
      </div>
      {examples && examples.length === 0 && <Empty title="No examples found" />}
    </div>
  );
}
