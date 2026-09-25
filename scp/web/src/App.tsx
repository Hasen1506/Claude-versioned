import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Dataset, ExampleInfo } from "./api/types";
import { Badge, Empty } from "./components/ui";
import { COLLECTIONS, items } from "./model/collections";
import { href, go, useRoute } from "./lib/router";
import { MasterData } from "./pages/MasterData";
import { Network } from "./pages/Network";
import { Plan } from "./pages/Plan";
import { Readiness } from "./pages/Readiness";
import { planIsStale, store, useStore, NO_ISSUES } from "./state/store";

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
      {ds ? <Sidebar page={page} sub={route[1]} ds={ds} /> : <aside className="sidebar" />}
      <main className="main">
        {!ds ? <Welcome /> : page === "data" ? <MasterData route={route} />
          : page === "settings" ? <MasterData route={["data", "settings"]} />
          : page === "readiness" ? <Readiness />
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
  const planning = useStore((s) => s.planning);
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const schemaBad = useStore((s) => s.schemaErrors.length > 0);
  const engineError = useStore((s) => s.engineError);
  const stale = useStore(planIsStale);
  const hasPlan = useStore((s) => s.plan !== null);
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
      {ds && (engineError ? <Badge sev="error">Engine unreachable</Badge>
        : schemaBad ? <a href={href("readiness")}><Badge sev="error">Invalid values</Badge></a>
        : blocking ? <a href={href("readiness")}><Badge sev="error">Not ready</Badge></a>
        : stale ? <Badge sev="warning">Plan stale</Badge>
        : hasPlan ? <Badge sev="ok">Plan current</Badge> : null)}
      <span className="spacer" />
      {ds && <>
        <button className="btn ghost icon-btn" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!canUndo} onClick={() => store.undo()}>↶</button>
        <button className="btn ghost icon-btn" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled={!canRedo} onClick={() => store.redo()}>↷</button>
        <button className="btn" onClick={() => file.current?.click()}>Import</button>
        <button className="btn" onClick={exportJson}>Export</button>
        <button className="btn ghost" onClick={() => { if (window.confirm("Close this dataset? Export it first if you want to keep it.")) { store.clear(); go(); } }}>Close</button>
        <button className="btn primary" disabled={planning || blocking || schemaBad}
          onClick={() => { store.runPlan(); go("plan"); }}>{planning ? "Planning…" : "Run plan"}</button>
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

function Sidebar({ page, sub, ds }: { page: string; sub?: string; ds: Dataset }) {
  const issues = useStore((s) => s.validation?.issues ?? NO_ISSUES);
  const errors = issues.filter((i) => i.severity === "error").length;
  const plan = useStore((s) => s.plan);
  const planErr = plan?.exceptions.filter((e) => e.severity === "error").length ?? 0;
  const item = (to: string[], label: string, active: boolean, right?: React.ReactNode) => (
    <a className={`nav-item ${active ? "active" : ""}`} href={href(...to)}>{label}<span className="count">{right}</span></a>
  );
  return (
    <nav className="sidebar" aria-label="Main">
      {item(["network"], "Network", page === "network")}
      {item(["readiness"], "Readiness", page === "readiness",
        errors ? <Badge sev="error">{errors}</Badge> : issues.length ? <Badge sev="warning">{issues.length}</Badge> : <Badge sev="ok">{" "}</Badge>)}
      {item(["plan"], "Supply plan", page === "plan", planErr ? <Badge sev="error">{planErr}</Badge> : null)}
      {(["Network", "Make & buy", "Planning data"] as const).map((g) => (
        <div key={g}>
          <div className="nav-section">{g}</div>
          {COLLECTIONS.filter((c) => c.group === g).map((c) =>
            item(["data", c.key], c.label, page === "data" && sub === c.key, <span className="faint">{items(ds, c.key).length}</span>))}
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
      purchasing_sources: [], lanes: [], demand: [], receipts: [], history: [],
    } as Dataset);
    go("data", "locations");
  };
  return (
    <div style={{ maxWidth: 880, margin: "24px auto" }}>
      <h1 style={{ fontSize: 26 }}>Plan your supply chain, end to end</h1>
      <p className="muted" style={{ fontSize: 15, maxWidth: 700 }}>
        Model your own network: locations, products, bills of material, routings on machines and labour, suppliers
        and transport lanes. Check it for data defects, then plan it: net requirements across every echelon,
        lot-size, source, schedule on working days, and see capacity, stock and exceptions, with every order pegged
        to the demand it serves.
      </p>
      <div className="grid-2" style={{ marginTop: 20 }}>
        <div className="panel" style={{ padding: 16 }}>
          <h2>Start from an example</h2>
          <p className="muted small">Fictional companies that exercise every feature. Edit them freely.</p>
          {err && <div className="banner error">Engine unreachable: {err}. Start it with <code>uvicorn scp.api.app:app</code>.</div>}
          {!examples && !err && <div className="faint">Loading…</div>}
          <div className="stack" style={{ gap: 8 }}>
            {examples?.map((x) => (
              <button key={x.name} className="btn" style={{ height: "auto", padding: "10px 12px", justifyContent: "flex-start", textAlign: "left" }}
                onClick={async () => { store.load(await api.example(x.name)); go("network"); }}>
                <div><div style={{ fontWeight: 600 }}>{x.title}</div><div className="faint small">{x.locations} locations · {x.products} products</div></div>
              </button>
            ))}
          </div>
        </div>
        <div className="panel" style={{ padding: 16 }}>
          <h2>Start your own network</h2>
          <p className="muted small">An empty dataset with a Mon–Sat calendar. Add locations first, then products, sources and lanes; readiness checks guide you.</p>
          <button className="btn primary" onClick={blank}>Create blank network</button>
          <p className="muted small" style={{ marginTop: 16 }}>Or import a dataset JSON exported earlier, using <b>Import JSON</b> at the top.</p>
        </div>
      </div>
      {examples && examples.length === 0 && <Empty title="No examples found" />}
    </div>
  );
}
