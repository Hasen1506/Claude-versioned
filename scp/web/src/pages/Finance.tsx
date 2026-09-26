import { useMemo, useState } from "react";
import type { CapacityAppraisal, Dataset, FinanceResult, ServeRow } from "../api/types";
import { BucketChart } from "../components/charts";
import {
  Badge, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, RunButton, Term,
} from "../components/ui";
import { money, pct, qty, unitMoney } from "../lib/format";
import { go } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "overview" | "serve" | "inventory" | "capacity";

// Plan cost categories in a fixed colour order (identity follows the category, never its rank);
// stock and firm receipts consumed are already committed, so they share one neutral key.
const CATS: { id: string; label: string; color: string }[] = [
  { id: "purchase", label: "Purchase", color: "var(--series-1)" },
  { id: "production", label: "Production", color: "var(--series-2)" },
  { id: "setup", label: "Setup", color: "var(--series-3)" },
  { id: "ordering", label: "Ordering", color: "var(--series-4)" },
  { id: "transport", label: "Transport", color: "var(--series-5)" },
  { id: "handling", label: "Handling", color: "var(--series-6)" },
  { id: "holding", label: "Holding", color: "var(--series-7)" },
];
const COMMITTED = { label: "Stock & firm receipts", color: "var(--text-3)" };
const TYPE_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

