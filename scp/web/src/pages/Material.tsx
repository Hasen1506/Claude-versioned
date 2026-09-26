// A product at a place (≈ SAP material master, MRP views 1–4, with the MD04 stock/requirements list): how it is
// planned there, how it is supplied and made, and, once a plan has run, every receipt and requirement by date
// with the stock after each. The index lists every product at every place, filterable by who plans it.
import { useMemo, useState } from "react";
import type { Dataset, LocationProduct, PlanResult, ProductionSource } from "../api/types";
import { Badge, Empty, Panel, StageHeader, Tabs } from "../components/ui";
import { day, ORDER_LABEL, qty, TYPE_LABEL } from "../lib/format";
import { useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { codeLabel } from "../lib/situations";
import { SchemaForm } from "../schema/SchemaForm";
import { freshness, store, useStore } from "../state/store";

type Tab = "stock" | "mrp1" | "mrp2" | "mrp3" | "mrp4";
const TABS: { id: Tab; label: string }[] = [
  { id: "stock", label: "Stock & requirements" }, { id: "mrp1", label: "MRP 1 · Ordering" },
  { id: "mrp2", label: "MRP 2 · Supply" }, { id: "mrp3", label: "MRP 3 · Strategy & buffers" },
  { id: "mrp4", label: "MRP 4 · Structure" },
];
const MRP1 = ["mrp_type", "mrp_controller", "reorder_point", "lot_sizing", "max_stock", "planning_time_fence_days"];
const MRP2 = ["procurement", "phantom", "on_hand", "gr_processing_days", "safety_time_days", "float_before_workdays",
  "float_after_workdays", "unit_cost"];
const MRP3 = ["strategy", "consumption_backward_days", "consumption_forward_days", "safety_stock", "holding_rate",
  "ddmrp_buffer", "max_service_days"];
const PROC: Record<string, string> = { any: "made or got from outside", make: "made here only", external: "bought or shipped in only" };

export function Material({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset);
  if (!ds) return null;
  const [, prod, loc, tab] = route;
  return prod && loc ? <MaterialPage ds={ds} prod={prod} loc={loc} tab={(TABS.some((t) => t.id === tab) ? tab : "stock") as Tab} />
    : <MaterialIndex ds={ds} />;
}

/** How a product reaches a place, from the master data alone (no plan needed). */
function supplyWays(ds: Dataset, loc: string, prod: string) {
  const makes = (ds.production_sources ?? []).filter((p) => p.location === loc && p.product === prod);
  const buys = (ds.purchasing_sources ?? []).filter((p) => p.location === loc && p.product === prod);
  const stocking = new Set((ds.locations ?? []).filter((l) => l.type !== "supplier" && l.type !== "customer").map((l) => l.id));
  const ships = (ds.lanes ?? []).filter((l) => l.destination === loc && stocking.has(l.origin) && (!l.products?.length || l.products.includes(prod)));
  const co = (ds.production_sources ?? []).filter((p) => p.location === loc && (p.co_products ?? []).some((c) => c.product === prod));
  return { makes, buys, ships, co };
}

// ------------------------------------------------------------------------------------------------
function MaterialIndex({ ds }: { ds: Dataset }) {
  const plan = useStore((s) => s.runs.plan.data);
  const nm = useNames();
  const [q, setQ] = useState("");
  const [ctl, setCtl] = useState("");
  const [place, setPlace] = useState("");
  const kept = useMemo(() => new Set((ds.locations ?? []).filter((l) => l.type !== "supplier" && l.type !== "customer").map((l) => l.id)), [ds]);
  const rows = useMemo(() => {
    const m = new Map<string, { loc: string; prod: string; lp?: LocationProduct }>();
    const put = (loc: string, prod: string, lp?: LocationProduct) => {
      if (!kept.has(loc)) return;
      const k = `${loc}|${prod}`;
      if (!m.has(k) || lp) m.set(k, { loc, prod, lp: lp ?? m.get(k)?.lp });
    };
    for (const lp of ds.location_products ?? []) put(lp.location, lp.product, lp);
    for (const n of plan?.nodes ?? []) put(n.location, n.product);
    for (const d of ds.demand ?? []) put(d.location, d.product);
    return [...m.values()].sort((a, b) => nm.prod(a.prod).localeCompare(nm.prod(b.prod)) || nm.loc(a.loc).localeCompare(nm.loc(b.loc)));
  }, [ds, plan, kept, nm]);
  const problems = useMemo(() => {
    const m = new Map<string, { n: number; error: boolean }>();
    for (const e of plan?.exceptions ?? []) {
      if (!e.location || !e.product || e.severity === "info") continue;
      const k = `${e.location}|${e.product}`;
      const c = m.get(k) ?? { n: 0, error: false };
      m.set(k, { n: c.n + 1, error: c.error || e.severity === "error" });
    }
    return m;
  }, [plan]);
  const controllers = [...new Set((ds.location_products ?? []).map((x) => x.mrp_controller).filter(Boolean))].sort() as string[];
  const shown = rows.filter((r) => (!ctl || (ctl === "-" ? !r.lp?.mrp_controller : r.lp?.mrp_controller === ctl))
    && (!place || r.loc === place)
    && (!q || `${nm.prod(r.prod)} ${r.prod} ${nm.loc(r.loc)}`.toLowerCase().includes(q.toLowerCase())));
  const ptype = (id: string) => (ds.products ?? []).find((p) => p.id === id)?.type ?? "";

  return (
    <div>
      <StageHeader title="Products at places" kicker={<>Every product at every place it is kept, and how it is planned there:
        ordering, supply, buffers and what it is made from. Open one to see its stock and requirements day by day.</>}
        how={<>This is SAP's material master at plant level (MRP views 1–4) with the stock/requirements list (MD04) on the
          same page. <b>Planned by</b> is the MRP controller: give each product at each place an owner, then filter here to
          see just yours.</>} />
      <div className="content stack">
        <div className="row wrap">
          <input className="input" style={{ maxWidth: 260 }} placeholder="Find a product or place…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find" />
          <select className="select" style={{ width: "auto" }} value={ctl} onChange={(e) => setCtl(e.target.value)} aria-label="Planned by">
            <option value="">Planned by: anyone</option>
            {controllers.map((c) => <option key={c} value={c}>{c}</option>)}
            <option value="-">Planned by: nobody yet</option>
          </select>
          <select className="select" style={{ width: "auto" }} value={place} onChange={(e) => setPlace(e.target.value)} aria-label="Place">
            <option value="">Every place</option>
            {[...kept].map((l) => <option key={l} value={l}>{nm.loc(l)}</option>)}
          </select>
          <span className="small muted">{shown.length} of {rows.length}</span>
        </div>
        {rows.length === 0 ? <Panel><Empty title="No products at places yet">
          <p>Say where each product is kept, and how it gets there, in <a href={href("setup", "products")}>Set up → Products</a>.</p></Empty></Panel> : (
          <Panel flush>
            <div className="table-wrap">
              <table className="t">
                <thead><tr><th>Product</th><th>Place</th><th>Planned by</th><th>How it is got</th><th>Ordering</th><th>Safety stock</th><th className="num">On hand</th><th>Plan</th></tr></thead>
                <tbody>{shown.map((r) => {
                  const w = supplyWays(ds, r.loc, r.prod);
                  const how = [w.makes.length && "made", w.co.length && "co-product", w.buys.length && "bought", w.ships.length && "shipped in"].filter(Boolean).join(", ") || "—";
                  const x = problems.get(`${r.loc}|${r.prod}`);
                  return (
                    <tr key={`${r.loc}|${r.prod}`} className="clickable" onClick={() => go("material", r.prod, r.loc)}>
                      <td><a href={href("material", r.prod, r.loc)} onClick={(e) => e.stopPropagation()}><b>{nm.prod(r.prod)}</b></a> <span className="faint small">{TYPE_LABEL[ptype(r.prod)] ?? ptype(r.prod)}</span>
                        {r.lp?.phantom && <Badge sev="info">phantom</Badge>}</td>
                      <td>{nm.loc(r.loc)}</td>
                      <td>{r.lp?.mrp_controller || <span className="faint">—</span>}</td>
                      <td className="small">{how}{r.lp && r.lp.procurement && r.lp.procurement !== "any" && <div className="faint">{PROC[r.lp.procurement]}</div>}</td>
                      <td className="small">{r.lp ? (r.lp.mrp_type === "none" ? "not replenished" : r.lp.mrp_type === "reorder_point" ? `reorder at ${qty(r.lp.reorder_point)}` : r.lp.lot_sizing?.policy ?? "L4L") : <span className="faint">defaults</span>}</td>
                      <td className="small">{!r.lp || r.lp.safety_stock?.method === "none" || !r.lp.safety_stock ? "none" : r.lp.safety_stock.method.replace(/_/g, " ")}</td>
                      <td className="num">{qty(r.lp?.on_hand ?? 0)}</td>
                      <td>{!plan ? <span className="faint small">not planned</span> : x ? <Badge sev={x.error ? "error" : "warning"}>{x.n}</Badge> : <Badge sev="ok">OK</Badge>}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function MaterialPage({ ds, prod, loc, tab }: { ds: Dataset; prod: string; loc: string; tab: Tab }) {
  const nm = useNames();
  const plan = useStore((s) => s.runs.plan.data);
  const lp = (ds.location_products ?? []).find((x) => x.location === loc && x.product === prod) ?? null;
  const p = (ds.products ?? []).find((x) => x.id === prod);
  const setLp = (next: Record<string, unknown>) => store.update((d) => {
    const list = (d.location_products ??= []);
    const i = list.findIndex((x) => x.location === loc && x.product === prod);
    if (i >= 0) list[i] = next as unknown as LocationProduct;
    else list.push(next as unknown as LocationProduct);
  });
  const create = () => setLp({ location: loc, product: prod });
  const places = [...new Set([...(ds.location_products ?? []).filter((x) => x.product === prod).map((x) => x.location),
    ...(plan?.nodes ?? []).filter((n) => n.product === prod).map((n) => n.location)])];
  const form = (only: string[]) => lp ? (
    <SchemaForm defName="LocationProduct" value={lp as unknown as Record<string, unknown>} onChange={setLp} only={only} />
  ) : (
    <div className="stack">
      <p className="muted">There is no planning record for {nm.prod(prod)} at {nm.loc(loc)} yet, so it is planned with the defaults:
        ordered exactly as needed, no safety stock, nothing on hand.</p>
      <div><button className="btn primary" onClick={create}>Create its planning record</button></div>
    </div>
  );

  return (
    <div>
      <StageHeader title={`${nm.prod(prod)} at ${nm.loc(loc)}`}
        kicker={<>{p ? TYPE_LABEL[p.type] ?? p.type : "Unknown product"}{lp?.mrp_controller ? <> · planned by <b>{lp.mrp_controller}</b></> : null}
          {lp?.phantom ? <> · phantom assembly</> : null}. <a href={href("material")}>All products at places</a></>}
        right={places.length > 1 ? <select className="select" style={{ width: "auto" }} value={loc} onChange={(e) => go("material", prod, e.target.value, tab)} aria-label="Place">
          {places.map((l) => <option key={l} value={l}>{nm.loc(l)}</option>)}</select> : undefined} />
      <div className="content stack">
        <Tabs tabs={TABS} value={tab} onChange={(t) => go("material", prod, loc, t)} />
        {tab === "stock" && <StockList ds={ds} plan={plan} prod={prod} loc={loc} />}
        {tab === "mrp1" && <Panel title="How it is ordered">{form(MRP1)}</Panel>}
        {tab === "mrp2" && <>
          <Sources ds={ds} prod={prod} loc={loc} plan={plan} />
          <Panel title="Procurement, lead times and stock">{form(MRP2)}</Panel>
        </>}
        {tab === "mrp3" && <Panel title="Strategy, forecast consumption and buffers">{form(MRP3)}</Panel>}
        {tab === "mrp4" && <Structure ds={ds} prod={prod} loc={loc} />}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
interface Element { date: string; kind: "stock" | "in" | "out"; what: string; detail?: string; qty: number; link?: string[] }

/** Every receipt and requirement of the node, by date (MD04). */
function elements(ds: Dataset, plan: PlanResult, prod: string, loc: string, nm: ReturnType<typeof useNames>): Element[] {
  const out: Element[] = [];
  const node = plan.nodes.find((n) => n.location === loc && n.product === prod);
  const start = ds.settings.planning_start;
  if (node && node.on_hand) out.push({ date: start, kind: "stock", what: "On hand today", qty: node.on_hand });
  for (const r of plan.receipts) if (r.location === loc && r.product === prod)
    out.push({ date: r.date, kind: "in", what: `Firm ${r.kind} order ${r.id}`, qty: r.qty });
  const byId = new Map(plan.orders.map((o) => [o.id, o]));
  for (const o of plan.orders) {
    if (o.location === loc && o.product === prod) {
      const from = o.kind === "transfer" && o.origin ? ` from ${nm.loc(o.origin)}` : o.kind === "buy" && o.origin ? ` from ${nm.loc(o.origin)}` : "";
      out.push({ date: o.available_date, kind: "in", what: `Planned ${ORDER_LABEL[o.kind]?.toLowerCase() ?? o.kind} ${o.id}${from}`,
        detail: `starts ${day(o.start_date)}${o.start_in_past ? " — should already have started" : ""}`, qty: o.qty, link: ["plan", "orders", o.id] });
    }
    if (o.kind === "make" && o.location === loc && o.product !== prod) {
      const ps = (ds.production_sources ?? []).find((x) => x.id === o.source_id);
      const co = ps?.co_products?.find((c) => c.product === prod);
      if (ps && co) out.push({ date: o.available_date, kind: "in", what: `Comes out of ${o.id} (${nm.prod(o.product)})`,
        detail: co.cost_share ? "co-product" : "by-product", qty: o.qty * co.qty / (ps.output_qty ?? 1), link: ["plan", "orders", o.id] });
    }
  }
  const KIND: Record<string, string> = { forecast: "Forecast", sales_order: "Customer order", dependent: "Needed to make", transfer: "Shipped out for" };
  for (const r of plan.requirements) {
    if (r.location !== loc || r.product !== prod) continue;
    const parent = r.parent_order ? byId.get(r.parent_order) : undefined;
    const what = r.kind === "dependent" && parent ? `Needed to make ${nm.prod(parent.product)} (${parent.id})`
      : r.kind === "transfer" && parent ? `Shipped to ${nm.loc(parent.location)} (${parent.id})`
      : r.kind === "dependent" || r.kind === "transfer" ? `${KIND[r.kind]} ${r.parent_order ?? ""}` : KIND[r.kind] ?? r.kind;
    out.push({ date: r.date, kind: "out", what, detail: r.past_due ? "overdue: due before today" : undefined, qty: -r.qty,
      link: parent ? ["plan", "orders", parent.id] : undefined });
  }
  const rank = { stock: 0, in: 1, out: 2 };
  return out.sort((a, b) => a.date.localeCompare(b.date) || rank[a.kind] - rank[b.kind]);
}

function StockList({ ds, plan, prod, loc }: { ds: Dataset; plan: PlanResult | null; prod: string; loc: string }) {
  const nm = useNames();
  const fresh = useStore((s) => freshness(s, "plan"));
  const running = useStore((s) => s.runs.plan.running);
  const els = useMemo(() => (plan ? elements(ds, plan, prod, loc, nm) : []), [ds, plan, prod, loc, nm]);
  if (!plan) return (
    <Panel><Empty title="Not planned yet">
      <p>The stock and requirements list shows what the supply plan expects, day by day. Plan supply to see it.</p>
      <button className="btn primary" disabled={running} onClick={() => store.run("plan")}>{running ? "Planning…" : "Plan supply"}</button>
    </Empty></Panel>
  );
  const node = plan.nodes.find((n) => n.location === loc && n.product === prod);
  const ss = node?.buckets[0]?.safety_stock ?? 0;
  const ex = plan.exceptions.filter((e) => e.location === loc && e.product === prod && e.severity !== "info");
  let bal = 0;
  const rows = els.map((e) => { bal += e.qty; return { ...e, bal }; });
  const low = rows.find((r) => r.bal < -1e-6);
  return (
    <div className="stack">
      {fresh === "stale" && <div className="banner warning">The data changed since this plan ran. <button className="btn sm" disabled={running} onClick={() => store.run("plan")}>Plan again</button></div>}
      <Panel title={<h3>What the plan expects</h3>} actions={<a className="btn sm ghost" href={href("plan", "node", loc, prod)}>Week by week</a>}>
        {!node ? <p className="muted">The plan does not reach {nm.prod(prod)} at {nm.loc(loc)}: nothing needs it here.</p> : <>
          <p style={{ marginTop: 0 }}>{low ? <>Stock runs out on <b>{day(low.date)}</b> ({qty(low.bal)}).</> : <>Stock never runs out over the plan.</>}
            {ss > 0 && <> Safety stock is {qty(ss)}.</>}
            {node.lead_time_days != null && <> Getting more takes about {qty(Math.round(node.lead_time_days * 10) / 10)} days.</>}</p>
          {ex.length > 0 && <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{ex.map((e, i) => <li key={i}>
            <Badge sev={e.severity === "error" ? "error" : "warning"}>{codeLabel(e.code)}</Badge> {e.date ? `from ${day(e.date)}` : ""}{e.qty ? ` · ${qty(e.qty)}` : ""}</li>)}</ul>}
        </>}
      </Panel>
      {node && <Panel flush title={`Receipts and requirements (${rows.length})`}>
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Date</th><th>What</th><th className="num">In / out</th><th className="num">Available after</th></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={i}>
                <td className="nowrap">{day(r.date)}</td>
                <td>{r.link ? <a href={href(...r.link)}>{r.what}</a> : r.what}{r.detail && <div className="faint small">{r.detail}</div>}</td>
                <td className={`num ${r.qty < 0 ? "" : "pos"}`}>{r.qty > 0 ? "+" : ""}{qty(r.qty)}</td>
                <td className={`num ${r.bal < -1e-6 ? "neg" : r.bal < ss - 1e-6 ? "warnc" : ""}`}><b>{qty(r.bal)}</b></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Panel>}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Sources({ ds, prod, loc, plan }: { ds: Dataset; prod: string; loc: string; plan: PlanResult | null }) {
  const nm = useNames();
  const w = supplyWays(ds, loc, prod);
  const node = plan?.nodes.find((n) => n.location === loc && n.product === prod);
  const none = !w.makes.length && !w.buys.length && !w.ships.length && !w.co.length;
  return (
    <Panel title="How it is got here" actions={<a className="btn sm" href={href("setup", "product", prod, loc)}>Change in the setup wizard</a>}>
      {none ? <p className="muted">It is not made, bought or shipped here yet.</p> : (
        <div className="table-wrap">
          <table className="t">
            <thead><tr><th>Way</th><th>Details</th><th>Lead time</th><th>Priority · share</th><th>Valid</th></tr></thead>
            <tbody>
              {w.makes.map((ps) => <tr key={ps.id}><td><a href={href("data", "production_sources", ps.id)}>Made here</a> <span className="faint small">{ps.id}</span></td>
                <td className="small">{ps.components?.length ?? 0} parts, {ps.operations?.length ?? 0} steps{ps.co_products?.length ? `, yields ${ps.co_products.map((c) => nm.prod(c.product)).join(", ")}` : ""}</td>
                <td className="small">{ps.fixed_lead_time_workdays != null ? `${qty(ps.fixed_lead_time_workdays)} working days` : "from the steps"}</td>
                <td className="small">{ps.priority ?? 1}{ps.quota != null ? ` · ${qty(ps.quota * 100)}%` : ""}</td>
                <td className="small">{validity(ps.valid_from, ps.valid_to)}</td></tr>)}
              {w.co.map((ps) => <tr key={`co-${ps.id}`}><td>Comes out of making {nm.prod(ps.product)}</td>
                <td className="small">{qty(ps.co_products!.find((c) => c.product === prod)!.qty)} per {qty(ps.output_qty ?? 1)} made ({ps.id})</td>
                <td className="small">with the run</td><td /><td /></tr>)}
              {w.buys.map((pu) => <tr key={pu.id}><td><a href={href("data", "purchasing_sources", pu.id)}>Bought from {nm.loc(pu.supplier)}</a></td>
                <td className="small">{qty(pu.price)} {pu.currency ?? ds.settings.currency} each{pu.moq ? `, at least ${qty(pu.moq)}` : ""}{pu.rounding_qty ? `, in multiples of ${qty(pu.rounding_qty)}` : ""}</td>
                <td className="small">{qty(pu.lead_time_days)} days + transit</td>
                <td className="small">{pu.priority ?? 1}{pu.quota != null ? ` · ${qty(pu.quota * 100)}%` : ""}</td>
                <td className="small">{validity(pu.valid_from, pu.valid_to)}</td></tr>)}
              {w.ships.map((ln) => <tr key={ln.id}><td><a href={href("data", "lanes", ln.id)}>Shipped from {nm.loc(ln.origin)}</a></td>
                <td className="small">{ln.products?.length ? `carries ${ln.products.length} product${ln.products.length === 1 ? "" : "s"}` : "carries every product"}</td>
                <td className="small">{qty(ln.modes?.[0]?.transit_days ?? 0)} days in transit</td>
                <td className="small">{ln.priority ?? 1}{ln.quota != null ? ` · ${qty(ln.quota * 100)}%` : ""}</td><td /></tr>)}
            </tbody>
          </table>
        </div>
      )}
      {node?.lead_time_days != null && <p className="small muted">The plan uses about {qty(Math.round(node.lead_time_days * 10) / 10)} days to get more (first way, including goods-receipt time).</p>}
    </Panel>
  );
}

const validity = (a?: string | null, b?: string | null) => !a && !b ? "always" : `${a ? `from ${day(a)}` : ""}${a && b ? " " : ""}${b ? `to ${day(b)}` : ""}`;

// ------------------------------------------------------------------------------------------------
interface TreeRow {
  key: string; depth: number; product: string; perUnit: number; perOrder: number; scrap: number; step?: number | null;
  how: string; tone?: "error" | "info"; valid: boolean; change?: string; phantom: boolean;
}

function explode(ds: Dataset, ps: ProductionSource, on: string, levels: number): TreeRow[] {
  const out: TreeRow[] = [];
  const lpOf = (l: string, p: string) => (ds.location_products ?? []).find((x) => x.location === l && x.product === p);
  const walk = (src: ProductionSource, depth: number, mult: number, path: string[], keyp: string) => {
    for (const [i, c] of (src.components ?? []).entries()) {
      const valid = (!c.valid_from || c.valid_from <= on) && (!c.valid_to || on <= c.valid_to);
      const loss = 1 - (c.scrap ?? 0);
      const perUnit = c.fixed_qty ? 0 : (mult * c.qty) / (src.output_qty ?? 1) / loss;
      const perOrder = c.fixed_qty ? c.qty / loss : 0;
      const w = supplyWays(ds, src.location, c.product);
      const phantom = !!lpOf(src.location, c.product)?.phantom && w.makes.length > 0;
      const how = phantom ? "phantom: its parts go straight in"
        : w.makes.length ? "made here" : w.co.length ? "comes out of another run"
        : w.buys.length ? `bought from ${w.buys.map((b) => ds.locations?.find((l) => l.id === b.supplier)?.name || b.supplier).join(", ")}`
        : w.ships.length ? `shipped from ${w.ships.map((s) => ds.locations?.find((l) => l.id === s.origin)?.name || s.origin).join(", ")}`
        : "no way to get it here";
      const key = `${keyp}/${i}`;
      out.push({ key, depth, product: c.product, perUnit, perOrder, scrap: c.scrap ?? 0, step: c.operation, how, valid,
        tone: how === "no way to get it here" ? "error" : phantom ? "info" : undefined, change: c.change || undefined, phantom });
      const sub = [...w.makes].sort((a, b) => (a.priority ?? 1) - (b.priority ?? 1))[0];
      if (valid && sub && depth + 1 < levels && !path.includes(c.product)) walk(sub, depth + 1, c.fixed_qty ? 1 : perUnit, [...path, c.product], key);
    }
  };
  walk(ps, 0, 1, [ps.product], ps.id);
  return out;
}

function Structure({ ds, prod, loc }: { ds: Dataset; prod: string; loc: string }) {
  const nm = useNames();
  const versions = (ds.production_sources ?? []).filter((p) => p.location === loc && p.product === prod)
    .sort((a, b) => (a.priority ?? 1) - (b.priority ?? 1) || a.id.localeCompare(b.id));
  const [vid, setVid] = useState<string>(versions[0]?.id ?? "");
  const [on, setOn] = useState<string>(ds.settings.planning_start);
  const [levels, setLevels] = useState(9);
  const ps = versions.find((v) => v.id === vid) ?? versions[0];
  const rows = useMemo(() => (ps ? explode(ds, ps, on, levels) : []), [ds, ps, on, levels]);
  const used = (ds.production_sources ?? []).flatMap((p) => (p.components ?? []).filter((c) => c.product === prod).map((c) => ({ p, c })));
  return (
    <div className="stack">
      <Panel title="Ways of making it here (production versions)" actions={<a className="btn sm" href={href("setup", "product", prod, loc)}>Add or change</a>}>
        {!versions.length ? <p className="muted">It is not made here.</p> : (
          <div className="table-wrap">
            <table className="t">
              <thead><tr><th>Version</th><th>Makes per run</th><th>Parts · steps</th><th>Also yields</th><th>Priority · share</th><th>Lots</th><th>Valid</th></tr></thead>
              <tbody>{versions.map((v) => (
                <tr key={v.id} className={`clickable ${ps?.id === v.id ? "selected" : ""}`} onClick={() => setVid(v.id)}>
                  <td><a href={href("data", "production_sources", v.id)} onClick={(e) => e.stopPropagation()}>{v.id}</a></td>
                  <td className="num">{qty(v.output_qty ?? 1)}</td>
                  <td className="small">{v.components?.length ?? 0} · {v.operations?.length ?? 0}
                    {v.operations?.some((o) => o.subcontract) && <div className="faint">a step done outside</div>}
                    {v.operations?.some((o) => o.send_ahead_qty) && <div className="faint">overlapped steps</div>}</td>
                  <td className="small">{v.co_products?.length ? v.co_products.map((c) => `${nm.prod(c.product)} (${c.cost_share ? `${qty(c.cost_share * 100)}% of cost` : "by-product"})`).join(", ") : "—"}</td>
                  <td className="small">{v.priority ?? 1}{v.quota != null ? ` · ${qty(v.quota * 100)}%` : ""}</td>
                  <td className="small">{v.min_lot ? `min ${qty(v.min_lot)}` : ""}{v.max_lot ? ` max ${qty(v.max_lot)}` : ""}{!v.min_lot && !v.max_lot ? "any size" : ""}</td>
                  <td className="small">{validity(v.valid_from, v.valid_to)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </Panel>
      {ps && <Panel flush title={<h3>What one {nm.prod(prod)} is made from</h3>} actions={<div className="row wrap">
        <label className="small muted">On <input className="input" type="date" value={on} onChange={(e) => setOn(e.target.value || ds.settings.planning_start)} style={{ width: 150 }} aria-label="BOM as of" /></label>
        <select className="select" style={{ width: "auto" }} value={levels} onChange={(e) => setLevels(Number(e.target.value))} aria-label="Levels">
          <option value={1}>1 level</option><option value={2}>2 levels</option><option value={3}>3 levels</option><option value={9}>All levels</option></select></div>}>
        {!rows.length ? <p className="muted" style={{ padding: "0 14px" }}>No parts: it is made from nothing.</p> : (
          <div className="table-wrap">
            <table className="t bom">
              <thead><tr><th>Part</th><th className="num">Per {nm.prod(prod)}</th><th className="num">Per run</th><th className="num">Scrap</th><th>Step</th><th>How it is got</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.key} className={r.valid ? "" : "struck"} title={r.valid ? undefined : "Not used on this date (engineering change)"}>
                  <td style={{ paddingLeft: 12 + r.depth * 18 }}>{r.depth > 0 && <span className="faint">└ </span>}
                    <a href={href("material", r.product, loc)}>{nm.prod(r.product)}</a>
                    {r.change && <span className="chip small" title="Engineering change">{r.change}</span>}
                    {!r.valid && <span className="faint small"> not used on this date</span>}</td>
                  <td className="num">{r.perUnit ? qty(r.perUnit) : ""}</td>
                  <td className="num">{r.perOrder ? qty(r.perOrder) : ""}</td>
                  <td className="num">{r.scrap ? `${qty(r.scrap * 100)}%` : ""}</td>
                  <td>{r.step ?? ""}</td>
                  <td className="small">{r.tone ? <Badge sev={r.tone}>{r.how}</Badge> : r.how}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
        <p className="faint small" style={{ padding: "0 14px" }}>Per {nm.prod(prod)}: including each part's scrap. Per run: a fixed quantity used once per production run, whatever its size.</p>
      </Panel>}
      <Panel title="Where it is used">
        {!used.length ? <p className="muted">No product uses it as a part.</p> : (
          <ul style={{ margin: 0, paddingLeft: 18 }}>{used.map(({ p, c }, i) => <li key={i}>
            <a href={href("material", p.product, p.location, "mrp4")}>{nm.prod(p.product)}</a> at {nm.loc(p.location)}: {qty(c.qty)}{c.fixed_qty ? " per run" : ` per ${qty(p.output_qty ?? 1)}`}
            {(c.valid_from || c.valid_to) && <span className="faint small"> ({validity(c.valid_from, c.valid_to)})</span>}</li>)}</ul>
        )}
      </Panel>
    </div>
  );
}
