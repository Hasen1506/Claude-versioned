import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Dataset, ExampleInfo } from "./api/types";
import { Badge, Empty, ThemeSwitch } from "./components/ui";
import { href, go, useRoute } from "./lib/router";
import { NAV, navItemFor, type NavItem } from "./lib/nav";
import { Demand } from "./pages/Demand";
import { Execution } from "./pages/Execution";
import { Finance } from "./pages/Finance";
import { Home, markVisited } from "./pages/Home";
import { Tower } from "./pages/Tower";
import { Versions } from "./pages/Versions";
import { Inventory } from "./pages/Inventory";
import { Promising } from "./pages/Promising";
import { Proof } from "./pages/Proof";
import { Schedule } from "./pages/Schedule";
import { Sop } from "./pages/Sop";
import { MasterData } from "./pages/MasterData";
import { Network } from "./pages/Network";
import { Plan } from "./pages/Plan";
import { Readiness } from "./pages/Readiness";
import { freshness, isModified, planFreshness, store, useStore, NO_ISSUES } from "./state/store";

/** Open a dataset and calculate everything, so no page opens empty. */
function openAndPlan(ds: Dataset) {
  store.load(ds);
  go("home");
  void store.planAll();
}

export function App() {
  const route = useRoute();
  const ds = useStore((s) => s.dataset);
  useEffect(() => {
    store.restore();
    if (store.get().dataset) void store.planAll();
  }, []);
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

  const page = route[0] || "home";
  useEffect(() => { if (ds) markVisited(page); }, [page, ds]);
  const item = ds ? navItemFor(page) : undefined;
  return (
    <div className="app">
      <TopBar />
      {ds ? <Rail page={page} /> : (
        <nav className="rail" aria-label="Main">
          <div className="rail-group">
            <a className={`rail-item ${page !== "proof" ? "active" : ""}`} href="#/">Start</a>
            <a className={`rail-item ${page === "proof" ? "active" : ""}`} href={href("proof")}>Proof</a>
          </div>
        </nav>
      )}
      <main className="main">
        {item?.tabs && <SectionTabs item={item} page={page} />}
        {page === "proof" ? <Proof route={route} />
          : !ds ? <div className="content"><Welcome /></div>
          : page === "data" ? <MasterData route={route} />
          : page === "settings" ? <MasterData route={["data", "settings"]} />
          : page === "readiness" ? <Readiness />
          : page === "network" ? <Network route={route} />
          : page === "demand" ? <Demand route={route} />
          : page === "inventory" ? <Inventory route={route} />
          : page === "sop" ? <Sop route={route} />
          : page === "plan" ? <Plan route={route} />
          : page === "schedule" ? <Schedule route={route} />
          : page === "promise" ? <Promising route={route} />
          : page === "execution" ? <Execution route={route} />
          : page === "finance" ? <Finance route={route} />
          : page === "tower" ? <Tower route={route} />
          : page === "versions" ? <Versions />
          : <div className="content"><Home ds={ds} /></div>}
      </main>
    </div>
  );
}

/** The one button that calculates everything. Yellow only when something needs calculating. */
function PlanButton() {
  const planning = useStore((s) => s.planning);
  const f = useStore(planFreshness);
  const blocked = useStore((s) => !!s.validation?.blocking || s.schemaErrors.length > 0);
  const empty = useStore((s) => !s.dataset?.locations?.length);
  if (planning) {
    return <button className="btn plan-btn" disabled aria-live="polite">
      <span className="spin" aria-hidden />Planning… {planning.done + 1}/{planning.of}</button>;
  }
  return (
    <button className={`btn plan-btn ${f !== "fresh" && !blocked && !empty ? "accent" : ""}`} onClick={() => store.planAll()}
      title={blocked ? "Fix the data problems first (Setup → Network → Data check)" : "Calculate every result from the current data. Your data is not changed."}>
      {f === "stale" ? "Plan everything again" : "Plan everything"}
    </button>
  );
}

