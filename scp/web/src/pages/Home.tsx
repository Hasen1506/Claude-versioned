// Home: the page a dataset opens on. It answers the questions people come with (will customers get what
// they need, what do I do this week, what does it cost, what is off track) from the results "Plan
// everything" calculates, and links each answer to the page where you act on it.
import { useEffect, useState, type ReactNode } from "react";
import { Edits } from "../components/ui";
import { api } from "../api/client";
import type { Dataset, Kpi, PlannedOrder } from "../api/types";
import { addDays, dayName, money, pct, plural, qty, unitMoney } from "../lib/format";
import { href } from "../lib/router";
import { earliestArrival } from "../lib/situations";
import { earnings } from "../lib/earnings";
import { guideDone } from "../lib/guide";
import { Checklist, setupTodo } from "../components/Checklist";
import { freshness, PLAN_STEPS, planFreshness, store, useStore, type RunKey } from "../state/store";

// ---- first-run guide: remembers which pages this browser has visited --------------------------------
const VISITED_KEY = "scp.visited.v1";
const GUIDE_KEY = "scp.guide.v1";

function readSet(key: string): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(key) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

/** Remember that a page was opened, so the guide can tick it off. */
export function markVisited(page: string) {
  const s = readSet(VISITED_KEY);
  if (s.has(page)) return;
  s.add(page);
  try {
    localStorage.setItem(VISITED_KEY, JSON.stringify([...s]));
  } catch {
    /* storage unavailable: the guide just doesn't tick */
  }
}

function Guide({ planned }: { planned: boolean }) {
  const [hidden, setHidden] = useState(() => {
    try {
      return localStorage.getItem(GUIDE_KEY) === "hidden";
    } catch {
      return false;
    }
  });
  if (hidden) return null;
  const seen = readSet(VISITED_KEY);
  const did = guideDone();
  const steps: { done: boolean; title: string; body: ReactNode; to?: string }[] = [
    { done: planned, title: "Plan everything", body: <>Calculates every result from your data. It never changes the data itself.</> },
    { done: seen.has("plan"), title: "See what will be late, and why", body: <>The supply plan: what to make, buy and move.</>, to: href("plan") },
    { done: did.has("check"), title: "Check a new customer order", body: <>When could you deliver it, and from where?</>, to: href("promise", "simulate") },
    { done: did.has("whatif"), title: "Try a what-if", body: <>Save a version, change something, compare the two.</>, to: href("versions") },
  ];
  const next = steps.findIndex((s) => !s.done);
  const close = () => {
    try {
      localStorage.setItem(GUIDE_KEY, "hidden");
    } catch {
      /* ignore */
    }
    setHidden(true);
  };
  return (
    <section className="guide" aria-label="Getting started">
      <div className="guide-title">
        <b>New here?</b>
        <span>Four things to try</span>
        <button className="linkish small" onClick={close}>Hide</button>
      </div>
      <ol>
        {steps.map((s, i) => {
          const inner = <>
            <span className="k" aria-hidden>{s.done ? "✓" : i + 1}</span>
            <span><b>{s.title}</b><span className="muted">{s.body}</span></span>
          </>;
          const cls = `${s.done ? "done" : ""} ${i === next ? "now" : ""}`;
          return <li key={s.title} className={cls}>{s.to ? <a href={s.to}>{inner}</a> : <div>{inner}</div>}
            <span className="sr">{s.done ? "(done)" : ""}</span></li>;
        })}
      </ol>
    </section>
  );
}

// ---- small building blocks ---------------------------------------------------------------------------

function Card({ q, attn, loading, children, links }: {
  q: string; attn?: boolean; loading?: boolean; children?: ReactNode; links?: { to: string; label: string }[];
}) {
  return (
    <section className={`hcard ${attn ? "attn" : ""}`} aria-label={q}>
      <h2 className="q">{q}</h2>
      {loading ? <div className="skeleton" aria-label="Not calculated yet"><span /><span /><span /></div> : children}
      {!loading && links && links.length > 0 && (
        <div className="links">{links.map((l) => <a key={l.to + l.label} href={l.to}>{l.label}</a>)}</div>
      )}
    </section>
  );
}

const TYPE_WORDS: Record<string, [string, string]> = {
  plant: ["plant", "plants"], dc: ["distribution centre", "distribution centres"], warehouse: ["warehouse", "warehouses"],
  store: ["store", "stores"], customer: ["customer channel", "customer channels"], supplier: ["supplier", "suppliers"],
};

