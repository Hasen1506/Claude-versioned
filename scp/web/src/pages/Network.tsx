import { useMemo, useState } from "react";
import type { Dataset, NetEdge, NetLocation, NetworkView, PlanResult } from "../api/types";
import { Badge, Empty, Panel, StageHeader, cols, useTooltip } from "../components/ui";
import { TYPE_LABEL } from "../lib/format";
import { go, href } from "../lib/router";
import { useStore, NO_ISSUES } from "../state/store";

const TYPE_COLOR: Record<string, string> = {
  supplier: "var(--series-2)", plant: "var(--series-1)", dc: "var(--series-3)", warehouse: "var(--series-3)",
  store: "var(--series-7)", customer: "var(--series-4)",
};
const TYPE_GLYPH: Record<string, string> = { supplier: "S", plant: "P", dc: "D", warehouse: "W", store: "R", customer: "C" };
const NODE_W = 196;
const NODE_H = 46;
const ROW = 62;

interface Placed { loc: NetLocation; x: number; y: number }

/** Column layout with two barycenter sweeps to reduce edge crossings. */
function layout(net: NetworkView): { placed: Map<string, Placed>; width: number; height: number; cols: number } {
  const cols = Math.max(0, ...net.locations.map((l) => l.layer)) + 1;
  const byCol: NetLocation[][] = Array.from({ length: cols }, () => []);
  const order = ["supplier", "plant", "warehouse", "dc", "store", "customer"];
  net.locations.forEach((l) => byCol[l.layer].push(l));
  byCol.forEach((c) => c.sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || a.region.localeCompare(b.region) || a.id.localeCompare(b.id)));
  const pos = new Map<string, number>();
  const assign = () => byCol.forEach((c) => c.forEach((l, i) => pos.set(l.id, i)));
  assign();
  const nbrs = new Map<string, string[]>();
  for (const e of net.edges) {
    nbrs.set(e.origin, [...(nbrs.get(e.origin) ?? []), e.destination]);
    nbrs.set(e.destination, [...(nbrs.get(e.destination) ?? []), e.origin]);
  }
  for (let sweep = 0; sweep < 4; sweep++) {
    const cs = sweep % 2 === 0 ? byCol.map((_, i) => i) : byCol.map((_, i) => cols - 1 - i);
    for (const ci of cs) {
      const bc = (l: NetLocation) => {
        const ns = (nbrs.get(l.id) ?? []).filter((n) => pos.has(n));
        return ns.length ? ns.reduce((s, n) => s + pos.get(n)!, 0) / ns.length : pos.get(l.id)!;
      };
      byCol[ci].sort((a, b) => bc(a) - bc(b));
      assign();
    }
  }
  const maxRows = Math.max(1, ...byCol.map((c) => c.length));
  const colGap = cols > 1 ? Math.max(250, (1180 - NODE_W) / (cols - 1)) : 250;
  const width = (cols - 1) * colGap + NODE_W + 40;
  const height = maxRows * ROW + 50;
  const placed = new Map<string, Placed>();
  byCol.forEach((c, ci) => {
    const offset = ((maxRows - c.length) * ROW) / 2;
    c.forEach((loc, i) => placed.set(loc.id, { loc, x: 20 + ci * colGap, y: 40 + offset + i * ROW }));
  });
  return { placed, width, height, cols };
}

function bomClosure(ds: Dataset, roots: string[]): Set<string> {
  const out = new Set(roots);
  const stack = [...roots];
  while (stack.length) {
    const p = stack.pop()!;
    for (const ps of ds.production_sources ?? [])
      if (ps.product === p)
        for (const c of ps.components ?? []) if (!out.has(c.product)) { out.add(c.product); stack.push(c.product); }
  }
  return out;
}