export function Finance({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.finance);
  const res = run.data;
  const ds = useStore((s) => s.dataset)!;
  const stale = useStore((s) => isStale(s, "finance"));
  const view = ((route[1] as View) || "overview") as View;
  const cur = ds.settings.currency;

  const head = (
    <StageHeader title="Money" kicker="What the plan costs, what each customer and product earns, what the stock is worth, and whether extra capacity would pay."
      how={<>Every cost in the supply plan is traced to the demand it serves along the <Term t="Pegging">pegging</Term>; what no demand
        absorbs is kept separate, so the totals reconcile category by category. Stock is valued week by week. Capacity investments
        are appraised on the capacity plan: <Term t="Shadow price">shadow prices</Term> first, confirmed by solving again with the
        extra capacity, then <Term t="NPV" />.</>}
      answer={res?.reconciliation && moneyAnswer(res, cur, ds.settings.horizon_days)}
      right={<>
      {res && <Provenance kind="derived" at={run.at} stale={stale} />}
      <RunButton running={run.running} has={!!res} onClick={() => store.run("finance")} /></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;
  const nav = (
    <Tabs<View> value={view} onChange={(v) => go("finance", v)} tabs={[
      { id: "overview", label: "Summary" },
      { id: "serve", label: "Cost to serve & margin", count: res?.serve.length },
      { id: "inventory", label: "Inventory value", count: res?.inventory?.locations.length },
      { id: "capacity", label: "Capacity investments", count: ds.finance?.capacity_options?.length ?? 0 },
    ]} />
  );
  if (run.error) return body(<div className="banner error"><Badge sev="error">Could not cost the plan</Badge>{run.error}</div>);
  if (!res) {
    return body(<>
      <SolverIO answers="What the plan costs by category and whether that reconciles, what it costs to serve each customer and product and the margin left, what the stock is worth over time, and whether a capacity investment pays back."
        from="The supply plan (orders, pegging, projected stock), unit values and carrying rate, selling prices, and for investments the S&OP plan and its shadow prices."
        feeds="Pricing and customer decisions, the capacity business case, the control tower's cost-to-serve KPI." />
      <div style={{ height: 14 }} />
      {view === "capacity" ? <>{nav}<OptionsEditor ds={ds} /></> : <Panel><Empty title="Not costed yet">
        <p>Costing runs the supply plan and follows its pegging. {ds.finance?.capacity_options?.length ?? 0} capacity options are set up.</p>
      </Empty></Panel>}
    </>);
  }
  if (!res.ok || !res.reconciliation || !res.inventory) {
    return body(<div className="banner error"><Badge sev="error">No plan to cost</Badge>The supply plan is blocked by readiness errors.</div>);
  }
  return body(<>
    {stale && <StaleMark what="costing" onRerun={() => store.run("finance")} busy={run.running} />}
    {nav}
    {view === "overview" && <Overview res={res} cur={cur} ds={ds} />}
    {view === "serve" && <Serve res={res} cur={cur} />}
    {view === "inventory" && <Inventory res={res} cur={cur} />}
    {view === "capacity" && <Capacity res={res} cur={cur} ds={ds} sel={route[2]} />}
  </>);
}

function moneyAnswer(res: FinanceResult, cur: string, days: number) {
  const revenue = res.serve.reduce((a, r) => a + r.revenue, 0);
  const margin = res.serve.reduce((a, r) => a + r.margin, 0);
  return <>The plan costs {money(res.reconciliation!.total_plan, cur)} over {days} days.{revenue > 0
    ? <> The demand it serves brings in {money(revenue, cur)}, leaving a margin of {money(margin, cur)} ({pct(margin / revenue, 0)}).</>
    : <> Set selling prices on products to see revenue and margin.</>}</>;
}

// ------------------------------------------------------------------------------------------------
function Overview({ res, cur, ds }: { res: FinanceResult; cur: string; ds: Dataset }) {
  const rec = res.reconciliation!;
  const inv = res.inventory!;
  const revenue = res.serve.reduce((a, r) => a + r.revenue, 0);
  const margin = res.serve.reduce((a, r) => a + r.margin, 0);
  const servedCost = res.serve.reduce((a, r) => a + r.total_cost, 0);
  const turns = inv.avg > 0 ? (servedCost * 365) / ds.settings.horizon_days / inv.avg : null;
  const maxPlan = Math.max(1, ...rec.lines.map((l) => l.plan));
  const reasons = Object.entries(rec.unabsorbed_reasons).sort((a, b) => b[1] - a[1]);
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Plan cost" value={money(rec.total_plan, cur)} sub={`${ds.settings.horizon_days} days`} tone="ink" />
        <StatTile label="Serves demand" value={money(rec.total_served, cur)} sub={`${pct(rec.total_plan ? rec.total_served / rec.total_plan : 0, 1)} of plan cost`} />
        <StatTile label="Unabsorbed" value={money(rec.total_unabsorbed, cur)} sub="no demand pegged to it" />
        <StatTile label="Revenue served" value={money(revenue, cur)} sub={`${res.serve.length} demand points`} />
        <StatTile label="Margin" value={money(margin, cur)} sub={revenue > 0 ? `${pct(margin / revenue, 1)} of revenue` : "no prices set"} />
        <StatTile label="Avg inventory value" value={money(inv.avg, cur)} sub={turns !== null ? `${turns.toFixed(1)} turns a year` : "—"} />
      </div>
      {rec.reconciled
        ? <div className="banner ok"><Badge sev="ok">Books balance</Badge>Every cost in the plan is accounted for, either against the demand it serves or as unabsorbed.</div>
        : <div className="banner error"><Badge sev="error">Does not reconcile</Badge>A category's allocation differs from the plan. This is an engine defect: report it with the dataset.</div>}
      <div className="grid-2" style={{ alignItems: "start" }}>
        <Panel flush title="Cost reconciliation">
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Category</th><th className="num">Plan KPI</th><th className="num">Σ sources</th><th className="num">Served</th>
                <th className="num">Unabsorbed</th><th className="num">Δ</th><th style={{ width: "30%" }}>Served · unabsorbed</th></tr></thead>
              <tbody>
                {rec.lines.map((l) => {
                  const c = CATS.find((x) => x.id === l.category)!;
                  return (
                    <tr key={l.category}>
                      <td style={{ whiteSpace: "nowrap" }}><span className="key-sq" style={{ background: c.color }} />{c.label}</td>
                      <td className="num">{money(l.plan, cur)}</td>
                      <td className="num">{money(l.sources, cur)}</td>
                      <td className="num">{money(l.served, cur)}</td>
                      <td className="num">{money(l.unabsorbed, cur)}</td>
                      <td className={`num ${Math.abs(l.difference) > 1e-6 * Math.max(1, l.plan) ? "neg" : "faint"}`}>{Math.abs(l.difference) < 0.005 ? "0" : l.difference.toFixed(2)}</td>
                      <td>
                        <div className="split-bar" style={{ width: `${(l.plan / maxPlan) * 100}%` }} title={`${pct(l.plan ? l.served / l.plan : 0, 1)} served`}>
                          <span style={{ flex: Math.max(0, l.served), background: c.color }} />
                          <span style={{ flex: Math.max(0, l.unabsorbed), background: c.color, opacity: 0.35 }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
                <tr className="total">
                  <td>Total</td><td className="num">{money(rec.total_plan, cur)}</td><td className="num" />
                  <td className="num">{money(rec.total_served, cur)}</td><td className="num">{money(rec.total_unabsorbed, cur)}</td><td /><td />
                </tr>
              </tbody>
            </table>
          </div>
        </Panel>
        <div className="stack">
          <Panel title="Why cost is unabsorbed">
            {reasons.length === 0 ? <p className="faint small">Every unit of plan cost reaches a demand.</p> : (
              <div className="bar-list">
                {reasons.map(([why, v]) => (
                  <div key={why} className="bar-row">
                    <span>{why}</span>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / Math.max(1, reasons[0][1])) * 100}%` }} /></div>
                    <span className="num">{money(v, cur)}</span>
                  </div>
                ))}
              </div>
            )}
          </Panel>
          <Reading formula={<>order full cost = own cost + Σ its input requirements; requirement cost = Σ pegs × (peg qty ÷ order qty) × supplying order's full cost
            + holding share (qty × days held); stock and firm receipts pegged at unit value.</>}
            soWhat="Unabsorbed cost is real spend no demand in the horizon asked for: lot sizes above need, safety-stock build, stock left at the horizon end. It is the first place to look for savings." />
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
type GroupBy = "customer" | "region" | "product";

function Composition({ costs, total }: { costs: Record<string, number>; total: number }) {
  const committed = (costs.stock ?? 0) + (costs.firm ?? 0);
  if (total <= 0) return <span className="faint">—</span>;
  return (
    <div className="split-bar" title={CATS.map((c) => `${c.label} ${pct((costs[c.id] ?? 0) / total, 0)}`).join(" · ") + ` · ${COMMITTED.label} ${pct(committed / total, 0)}`}>
      {CATS.map((c) => (costs[c.id] ?? 0) > 0 && <span key={c.id} style={{ flex: costs[c.id], background: c.color }} />)}
      {committed > 0 && <span style={{ flex: committed, background: COMMITTED.color }} />}
    </div>
  );
}

function Serve({ res, cur }: { res: FinanceResult; cur: string }) {
  const [by, setBy] = useState<GroupBy>("customer");
  const groups = useMemo(() => {
    const m = new Map<string, { key: string; sub: string; rows: ServeRow[]; costs: Record<string, number> }>();
    for (const r of res.serve) {
      const key = by === "customer" ? r.location : by === "region" ? r.region || "(no region)" : r.product;
      const sub = by === "customer" ? `${r.location_type}${r.region ? ` · ${r.region}` : ""}` : "";
      const g = m.get(key) ?? { key, sub, rows: [], costs: {} };
      g.rows.push(r);
      for (const [k, v] of Object.entries(r.costs)) g.costs[k] = (g.costs[k] ?? 0) + v;
      m.set(key, g);
    }
    return [...m.values()].map((g) => {
      const sum = (f: (r: ServeRow) => number) => g.rows.reduce((a, r) => a + f(r), 0);
      const revenue = sum((r) => r.revenue);
      const total = sum((r) => r.total_cost);
      const served = sum((r) => r.served);
      return { ...g, demand: sum((r) => r.demand), served, revenue, plan: sum((r) => r.plan_cost), total,
        margin: revenue - total, unit: served > 0 ? total / served : 0, noPrice: g.rows.some((r) => r.price === null) };
    }).sort((a, b) => b.margin - a.margin);
  }, [res.serve, by]);
  const revenue = groups.reduce((a, g) => a + g.revenue, 0);
  const margin = groups.reduce((a, g) => a + g.margin, 0);
  const worst = groups.length ? groups[groups.length - 1] : null;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Revenue served" value={money(revenue, cur)} />
        <StatTile label="Cost to serve" value={money(groups.reduce((a, g) => a + g.total, 0), cur)} sub="plan cost + stock & firm consumed" />
        <StatTile label="Margin" value={money(margin, cur)} sub={revenue > 0 ? pct(margin / revenue, 1) : "—"} />
        {worst && <StatTile label={`Thinnest ${by}`} value={worst.key} sub={worst.revenue > 0 ? `margin ${pct(worst.margin / worst.revenue, 1)}` : "no revenue"} />}
      </div>
      <SectionBand title="Cost to serve and margin" right={
        <div className="seg" role="group" aria-label="Group by">
          {(["customer", "region", "product"] as GroupBy[]).map((g) => (
            <button key={g} className={by === g ? "on" : ""} aria-pressed={by === g} onClick={() => setBy(g)}>By {g}</button>
          ))}
        </div>} />
      <Panel flush>
        <div className="legend" style={{ padding: "8px 12px" }}>
          {CATS.map((c) => <span key={c.id}><span className="key box" style={{ background: c.color, height: 10 }} />{c.label}</span>)}
          <span><span className="key box" style={{ background: COMMITTED.color, height: 10 }} />{COMMITTED.label}</span>
        </div>
        <div className="table-wrap" style={{ maxHeight: 620 }}>
          <table className="t">
            <thead><tr><th>{by[0].toUpperCase() + by.slice(1)}</th><th className="num">Demand</th><th className="num">Served</th>
              <th className="num">Revenue</th><th className="num">Plan cost</th><th className="num">Total cost</th><th className="num">Cost / unit</th>
              <th className="num">Margin</th><th className="num">Margin %</th><th style={{ width: "22%" }}>Cost composition</th></tr></thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.key}>
                  <td><b>{g.key}</b>{g.sub && <div className="faint small">{g.sub}</div>}</td>
                  <td className="num">{qty(g.demand)}</td>
                  <td className={`num ${g.served < g.demand - 1e-6 ? "neg" : ""}`}>{qty(g.served)}</td>
                  <td className="num">{g.noPrice && g.revenue === 0 ? <span className="faint">no price</span> : money(g.revenue, cur)}</td>
                  <td className="num">{money(g.plan, cur)}</td>
                  <td className="num">{money(g.total, cur)}</td>
                  <td className="num">{unitMoney(g.unit, cur)}</td>
                  <td className={`num ${g.margin < 0 ? "neg" : ""}`}>{money(g.margin, cur)}</td>
                  <td className={`num ${g.margin < 0 ? "neg" : ""}`}>{g.revenue > 0 ? pct(g.margin / g.revenue, 1) : "—"}</td>
                  <td><Composition costs={g.costs} total={g.total} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="margin = served qty × selling price − (plan cost pegged to it + stock and firm receipts it consumes at unit value)."
        soWhat="Cost to serve differs by customer because of the route (transport, handling, extra echelons), the lot sizes and stock held for them. A thin margin is a pricing, sourcing or service-policy question, not only a cost one." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Inventory({ res, cur }: { res: FinanceResult; cur: string }) {
  const inv = res.inventory!;
  const peak = inv.buckets.reduce((a, b) => (b.value > a.value ? b : a), inv.buckets[0]);
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="At start" value={money(inv.start, cur)} />
        <StatTile label="Time-weighted average" value={money(inv.avg, cur)} tone="ink" />
        <StatTile label="At horizon end" value={money(inv.end, cur)} />
        {peak && <StatTile label="Peak bucket" value={money(peak.value, cur)} sub={peak.label} />}
      </div>
      <Panel title="Inventory value by product type (end of bucket)">
        <BucketChart labels={inv.buckets.map((b) => b.label)} format={(v) => money(v, cur)} height={260}
          series={[
            ...inv.types.slice(0, 4).map((t, i) => ({ name: t, color: TYPE_COLORS[i], kind: "column" as const, values: inv.buckets.map((b) => b.by_type[t] ?? 0) })),
            { name: "Total", color: "var(--text)", kind: "line" as const, values: inv.buckets.map((b) => b.value) },
          ]} />
      </Panel>
      <Panel flush title="By location">
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Location</th><th>Type</th><th className="num">Start</th><th className="num">Average</th><th className="num">End</th>
              <th className="num">Holding cost</th><th className="num">Share of average</th></tr></thead>
            <tbody>
              {inv.locations.map((l) => (
                <tr key={l.location}>
                  <td><b>{l.location}</b></td><td>{l.type}</td>
                  <td className="num">{money(l.start, cur)}</td><td className="num">{money(l.avg, cur)}</td><td className="num">{money(l.end, cur)}</td>
                  <td className="num">{money(l.holding, cur)}</td><td className="num">{pct(inv.avg ? l.avg / inv.avg : 0, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Reading formula="value(bucket) = Σ stocking nodes max(0, projected on-hand at bucket end) × unit value; average = Σ value × bucket days ÷ horizon days (the plan KPI)."
        soWhat="Holding cost is this value × carrying rate (WACC + storage, insurance, obsolescence) × days ÷ 365; it is what safety stock and lot sizes cost to keep." />
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Capacity({ res, cur, ds, sel }: { res: FinanceResult; cur: string; ds: Dataset; sel?: string }) {
  const opts = res.capacity;
  const cur_ = opts.find((o) => o.id === sel) ?? opts[0];
  return (
    <div className="stack">
      {opts.length === 0 ? <Panel><Empty title="No capacity options">
        <p>Add an option below — a resource, the hours a week it adds, its investment and running cost — then re-cost.</p>
      </Empty></Panel> : <>
        <div className="banner info"><Badge sev="info">S&OP {res.sop_mode} mode</Badge>
          Savings are what the S&OP plan gains with the hours; NPV discounts the cash effect over each option's life.</div>
        <Panel flush title="Options">
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Option</th><th>Resource</th><th className="num">+ h / week</th><th className="num">Dual estimate</th>
                <th className="num">Re-solve saving</th><th className="num">Cash Δ / year</th><th className="num">Net / year</th>
                <th className="num">Capex</th><th className="num">NPV</th><th className="num">IRR</th><th className="num">Payback</th><th>Verdict</th></tr></thead>
              <tbody>
                {opts.map((o) => (
                  <tr key={o.id} className={`clickable ${cur_?.id === o.id ? "selected" : ""}`} onClick={() => go("finance", "capacity", o.id)}>
                    <td><b>{o.name}</b><div className="faint small">{o.id}</div></td>
                    <td>{o.resource}</td>
                    <td className="num">{qty(o.added_hours_per_week)}</td>
                    <td className="num">{money(o.dual_estimate, cur)}{!o.within_range && <div className="faint small">capped at range</div>}</td>
                    <td className="num">{money(o.objective_saving, cur)}</td>
                    <td className="num">{money(o.annual_cash, cur)}</td>
                    <td className={`num ${o.annual_net < 0 ? "neg" : ""}`}>{money(o.annual_net, cur)}</td>
                    <td className="num">{money(o.capex, cur)}</td>
                    <td className={`num ${o.npv < 0 ? "neg" : ""}`}><b>{money(o.npv, cur)}</b></td>
                    <td className="num">{o.irr !== null ? pct(o.irr, 1) : "—"}</td>
                    <td className="num">{o.payback_years !== null ? `${o.payback_years.toFixed(1)} y` : "never"}</td>
                    <td>{o.npv > 0 ? <Badge sev="ok">Invest</Badge> : <Badge sev="warning">Not worth it</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        {cur_ && <OptionDetail o={cur_} cur={cur} />}
      </>}
      <OptionsEditor ds={ds} />
    </div>
  );
}

function OptionDetail({ o, cur }: { o: CapacityAppraisal; cur: string }) {
  const binding = o.buckets.filter((b) => Math.abs(b.shadow_price) > 1e-9).length;
  return (
    <>
      <SectionBand title={o.name} right={<span className="faint small">{o.resource} · +{qty(o.added_hours_per_week)} h/week · {o.life_years} years at {pct(o.discount_rate, 1)}</span>} />
      <div className="grid-auto">
        <StatTile label="Buckets where hours bind" value={`${binding} / ${o.buckets.length}`} sub={binding ? "shadow price > 0" : "capacity is not the constraint"} />
        <StatTile label="Dual vs re-solve" value={Math.abs(o.dual_estimate - o.objective_saving) <= 1e-6 * Math.max(1, Math.abs(o.objective_saving)) ? "agree" : "differ"}
          sub={o.within_range ? "hours inside the valid range" : "hours beyond the valid range"} />
        <StatTile label="Fill rate" value={`${pct(o.fill_rate_before, 1)} → ${pct(o.fill_rate_after, 1)}`} sub="S&OP, before → after" />
        <StatTile label="NPV" value={money(o.npv, cur)} sub={o.irr !== null ? `IRR ${pct(o.irr, 1)}` : undefined} />
      </div>
      <Panel title="Net cash flow by year (year 0 = the investment)">
        <BucketChart labels={o.cash_flows.map((_, y) => `Year ${y}`)} format={(v) => money(v, cur)} height={200}
          series={[{ name: "Net cash", color: "var(--series-1)", kind: "column", values: o.cash_flows }]} />
      </Panel>
      <div>
        <Panel flush title="Value of the hours by S&OP bucket">
          <div className="table-wrap" style={{ maxHeight: 300 }}>
            <table className="t">
              <thead><tr><th>Bucket</th><th className="num">Capacity h</th><th className="num">Added h</th><th className="num">Shadow price</th>
                <th className="num">Valid for h</th><th className="num">Estimate</th></tr></thead>
              <tbody>
                {o.buckets.map((b) => (
                  <tr key={b.bucket} className={Math.abs(b.shadow_price) > 1e-9 ? "" : "dim"}>
                    <td>{b.label}</td><td className="num">{qty(b.capacity)}</td><td className="num">{qty(b.added)}</td>
                    <td className="num">{unitMoney(b.shadow_price, cur)}</td>
                    <td className="num">{b.valid_headroom === null ? "∞" : qty(b.valid_headroom)}</td>
                    <td className="num">{money(b.estimate, cur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
      <Reading formula={<>dual estimate = Σ buckets shadow price × min(added hours, valid range); annual cash = re-solved Δ(revenue − purchase − production − transport − holding − overtime) × 365 ÷ {o.horizon_days} days;
        NPV = −capex + Σ<sub>y=1..{o.life_years}</sub> (annual cash − fixed cost) ÷ (1 + r)<sup>y</sup>.</>}
        soWhat={binding ? "Where the hours bind, the shadow price is what one more hour is worth to the plan; beyond its valid range the next hour is worth less, which the re-solve captures."
          : "No bucket is short of these hours: the plan would not use them, so the option only adds cost. Test it against a demand-growth scenario (S&OP levers) before deciding."} />
    </>
  );
}

function OptionsEditor({ ds }: { ds: Dataset }) {
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Capacity options & discount rate">
        <SchemaForm defName="FinanceSettings" value={(ds.finance ?? {}) as unknown as Obj}
          onChange={(next) => store.update((d) => { d.finance = next as unknown as Dataset["finance"]; })} />
      </Panel>
      <Reading formula="An option adds regular hours to one resource in every S&OP bucket (added hours per week × bucket days ÷ 7). Discount rate empty = the company WACC."
        soWhat="Edits here are part of the dataset: save a scenario version to keep an appraisal next to the base plan." />
    </div>
  );
}