const KIND_WORDS: Record<string, [string, string]> = {
  make: ["production run", "production runs"], buy: ["purchase", "purchases"], transfer: ["shipment", "shipments"],
};

function fmtKpi(k: Kpi, v: number | null, cur: string): string {
  if (v === null) return "—";
  if (k.unit === "ratio") return pct(v, 0);
  if (k.unit === "days") return `${qty(v)} days`;
  if (k.unit === "money_per_unit") return unitMoney(v, cur);
  return money(v, cur);
}

function targetText(k: Kpi, cur: string): string {
  if (k.target === null) return "";
  const t = fmtKpi(k, k.target, cur);
  return k.direction === "up" ? `target ${t} or more` : k.direction === "down" ? `target ${t} or less` : k.direction === "zero" ? `target within ±${t}` : `target ${t}`;
}

// ---- the page ----------------------------------------------------------------------------------------

/** Promise lines on the same day read as one (two ship-from places, one date). */
function byDay<T extends { date: string; qty: number; on_time: boolean }>(lines: T[]): T[] {
  const out: T[] = [];
  for (const l of lines) {
    const same = out.find((x) => x.date === l.date);
    if (same) same.qty += l.qty;
    else out.push({ ...l });
  }
  return out;
}

/** Forecast accuracy against real sales, from the weeks moved forward (as Actuals shows it). */
function realAccuracy(ds: Dataset): { accuracy: number; bias: number; weeks: number } | null {
  const recs = ds.accuracy ?? [];
  const f = recs.reduce((t, r) => t + r.forecast, 0), a = recs.reduce((t, r) => t + r.actual, 0);
  const e = recs.reduce((t, r) => t + Math.abs(r.forecast - r.actual), 0);
  if (!recs.length || a <= 0) return null;
  return { accuracy: Math.max(0, 1 - e / a), bias: (f - a) / a, weeks: new Set(recs.map((r) => r.start)).size };
}