function health(ds: Dataset, issues: { object_type: string; object_id: string; severity: string }[],
  plan: PlanResult | null): Map<string, { errors: number; warnings: number }> {
  const out = new Map<string, { errors: number; warnings: number }>();
  const bump = (loc: string, sev: string) => {
    const h = out.get(loc) ?? { errors: 0, warnings: 0 };
    if (sev === "error") h.errors++;
    else if (sev === "warning") h.warnings++;
    out.set(loc, h);
  };
  const locOfObject = (t: string, id: string): string | null => {
    if (t === "location") return id;
    if (t === "location_product") return id.split("/")[0];
    if (t === "resource") return ds.resources?.find((r) => r.id === id)?.location ?? null;
    if (t === "production_source") return ds.production_sources?.find((r) => r.id === id)?.location ?? null;
    if (t === "purchasing_source") return ds.purchasing_sources?.find((r) => r.id === id)?.location ?? null;
    if (t === "lane") return ds.lanes?.find((r) => r.id === id)?.destination ?? null;
    if (t === "network") return id;
    return null;
  };
  for (const i of issues) {
    const l = locOfObject(i.object_type, i.object_id);
    if (l) bump(l, i.severity);
  }
  for (const e of plan?.exceptions ?? []) {
    const l = e.location ?? (e.resource ? ds.resources?.find((r) => r.id === e.resource)?.location : null);
    if (l) bump(l, e.severity);
  }
  return out;
}

