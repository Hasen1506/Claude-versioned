import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";
import type { Dataset, ExampleInfo } from "./api/types";
import { Badge, Empty, ThemeSwitch } from "./components/ui";
import { setPlanYear } from "./lib/format";
import { href, go, useRoute } from "./lib/router";
import { NAV, PAGES, navItemFor, type NavItem } from "./lib/nav";
import { Demand } from "./pages/Demand";
import { Buying } from "./pages/Buying";
import { Selling } from "./pages/Selling";
import { Execution } from "./pages/Execution";
import { Finance } from "./pages/Finance";
import { Home, markVisited } from "./pages/Home";
import { Tower } from "./pages/Tower";
import { Versions } from "./pages/Versions";
import { WhatIf } from "./pages/WhatIf";
import { Inventory } from "./pages/Inventory";
import { Promising } from "./pages/Promising";
import { Proof } from "./pages/Proof";
import { Schedule } from "./pages/Schedule";
import { Sop } from "./pages/Sop";
import { MasterData } from "./pages/MasterData";
import { Network } from "./pages/Network";
import { Plan } from "./pages/Plan";
import { Readiness } from "./pages/Readiness";
import { Setup } from "./pages/Setup";
import { blankCompany, CompanyForm, nextMonday, type CompanyValues } from "./pages/Company";
import { Material } from "./pages/Material";
import { Machines } from "./pages/Machines";
import { Capacity } from "./pages/Capacity";
import { Account, CompanyList, SignIn, useAuthConfig } from "./pages/Account";
import { History } from "./pages/History";
import { Connections } from "./pages/Connections";
import { SaveBanner, SaveChip } from "./components/SaveStatus";
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

  setPlanYear(ds?.settings.planning_start);   // idempotent: dates print their year only outside the planning year
  const page = route[0] || "home";
  useEffect(() => { if (ds) markVisited(page); }, [page, ds]);
  const item = ds ? navItemFor(page) : undefined;
  const [navOpen, setNavOpen] = useState(false);   // phones: the rail opens over the page from the Menu button
  useEffect(() => setNavOpen(false), [route.join("/")]);
  return (
    <div className={`app ${navOpen ? "nav-open" : ""}`}>
      <TopBar navOpen={navOpen} onNav={() => setNavOpen((o) => !o)} />
      {navOpen && <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden />}
      {ds ? <Rail page={page} /> : (
        <nav className="rail" id="main-nav" aria-label="Main">
          <div className="rail-group">
            <a className={`rail-item ${page !== "proof" && page !== "account" ? "active" : ""}`} href="#/">Start</a>
            <a className={`rail-item ${page === "account" ? "active" : ""}`} href={href("account")}>Sign in and companies</a>
            <a className={`rail-item ${page === "proof" ? "active" : ""}`} href={href("proof")}>Proof</a>
          </div>
        </nav>
      )}
      <main className="main">
        {item?.tabs && <SectionTabs item={item} page={page} />}
        <SaveBanner />
        {page === "proof" ? <Proof route={route} />
          : page === "account" ? <Account route={route} />
          : !ds ? <div className="content"><Welcome /></div>
          : page === "data" ? <MasterData route={route} />
          : page === "settings" ? <MasterData route={["data", "settings"]} />
          : page === "readiness" ? <Readiness />
          : page === "setup" ? <Setup route={route} />
          : page === "material" ? <Material route={route} />
          : page === "machines" ? <Machines route={route} />
          : page === "capacity" ? <Capacity route={route} />
          : page === "network" ? <Network route={route} />
          : page === "demand" ? <Demand route={route} />
          : page === "inventory" ? <Inventory route={route} />
          : page === "sop" ? <Sop route={route} />
          : page === "plan" ? <Plan route={route} />
          : page === "schedule" ? <Schedule route={route} />
          : page === "promise" ? <Promising route={route} />
          : page === "execution" ? <Execution route={route} />
          : page === "buying" ? <Buying route={route} />
          : page === "selling" ? <Selling route={route} />
          : page === "finance" ? <Finance route={route} />
          : page === "tower" ? <Tower route={route} />
          : page === "versions" ? <Versions />
          : page === "whatif" ? <WhatIf />
          : page === "history" ? <History />
          : page === "connections" ? <Connections route={route} />
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
  // nothing worth calculating yet: no places, or the checklist still has things to do (e.g. no demand at all)
  const empty = useStore((s) => !s.dataset?.locations?.length || (s.validation?.setup ?? []).some((i) => i.status === "todo"));
  if (planning) {
    return <button className="btn plan-btn" disabled aria-live="polite">
      <span className="spin" aria-hidden />Planning… {planning.done + 1}/{planning.of}</button>;
  }
  return (
    <button className={`btn plan-btn ${f !== "fresh" && !blocked && !empty ? "accent" : ""}`} onClick={() => store.planAll()}
      title={blocked ? "Fix the data problems first (Setup → Data check)" : empty ? "Your company isn't fully set up yet: see the Data check" : "Calculate every result from the current data. Your data is not changed."}>
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

function TopBar({ navOpen, onNav }: { navOpen: boolean; onNav: () => void }) {
  const ds = useStore((s) => s.dataset);
  const canUndo = useStore((s) => s.canUndo);
  const canRedo = useStore((s) => s.canRedo);
  const undoElsewhere = useStore((s) => s.undoElsewhere);
  const redoElsewhere = useStore((s) => s.redoElsewhere);
  const where = (id: string) => PAGES.find((p) => p.id === id)?.label ?? (id === "data" ? "Master data" : id);
  const engineError = useStore((s) => s.engineError);
  const schemaBad = useStore((s) => s.schemaErrors.length > 0);
  const file = useRef<HTMLInputElement>(null);
  const version = useStore((s) => s.version);
  const modified = useStore(isModified);
  const company = useStore((s) => s.company);
  const session = useStore((s) => s.session);

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
      <button className="btn ghost nav-toggle" aria-expanded={navOpen} aria-controls="main-nav" onClick={onNav}>{navOpen ? "✕ Close" : "☰ Menu"}</button>
      <a className="brand" href={ds ? href("home") : "#/"} aria-label="Home"><span className="brand-mark">S</span><span className="brand-name">SCP</span></a>
      {ds && <span className="company" title={ds.settings.company_name}>{ds.settings.company_name}</span>}
      {ds && <SaveChip />}
      {ds && version && (!company || company.live) && <a className="version-chip" href={href("versions")} title="Versions and what-ifs: save, branch and compare">
        {version.name} · {version.kind}{modified && <span className="mod"> · unsaved changes</span>}</a>}
      {ds && engineError && <Badge sev="error">Engine not answering</Badge>}
      {ds && !engineError && schemaBad && <a href={href("readiness")}><Badge sev="error">Invalid values</Badge></a>}
      <span className="spacer" />
      {ds && <>
        <PlanButton />
        <button className="btn ghost icon-btn" aria-label="Undo" disabled={!canUndo} onClick={() => store.undo()}
          title={undoElsewhere ? `The last change was made on ${where(undoElsewhere)}: open it to undo it` : "Undo the last change on this screen (Ctrl+Z)"}>↶</button>
        <button className="btn ghost icon-btn" aria-label="Redo" disabled={!canRedo} onClick={() => store.redo()}
          title={redoElsewhere ? `The change to redo was made on ${where(redoElsewhere)}: open it to redo it` : "Redo on this screen (Ctrl+Shift+Z)"}>↷</button>
      </>}
      {!ds && <button className="btn" onClick={() => file.current?.click()}>Import a file</button>}
      <Menu label="More">
        {ds && <>
          <button role="menuitem" data-close onClick={() => file.current?.click()}>Import a dataset file…</button>
          <button role="menuitem" data-close onClick={exportJson}>Export this dataset</button>
          <a role="menuitem" data-close href={href("versions")}>Versions and what-ifs</a>
          <a role="menuitem" data-close href={href("whatif")}>What if… side by side</a>
          {company && <a role="menuitem" data-close href={href("history")}>History: who changed what</a>}
          {company?.live && <a role="menuitem" data-close href={href("connections")}>Connections: ERP, imports, e-mail</a>}
          <a role="menuitem" data-close href={href("proof")}>Proof: check the numbers</a>
          <hr />
        </>}
        <a role="menuitem" data-close href={href("account")}>{session ? `${session.user.name}: companies and people` : "Sign in"}</a>
        <div className="menu-row"><span>Theme</span><ThemeSwitch /></div>
        {ds && <>
          <hr />
          <button role="menuitem" data-close onClick={() => {
            const ask = company ? `Close ${company.name} on this browser? It stays on the server.` : "Close this dataset? Export it first if you want to keep it.";
            if (window.confirm(ask)) { store.clear(); go(); }
          }}>{company ? "Close the company" : "Close dataset"}</button>
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
  const offTrack = tower?.ok ? tower.kpis.filter((k) => k.status === "critical").length : 0;
  const active = navItemFor(page);
  const live = !!s.company?.live;
  const right = (it: NavItem) => {
    if (it.id === "network" && errors) return <Badge sev="error">{errors}</Badge>;
    if (it.id === "tower" && offTrack && freshness(s, "tower") !== "none") return <span className="rail-count" title={`${offTrack} measures off target`}>{offTrack}</span>;
    if (!it.run || s.planning || !s.dataset?.locations?.length) return null;
    const f = freshness(s, it.run);
    if (f === "fresh") return null;
    return <span className={`rail-dot ${f}`} title={f === "stale" ? "Out of date: the data changed after this was calculated" : "Not calculated yet"}>
      <span className="sr">{f === "stale" ? "out of date" : "not calculated"}</span></span>;
  };
  return (
    <nav className="rail" id="main-nav" aria-label="Main">
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
        <a className={page === "whatif" ? "active" : ""} href={href("whatif")}>What if… side by side</a>
        <a className={page === "account" || page === "history" ? "active" : ""} href={href("account")}>Sign in, companies, people</a>
        {live && <a className={page === "connections" ? "active" : ""} href={href("connections")}>Connections</a>}
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
  const session = useStore((s) => s.session);
  const config = useAuthConfig();
  const locked = !!config?.require_signin && !session;
  useEffect(() => {
    if (locked || !config) return;
    api.examples().then(setExamples).catch((e) => setErr(String(e)));
  }, [locked, config, session]);
  const [starting, setStarting] = useState(false);
  const [createErr, setCreateErr] = useState<string | null>(null);
  const opening = useRef(0);
  useEffect(() => () => { opening.current++; }, []);
  const blank = async (v: CompanyValues) => {
    const context = store.captureContext();
    const request = ++opening.current;
    const ds = blankCompany(v);
    // signed in: the company is kept on the server from the start (R28), not first in this browser only
    if (session) {
      setCreateErr(null);
      try {
        const m = await api.createCompany(ds, "created");
        if (request !== opening.current || !store.currentContext(context, true)) return;
        const doc = await api.company(m.id);
        if (request !== opening.current) return;
        store.openCompany(doc, context);
        go("setup");
        return;
      } catch (e) {
        if (request !== opening.current || !store.currentContext(context, true)) return;
        setCreateErr(`Not kept on the server (${e instanceof Error ? e.message : String(e)}): it is in this browser only for now.`);
      }
    }
    if (request !== opening.current || !store.currentContext(context, true)) return;
    store.load(ds);
    go("setup");
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
      {(session || config?.require_signin) && <div className="welcome-grid" style={{ marginBottom: 16 }}>
        <section className="hcard">
          <h2 className="q">{session ? `Your companies, ${session.user.name}` : "Sign in to open your company"}</h2>
          {session ? <CompanyList /> : <SignIn config={config} />}
        </section>
      </div>}
      {!locked && <div className="welcome-grid">
        <section className="hcard">
          <h2 className="q">Try an example</h2>
          <p className="muted">A fictional company, fully set up. It opens planned, so you can look around straight away. Change anything you like.</p>
          {err && <div className="banner error">The planning engine isn't answering: {err}. Start it with <code>uvicorn scp.api.app:app</code>.</div>}
          {!examples && !err && <div className="faint">Loading…</div>}
          <div className="stack" style={{ gap: 8 }}>
            {examples?.map((x) => (
              <button key={x.name} className="example" onClick={async () => {
                const context = store.captureContext();
                const request = ++opening.current;
                try {
                  const ds = await api.example(x.name);
                  if (request === opening.current && store.currentContext(context, true)) openAndPlan(ds);
                } catch (e) { if (request === opening.current && store.currentContext(context)) setErr(String(e)); }
              }}>
                <b>{x.title}</b>
                <span className="faint small">{x.locations} locations · {x.products} products</span>
              </button>
            ))}
          </div>
          {examples && examples.length === 0 && <Empty title="No examples found" />}
        </section>
        <section className="hcard">
          <h2 className="q">Start your own</h2>
          <p className="muted">Name your company, its currency and working week, then set up places, products and demand step by step.
            Home shows what to fill in next.</p>
          {starting ? <CompanyForm ds={null} submit={blank} submitLabel="Create the company" cancel={() => setStarting(false)}
            initial={{ name: "", currency: "INR", start: nextMonday(), workdays: [0, 1, 2, 3, 4], cover: "week", fx: {} }} />
            : <div><button className="btn" onClick={() => setStarting(true)}>Start with an empty company</button></div>}
          <p className="muted small">Or open a file you exported earlier with <b>Import a file</b>, top right.</p>
          {!session && <p className="muted small">To work on it with colleagues and keep it safe on the server, <a href={href("account")}>sign in</a>.</p>}
          {session && <p className="muted small">Signed in as {session.user.name}: the company is kept on the server, and you are its owner.</p>}
          {createErr && <div className="banner warning">{createErr}</div>}
        </section>
      </div>}
      <p className="welcome-proof">Can you trust the numbers? Eight companies were worked out by hand and checked against the engine
        step by step, and one more flow runs over many generated companies. <a href={href("proof")}>See the proof</a></p>
    </div>
  );
}