function Menu({ children, label }: { children: React.ReactNode; label: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="menu-wrap" ref={ref}>
      <button className="btn ghost icon-btn" aria-label={label} aria-expanded={open} title={label} onClick={() => setOpen(!open)}>⋯</button>
      {open && <div className="menu" role="menu" onClick={(e) => { if ((e.target as HTMLElement).closest("[data-close]")) setOpen(false); }}>{children}</div>}
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
  const version = useStore((s) => s.version);
  const modified = useStore(isModified);

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
      <a className="brand" href={ds ? href("home") : "#/"} aria-label="Home"><span className="brand-mark">S</span><span className="brand-name">SCP</span></a>
      {ds && <span className="company" title={ds.settings.company_name}>{ds.settings.company_name}</span>}
      {ds && <a className="version-chip" href={href("versions")} title="Versions and what-ifs: save, branch and compare">
        {version ? <>{version.name} · {version.kind}{modified && <span className="mod"> · unsaved changes</span>}</> : <>working copy, not saved</>}</a>}
      {ds && engineError && <Badge sev="error">Engine not answering</Badge>}
      {ds && !engineError && schemaBad && <a href={href("readiness")}><Badge sev="error">Invalid values</Badge></a>}
      <span className="spacer" />
      {ds && <>
        <PlanButton />
        <button className="btn ghost icon-btn" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!canUndo} onClick={() => store.undo()}>↶</button>
        <button className="btn ghost icon-btn" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled={!canRedo} onClick={() => store.redo()}>↷</button>
      </>}
      {!ds && <button className="btn" onClick={() => file.current?.click()}>Import a file</button>}
      <Menu label="More">
        {ds && <>
          <button role="menuitem" data-close onClick={() => file.current?.click()}>Import a dataset file…</button>
          <button role="menuitem" data-close onClick={exportJson}>Export this dataset</button>
          <a role="menuitem" data-close href={href("versions")}>Versions and what-ifs</a>
          <a role="menuitem" data-close href={href("proof")}>Proof: check the numbers</a>
          <hr />
        </>}
        <div className="menu-row"><span>Theme</span><ThemeSwitch /></div>
        {ds && <>
          <hr />
          <button role="menuitem" data-close onClick={() => { if (window.confirm("Close this dataset? Export it first if you want to keep it.")) { store.clear(); go(); } }}>Close dataset</button>
        </>}
      </Menu>
      <input ref={file} type="file" accept="application/json,.json" hidden onChange={async (e) => {
        const f = e.target.files?.[0];
        e.target.value = "";
        if (!f) return;
        try {
          openAndPlan(JSON.parse(await f.text()) as Dataset);
        } catch {
          window.alert("That file is not valid JSON.");
        }
      }} />
    </header>
  );
}

/** The rail: one link per question, grouped. A dot marks a result that is out of date or not calculated. */
function Rail({ page }: { page: string }) {
  const s = useStore((x) => x);
  const issues = s.validation?.issues ?? NO_ISSUES;
  const errors = issues.filter((i) => i.severity === "error").length + s.schemaErrors.length;
  const tower = s.runs.tower.data;
  const offTrack = tower?.ok ? tower.kpis.filter((k) => k.status === "critical" || k.status === "warning").length : 0;
  const active = navItemFor(page);
  const right = (it: NavItem) => {
    if (it.id === "network" && errors) return <Badge sev="error">{errors}</Badge>;
    if (it.id === "tower" && offTrack && freshness(s, "tower") !== "none") return <span className="rail-count" title={`${offTrack} measures below target`}>{offTrack}</span>;
    if (!it.run || s.planning || !s.dataset?.locations?.length) return null;
    const f = freshness(s, it.run);
    if (f === "fresh") return null;
    return <span className={`rail-dot ${f}`} title={f === "stale" ? "Out of date: the data changed after this was calculated" : "Not calculated yet"}>
      <span className="sr">{f === "stale" ? "out of date" : "not calculated"}</span></span>;
  };
  return (
    <nav className="rail" aria-label="Main">
      {NAV.map((g, i) => (
        <div className="rail-group" key={g.label ?? i}>
          {g.label && <div className="rail-label">{g.label}</div>}
          {g.items.map((it) => (
            <a key={it.id} className={`rail-item ${active?.id === it.id ? "active" : ""}`} href={href(it.id)} title={it.question}
              aria-current={active?.id === it.id ? "page" : undefined} data-fresh={it.run ? freshness(s, it.run) : undefined}>
              <span className="rail-text">{it.label}</span>{right(it)}
            </a>
          ))}
        </div>
      ))}
      <div className="rail-foot">
        <a className={page === "versions" ? "active" : ""} href={href("versions")}>Versions and what-ifs</a>
        <a className={page === "proof" ? "active" : ""} href={href("proof")}>Proof</a>
      </div>
    </nav>
  );
}