export function Network({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset);
  const net = useStore((s) => s.network);
  const issues = useStore((s) => s.validation?.issues ?? NO_ISSUES);
  const plan = useStore((s) => s.runs.plan.data);
  const [product, setProduct] = useState("");
  const [withBom, setWithBom] = useState(true);
  const [geo, setGeo] = useState(false);
  const tip = useTooltip();
  const selected = route[1];

  const lay = useMemo(() => (net ? layout(net) : null), [net]);
  const focus = useMemo(() => (ds && product ? (withBom ? bomClosure(ds, [product]) : new Set([product])) : null),
    [ds, product, withBom]);
  const hp = useMemo(() => (net && ds ? health(ds, issues, plan) : new Map()), [net, ds, issues, plan]);

  if (!ds) return null;
  if (!net || !lay) return <Empty title="Building the network…" />;
  if (!net.locations.length) {
    return <Empty title="No places yet"><p>Start by adding your plants, warehouses, suppliers and customers.</p>
      <a className="btn primary" href={href("setup", "network")}>Set up places and routes</a></Empty>;
  }

  const active = (l: NetLocation) => !focus || l.products.some((p) => focus.has(p));
  const edgeActive = (e: NetEdge) => {
    if (!focus) return true;
    const a = lay.placed.get(e.origin)?.loc;
    const b = lay.placed.get(e.destination)?.loc;
    if (!a || !b || !active(a) || !active(b)) return false;
    return !e.products || e.products.some((p) => focus.has(p));
  };
  const geoOk = net.locations.filter((l) => l.lat !== null && l.lon !== null).length >= 2;
  const products = (ds.products ?? []).map((p) => p.id);

  return (
    <div>
      <StageHeader title="Network" kicker="Your supply network, from suppliers to customers. Pick a product to trace its path, with its components, through every place that stocks, makes, buys or moves it." right={<>
          <select className="select" value={product} onChange={(e) => setProduct(e.target.value)} style={{ width: 220 }} aria-label="Trace product">
            <option value="">All products</option>
            {products.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          <label className="row small"><input type="checkbox" checked={withBom} onChange={(e) => setWithBom(e.target.checked)} /> incl. components</label>
          <div className="row" role="group" aria-label="View">
            <button className={`btn sm ${!geo ? "primary" : ""}`} onClick={() => setGeo(false)}>Flow</button>
            <button className={`btn sm ${geo ? "primary" : ""}`} onClick={() => setGeo(true)} disabled={!geoOk}
              title={geoOk ? "" : "Add latitude/longitude to locations"}>Geography</button>
          </div>
      </>} />
      <div className="content">
      {net.cycles.length > 0 && <div className="banner error"><Badge sev="error">Circular sourcing</Badge>{net.cycles.length} loop(s) — see Readiness.</div>}
      <div className="split" style={cols(selected ? "minmax(0,1fr) 380px" : "minmax(0,1fr)")}>
        <Panel flush>
          <div className="legend" style={{ padding: "10px 14px 0" }}>
            {Object.entries(TYPE_LABEL).filter(([t]) => net.locations.some((l) => l.type === t)).map(([t, label]) => (
              <span key={t}><span className="key box" style={{ background: TYPE_COLOR[t] }} />{label}</span>
            ))}
            <span><span className="key" style={{ background: "var(--text-3)" }} />Transport lane</span>
            <span><span className="key" style={{ background: "var(--series-2)" }} />Purchasing</span>
          </div>
          <div className="net" style={{ overflowX: "auto" }}>
            {geo ? <GeoMap net={net} selected={selected} active={active} edgeActive={edgeActive} tip={tip} />
              : (
                <svg viewBox={`0 0 ${lay.width} ${lay.height}`} style={{ minWidth: selected ? undefined : lay.width * 0.75 }} role="img" aria-label="Network flow map">
                  {Array.from({ length: lay.cols }, (_, ci) => {
                    const any = [...lay.placed.values()].find((p) => p.loc.layer === ci);
                    return any ? <text key={ci} className="col-label" x={any.x} y={22}>{colName([...lay.placed.values()].filter((p) => p.loc.layer === ci).map((p) => p.loc.type))}</text> : null;
                  })}
                  {net.edges.map((e) => {
                    const a = lay.placed.get(e.origin);
                    const b = lay.placed.get(e.destination);
                    if (!a || !b) return null;
                    const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2;
                    const back = x2 <= x1;
                    const d = back
                      ? `M${a.x + NODE_W / 2},${a.y + NODE_H} C${a.x + NODE_W / 2},${a.y + NODE_H + 40} ${b.x + NODE_W / 2},${b.y + NODE_H + 40} ${b.x + NODE_W / 2},${b.y + NODE_H}`
                      : `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`;
                    const on = edgeActive(e);
                    const hot = selected && (e.origin === selected || e.destination === selected);
                    return (
                      <g key={`${e.kind}-${e.origin}-${e.destination}`}>
                        <path className={`edge ${e.kind} ${on ? "" : "dim"} ${hot ? "hot" : ""}`} d={d} markerEnd="" />
                        <path className="edge-hit" d={d} onMouseMove={(ev) => tip.show(ev, <EdgeTip e={e} />)} onMouseLeave={tip.hide} />
                      </g>
                    );
                  })}
                  {[...lay.placed.values()].map(({ loc, x, y }) => {
                    const h = hp.get(loc.id);
                    return (
                      <g key={loc.id} className={`node ${selected === loc.id ? "sel" : ""} ${active(loc) ? "" : "dim"}`}
                        transform={`translate(${x},${y})`} style={{ cursor: "pointer" }}
                        onClick={() => go("network", loc.id)} onMouseMove={(ev) => tip.show(ev, <NodeTip loc={loc} />)}
                        onMouseLeave={tip.hide}>
                        <rect width={NODE_W} height={NODE_H} />
                        <circle cx={20} cy={NODE_H / 2} r={11} fill={TYPE_COLOR[loc.type]} />
                        <text x={20} y={NODE_H / 2 + 4} textAnchor="middle" style={{ fill: "#fff", fontSize: 11 }}>{TYPE_GLYPH[loc.type]}</text>
                        <text x={38} y={19}>{trunc(loc.name || loc.id, 20)}</text>
                        <text className="sub" x={38} y={34}>{trunc(loc.name && loc.name !== loc.id ? loc.id : TYPE_LABEL[loc.type], 24)}</text>
                        {h && (h.errors > 0 || h.warnings > 0) && (
                          <g transform={`translate(${NODE_W - 8},-6)`}>
                            <rect x={-26} y={0} width={28} height={16} style={{ fill: h.errors ? "var(--critical)" : "var(--warning)", stroke: "none" }} />
                            <text x={-12} y={12} textAnchor="middle" style={{ fill: h.errors ? "#fff" : "#000", fontSize: 10, fontWeight: 700 }}>
                              {h.errors ? `!${h.errors}` : `▲${h.warnings}`}
                            </text>
                          </g>
                        )}
                      </g>
                    );
                  })}
                </svg>
              )}
          </div>
        </Panel>
        {selected && <LocationPanel id={selected} ds={ds} net={net} plan={plan} />}
      </div>
      {tip.node}
      </div>
    </div>
  );
}

function colName(types: string[]): string {
  const t = [...new Set(types)];
  if (t.length === 1) return `${TYPE_LABEL[t[0]]}s`;
  return t.map((x) => TYPE_LABEL[x]).join(" / ");
}

const trunc = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function EdgeTip({ e }: { e: NetEdge }) {
  return (
    <div>
      <div style={{ fontWeight: 600 }}>{e.origin} → {e.destination}</div>
      <div className="muted">{e.kind === "lane" ? `Lane ${e.ids.join(", ")}` : `Purchasing ${e.ids.join(", ")}`}</div>
      {e.modes.length > 0 && <div>Modes: {e.modes.join(", ")}{e.transit_days !== null && ` · ${e.transit_days} d transit`}</div>}
      <div>Products: {e.products ? e.products.join(", ") : "all"}</div>
    </div>
  );
}

function NodeTip({ loc }: { loc: NetLocation }) {
  return (
    <div>
      <div style={{ fontWeight: 600 }}>{loc.name}</div>
      <div className="muted">{TYPE_LABEL[loc.type]}{loc.region && ` · ${loc.region}`}</div>
      <div>{loc.products.length} product(s){loc.resources.length > 0 && ` · ${loc.resources.length} resource(s)`}</div>
    </div>
  );
}

function GeoMap({ net, selected, active, edgeActive, tip }: {
  net: NetworkView; selected?: string; active: (l: NetLocation) => boolean; edgeActive: (e: NetEdge) => boolean;
  tip: ReturnType<typeof useTooltip>;
}) {
  const pts = net.locations.filter((l) => l.lat !== null && l.lon !== null);
  const W = 1000, H = 620, P = 60;
  const lons = pts.map((p) => p.lon!), lats = pts.map((p) => p.lat!);
  const [x0, x1, y0, y1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const sx = (W - 2 * P) / Math.max(1e-6, x1 - x0), sy = (H - 2 * P) / Math.max(1e-6, y1 - y0);
  const s = Math.min(sx, sy);
  const px = (l: NetLocation) => P + (l.lon! - x0) * s;
  const py = (l: NetLocation) => H - P - (l.lat! - y0) * s;
  const at = new Map(pts.map((l) => [l.id, l]));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Network geography">
      {net.edges.map((e) => {
        const a = at.get(e.origin), b = at.get(e.destination);
        if (!a || !b) return null;
        const d = `M${px(a)},${py(a)} L${px(b)},${py(b)}`;
        return (
          <g key={`${e.kind}-${e.origin}-${e.destination}`}>
            <path className={`edge ${e.kind} ${edgeActive(e) ? "" : "dim"}`} d={d} />
            <path className="edge-hit" d={d} onMouseMove={(ev) => tip.show(ev, <EdgeTip e={e} />)} onMouseLeave={tip.hide} />
          </g>
        );
      })}
      {pts.map((l) => (
        <g key={l.id} className={`node ${active(l) ? "" : "dim"}`} style={{ cursor: "pointer" }} onClick={() => go("network", l.id)}
          onMouseMove={(ev) => tip.show(ev, <NodeTip loc={l} />)} onMouseLeave={tip.hide}>
          <circle cx={px(l)} cy={py(l)} r={selected === l.id ? 10 : 8} fill={TYPE_COLOR[l.type]} stroke="var(--surface)" strokeWidth={2} />
          <text x={px(l) + 12} y={py(l) + 4} style={{ font: "600 11px var(--font)" }}>{l.id}</text>
        </g>
      ))}
    </svg>
  );
}

function LocationPanel({ id, ds, net, plan }: { id: string; ds: Dataset; net: NetworkView; plan: PlanResult | null }) {
  const loc = net.locations.find((l) => l.id === id);
  const raw = ds.locations?.find((l) => l.id === id);
  if (!loc || !raw) return <Panel><div className="faint">Location {id} not found.</div></Panel>;
  const nodes = net.nodes.filter((n) => n.location === id);
  const inbound = net.edges.filter((e) => e.destination === id);
  const outbound = net.edges.filter((e) => e.origin === id);
  const planned = new Set((plan?.nodes ?? []).filter((n) => n.location === id).map((n) => n.product));
  return (
    <Panel title={<div className="context-bar"><span>{TYPE_LABEL[loc.type]}</span><span>›</span><b>{loc.id}</b></div>}
      actions={<><a className="btn sm" href={href("data", "locations", id)}>Edit</a><a className="btn ghost sm" href={href("network")}>Close</a></>}>
      <div className="stack">
        <div>
          <div style={{ fontWeight: 600 }}>{loc.name}</div>
          <div className="muted small">{loc.region || "—"}{raw.calendar && ` · calendar ${raw.calendar}`}
            {raw.storage_capacity_m3 != null && ` · ${raw.storage_capacity_m3} m³ storage`}</div>
        </div>
        {loc.resources.length > 0 && (
          <div>
            <h3 style={{ marginBottom: 4 }}>Resources</h3>
            <div className="chips">{loc.resources.map((r) => <a key={r} className="chip" href={href("data", "resources", r)}>{r}</a>)}</div>
          </div>
        )}
        <div>
          <h3 style={{ marginBottom: 4 }}>{loc.type === "supplier" ? "Sells" : "Products planned here"}</h3>
          {loc.type === "supplier" ? (
            <div className="chips">{loc.products.map((p) => <span key={p} className="chip">{p}</span>)}</div>
          ) : nodes.length ? (
            <table className="t">
              <thead><tr><th>Product</th><th>Supplied by</th><th className="num">LLC</th></tr></thead>
              <tbody>
                {nodes.sort((a, b) => (a.llc ?? 99) - (b.llc ?? 99) || a.product.localeCompare(b.product)).map((n) => (
                  <tr key={n.product}>
                    <td>{planned.has(n.product) ? <a href={href("plan", "node", id, n.product)}>{n.product}</a> : n.product}</td>
                    <td className="small">{n.options.length ? n.options.map((o) => `${o.kind} ${o.source_id}`).join(", ") : <Badge sev="error">no source</Badge>}</td>
                    <td className="num">{n.llc ?? "∞"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="faint small">Nothing is planned at this location yet.</div>}
        </div>
        <EdgeList title="Inbound" edges={inbound} other={(e) => e.origin} />
        <EdgeList title="Outbound" edges={outbound} other={(e) => e.destination} />
      </div>
    </Panel>
  );
}

function EdgeList({ title, edges, other }: { title: string; edges: NetEdge[]; other: (e: NetEdge) => string }) {
  if (!edges.length) return null;
  return (
    <div>
      <h3 style={{ marginBottom: 4 }}>{title}</h3>
      <table className="t">
        <tbody>
          {edges.map((e) => (
            <tr key={`${e.kind}-${e.origin}-${e.destination}`}>
              <td><a href={href("network", other(e))}>{other(e)}</a></td>
              <td className="small muted">{e.kind === "lane" ? `${e.modes.join("/")} · ${e.transit_days ?? "?"} d` : "purchase"}</td>
              <td className="small">{e.products ? e.products.join(", ") : "all products"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
