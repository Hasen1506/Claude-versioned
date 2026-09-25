import { useMemo, useState } from "react";
import type { PlanResult, PlannedOrder, Requirement } from "../api/types";
import { BucketChart } from "../components/charts";
import { Badge, cols, Empty, Panel, StatTile, Tabs, type Severity } from "../components/ui";
import { day, money, ORDER_LABEL, pct, qty } from "../lib/format";
import { go, href } from "../lib/router";
import { planIsStale, store, useStore } from "../state/store";

type View = "overview" | "node" | "capacity" | "orders";

export function Plan({ route }: { route: string[] }) {
  const plan = useStore((s) => s.plan);
  const stale = useStore(planIsStale);
  const planning = useStore((s) => s.planning);
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const view = ((route[1] as View) || "overview") as View;

  const head = (
    <div className="page-head">
      <div>
        <h1>Supply plan</h1>
        <p>Network MRP/DRP: requirements are netted per location and product in low-level-code order, lot-sized,
          sourced, scheduled on working days and exploded through BOMs and lanes. Every order is pegged to the demand it serves.</p>
      </div>
      <span className="spacer" />
      <button className="btn primary" onClick={() => store.runPlan()} disabled={planning || blocking}>
        {planning ? "Planning…" : plan ? "Re-plan" : "Run plan"}
      </button>
    </div>
  );
  if (!plan) {
    return <div>{head}<Panel><Empty title={blocking ? "Fix blocking readiness issues first" : "No plan yet"}>
      {blocking ? <a className="btn" href={href("readiness")}>Open readiness</a> : <p>Run the plan to see orders, projected stock, capacity load and exceptions.</p>}
    </Empty></Panel></div>;
  }
  if (!plan.ok) {
    return <div>{head}<div className="banner error"><Badge sev="error">Not planned</Badge>The dataset has blocking readiness issues. <a href={href("readiness")}>Review them</a>.</div></div>;
  }
  return (
    <div>
      {head}
      {stale && <div className="banner warning"><Badge sev="warning">Stale</Badge>Inputs changed since this plan was computed. Re-plan to refresh every number below.</div>}
      <Tabs<View> value={view} onChange={(v) => go("plan", v)} tabs={[
        { id: "overview", label: "Overview" },
        { id: "node", label: "Stock & requirements", count: plan.nodes.length },
        { id: "capacity", label: "Capacity", count: plan.resources.length },
        { id: "orders", label: "Orders", count: plan.orders.length },
      ]} />
      {view === "overview" && <Overview plan={plan} />}
      {view === "node" && <NodeView plan={plan} loc={route[2]} prod={route[3]} />}
      {view === "capacity" && <CapacityView plan={plan} res={route[2]} />}
      {view === "orders" && <OrdersView plan={plan} sel={route[2]} />}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Overview({ plan }: { plan: PlanResult }) {
  const k = plan.kpis;
  const c = plan.currency;
  const [sev, setSev] = useState<"" | "error" | "warning" | "info">("");
  const costs: [string, number][] = [
    ["Purchases", k.purchase_cost ?? 0], ["Production (run)", k.production_cost ?? 0], ["Setups", k.setup_cost ?? 0],
    ["Ordering", k.ordering_cost ?? 0], ["Transport", k.transport_cost ?? 0], ["Handling", k.handling_cost ?? 0],
    ["Inventory holding", k.holding_cost ?? 0],
  ];
  const maxCost = Math.max(...costs.map(([, v]) => v), 1);
  const ex = plan.exceptions.filter((e) => !sev || e.severity === sev);
  const counts = { error: 0, warning: 0, info: 0 } as Record<string, number>;
  plan.exceptions.forEach((e) => counts[e.severity]++);
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Total plan cost" value={money(k.total_cost, c)} sub={`over ${plan.buckets.length} buckets`} />
        <StatTile label="Demand on time (projected)" value={pct(k.on_time_fill_rate)} sub={`${qty(k.on_time_qty)} of ${qty(k.independent_demand)} units`} />
        <StatTile label="Average inventory value" value={money(k.inventory_value_avg, c)} sub={`start ${money(k.inventory_value_start, c)} → end ${money(k.inventory_value_end, c)}`} />
        <StatTile label="Peak resource load" value={pct(k.max_utilization, 0)} sub="of regular capacity" />
        <StatTile label="Planned orders" value={qty((k.orders_make ?? 0) + (k.orders_buy ?? 0) + (k.orders_transfer ?? 0))}
          sub={`${k.orders_make} make · ${k.orders_buy} buy · ${k.orders_transfer} move`} />
      </div>
      <div className="grid-2">
        <Panel title="Cost build-up">
          <div className="bar-list">
            {costs.map(([label, v]) => (
              <div key={label} className="bar-row">
                <span className="muted">{label}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(v / maxCost) * 100}%` }} /></div>
                <span className="num">{money(v, c)}</span>
              </div>
            ))}
          </div>
          <p className="faint small" style={{ marginBottom: 0 }}>Holding cost uses the carrying rate {pct(plan.carrying_rate)} per year (WACC + holding spread) on projected stock × unit value.</p>
        </Panel>
        <Panel title="Exceptions" actions={
          <div className="row">
            {(["", "error", "warning", "info"] as const).map((s) => (
              <button key={s || "all"} className={`btn sm ${sev === s ? "primary" : ""}`} onClick={() => setSev(s)}>
                {s ? `${s} (${counts[s]})` : `all (${plan.exceptions.length})`}
              </button>
            ))}
          </div>}>
          <div className="table-wrap" style={{ maxHeight: 360 }}>
            <ExceptionTable rows={ex} />
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ExceptionTable({ rows }: { rows: PlanResult["exceptions"] }) {
  if (!rows.length) return <div className="faint">No exceptions.</div>;
  return (
    <table className="t">
      <tbody>
        {rows.map((e, i) => {
          const where = e.order_id ? href("plan", "orders", e.order_id)
            : e.resource ? href("plan", "capacity", e.resource)
            : e.location && e.product ? href("plan", "node", e.location, e.product) : null;
          return (
            <tr key={i}>
              <td><Badge sev={e.severity as Severity}>{e.code}</Badge></td>
              <td className="small">{where ? <a href={where}>{e.resource ?? `${e.product} @ ${e.location}`}</a> : "—"}</td>
              <td className="small">{e.message}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ------------------------------------------------------------------------------------------------
function NodeView({ plan, loc, prod }: { plan: PlanResult; loc?: string; prod?: string }) {
  const [q, setQ] = useState("");
  const exBy = useMemo(() => {
    const m = new Map<string, { n: number; error: boolean }>();
    plan.exceptions.forEach((e) => {
      if (!e.location || !e.product || e.severity === "info") return;
      const k = `${e.location}|${e.product}`;
      const cur = m.get(k) ?? { n: 0, error: false };
      m.set(k, { n: cur.n + 1, error: cur.error || e.severity === "error" });
    });
    return m;
  }, [plan]);
  const nodes = plan.nodes.filter((n) => !q || `${n.location} ${n.product}`.toLowerCase().includes(q.toLowerCase()));
  const node = plan.nodes.find((n) => n.location === loc && n.product === prod) ?? null;
  return (
    <div className="split" style={cols("380px minmax(0,1fr)")}>
      <Panel flush title={<input className="input" placeholder="Filter nodes…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter nodes" />}>
        <div className="table-wrap" style={{ maxHeight: "calc(100vh - 260px)" }}>
          <table className="t nowrap">
            <thead><tr><th>Location</th><th>Product</th><th className="num">LLC</th><th /></tr></thead>
            <tbody>
              {nodes.map((n) => {
                const x = exBy.get(`${n.location}|${n.product}`);
                return (
                  <tr key={`${n.location}|${n.product}`} className={`clickable ${node === n ? "selected" : ""}`}
                    onClick={() => go("plan", "node", n.location, n.product)}>
                    <td>{n.location}</td><td>{n.product}</td><td className="num">{n.llc}</td>
                    <td>{x ? <Badge sev={x.error ? "error" : "warning"}>{x.n}</Badge> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      {node ? <NodeDetail plan={plan} node={node} /> : <Panel><div className="faint">Select a location–product to see its stock/requirements picture.</div></Panel>}
    </div>
  );
}

function NodeDetail({ plan, node }: { plan: PlanResult; node: PlanResult["nodes"][number] }) {
  const labels = plan.buckets.map((b) => b.label.replace(/^W\d+ /, ""));
  const b = node.buckets;
  const orders = plan.orders.filter((o) => o.location === node.location && o.product === node.product);
  const [sel, setSel] = useState<string | null>(null);
  const rows: [string, (x: typeof b[number]) => number, string?][] = [
    ["Independent demand", (x) => x.gross_independent ?? 0],
    ["Dependent / transfer demand", (x) => x.gross_dependent ?? 0],
    ["Scheduled receipts", (x) => x.scheduled_receipts ?? 0],
    ["Planned receipts", (x) => x.planned_receipts ?? 0],
    ["Projected on hand", (x) => x.projected_on_hand ?? 0, "emph"],
    ["Safety stock", (x) => x.safety_stock ?? 0],
  ];
  return (
    <div className="stack">
      <Panel title={<div className="context-bar"><a href={href("network", node.location)}>{node.location}</a><span>›</span><b>{node.product}</b></div>}
        actions={<a className="btn sm" href={href("data", "location_products", `${node.location}|${node.product}`)}>Edit policy</a>}>
        <div className="grid-auto small" style={{ marginBottom: 12 }}>
          <div><div className="faint">Strategy · MRP type</div>{node.strategy} · {node.mrp_type}</div>
          <div><div className="faint">Lot sizing</div>{node.lot_policy}</div>
          <div><div className="faint">Safety stock</div>{node.safety_stock_method}<div className="faint">{node.safety_stock_note}</div></div>
          <div><div className="faint">Replenishment lead time</div>{node.lead_time_days != null ? `${qty(node.lead_time_days)} days` : "—"}</div>
          <div><div className="faint">Unit value</div>{money(node.unit_value, plan.currency)}<div className="faint">{node.value_basis}</div></div>
          <div><div className="faint">Sources</div>{node.sources?.length ? node.sources.join(", ") : "none"}</div>
        </div>
        <BucketChart labels={labels} series={[
          { name: "Safety stock", color: "var(--series-2)", values: b.map((x) => x.safety_stock ?? 0), kind: "step" },
          { name: "Projected on hand (end of bucket)", color: "var(--series-1)", values: b.map((x) => x.projected_on_hand ?? 0), kind: "line" },
        ]} />
      </Panel>
      <Panel flush title="Stock / requirements by bucket">
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th className="stub">Row</th>{plan.buckets.map((bk) => <th key={bk.index} className="num" title={`${bk.start} – ${bk.end}`}>{bk.label.replace(/^W\d+ /, "")}</th>)}</tr></thead>
            <tbody>
              {rows.map(([label, get, cls]) => (
                <tr key={label} className={cls}>
                  <td className="stub">{label}</td>
                  {b.map((x, i) => {
                    const v = get(x);
                    const neg = label === "Projected on hand" && v < -1e-6;
                    const low = label === "Projected on hand" && !neg && (x.below_safety ?? 0) > 1e-6;
                    return <td key={i} className={`num ${neg ? "neg" : low ? "warnc" : ""}`}>{Math.abs(v) < 1e-9 ? "·" : qty(v)}</td>;
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel flush title={`Planned orders (${orders.length})`}>
        <div className="split" style={cols(sel ? "minmax(0,1fr) minmax(0,1fr)" : "minmax(0,1fr)", { gap: 0 })}>
          <div className="table-wrap" style={{ maxHeight: 420 }}>
            <OrderTable plan={plan} orders={orders} sel={sel} onSelect={setSel} compact />
          </div>
          {sel && <div style={{ borderLeft: "1px solid var(--border)", padding: 12, maxHeight: 420, overflow: "auto" }}><PegTree plan={plan} orderId={sel} /></div>}
        </div>
      </Panel>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function CapacityView({ plan, res }: { plan: PlanResult; res?: string }) {
  const r = plan.resources.find((x) => x.resource === res) ?? plan.resources[0];
  if (!r) return <Panel><div className="faint">No resources in this network.</div></Panel>;
  const labels = plan.buckets.map((b) => b.label.replace(/^W\d+ /, ""));
  return (
    <div className="split" style={cols("300px minmax(0,1fr)")}>
      <Panel flush>
        <table className="t nowrap">
          <thead><tr><th>Resource</th><th className="num">Peak</th></tr></thead>
          <tbody>
            {plan.resources.map((x) => {
              const peak = Math.max(0, ...x.buckets.map((b) => (Number.isFinite(b.utilization) ? b.utilization : 9.99)));
              const over = x.buckets.some((b) => b.load_hours > b.capacity_hours + b.overtime_hours + 1e-6);
              const ot = x.buckets.some((b) => b.load_hours > b.capacity_hours + 1e-6);
              return (
                <tr key={x.resource} className={`clickable ${x === r ? "selected" : ""}`} onClick={() => go("plan", "capacity", x.resource)}>
                  <td>{x.resource}<div className="faint small">{x.location} · {x.kind}{x.finite ? "" : " · infinite"}</div></td>
                  <td className="num">{over ? <Badge sev="error">{pct(peak, 0)}</Badge> : ot ? <Badge sev="warning">{pct(peak, 0)}</Badge> : pct(peak, 0)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
      <div className="stack">
        <Panel title={<div className="context-bar"><span>Resource</span><span>›</span><b>{r.resource}</b></div>}
          actions={<a className="btn sm" href={href("data", "resources", r.resource)}>Edit resource</a>}>
          <BucketChart labels={labels} unit=" h" series={[
            { name: "Load", color: "var(--series-1)", values: r.buckets.map((b) => b.load_hours), kind: "column" },
            { name: "Regular capacity", color: "var(--text-2)", values: r.buckets.map((b) => b.capacity_hours), kind: "step" },
            { name: "Capacity incl. overtime", color: "var(--series-2)", values: r.buckets.map((b) => b.capacity_hours + b.overtime_hours), kind: "step" },
          ]} />
        </Panel>
        <Panel flush title="Load by bucket">
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th className="stub">Hours</th>{plan.buckets.map((b) => <th key={b.index} className="num">{b.label.replace(/^W\d+ /, "")}</th>)}</tr></thead>
              <tbody>
                <tr><td className="stub">Load</td>{r.buckets.map((b) => <td key={b.bucket} className="num">{qty(b.load_hours)}</td>)}</tr>
                <tr><td className="stub">Capacity</td>{r.buckets.map((b) => <td key={b.bucket} className="num">{qty(b.capacity_hours)}</td>)}</tr>
                <tr><td className="stub">Overtime available</td>{r.buckets.map((b) => <td key={b.bucket} className="num">{qty(b.overtime_hours)}</td>)}</tr>
                <tr className="emph"><td className="stub">Utilisation</td>{r.buckets.map((b) => (
                  <td key={b.bucket} className={`num ${b.load_hours > b.capacity_hours + b.overtime_hours + 1e-6 ? "neg" : b.load_hours > b.capacity_hours + 1e-6 ? "warnc" : ""}`}>{pct(b.utilization, 0)}</td>
                ))}</tr>
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function OrdersView({ plan, sel }: { plan: PlanResult; sel?: string }) {
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const [late, setLate] = useState(false);
  const rows = plan.orders.filter((o) => (!kind || o.kind === kind) && (!late || (o.delay_days ?? 0) !== 0)
    && (!q || `${o.id} ${o.product} ${o.location} ${o.origin ?? ""}`.toLowerCase().includes(q.toLowerCase())))
    .sort((a, b) => a.start_date.localeCompare(b.start_date) || a.id.localeCompare(b.id));
  const LIMIT = 1000;
  return (
    <div className="split" style={cols(sel ? "minmax(0,1fr) 440px" : "minmax(0,1fr)")}>
      <Panel flush title={<div className="row wrap" style={{ flex: 1 }}>
        <input className="input" placeholder="Search id, product, location…" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 260 }} aria-label="Search orders" />
        <select className="select" value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: 150 }} aria-label="Order kind">
          <option value="">All kinds</option><option value="make">Production</option><option value="buy">Purchase</option><option value="transfer">Transfer</option>
        </select>
        <label className="row small"><input type="checkbox" checked={late} onChange={(e) => setLate(e.target.checked)} /> late only</label>
        <span className="faint small">{rows.length} orders</span>
      </div>}>
        <div className="table-wrap" style={{ maxHeight: "calc(100vh - 260px)" }}>
          <OrderTable plan={plan} orders={rows.slice(0, LIMIT)} sel={sel ?? null} onSelect={(id) => go("plan", "orders", id)} />
          {rows.length > LIMIT && <div className="faint small" style={{ padding: 10 }}>Showing the first {LIMIT} of {rows.length} by start date. Filter to narrow the list.</div>}
        </div>
      </Panel>
      {sel && <Panel title={<div className="context-bar"><span>Order</span><span>›</span><b>{sel}</b></div>}
        actions={<a className="btn ghost sm" href={href("plan", "orders")}>Close</a>}><PegTree plan={plan} orderId={sel} /></Panel>}
    </div>
  );
}

function OrderTable({ plan, orders, sel, onSelect, compact }: {
  plan: PlanResult; orders: PlannedOrder[]; sel: string | null; onSelect: (id: string) => void; compact?: boolean;
}) {
  return (
    <table className="t nowrap">
      <thead><tr>
        <th>Order</th>{!compact && <th>Product</th>}{!compact && <th>At</th>}<th>From</th>
        <th className="num">Qty</th><th>Start</th><th>Available</th><th className="num">Late</th><th className="num">Cost</th>
      </tr></thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.id} className={`clickable ${sel === o.id ? "selected" : ""}`} onClick={() => onSelect(o.id)}>
            <td><span className="mono">{o.id}</span> <span className="faint small">{ORDER_LABEL[o.kind]}</span>
              {!o.convertible && <> <Badge>ATO</Badge></>}</td>
            {!compact && <td>{o.product}</td>}
            {!compact && <td>{o.location}</td>}
            <td className="small">{o.origin ?? o.source_id}</td>
            <td className="num">{qty(o.qty)}</td>
            <td className="small">{day(o.start_date)}{o.start_in_past && <> <Badge sev="warning">past</Badge></>}</td>
            <td className="small">{day(o.available_date)}{o.fence_shifted && <> <Badge sev="info">fence</Badge></>}</td>
            <td className="num">{o.delay_days === -1 ? <Badge sev="error">uncovered</Badge> : (o.delay_days ?? 0) > 0 ? <Badge sev="warning">{o.delay_days} d</Badge> : "·"}</td>
            <td className="num">{money(o.total_cost, plan.currency)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ------------------------------------------------------------------------------------------------
/** Pegging tree: what this order serves (upstream to the customer) and what it depends on. */
function PegTree({ plan, orderId }: { plan: PlanResult; orderId: string }) {
  const idx = useMemo(() => {
    const orders = new Map(plan.orders.map((o) => [o.id, o]));
    const reqs = new Map(plan.requirements.map((r) => [r.id, r]));
    const bySupply = new Map<string, PlanResult["pegs"]>();
    const byReq = new Map<string, PlanResult["pegs"]>();
    const byParent = new Map<string, Requirement[]>();
    for (const p of plan.pegs) {
      bySupply.set(p.supply_id, [...(bySupply.get(p.supply_id) ?? []), p]);
      byReq.set(p.requirement_id, [...(byReq.get(p.requirement_id) ?? []), p]);
    }
    for (const r of plan.requirements) if (r.parent_order) byParent.set(r.parent_order, [...(byParent.get(r.parent_order) ?? []), r]);
    return { orders, reqs, bySupply, byReq, byParent };
  }, [plan]);
  const o = idx.orders.get(orderId);
  if (!o) return <div className="faint">Order not found.</div>;

  const serves = (id: string, depth: number): JSX.Element[] => (idx.bySupply.get(id) ?? []).map((p, i) => {
    const r = idx.reqs.get(p.requirement_id)!;
    const parent = r.parent_order ? idx.orders.get(r.parent_order) : null;
    return (
      <li key={i}>
        <b className="num">{qty(p.qty)}</b> → {r.kind === "forecast" || r.kind === "sales_order"
          ? <><Badge sev="info">{r.kind === "sales_order" ? "sales order" : "forecast"}</Badge> {r.product} at {r.location} on {day(r.date)}</>
          : parent ? <>{r.kind} requirement of <a href={href("plan", "orders", parent.id)}>{parent.id}</a> ({ORDER_LABEL[parent.kind]} {parent.product} at {parent.location}) on {day(r.date)}</>
          : r.id}
        {parent && depth < 6 && <ul>{serves(parent.id, depth + 1)}</ul>}
      </li>
    );
  });

  const needs = (id: string, depth: number): JSX.Element[] => (idx.byParent.get(id) ?? []).map((r) => {
    const pegs = idx.byReq.get(r.id) ?? [];
    const covered = pegs.reduce((s, p) => s + p.qty, 0);
    return (
      <li key={r.id}>
        needs <b className="num">{qty(r.qty)}</b> {r.product} at {r.location} on {day(r.date)}
        {covered < r.qty - 1e-6 && <> <Badge sev="error">{qty(r.qty - covered)} uncovered</Badge></>}
        <ul>
          {pegs.map((p, i) => {
            const so = p.supply_kind === "order" ? idx.orders.get(p.supply_id) : null;
            return (
              <li key={i}>
                <b className="num">{qty(p.qty)}</b> from {so
                  ? <><a href={href("plan", "orders", so.id)}>{so.id}</a> ({ORDER_LABEL[so.kind]}{so.origin ? ` from ${so.origin}` : ""}, available {day(so.available_date)})
                    {depth < 6 && <ul>{needs(so.id, depth + 1)}</ul>}</>
                  : p.supply_kind === "on_hand" ? "stock on hand" : `scheduled receipt ${p.supply_id}`}
              </li>
            );
          })}
        </ul>
      </li>
    );
  });

  return (
    <div className="peg-tree stack">
      <div>
        <div style={{ fontWeight: 600 }}>{ORDER_LABEL[o.kind]} of {qty(o.qty)} {o.product} at {o.location}</div>
        <div className="muted small">
          {o.origin && <>from {o.origin} · </>}source {o.source_id} · start {day(o.start_date)} · due {day(o.due_date)} · available {day(o.available_date)}
          {o.projected_available_date && o.projected_available_date !== o.available_date && <> · projected {day(o.projected_available_date)}</>}
        </div>
        <div className="muted small">Need date {day(o.need_date)} · cost {money(o.total_cost, plan.currency)}{o.shipments ? ` · ${o.shipments} shipment(s)` : ""}
          {(o.lot_excess ?? 0) > 1e-6 && <> · {qty(o.lot_excess)} beyond requirements (lot size / safety stock)</>}</div>
      </div>
      <div>
        <h3>Serves</h3>
        {(idx.bySupply.get(o.id) ?? []).length ? <ul>{serves(o.id, 0)}</ul> : <div className="faint small">Not pegged to a requirement (lot-size excess or safety stock replenishment).</div>}
      </div>
      <div>
        <h3>Depends on</h3>
        {(idx.byParent.get(o.id) ?? []).length ? <ul>{needs(o.id, 0)}</ul> : <div className="faint small">{o.kind === "buy" ? "Bought from the supplier: the end of the chain." : "No inputs."}</div>}
      </div>
    </div>
  );
}