/** Tabs across the top of a section with more than one page (Supply, Network). */
function SectionTabs({ item, page }: { item: NavItem; page: string }) {
  const s = useStore((x) => x);
  return (
    <nav className="section-tabs" aria-label={`${item.label} pages`}>
      {item.tabs!.map((t) => {
        const f = t.run ? freshness(s, t.run) : undefined;
        return (
          <a key={t.id} href={href(t.id)} className={t.id === page ? "on" : ""} aria-current={t.id === page ? "page" : undefined}
            title={t.question} data-fresh={f}>
            {t.label}{t.optional && <span className="opt">optional</span>}
            {f === "stale" && !s.planning && <span className="rail-dot stale" title="Out of date: the data changed after this was calculated"><span className="sr">out of date</span></span>}
          </a>
        );
      })}
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
    go("home");
  };
  return (
    <div className="welcome animate-in">
      <h1>Plan your supply chain, from forecast to delivery</h1>
      <p className="lede">Tell it your plants, warehouses, suppliers, products and customers. It works out what to make, buy and
        move each day, and tells you whether customers will get their orders, what to do this week, what it costs and
        what's off track.</p>
      <ul className="welcome-points">
        <li><b>For planners:</b> every page opens with the answer and what needs you.</li>
        <li><b>For managers:</b> Home sums up service, cost and performance on one screen.</li>
        <li><b>For analysts and students:</b> the method and formulas behind every number are one click away.</li>
      </ul>
      <div className="welcome-grid">
        <section className="hcard">
          <h2 className="q">Try an example</h2>
          <p className="muted">A fictional company, fully set up. It opens planned, so you can look around straight away. Change anything you like.</p>
          {err && <div className="banner error">The planning engine isn't answering: {err}. Start it with <code>uvicorn scp.api.app:app</code>.</div>}
          {!examples && !err && <div className="faint">Loading…</div>}
          <div className="stack" style={{ gap: 8 }}>
            {examples?.map((x) => (
              <button key={x.name} className="example" onClick={async () => openAndPlan(await api.example(x.name))}>
                <b>{x.title}</b>
                <span className="faint small">{x.locations} locations · {x.products} products</span>
              </button>
            ))}
          </div>
          {examples && examples.length === 0 && <Empty title="No examples found" />}
        </section>
        <section className="hcard">
          <h2 className="q">Start your own</h2>
          <p className="muted">An empty company with a Monday-to-Saturday calendar. Home shows what to fill in first, and the data
            check tells you what's still missing.</p>
          <div><button className="btn" onClick={blank}>Start with an empty company</button></div>
          <p className="muted small">Or open a file you exported earlier with <b>Import a file</b>, top right.</p>
        </section>
      </div>
      <p className="welcome-proof">Can you trust the numbers? Eight companies were worked out by hand and checked against the engine
        step by step, and one more flow runs over many generated companies. <a href={href("proof")}>See the proof</a></p>
    </div>
  );
}