export function Home({ ds }: { ds: Dataset }) {
  const s = useStore((x) => x);
  const planned = planFreshness(s);
  const loading = (key: RunKey) => !s.runs[key].data;
  const cur = ds.settings.currency;
  const start = ds.settings.planning_start;
  const end = addDays(start, ds.settings.horizon_days - 1);
  const year = new Date(start + "T00:00:00").getFullYear();
  const locations = ds.locations ?? [];
  const locName = Object.fromEntries(locations.map((l) => [l.id, l.name])) as Record<string, string>;
  const prodName = Object.fromEntries((ds.products ?? []).map((p) => [p.id, p.name])) as Record<string, string>;
  const byType = new Map<string, number>();
  locations.forEach((l) => byType.set(l.type, (byType.get(l.type) ?? 0) + 1));
  const shape = [...byType].map(([t, n]) => `${n} ${(TYPE_WORDS[t] ?? [t, t])[n === 1 ? 0 : 1]}`).join(", ");
  const weeks = Math.round(ds.settings.horizon_days / 7);

  const issues = s.validation?.issues ?? [];
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.length - errors;
  const blocked = !!s.validation?.blocking || s.schemaErrors.length > 0;
  const todo = setupTodo(s.validation);
  // still setting up and nothing calculated: show what's missing instead of empty answer cards
  const settingUp = (todo.length > 0 || blocked) && planned === "none";

  const plan = s.runs.plan.data?.ok ? s.runs.plan.data : null;
  const noStock = !(ds.location_products ?? []).some((x) => (x.on_hand ?? 0) > 0) && !(ds.movements ?? []).length;
  const prom = s.runs.promise.data?.ok ? s.runs.promise.data : null;
  const fin = s.runs.finance.data?.ok ? s.runs.finance.data : null;
  const inv = s.runs.inventory.data?.ok ? s.runs.inventory.data : null;
  const tow = s.runs.tower.data?.ok ? s.runs.tower.data : null;
  const fc = s.runs.forecast.data?.ok ? s.runs.forecast.data : null;
  const stale = (key: RunKey) => freshness(s, key) === "stale";

  // --- will customers get what they need?
  let serve: ReactNode = null;
  let serveAttn = false;
  if (plan) {
    const k = plan.kpis;
    const late = Math.max(0, k.independent_demand - k.on_time_qty);
    const risk = plan.exceptions.filter((e) => e.code === "DEMAND_AT_RISK").sort((a, b) => (b.qty ?? 0) - (a.qty ?? 0));
    serveAttn = late >= 0.5;
    const first = risk.map((e) => e.date).filter((d): d is string => !!d).sort()[0];
    const early = risk.map(earliestArrival).filter((d): d is string => !!d).sort()[0];
    serve = late < 0.5 ? (
      <p className="answer">Yes. All {qty(k.independent_demand)} units of demand are covered on time.</p>
    ) : (<>
      <p className="answer">{pct(k.on_time_fill_rate, 1)} on time. <em>{qty(late)} units</em> may arrive late or short.</p>
      <p className="muted">{first && <>The first is due {dayName(first, year)}. </>}
        {early && <>Nothing started today reaches these customers before {dayName(early, year)}, so earlier demand needs stock already
          there or on its way. </>}
        {risk.length > 0 && <>The largest: </>}</p>
      {risk.length > 0 && <ul className="plain">
        {risk.slice(0, 3).map((e, i) => <li key={i}><b>{qty(Math.round(e.qty ?? 0))}</b> {prodName[e.product ?? ""] ?? e.product} for {locName[e.location ?? ""] ?? e.location}</li>)}
        {risk.length > 3 && <li className="faint">and {plural(risk.length - 3, "more product and place", "more products and places")}</li>}
      </ul>}
    </>);
  }

  // --- customer orders
  let orders: ReactNode = null;
  if (prom) {
    const k = prom.kpis;
    const off = prom.orders.filter((o) => o.status !== "on_time").sort((a, b) => a.requested.localeCompare(b.requested));
    const o = off[0];
    orders = k.orders === 0 ? <p className="answer">No open customer orders.</p> : (<>
      <p className="answer">{k.on_time_orders === k.orders ? `All ${k.orders} on time.` : <><em>{k.on_time_orders} of {k.orders}</em> on time.</>}</p>
      {o && <p className="muted"><b>{o.order}</b>, {qty(o.qty)} {prodName[o.product] ?? o.product} for {locName[o.location] ?? o.location}:{" "}
        {byDay(o.lines).map((l, i) => <span key={i}>{i > 0 && ", "}{qty(l.qty)} on {dayName(l.date, year)}{l.on_time ? " as asked" : ""}</span>)}
        {o.unconfirmed > 0 && <>{o.lines.length ? ", " : ""}{qty(o.unconfirmed)} can't be promised yet</>}.
        {off.length > 1 && <> {plural(off.length - 1, "other order")} also can't be met in full on time.</>}</p>}
      {k.at_risk_orders > 0 && <p className="muted">{plural(k.at_risk_orders, "promised order")} would now be at risk.</p>}
    </>);
  }

  // --- this week
  let week: ReactNode = null;
  let weekAttn = false;
  if (plan) {
    const cut = addDays(start, 7);
    const wk = plan.orders.filter((o: PlannedOrder) => o.start_date < cut);
    const past = wk.filter((o) => o.start_in_past);
    weekAttn = past.length > 0;
    const kinds = (["make", "buy", "transfer"] as const).map((kind) => [kind, wk.filter((o) => o.kind === kind)] as const).filter(([, l]) => l.length);
    week = wk.length === 0 ? <p className="answer">Nothing needs to start this week.</p> : (<>
      <p className="answer">{plural(wk.length, "order")} start by {dayName(addDays(start, 6), year)}.</p>
      <ul className="plain">
        {kinds.map(([kind, l]) => {
          const at = [...new Set(l.map((o) => locName[o.location] ?? o.location))];
          return <li key={kind}>{qty(l.length)} {KIND_WORDS[kind][l.length === 1 ? 0 : 1]}
            {kind !== "transfer" && at.length <= 2 && <span className="faint"> at {at.join(" and ")}</span>}</li>;
        })}
      </ul>
      {past.length > 0 && <p className="muted"><em>{qty(past.length)} of them should already have started.</em> Starting them today loses the least time.
        {noStock && <> No stock on hand has been entered, so the plan starts every place from zero; <a href={href("execution", "count")}>count today's stock</a> for a realistic first plan.</>}</p>}
    </>);
  }

  // --- money
  let moneyBody: ReactNode = null;
  if (plan) {
    const { revenue: rev, margin: mar, unpriced } = fin ? earnings(fin.serve) : { revenue: 0, margin: 0, unpriced: [] as string[] };
    const t = inv?.totals;
    moneyBody = (<>
      <dl className="kv">
        <dt>Plan cost, whole horizon</dt><dd>{money(plan.kpis.total_cost, cur)}</dd>
        {fin && rev > 0 && <><dt>Revenue</dt><dd>{money(rev, cur)}</dd>
          <dt>Margin</dt><dd>{money(mar, cur)} · {pct(mar / rev, 0)}</dd></>}
        {fin && unpriced.length > 0 && <><dt>{rev > 0 ? "Not in revenue" : "Revenue"}</dt>
          <dd>{plural(unpriced.length, "product")} without a selling price · <a href={href("setup", "products")}>set prices</a></dd></>}
        <dt>Average stock value</dt><dd>{money(plan.kpis.inventory_value_avg, cur)}</dd>
      </dl>
      {t && t.saving_vs_current > 0.5 && <p className="muted">Safety stock worth {money(t.current_ss_value, cur)} today could be{" "}
        <em>{money(t.meio_ss_value, cur)}</em> if placed where it protects most, saving {money(t.saving_vs_current, cur)} a year to carry.</p>}
    </>);
  }

  // --- off track
  let track: ReactNode = null;
  if (tow) {
    const scored = tow.kpis.filter((k) => k.status !== "none");
    const bad = scored.filter((k) => k.status === "critical" || k.status === "warning")
      .sort((a, b) => (a.status === b.status ? 0 : a.status === "critical" ? -1 : 1));
    const off = bad.filter((k) => k.status === "critical").length;
    const open = tow.worklist.filter((w) => w.status === "open" || w.status === "acknowledged").length;
    track = (<>
      <p className="answer">{bad.length === 0 ? (scored.length === 0 ? "Nothing to measure yet." : scored.length === 1 ? "The one measure with data is on target." : `All ${scored.length} measures on target.`) : <>{off ? <><em>{off} of {scored.length}</em> measures off target</> : "None off target"}{bad.length > off && `, ${bad.length - off} near it`}.</>}</p>
      {bad.length > 0 && <ul className="plain meters">
        {bad.slice(0, 4).map((k) => (
          <li key={k.id}><span className={`sq ${k.status}`} aria-hidden />{k.name}
            <span className="num">{fmtKpi(k, k.value, cur)}</span><span className="faint small">{targetText(k, cur)}</span></li>
        ))}
      </ul>}
      <p className="muted">{open === 0 ? "Nothing on the follow-up list." : `${plural(open, "item")} on the follow-up list.`}</p>
    </>);
  }

  // --- data check
  const dataCard = (
    <Card q="Is the data good enough to plan?" attn={blocked} loading={!s.validation && !s.schemaErrors.length}
      links={[{ to: href("readiness"), label: errors || todo.length ? "See what's missing" : issues.length ? "See the warnings" : "See the data check" }]}>
      {s.schemaErrors.length ? <p className="answer"><em>No.</em> {plural(s.schemaErrors.length, "value")} can't be read.</p>
        : errors ? <p className="answer"><em>Not yet.</em> {plural(errors, "problem")} stop planning.</p>
        : todo.length ? <p className="answer"><em>Not yet.</em> {plural(todo.length, "thing")} still to set up.</p>
        : <p className="answer">Yes.{warnings ? ` ${plural(warnings, "warning")} worth a look.` : " No problems found."}</p>}
      {(s.validation?.set_aside?.length ?? 0) > 0 && <p className="muted">{plural(s.validation!.set_aside!.length, "unfinished record")} {s.validation!.set_aside!.length === 1 ? "is" : "are"} left
        out of the plan until {s.validation!.set_aside!.length === 1 ? "it is" : "they are"} finished.</p>}
      {(() => {
        // two different numbers (R22): against the sales that really happened once weeks were moved forward, and a
        // backtest (the forecast made again for weeks already in the history)
        const real = realAccuracy(ds);
        const test = fc && fc.summary.wape !== null && (ds.history ?? []).length > 0 ? fc.summary : null;
        const side = (b: number | null | undefined) => b !== null && b !== undefined && Math.abs(b) >= 0.005 ? `, ${pct(Math.abs(b), 0)} on the ${b > 0 ? "high" : "low"} side` : "";
        if (!real && !test) return null;
        return <p className="muted">
          {real && <>Against real sales the forecast was <b>{pct(real.accuracy, 0)}</b> accurate over {plural(real.weeks, "week")}{side(real.bias)}. </>}
          {test && <>Tried on past weeks of the sales history (a backtest) it scores {pct(1 - test.wape!, 0)}{side(test.bias)}.</>}
          {!real && test && <> Its accuracy against real sales shows once weeks are moved forward (Actuals).</>}
        </p>;
      })()}
    </Card>
  );

  const staleNote = (keys: RunKey[]) => keys.some(stale) ? <span className="stale-tag">out of date</span> : null;

  return (
    <div className="home animate-in">
      <header className="home-head">
        <div>
          <h1>Plan for {dayName(start, year)} to {dayName(end, year)}</h1>
          <p className="muted">{weeks} weeks · {shape || "no locations yet"}</p>
        </div>
      </header>

      <Status />
      {!!s.company?.pending && <div className="banner info" role="status">
        <span><b>{plural(s.company.pending, "master data change")} {s.company.pending === 1 ? "waits" : "wait"} for approval.</b>{" "}
          {s.company.role === "viewer" ? "A planner or owner approves them." : "Someone other than who made each one approves it."}</span>
        <a href={href("history")}>See {s.company.pending === 1 ? "it" : "them"}</a>
      </div>}
      {locations.length > 0 && !settingUp && <StockAlert ds={ds} />}
      {locations.length > 0 && !settingUp && <Guide planned={planned !== "none"} />}

      {locations.length === 0 ? (
        <section className="hcard attn">
          <h2 className="q">Your network is empty</h2>
          <p>Start with the places goods move between: plants, warehouses, suppliers and customers. Then add products,
            how each is made or bought, and the demand to plan for. A checklist here tells you what is still missing.</p>
          <p className="muted">Already have this in spreadsheets? Every table can be uploaded from CSV or Excel.</p>
          <div className="links"><a href={href("setup", "network")}>Set up the network</a><a href={href("data", "locations")}>Upload places from a spreadsheet</a></div>
        </section>
      ) : settingUp ? (
        <div className="stack">
          <section className="hcard attn" aria-label="Finish setting up">
            <h2 className="q">Finish setting up</h2>
            <p className="answer">{todo.length ? `${plural(todo.length, "thing")} to do before the plan means something.` : "Fix the data problems first."}</p>
            <Checklist items={s.validation?.setup ?? []} compact />
          </section>
          {dataCard}
        </div>
      ) : (
        <div className="hgrid">
          <Card q="Will customers get what they need?" attn={serveAttn} loading={loading("plan")}
            links={[{ to: href("plan"), label: serveAttn ? "See which, and why" : "Open the supply plan" }]}>
            {staleNote(["plan"])}{serve}
          </Card>
          <Card q="Customer orders" loading={loading("promise")}
            links={[{ to: href("promise"), label: "Open orders" },
              ...(prom && prom.kpis.on_time_orders < prom.kpis.orders ? [{ to: href("promise", "bop"), label: "Try to bring late orders forward" }] : []),
              { to: href("promise", "simulate"), label: "Check a new order" }]}>
            {staleNote(["promise"])}{orders}
          </Card>
          <Card q="What to do this week" attn={weekAttn} loading={loading("plan")}
            links={[{ to: href("plan", "orders"), label: "Review this week's orders" }]}>
            {staleNote(["plan"])}{week}
          </Card>
          <Card q="Money" loading={loading("plan")}
            links={[{ to: href("finance"), label: "Cost and margin" }, ...(inv?.totals && inv.totals.saving_vs_current > 0.5 ? [{ to: href("inventory"), label: "Where safety stock should sit" }] : [])]}>
            {staleNote(["plan", "finance", "inventory"])}{moneyBody}
          </Card>
          <Card q="What's off track?" loading={loading("tower")}
            links={[{ to: href("tower"), label: "All measures and the follow-up list" }]}>
            {staleNote(["tower"])}{track}
          </Card>
          {dataCard}
        </div>
      )}
    </div>
  );
}

/** Stock the plan starts from that the goods movements disagree with comes first: every answer below builds on it (Q15). */
function StockAlert({ ds }: { ds: Dataset }) {
  const act = useStore((x) => x.runs.actuals.data);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!act) return null;
  const u = act.unbooked;
  const off = act.stock.filter((r) => r.movement_stock !== null && Math.abs(r.difference) > 1e-6).length;
  const neg = act.stock.filter((r) => r.negative_on).length;
  if (!u?.needed && !off && !neg) return null;
  const book = async () => {
    setBusy(true);
    setErr(null);
    try {
      const out = await api.roll(ds, ds.settings.planning_start);
      store.replace(out.dataset, ds);
      await store.run("actuals");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };
  const what = u?.needed ? [u.stock && `stock at ${plural(u.stock, "place")}`, u.orders && plural(u.orders, "order"),
    u.accuracy_weeks && `forecast accuracy for ${plural(u.accuracy_weeks, "week")}`].filter(Boolean).join(", ") : "";
  return (
    <section className="hcard attn" aria-label="Stock needs attention" style={{ marginBottom: 16 }}>
      <h2 className="q">Is the stock the plan starts from right?</h2>
      <p className="answer"><em>Not quite.</em>{" "}
        {u?.needed ? <>Movements posted late are not counted yet{what ? `: they change ${what}` : ""}.</>
          : off ? <>{plural(off, "place")} {off === 1 ? "has" : "have"} stock that the goods movements disagree with.</> : null}
        {neg > 0 && <> {plural(neg, "place")} would go below zero: a receipt is missing or posted late.</>}</p>
      <p className="muted">Every answer below starts from this stock, so it comes first.</p>
      <div className="links">
        {(u?.needed || off > 0) && <Edits><button className="btn sm accent" onClick={book} disabled={busy}>{busy ? "Counting…" : "Count the movements now"}</button></Edits>}
        <a href={href("execution", "stock")}>See which places</a><a href={href("execution", "count")}>Count stock</a>
      </div>
      {err && <p className="small" style={{ color: "var(--error-text)" }}>{err}</p>}
    </section>
  );
}

/** How long a step has run, once it runs long (a large company's forecast takes minutes): the page is not stuck. */
function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const s = Math.floor((now - since) / 1000);
  if (s < 5) return null;
  return <>, {s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`} so far</>;
}

/** One line under the page title: what "Plan everything" is doing, or whether the results are current. */
function Status() {
  const s = useStore((x) => x);
  const f = planFreshness(s);
  const blocked = !!s.validation?.blocking || s.schemaErrors.length > 0;
  if (!s.dataset?.locations?.length) return <div className="status" role="status">Nothing to plan yet: the network is empty.</div>;
  if (s.planning) {
    const p = s.planning;
    return (
      <div className="status running" role="status">
        <div className="progress" aria-hidden><i style={{ width: `${(p.done / p.of) * 100}%` }} /></div>
        <span>{p.label}… <span className="faint">step {p.done + 1} of {p.of}<Elapsed since={p.since} /></span></span>
      </div>
    );
  }
  if (s.engineError) return <div className="status bad" role="status">The planning engine isn't answering. Results can't be calculated until it is back.</div>;
  if (blocked) return (
    <div className="status bad" role="status">Planning is blocked until the data problems below are fixed.
      <a href={href("readiness")}>Open the data check</a></div>
  );
  const todo = setupTodo(s.validation);
  if (f === "none" && todo.length) return (
    <div className="status" role="status">Not ready to plan yet: {plural(todo.length, "thing")} still to set up.
      <a href={href("readiness")}>Open the checklist</a></div>
  );
  if (f === "none" && Object.values(s.runs).some((r) => r.running)) return (
    <div className="status" role="status">Calculating the plan from the latest save…</div>
  );
  if (f === "none") return (
    <div className="status" role="status">Nothing calculated yet.
      <button className="btn sm" onClick={() => store.planAll()}>Plan everything</button></div>
  );
  // a step that failed is said as such, not as data that changed (at scale a failed answer was shown that way)
  const failed = PLAN_STEPS.filter((p) => s.runs[p.key].error && !s.runs[p.key].running);
  if (failed.length) return (
    <div className="status bad" role="status">{failed.map((p) => p.label).join(", ")} did not finish: {s.runs[failed[0].key].error}
      <button className="btn sm" onClick={() => store.planAll()}>Plan everything again</button></div>
  );
  if (f === "stale" && PLAN_STEPS.some((p) => !s.runs[p.key].data)) return (
    <div className="status warn" role="status">Some answers are not calculated yet.
      <button className="btn sm" onClick={() => store.planAll()}>Plan everything</button></div>
  );
  if (f === "stale") return (
    <div className="status warn" role="status">The data changed after the last calculation, so some answers are out of date.
      <button className="btn sm" onClick={() => store.planAll()}>Plan everything again</button></div>
  );
  const at = s.runs.tower.at ?? s.runs.plan.at;
  return <div className="status ok" role="status"><span className="tick" aria-hidden>✓</span>Everything is up to date{at ? `, calculated at ${at.slice(0, 5)}` : ""}.</div>;
}
