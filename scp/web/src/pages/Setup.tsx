// Guided setup: build a company the way a planner describes it, not table by table.
//   #/setup                          what's missing, and the three builders
//   #/setup/network                  places, and the routes goods take between them (click two places to connect)
//   #/setup/products                 the product list
//   #/setup/product/<id>[/<place>]   one product: where it is needed, and how it gets to each place
//                                    (made here from these parts on this line / bought from / shipped from)
// Every form writes ordinary master-data records, so Master data stays the place for bulk edits and depth.
import { useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { Dataset, LocationProduct, NetworkView, ProductionSource, ValidationResult } from "../api/types";
import { Checklist } from "../components/Checklist";
import { Badge, Edits, Panel, StageHeader } from "../components/ui";
import { TYPE_LABEL } from "../lib/format";
import { namesOf } from "../lib/names";
import { go, href } from "../lib/router";
import { store, useStore } from "../state/store";
import { applyCompany, CompanyPanel, coverLabel } from "./Company";

/** A stable empty list: a fresh `[]` from a store selector would re-render forever. */
const NO_SETUP: NonNullable<ValidationResult["setup"]> = [];

// ---- helpers --------------------------------------------------------------------------------------------------
/** A readable, unique id from a name: "Pune plant" → "PUNE-PLANT". */
export function newId(name: string, taken: Iterable<string>, fallback: string): string {
  const used = new Set(taken);
  const base = name.toUpperCase().normalize("NFKD").replace(/[^A-Z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 28) || fallback;
  let id = base, n = 2;
  while (used.has(id)) id = `${base}-${n++}`;
  return id;
}

const PLACE_TYPES: { type: string; what: string }[] = [
  { type: "plant", what: "makes products" },
  { type: "dc", what: "keeps stock and ships it on" },
  { type: "warehouse", what: "keeps stock" },
  { type: "store", what: "sells to consumers from its own stock" },
  { type: "supplier", what: "sells you materials" },
  { type: "customer", what: "a customer or sales channel you ship to" },
];
const PRODUCT_TYPES: { type: string; label: string; what: string }[] = [
  { type: "FG", label: "Finished good", what: "what you sell" },
  { type: "SFG", label: "Semi-finished", what: "made here, then used to make something else" },
  { type: "RM", label: "Raw material", what: "bought, then used to make something" },
  { type: "PKG", label: "Packaging", what: "bought packing material" },
];
const MODES: { mode: string; label: string }[] = [
  { mode: "truck_ftl", label: "Truck (full load)" }, { mode: "truck_ltl", label: "Truck (part load)" }, { mode: "reefer", label: "Refrigerated truck" }, { mode: "rail", label: "Rail" },
  { mode: "sea", label: "Sea" }, { mode: "air", label: "Air" }, { mode: "courier", label: "Courier" },
];
const modeLabel = (m: string) => MODES.find((x) => x.mode === m)?.label ?? m;
const STOCKING = ["plant", "dc", "warehouse", "store"];
/** Units counted in whole pieces (as the engine's COUNT_UNITS): a product in one is planned in whole units. */
const WHOLE = new Set(["EA", "EACH", "PC", "PCS", "PCE", "PIECE", "PIECES", "ST", "NO", "NOS", "NR", "UN", "UNIT", "UNITS", "ITEM",
  "BOX", "BX", "CS", "CASE", "CAR", "CTN", "CARTON", "PK", "PAC", "PACK", "PKT", "PACKET", "BAG", "BG", "SACK",
  "BOT", "BTL", "BOTTLE", "CAN", "TIN", "DR", "DRUM", "PAIL", "BKT", "BUCKET", "JAR", "TUB", "TUBE", "ROL", "ROLL",
  "SET", "KIT", "PAL", "PALLET", "PR", "PAIR", "DZ", "DOZ", "DOZEN", "SHEET", "REEL", "COIL", "BALE", "CRATE"]);
/** Append a record to a dataset collection. The engine fills every default, so a record needs only what the planner said
 *  (the generated types list defaulted fields as required, since responses always carry them). */
function add(d: Dataset, coll: string, rec: Record<string, unknown>) {
  const c = d as unknown as Record<string, Record<string, unknown>[] | undefined>;
  (c[coll] ??= []).push(rec);
}
const num = (v: string) => (v.trim() === "" ? NaN : Number(v));

function names(ds: Dataset) {
  const loc = Object.fromEntries((ds.locations ?? []).map((l) => [l.id, l.name || l.id])) as Record<string, string>;
  const prod = Object.fromEntries((ds.products ?? []).map((p) => [p.id, p.name || p.id])) as Record<string, string>;
  return { loc: (id: string) => loc[id] ?? id, prod: (id: string) => prod[id] ?? id };
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return <label className="qf"><span className="qf-l">{label}</span>{children}{hint && <span className="qf-h">{hint}</span>}</label>;
}

// ---- page ------------------------------------------------------------------------------------------------------
export function Setup({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset);
  if (!ds) return null;
  const sub = route[1] ?? "";
  if (sub === "company") return <Edits><CompanySetup ds={ds} /></Edits>;
  if (sub === "network") return <Edits><NetworkBuilder ds={ds} /></Edits>;
  if (sub === "products") return <Edits><Products ds={ds} /></Edits>;
  if (sub === "product") return <Edits><ProductWizard ds={ds} product={route[2]} place={route[3]} /></Edits>;
  return <Edits><SetupHome ds={ds} /></Edits>;
}

function SetupHome({ ds }: { ds: Dataset }) {
  const setup = useStore((s) => s.validation?.setup ?? NO_SETUP);
  const n = (k: keyof Dataset) => ((ds[k] as unknown[] | undefined) ?? []).length;
  return (
    <div>
      <StageHeader title="Set up your company" kicker={<>Describe your business the way you'd explain it to a new colleague: the places goods move
        between, the products, and for each product how it is made, bought or shipped. Everything here writes ordinary master
        data, so you can refine any record later in Master data.</>} />
      <div className="content stack">
        <div className="setup-cards">
          <a className="setup-card" href={href("setup", "company")}><b>Your company</b>
            <span>Name, currency, when planning starts, the working week, how much each order covers, exchange rates.</span>
            <span className="faint small">{ds.settings.currency} · orders cover {coverLabel(ds.settings as never)}</span></a>
          <a className="setup-card" href={href("setup", "network")}><b>1. Places and routes</b>
            <span>Plants, warehouses, suppliers and customers, and which routes goods take between them.</span>
            <span className="faint small">{n("locations")} places · {n("lanes")} routes</span></a>
          <a className="setup-card" href={href("setup", "products")}><b>2. Products</b>
            <span>What you sell, and the parts and materials it's made from.</span>
            <span className="faint small">{n("products")} products</span></a>
          <a className="setup-card" href={href("setup", "product")}><b>3. How each product is supplied</b>
            <span>Made here from these parts on this line, bought from a supplier, or shipped from another place.</span>
            <span className="faint small">{n("production_sources")} made · {n("purchasing_sources")} bought</span></a>
          <a className="setup-card" href={href("demand")}><b>4. Demand</b>
            <span>What customers will buy: type it in, paste it from a spreadsheet, or forecast it from sales history.</span>
            <span className="faint small">{n("demand")} demand rows · {n("history")} history rows</span></a>
        </div>
        <Panel title="What's missing">{setup.length ? <Checklist items={setup} /> : <p className="muted">Checking…</p>}</Panel>
      </div>
    </div>
  );
}

function CompanySetup({ ds }: { ds: Dataset }) {
  const [saved, setSaved] = useState(false);
  return (
    <div>
      <StageHeader title="Your company" kicker="The settings every plan starts from. Change them any time; the plan goes out of date and is worked out again."
        right={<a className="btn" href={href("setup")}>Back to setup</a>} />
      <div className="content stack">
        {saved && <div className="banner ok" role="status">Saved. <a href={href("setup")}>Back to setup</a></div>}
        <CompanyPanel key={JSON.stringify(ds.settings)} ds={ds} onSave={(v, alsoExact) => { store.update((d) => applyCompany(d, v, alsoExact)); setSaved(true); }} />
        <p className="faint small">More settings (horizon, cost of capital, service level, capacity rules) are in <a href={href("data", "settings")}>Master data → Company settings</a>.</p>
      </div>
    </div>
  );
}

// ---- places and routes -------------------------------------------------------------------------------------------
function NetworkBuilder({ ds }: { ds: Dataset }) {
  const net = useStore((s) => s.network);
  const nm = names(ds);
  const locs = ds.locations ?? [];
  const [name, setName] = useState("");
  const [type, setType] = useState("plant");
  const [region, setRegion] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [mode, setMode] = useState("truck_ftl");
  const [days, setDays] = useState("2");
  const [msg, setMsg] = useState<string | null>(null);

  const addPlace = () => {
    if (!name.trim()) return setMsg("Give the place a name.");
    const id = newId(name, locs.map((l) => l.id), type.toUpperCase());
    store.update((d) => add(d, "locations", { id, name: name.trim(), type, region: region.trim() }));
    setName(""); setRegion(""); setMsg(null);
  };
  const laneProblem = (): string | null => {
    if (!from || !to) return "Pick where goods leave from and where they arrive.";
    if (from === to) return "A route needs two different places.";
    const ft = locs.find((l) => l.id === from)?.type, tt = locs.find((l) => l.id === to)?.type;
    if (ft === "customer") return "Goods don't ship on from a customer.";
    if (tt === "supplier") return "Goods don't ship to a supplier.";
    if (!(num(days) >= 0)) return "Transit days must be 0 or more.";
    if ((ds.lanes ?? []).some((l) => l.origin === from && l.destination === to))
      return `There is already a route from ${nm.loc(from)} to ${nm.loc(to)}; change its days in the list.`;
    return null;
  };
  const addLane = () => {
    const p = laneProblem();
    if (p) return setMsg(p);
    const id = newId(`${from}-${to}`, (ds.lanes ?? []).map((l) => l.id), "LANE");
    store.update((d) => add(d, "lanes", { id, origin: from, destination: to, modes: [{ mode, transit_days: num(days) }] }));
    setFrom(""); setTo(""); setMode("truck_ftl"); setDays("2"); setMsg(null);   // the next route starts from the defaults
  };
  const pick = (id: string) => {
    if (!from || (from && to)) { setFrom(id); setTo(""); }
    else if (id !== from) setTo(id);
  };
  const setLaneDays = (i: number, v: string) => {
    const d = num(v);
    if (!(d >= 0)) return;
    store.update((x) => { x.lanes![i].modes[0].transit_days = d; });
  };
  const removeLane = (i: number) => store.update((x) => { x.lanes!.splice(i, 1); });
  const removePlace = (id: string) => {
    const used = (ds.lanes ?? []).some((l) => l.origin === id || l.destination === id)
      || (ds.production_sources ?? []).some((p) => p.location === id) || (ds.purchasing_sources ?? []).some((p) => p.supplier === id || p.location === id)
      || (ds.demand ?? []).some((d) => d.location === id) || (ds.resources ?? []).some((r) => r.location === id);
    if (used) return setMsg(`${nm.loc(id)} is still used by routes, sources, demand or resources. Remove those first, or edit the place in Master data.`);
    store.update((x) => { x.locations = (x.locations ?? []).filter((l) => l.id !== id); });
  };
  const suppliers = locs.filter((l) => l.type === "supplier").length;

  return (
    <div>
      <StageHeader title="Places and routes" kicker={<>Add the places goods move between, then connect them: click one place on the map and then
        another, or pick them below. A route says how long goods take to get from one place to the other.</>}
        right={<a className="btn" href={href("setup")}>Back to setup</a>} />
      <div className="content stack">
        <div className="grid-2 setup-net">
          <Panel title="Places">
            <div className="qrow">
              <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Pune plant"
                onKeyDown={(e) => e.key === "Enter" && addPlace()} /></Field>
              <Field label="What it is"><select className="select" value={type} onChange={(e) => setType(e.target.value)}>
                {PLACE_TYPES.map((t) => <option key={t.type} value={t.type}>{TYPE_LABEL[t.type]}: {t.what}</option>)}</select></Field>
              <Field label="City or region"><input className="input" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="optional" /></Field>
              <button className="btn primary" onClick={addPlace}>Add place</button>
            </div>
            {locs.length > 0 && <div className="table-wrap"><table className="t">
              <thead><tr><th>Place</th><th>What it is</th><th>Region</th><th /></tr></thead>
              <tbody>{locs.map((l) => <tr key={l.id}>
                <td><b>{l.name || l.id}</b> <span className="faint small mono">{l.id}</span></td>
                <td>{TYPE_LABEL[l.type]}</td><td>{l.region}</td>
                <td className="nowrap"><a className="btn sm ghost" href={href("data", "locations", l.id)}>More</a>
                  <button className="btn sm ghost danger" onClick={() => removePlace(l.id)} aria-label={`Remove ${l.name || l.id}`}>Remove</button></td>
              </tr>)}</tbody>
            </table></div>}
            {!suppliers && locs.length > 0 && <p className="muted small">Buy anything? Add your suppliers as places too.</p>}
          </Panel>
          <Panel title="Routes">
            <div className="qrow">
              <Field label="From"><select className="select" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="Route from">
                <option value="">Choose…</option>{locs.filter((l) => l.type !== "customer").map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></Field>
              <Field label="To"><select className="select" value={to} onChange={(e) => setTo(e.target.value)} aria-label="Route to">
                <option value="">Choose…</option>{locs.filter((l) => l.type !== "supplier" && l.id !== from).map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></Field>
              <Field label="By"><select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>
                {MODES.map((m) => <option key={m.mode} value={m.mode}>{m.label}</option>)}</select></Field>
              <Field label="Days in transit"><input className="input" type="number" min={0} step="0.5" value={days} onChange={(e) => setDays(e.target.value)} style={{ width: 90 }} /></Field>
              <button className="btn primary" onClick={addLane}>Add route</button>
            </div>
            {msg && <div className="banner warning" role="alert">{msg}</div>}
            {(ds.lanes ?? []).length > 0 ? <div className="table-wrap"><table className="t">
              <thead><tr><th>From</th><th>To</th><th>By</th><th className="num">Days</th><th>Carries</th><th /></tr></thead>
              <tbody>{(ds.lanes ?? []).map((l, i) => <tr key={`${l.id}-${i}`}>
                <td>{nm.loc(l.origin) || <span className="faint">not set</span>}</td><td>{nm.loc(l.destination) || <span className="faint">not set</span>}</td>
                <td>{l.modes.length ? l.modes.map((m) => modeLabel(m.mode)).join(", ") : <Badge sev="warning">no mode</Badge>}</td>
                <td className="num">{l.modes.length ? <input className="input num" type="number" min={0} step="0.5" defaultValue={l.modes[0].transit_days}
                  aria-label={`Days from ${nm.loc(l.origin)} to ${nm.loc(l.destination)}`} style={{ width: 70 }}
                  onBlur={(e) => setLaneDays(i, e.target.value)} /> : "—"}</td>
                <td className="small">{l.products?.length ? l.products.map(nm.prod).join(", ") : "all products"}</td>
                <td className="nowrap"><a className="btn sm ghost" href={href("data", "lanes", l.id)}>More</a>
                  <button className="btn sm ghost danger" onClick={() => removeLane(i)} aria-label={`Remove route ${l.id}`}>Remove</button></td>
              </tr>)}</tbody>
            </table></div> : <p className="muted small">No routes yet. Goods can only be shipped between places connected by a route. Purchases from a
              supplier are set up per product (who sells it, at what price and lead time); add a route from a supplier only to add its
              transit time and freight.</p>}
          </Panel>
        </div>
        {net && net.locations.length > 0 && <Panel title="Map" actions={<span className="faint small">{!from ? "Click a place to start a route" : !to ? `From ${nm.loc(from)}: now click where it goes` : `${nm.loc(from)} → ${nm.loc(to)}: set the days and add the route`}</span>}>
          <MiniMap net={net} from={from} to={to} onPick={pick} />
        </Panel>}
      </div>
    </div>
  );
}

const TYPE_COLOR: Record<string, string> = {
  supplier: "var(--series-2)", plant: "var(--series-1)", dc: "var(--series-3)", warehouse: "var(--series-3)",
  store: "var(--series-7)", customer: "var(--series-4)",
};

/** Places in columns by where they sit in the flow (suppliers → plants → warehouses → customers); click to connect. */
function MiniMap({ net, from, to, onPick }: { net: NetworkView; from: string; to: string; onPick: (id: string) => void }) {
  const W = 168, H = 40, GX = 230, GY = 56;
  const order = ["supplier", "plant", "warehouse", "dc", "store", "customer"];
  const col = (t: string) => ({ supplier: 0, plant: 1, warehouse: 2, dc: 2, store: 3, customer: 3 } as Record<string, number>)[t] ?? 2;
  const cols: string[][] = [[], [], [], []];
  [...net.locations].sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || a.id.localeCompare(b.id))
    .forEach((l) => cols[col(l.type)].push(l.id));
  const used = cols.map((c, i) => [c, i] as const).filter(([c]) => c.length);
  const rows = Math.max(1, ...used.map(([c]) => c.length));
  const pos = new Map<string, { x: number; y: number }>();
  used.forEach(([c], ci) => c.forEach((id, ri) => pos.set(id, { x: 10 + ci * GX, y: 16 + (rows - c.length) * GY / 2 + ri * GY })));
  const width = 20 + (used.length - 1) * GX + W, height = 24 + rows * GY;
  const byId = new Map(net.locations.map((l) => [l.id, l]));
  return (
    <div className="net" style={{ overflowX: "auto" }}>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width, maxWidth: "100%" }} role="img" aria-label="Places and routes">
        {net.edges.map((e) => {
          const a = pos.get(e.origin), b = pos.get(e.destination);
          if (!a || !b) return null;
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
          const d = x2 > x1 ? `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`
            : `M${a.x + W / 2},${a.y + H} C${a.x + W / 2},${a.y + H + 30} ${b.x + W / 2},${b.y + H + 30} ${b.x + W / 2},${b.y + H}`;
          return <path key={`${e.kind}-${e.origin}-${e.destination}`} className={`edge ${e.kind}`} d={d} />;
        })}
        {from && to && pos.get(from) && pos.get(to) && (() => {
          const a = pos.get(from)!, b = pos.get(to)!;
          return <path className="edge pending" d={`M${a.x + W / 2},${a.y + H / 2} L${b.x + W / 2},${b.y + H / 2}`} />;
        })()}
        {[...pos].map(([id, p]) => {
          const l = byId.get(id)!;
          const sel = id === from || id === to;
          return (
            <g key={id} className={`node ${sel ? "sel" : ""}`} transform={`translate(${p.x},${p.y})`} style={{ cursor: "pointer" }}
              onClick={() => onPick(id)} role="button" aria-label={`${l.name} (${TYPE_LABEL[l.type]})`}>
              <rect width={W} height={H} />
              <circle cx={18} cy={H / 2} r={9} fill={TYPE_COLOR[l.type]} />
              <text x={34} y={17}>{l.name.length > 19 ? l.name.slice(0, 18) + "…" : l.name}</text>
              <text className="sub" x={34} y={31}>{TYPE_LABEL[l.type]}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ---- products ------------------------------------------------------------------------------------------------------
function Products({ ds }: { ds: Dataset }) {
  const setup = useStore((s) => s.validation?.setup ?? NO_SETUP);
  const [name, setName] = useState("");
  const [type, setType] = useState("FG");
  const [uom, setUom] = useState("EA");
  const [price, setPrice] = useState("");
  const [group, setGroup] = useState("");
  const [life, setLife] = useState("");
  const prods = ds.products ?? [];
  const groups = [...new Set(prods.map((p) => p.family).filter(Boolean))];
  const cur = ds.settings.currency;
  const addProduct = () => {
    if (!name.trim()) return;
    const id = newId(name, prods.map((p) => p.id), type);
    const pr = num(price);
    const days = Math.round(num(life));
    store.update((d) => add(d, "products", { id, name: name.trim(), type, base_uom: uom.trim() || "EA", ...(pr > 0 ? { price: pr } : {}),
      ...(group.trim() ? { family: group.trim() } : {}), ...(days > 0 ? { shelf_life_days: days } : {}) }));
    setName(""); setPrice(""); setLife("");
  };
  const setProd = (id: string, f: (p: Record<string, unknown>) => void) => store.update((d) => {
    const p = (d.products ?? []).find((x) => x.id === id);
    if (p) f(p as unknown as Record<string, unknown>);
  });
  /** What a bought product costs: its cheapest supplier price, else the cost typed here. */
  const bought = (id: string) => {
    const ps = (ds.purchasing_sources ?? []).filter((x) => x.product === id);
    return ps.length ? Math.min(...ps.map((x) => x.price * (x.currency && x.currency !== cur ? ((ds.settings.fx_rates ?? {})[x.currency] ?? NaN) : 1))) : null;
  };
  const status = (id: string) => {
    const nm = prods.find((p) => p.id === id)?.name || id;
    const items = setup.filter((i) => i.status !== "done" && i.status !== "info" && i.text.startsWith(nm + " "));
    return items.length ? <Badge sev="warning">{items.length} to do</Badge> : null;
  };
  return (
    <div>
      <StageHeader title="Products" kicker={<>Everything you plan: what you sell, and the parts, materials and packaging it's made from.
        Then set up, for each product, how it is made, bought or shipped.</>} right={<a className="btn" href={href("setup")}>Back to setup</a>} />
      <div className="content stack">
        <Panel title="Add a product">
          <div className="qrow">
            <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Oil filter"
              onKeyDown={(e) => e.key === "Enter" && addProduct()} /></Field>
            <Field label="What it is"><select className="select" value={type} onChange={(e) => setType(e.target.value)}>
              {PRODUCT_TYPES.map((t) => <option key={t.type} value={t.type}>{t.label}: {t.what}</option>)}</select></Field>
            <Field label="Counted in" hint={WHOLE.has(uom.trim().toUpperCase()) ? "planned in whole units" : "planned in fractions"}>
              <input className="input" value={uom} onChange={(e) => setUom(e.target.value)} style={{ width: 80 }} aria-label="Unit" list="units" />
              <datalist id="units">{["EA", "BOX", "CASE", "BAG", "DRUM", "KG", "L", "M", "TON"].map((u) => <option key={u} value={u} />)}</datalist></Field>
            {(type === "FG" || type === "SFG") && <Field label={`Selling price (${cur})`} hint="optional; revenue and margin need it">
              <input className="input" type="number" min={0} step="any" value={price} onChange={(e) => setPrice(e.target.value)} style={{ width: 100 }} aria-label="Selling price" /></Field>}
            <Field label="Product group" hint="optional; rights and reports by group">
              <input className="input" value={group} onChange={(e) => setGroup(e.target.value)} list="product-groups" style={{ width: 140 }} aria-label="Product group" />
              <datalist id="product-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist></Field>
            <Field label="Keeps for (days)" hint="empty: does not spoil">
              <input className="input" type="number" min={1} step={1} value={life} onChange={(e) => setLife(e.target.value)} style={{ width: 80 }} aria-label="Shelf life in days" /></Field>
            <button className="btn primary" onClick={addProduct}>Add product</button>
          </div>
          <p className="faint small">Have a list already? <a href={href("data", "products")}>Upload products from a spreadsheet</a>.</p>
        </Panel>
        {prods.length > 0 && <Panel flush>
          <div className="table-wrap"><table className="t">
            <thead><tr><th>Product</th><th>What it is</th><th>Unit</th><th title="Planned in whole units">Whole</th>
              <th>Group</th><th className="num" title="Shelf life: how many days it keeps">Keeps (days)</th>
              <th className="num">Selling price ({cur})</th><th className="num" title="Its standard cost; a bought product costs its supplier's price">Cost ({cur})</th>
              <th>How it's supplied</th><th /></tr></thead>
            <tbody>{prods.map((p) => {
              const made = (ds.production_sources ?? []).filter((x) => x.product === p.id).length;
              const buys = bought(p.id);
              const bought_ = (ds.purchasing_sources ?? []).filter((x) => x.product === p.id).length;
              const whole = p.whole_units ?? WHOLE.has((p.base_uom ?? "EA").trim().toUpperCase());
              const sells = p.type === "FG" || p.type === "SFG";
              return <tr key={p.id}>
                <td><b>{p.name || p.id}</b> <span className="faint small mono">{p.id}</span></td>
                <td>{PRODUCT_TYPES.find((t) => t.type === p.type)?.label}</td><td>{p.base_uom ?? "EA"}</td>
                <td><input type="checkbox" checked={whole} aria-label={`${p.name || p.id} in whole units`}
                  onChange={(e) => setProd(p.id, (x) => { x.whole_units = e.target.checked; })} /></td>
                <td><input className="input" defaultValue={p.family ?? ""} list="product-groups" placeholder="none" style={{ width: 120 }}
                  aria-label={`Product group of ${p.name || p.id}`} onBlur={(e) => { const g = e.target.value.trim(); if (g !== (p.family ?? "")) setProd(p.id, (x) => { x.family = g; }); }} /></td>
                <td className="num"><input className="input num" type="number" min={1} step={1} defaultValue={p.shelf_life_days ?? ""} placeholder="—" style={{ width: 70 }}
                  aria-label={`Shelf life of ${p.name || p.id} in days`} onBlur={(e) => { const n = Math.round(num(e.target.value)); setProd(p.id, (x) => { x.shelf_life_days = n > 0 ? n : null; }); }} /></td>
                <td className="num">{sells ? <input className="input num" type="number" min={0} step="any" defaultValue={p.price ?? ""} placeholder="none" style={{ width: 90 }}
                  aria-label={`Selling price of ${p.name || p.id}`} onBlur={(e) => { const n = num(e.target.value); setProd(p.id, (x) => { x.price = n > 0 ? n : null; }); }} />
                  : <span className="faint">–</span>}</td>
                <td className="num">{buys !== null && p.standard_cost == null ? <span className="small" title="From its supplier's price">{isNaN(buys) ? "no rate" : buys.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
                  : <input className="input num" type="number" min={0} step="any" defaultValue={p.standard_cost ?? ""} placeholder={made ? "auto" : "none"} title={made ? "Empty: worked out from its parts and machine time" : undefined} style={{ width: 90 }}
                  aria-label={`Cost of ${p.name || p.id}`} onBlur={(e) => { const n = num(e.target.value); setProd(p.id, (x) => { x.standard_cost = n > 0 ? n : null; }); }} />}</td>
                <td className="small">{[made && `made in ${made} place${made > 1 ? "s" : ""}`, bought_ && `bought from ${bought_} supplier${bought_ > 1 ? "s" : ""}`].filter(Boolean).join(", ") || <span className="faint">not yet</span>} {status(p.id)}</td>
                <td className="nowrap"><a className="btn sm" href={href("setup", "product", p.id)}>Set up</a></td>
              </tr>;
            })}</tbody>
          </table></div>
          <p className="faint small" style={{ padding: "8px 12px", margin: 0 }}>A customer who pays a different price?{" "}
            <a href={href("data", "customer_prices")}>Prices per customer</a> ({(ds.customer_prices ?? []).length} set). An order can also carry its own price.</p>
        </Panel>}
      </div>
    </div>
  );
}

// ---- one product ---------------------------------------------------------------------------------------------------
/** Places that need this product: where it has demand, where it's a part of something made there, where it's made or
 *  stocked, and places the network already plans it at. */
function placesNeeding(ds: Dataset, net: NetworkView | null, product: string, extra?: string): string[] {
  const out = new Set<string>();
  const stocking = new Set((ds.locations ?? []).filter((l) => STOCKING.includes(l.type)).map((l) => l.id));
  for (const d of ds.demand ?? []) if (d.product === product) out.add(d.location);
  for (const ps of ds.production_sources ?? []) {
    if (ps.product === product) out.add(ps.location);
    if ((ps.components ?? []).some((c) => c.product === product)) out.add(ps.location);
  }
  for (const lp of ds.location_products ?? []) if (lp.product === product) out.add(lp.location);
  for (const pu of ds.purchasing_sources ?? []) if (pu.product === product) out.add(pu.location);
  for (const n of net?.nodes ?? []) if (n.product === product) out.add(n.location);
  if (extra) out.add(extra);
  // a place that ships it to a place that needs it needs it too
  for (let grew = true; grew;) {
    grew = false;
    for (const l of ds.lanes ?? []) {
      if (out.has(l.destination) && !out.has(l.origin) && stocking.has(l.origin) && (!l.products?.length || l.products.includes(product))) {
        out.add(l.origin);
        grew = true;
      }
    }
  }
  return [...out].filter((l) => stocking.has(l) || (ds.locations ?? []).find((x) => x.id === l)?.type === "customer");
}

function ProductWizard({ ds, product, place }: { ds: Dataset; product?: string; place?: string }) {
  const net = useStore((s) => s.network);
  const prods = ds.products ?? [];
  const p = prods.find((x) => x.id === product);
  const needed = useMemo(() => (p ? placesNeeding(ds, net, p.id, place) : []), [ds, net, p, place]);
  const [extra, setExtra] = useState("");

  if (!p) {
    return (
      <div>
        <StageHeader title="How each product is supplied" kicker="Pick a product." right={<a className="btn" href={href("setup")}>Back to setup</a>} />
        <div className="content"><Panel>
          {prods.length ? <div className="chips">{prods.map((x) => <a key={x.id} className="btn sm" href={href("setup", "product", x.id)}>{x.name || x.id}</a>)}</div>
            : <p>No products yet. <a href={href("setup", "products")}>Add products</a> first.</p>}
        </Panel></div>
      </div>
    );
  }
  const places = needed;
  const open = place && places.includes(place) ? place : places[0];
  const others = (ds.locations ?? []).filter((l) => STOCKING.includes(l.type) && !places.includes(l.id));
  return (
    <div>
      <StageHeader title={p.name || p.id} kicker={<>{PRODUCT_TYPES.find((t) => t.type === p.type)?.label}. For each place that needs it, say how it gets
        there: made there, bought from a supplier, or shipped from another place.</>}
        right={<><select className="select" value={p.id} onChange={(e) => go("setup", "product", e.target.value)} aria-label="Product">
          {prods.map((x) => <option key={x.id} value={x.id}>{x.name || x.id}</option>)}</select>
          <a className="btn" href={href("setup")}>Back to setup</a></>} />
      <div className="content stack">
        {!places.length && <div className="banner warning">{p.name || p.id} isn't needed anywhere yet: it has no demand and isn't a part of anything.
          {p.type === "FG" ? <> <a href={href("demand")}>Add demand for it</a>, or plan it at a place below.</> : <> Use it as a part when you set up how something is made, or plan it at a place below.</>}</div>}
        {places.map((loc) => <PlaceCard key={loc} ds={ds} net={net} product={p.id} place={loc} open={loc === open} />)}
        {others.length > 0 && <div className="row wrap">
          <span className="muted small">Also plan it at</span>
          <select className="select" value={extra} onChange={(e) => setExtra(e.target.value)} aria-label="Also plan it at" style={{ width: "auto" }}>
            <option value="">choose a place…</option>{others.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select>
          <button className="btn sm" disabled={!extra} onClick={() => { go("setup", "product", p.id, extra); setExtra(""); }}>Add</button>
        </div>}
        <p className="faint small">Every choice here is an ordinary record in Master data (production sources, purchasing sources, lanes and planning
          policies), where you can add alternatives, quotas, validity dates and more.</p>
      </div>
    </div>
  );
}

type Mode = null | "make" | "buy" | "ship";

function PlaceCard({ ds, net, product, place, open }: { ds: Dataset; net: NetworkView | null; product: string; place: string; open: boolean }) {
  const nm = names(ds);
  const [mode, setMode] = useState<Mode>(null);
  const [expanded, setExpanded] = useState(open);
  const loc = (ds.locations ?? []).find((l) => l.id === place);
  const make = (ds.production_sources ?? []).map((x, i) => [x, i] as const).filter(([x]) => x.product === product && x.location === place);
  const buy = (ds.purchasing_sources ?? []).map((x, i) => [x, i] as const).filter(([x]) => x.product === product && x.location === place);
  const ship = (ds.lanes ?? []).map((x, i) => [x, i] as const).filter(([x]) => x.destination === place
    && !["supplier", "customer"].includes((ds.locations ?? []).find((l) => l.id === x.origin)?.type ?? "")
    && (!x.products?.length || x.products.includes(product)));
  const supplied = make.length + buy.length + ship.length > 0;
  const lp = (ds.location_products ?? []).find((x) => x.location === place && x.product === product);
  const demandQty = (ds.demand ?? []).filter((d) => d.location === place && d.product === product).reduce((a, d) => a + d.qty, 0);
  const partOf = (ds.production_sources ?? []).filter((ps) => ps.location === place && (ps.components ?? []).some((c) => c.product === product));
  const isCustomer = loc?.type === "customer";
  const title = `${nm.prod(product)} at ${nm.loc(place)}`;
  const why = [demandQty > 0 && `${demandQty.toLocaleString()} in demand`, partOf.length && `a part of ${partOf.map((x) => nm.prod(x.product)).join(", ")}`]
    .filter(Boolean).join(" · ");

  return (
    <Panel className={`wz-card ${supplied ? "" : "attn"}`} title={<button className="linkish wz-head" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
      <b>{title}</b> {supplied ? <Badge sev="ok">supplied</Badge> : isCustomer ? <Badge sev="warning">needs a route in</Badge> : <Badge sev="error">not supplied yet</Badge>}
      {why && <span className="faint small">{why}</span>}</button>}>
      {expanded && <div className="stack">
        {supplied ? <ul className="wz-opts">
          {make.map(([x]) => <li key={x.id}><b>Made here</b> from {(x.components ?? []).length ? (x.components ?? []).map((c) => `${c.qty} × ${nm.prod(c.product)}`).join(", ") : "nothing (no parts listed)"}
            {(x.operations ?? []).length ? `, on ${(x.operations ?? []).map((o) => (ds.resources ?? []).find((r) => r.id === o.resource)?.name || o.resource).join(" then ")}` : ", with no routing"}
            <button className="btn sm ghost" onClick={() => setMode("make")}>Change</button></li>)}
          {buy.map(([x, i]) => <li key={x.id}><b>Bought</b> from {nm.loc(x.supplier)} at {x.price} {x.currency || ds.settings.currency}, {x.lead_time_days} days' lead time
            <a className="btn sm ghost" href={href("data", "purchasing_sources", x.id)}>More</a>
            <button className="btn sm ghost danger" onClick={() => store.update((d) => { d.purchasing_sources!.splice(i, 1); })}>Remove</button></li>)}
          {ship.map(([x]) => <li key={x.id}><b>Shipped</b> from {nm.loc(x.origin)}, {x.modes[0]?.transit_days ?? "?"} day{x.modes[0]?.transit_days === 1 ? "" : "s"} by {modeLabel(x.modes[0]?.mode ?? "")}
            {!x.products?.length && <span className="faint small"> (the route carries all products)</span>}
            <a className="btn sm ghost" href={href("setup", "product", product, x.origin)}>How it gets to {nm.loc(x.origin)}</a></li>)}
        </ul> : <p className="muted">{isCustomer ? `Customers are delivered to by a route from a warehouse or plant.` : `Nothing brings ${nm.prod(product)} to ${nm.loc(place)} yet.`} How does it get here?</p>}
        <div className="row wrap">
          {loc?.type === "plant" && !make.length && <button className={`btn ${mode === "make" ? "primary" : ""}`} onClick={() => setMode("make")}>Make it here</button>}
          {!isCustomer && <button className={`btn ${mode === "buy" ? "primary" : ""}`} onClick={() => setMode("buy")}>{buy.length ? "Add another supplier" : "Buy it"}</button>}
          <button className={`btn ${mode === "ship" ? "primary" : ""}`} onClick={() => setMode("ship")}>{isCustomer ? "Deliver it from…" : "Ship it from another place"}</button>
        </div>
        {mode === "make" && <MakeForm ds={ds} product={product} place={place} existing={make[0]?.[0]} index={make[0]?.[1]} done={() => setMode(null)} />}
        {mode === "buy" && <BuyForm ds={ds} product={product} place={place} done={() => setMode(null)} />}
        {mode === "ship" && <ShipForm ds={ds} product={product} place={place} done={() => setMode(null)} />}
        {make.length > 0 && <Parts ds={ds} net={net} ps={make[0][0]} />}
        {!isCustomer && <StockForm ds={ds} product={product} place={place} lp={lp} />}
      </div>}
    </Panel>
  );
}

/** The parts of what is made here, each with whether it can be had at this plant. */
function Parts({ ds, net, ps }: { ds: Dataset; net: NetworkView | null; ps: ProductionSource }) {
  const nm = names(ds);
  if (!(ps.components ?? []).length) return null;
  const has = (prod: string) => (ds.production_sources ?? []).some((x) => x.product === prod && x.location === ps.location)
    || (ds.purchasing_sources ?? []).some((x) => x.product === prod && x.location === ps.location)
    || (net?.nodes ?? []).some((n) => n.location === ps.location && n.product === prod && n.options.length > 0);
  return (
    <div className="wz-parts">
      <div className="small muted">Parts needed at {nm.loc(ps.location)}</div>
      <ul className="wz-opts">{(ps.components ?? []).map((c) => <li key={c.product}>{nm.prod(c.product)}
        {has(c.product) ? <Badge sev="ok">supplied</Badge> : <><Badge sev="error">not supplied yet</Badge>
          <a className="btn sm primary" href={href("setup", "product", c.product, ps.location)}>Set it up</a></>}</li>)}</ul>
    </div>
  );
}

// each row keeps the record it came from, so fields this form does not show (queue time, labour, validity dates,
// alternatives…) survive an edit here
interface CompRow { product: string; newName: string; qty: string; scrap: string; orig?: Record<string, unknown> }
interface StepRow { resource: string; newName: string; setup: string; runMin: string; outDays: string; batch: boolean; batchQty: string; batchHours: string; orig?: Record<string, unknown> }

function MakeForm({ ds, product, place, existing, index, done }: { ds: Dataset; product: string; place: string; existing?: ProductionSource; index?: number; done: () => void }) {
  const nm = names(ds);
  const [comps, setComps] = useState<CompRow[]>(() => (existing?.components ?? []).map((c) => ({ product: c.product, newName: "", qty: String(c.qty), scrap: String(Math.round((c.scrap ?? 0) * 1000) / 10), orig: c as unknown as Record<string, unknown> })));
  const [steps, setSteps] = useState<StepRow[]>(() => (existing?.operations ?? []).map((o) => ({
    resource: o.subcontract ? `out:${o.subcontract.supplier}` : o.resource ?? "", newName: "", setup: String(o.setup_hours ?? 0),
    runMin: String(Math.round((o.run_hours_per_unit ?? 0) * 60 * 1000) / 1000), outDays: String(o.subcontract?.workdays ?? 1),
    batch: !!o.batch_qty, batchQty: String(o.batch_qty ?? ""), batchHours: String(o.batch_hours ?? ""),
    orig: o as unknown as Record<string, unknown> })));
  const suppliers = (ds.locations ?? []).filter((l) => l.type === "supplier");
  const [lead, setLead] = useState(existing?.fixed_lead_time_workdays != null ? String(existing.fixed_lead_time_workdays) : "");
  const [err, setErr] = useState<string | null>(null);
  const partChoices = (ds.products ?? []).filter((x) => x.id !== product);
  const lines = (ds.resources ?? []).filter((r) => r.location === place);

  const save = () => {
    for (const c of comps) {
      if (c.product === "" || (c.product === "+new" && !c.newName.trim())) return setErr("Choose each part, or name the new one.");
      if (!(num(c.qty) > 0)) return setErr("Each part needs a quantity above 0 per unit made.");
      if (!(num(c.scrap || "0") >= 0 && num(c.scrap || "0") < 100)) return setErr("Scrap must be between 0 and 100%.");
    }
    for (const s of steps) {
      if (s.resource === "" || (s.resource === "+new" && !s.newName.trim())) return setErr("Choose the machine or line for each step, or name a new one.");
      if (!(num(s.runMin || "0") >= 0) || !(num(s.setup || "0") >= 0)) return setErr("Times must be 0 or more.");
      if (s.resource.startsWith("out:") && !(num(s.outDays || "0") >= 0)) return setErr("Days outside must be 0 or more.");
      if (s.batch && !s.resource.startsWith("out:") && (!(num(s.batchQty) > 0) || !(num(s.batchHours) >= 0))) return setErr("A batch step needs its batch size (above 0) and the hours one batch takes.");
    }
    if (lead !== "" && !(num(lead) >= 0)) return setErr("The lead time must be 0 or more working days.");
    store.update((d) => {
      const prodIds = (d.products ?? []).map((x) => x.id);
      const resIds = (d.resources ?? []).map((x) => x.id);
      const components = comps.map((c) => {
        let id = c.product;
        if (id === "+new") {
          id = newId(c.newName, prodIds, "PART");
          prodIds.push(id);
          add(d, "products", { id, name: c.newName.trim(), type: "RM" });
        }
        return { ...(c.orig ?? {}), product: id, qty: num(c.qty), scrap: num(c.scrap || "0") / 100 };
      });
      const operations = steps.map((s, i) => {
        const base = { ...(s.orig ?? {}), seq: (i + 1) * 10 } as Record<string, unknown>;
        if (s.resource.startsWith("out:")) {
          const old = (s.orig?.subcontract ?? {}) as Record<string, unknown>;
          return { ...base, resource: null, alternatives: [], setup_hours: 0, run_hours_per_unit: 0,
            subcontract: { ...old, supplier: s.resource.slice(4), workdays: num(s.outDays || "0") } };
        }
        let id = s.resource;
        if (id === "+new") {
          id = newId(s.newName, resIds, "LINE");
          resIds.push(id);
          add(d, "resources", { id, name: s.newName.trim(), location: place });
        }
        return { ...base, resource: id, subcontract: null, setup_hours: num(s.setup || "0"),
          ...(s.batch ? { run_hours_per_unit: 0, batch_qty: num(s.batchQty), batch_hours: num(s.batchHours) }
            : { run_hours_per_unit: num(s.runMin || "0") / 60, batch_qty: null, batch_hours: 0 }) };
      });
      const next: ProductionSource = {
        ...(existing ?? { id: newId(`${product}-${place}`, (d.production_sources ?? []).map((x) => x.id), "MAKE"), location: place, product }),
        components, operations, fixed_lead_time_workdays: lead === "" ? null : num(lead),
      } as unknown as ProductionSource;
      if (index !== undefined) d.production_sources![index] = next;
      else add(d, "production_sources", next as unknown as Record<string, unknown>);
    });
    done();
  };

  return (
    <div className="wz-form">
      <h4>What one {nm.prod(product)} is made from</h4>
      {comps.map((c, i) => <div key={i} className="qrow">
        <Field label="Part"><select className="select" value={c.product} onChange={(e) => setComps(comps.map((x, j) => j === i ? { ...x, product: e.target.value } : x))}>
          <option value="">Choose…</option>{partChoices.map((x) => <option key={x.id} value={x.id}>{x.name || x.id}</option>)}
          <option value="+new">+ a new part…</option></select></Field>
        {c.product === "+new" && <Field label="New part's name"><input className="input" value={c.newName} onChange={(e) => setComps(comps.map((x, j) => j === i ? { ...x, newName: e.target.value } : x))} /></Field>}
        <Field label="Quantity per unit"><input className="input" type="number" min={0} step="any" value={c.qty} style={{ width: 90 }} onChange={(e) => setComps(comps.map((x, j) => j === i ? { ...x, qty: e.target.value } : x))} /></Field>
        <Field label="Scrap %"><input className="input" type="number" min={0} max={99} step="any" value={c.scrap} style={{ width: 70 }} onChange={(e) => setComps(comps.map((x, j) => j === i ? { ...x, scrap: e.target.value } : x))} /></Field>
        <button className="btn sm ghost danger" onClick={() => setComps(comps.filter((_, j) => j !== i))} aria-label="Remove part">Remove</button>
      </div>)}
      <button className="btn sm" onClick={() => setComps([...comps, { product: "", newName: "", qty: "1", scrap: "0" }])}>+ Add a part</button>

      <h4>The steps, in order</h4>
      {steps.map((s, i) => <div key={i} className="qrow">
        <span className="wz-n">{i + 1}</span>
        <Field label="On machine or line"><select className="select" value={s.resource} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, resource: e.target.value } : x))}>
          <option value="">Choose…</option>{lines.map((r) => <option key={r.id} value={r.id}>{r.name || r.id}</option>)}
          <option value="+new">+ a new machine or line…</option>
          {suppliers.length > 0 && <optgroup label="Done outside by a supplier">{suppliers.map((l) => <option key={l.id} value={`out:${l.id}`}>{l.name || l.id}</option>)}</optgroup>}</select></Field>
        {s.resource === "+new" && <Field label="Its name"><input className="input" value={s.newName} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, newName: e.target.value } : x))} placeholder="e.g. Line 1" /></Field>}
        {s.resource.startsWith("out:") ? <Field label="Working days there and back"><input className="input" type="number" min={0} step="any" value={s.outDays} style={{ width: 90 }} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, outDays: e.target.value } : x))} /></Field> : <>
        <Field label="Runs" hint={s.batch ? "a batch takes its time however full it is; orders are made in whole batches" : undefined}>
          <select className="select" value={s.batch ? "batch" : "unit"} aria-label="How the step runs" onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, batch: e.target.value === "batch" } : x))}>
          <option value="unit">unit by unit</option><option value="batch">in batches (a mixer, a kiln, a reactor)</option></select></Field>
        {s.batch ? <>
          <Field label={`Batch size (${(ds.products ?? []).find((x) => x.id === product)?.base_uom ?? "units"})`}><input className="input" type="number" min={0} step="any" value={s.batchQty} style={{ width: 90 }} aria-label="Batch size" onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, batchQty: e.target.value } : x))} /></Field>
          <Field label="Hours per batch"><input className="input" type="number" min={0} step="any" value={s.batchHours} style={{ width: 80 }} aria-label="Hours per batch" onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, batchHours: e.target.value } : x))} /></Field>
        </> : <Field label="Minutes per unit"><input className="input" type="number" min={0} step="any" value={s.runMin} style={{ width: 90 }} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, runMin: e.target.value } : x))} /></Field>}
        <Field label="Setup hours per run"><input className="input" type="number" min={0} step="any" value={s.setup} style={{ width: 90 }} onChange={(e) => setSteps(steps.map((x, j) => j === i ? { ...x, setup: e.target.value } : x))} /></Field></>}
        <button className="btn sm ghost danger" onClick={() => setSteps(steps.filter((_, j) => j !== i))} aria-label="Remove step">Remove</button>
      </div>)}
      <button className="btn sm" onClick={() => setSteps([...steps, { resource: lines.length === 1 ? lines[0].id : lines.length ? "" : "+new", newName: "", setup: "0", runMin: "1", outDays: "2", batch: false, batchQty: "", batchHours: "" }])}>+ Add a step</button>
      {!steps.length && <p className="faint small">With no steps, no machine time is planned. Give a lead time instead, or add the steps to check capacity.</p>}
      <div className="qrow">
        <Field label="Fixed lead time" hint="working days; leave empty to take it from the steps"><input className="input" type="number" min={0} step="any" value={lead} style={{ width: 90 }} onChange={(e) => setLead(e.target.value)} /></Field>
      </div>
      {err && <div className="banner warning" role="alert">{err}</div>}
      <div className="row"><button className="btn primary" onClick={save}>Save</button><button className="btn ghost" onClick={done}>Cancel</button>
        {existing && <a className="btn ghost" href={href("data", "production_sources", existing.id)}>All settings</a>}</div>
    </div>
  );
}

function BuyForm({ ds, product, place, done }: { ds: Dataset; product: string; place: string; done: () => void }) {
  const sups = (ds.locations ?? []).filter((l) => l.type === "supplier");
  const [sup, setSup] = useState(sups.length === 1 ? sups[0].id : sups.length ? "" : "+new");
  const [newName, setNewName] = useState("");
  const [price, setPrice] = useState("");
  const own = ds.settings.currency;
  const vendorCur = (id: string) => (ds.vendors ?? []).find((v) => v.supplier === id)?.currency ?? "";
  const [cur, setCur] = useState(() => vendorCur(sup) || own);
  const [rate, setRate] = useState("");
  const known = [...new Set([own, ...Object.keys(ds.settings.fx_rates ?? {}), ...(ds.purchasing_sources ?? []).map((x) => x.currency ?? ""), "USD", "EUR"])].filter(Boolean);
  const needRate = cur !== own && !((ds.settings.fx_rates ?? {})[cur] > 0);
  const [lt, setLt] = useState("7");
  const [moq, setMoq] = useState("0");
  const [err, setErr] = useState<string | null>(null);
  const save = () => {
    if (!sup || (sup === "+new" && !newName.trim())) return setErr("Choose the supplier, or name a new one.");
    if (!(num(price) >= 0)) return setErr("Enter the price per unit.");
    if (!(num(lt) >= 0)) return setErr("Enter the lead time in days (0 or more).");
    if (!(num(moq || "0") >= 0)) return setErr("The minimum order must be 0 or more.");
    if (!/^[A-Z]{3}$/.test(cur)) return setErr("The currency is a three-letter code, e.g. USD.");
    if (needRate && !(num(rate) > 0)) return setErr(`Enter what one ${cur} costs in ${own}.`);
    store.update((d) => {
      if (needRate) d.settings.fx_rates = { ...(d.settings.fx_rates ?? {}), [cur]: num(rate) };
      let s = sup;
      if (s === "+new") {
        s = newId(newName, (d.locations ?? []).map((x) => x.id), "SUPPLIER");
        add(d, "locations", { id: s, name: newName.trim(), type: "supplier" });
      }
      const id = newId(`${product}-${s}`, (d.purchasing_sources ?? []).map((x) => x.id), "BUY");
      add(d, "purchasing_sources", { id, supplier: s, product, location: place, price: num(price), lead_time_days: num(lt), moq: num(moq || "0"),
        ...(cur !== own ? { currency: cur } : {}) });
    });
    done();
  };
  return (
    <div className="wz-form">
      <div className="qrow">
        <Field label="Supplier"><select className="select" value={sup} onChange={(e) => { setSup(e.target.value); setCur(vendorCur(e.target.value) || cur); }}>
          <option value="">Choose…</option>{sups.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}<option value="+new">+ a new supplier…</option></select></Field>
        {sup === "+new" && <Field label="Supplier's name"><input className="input" value={newName} onChange={(e) => setNewName(e.target.value)} /></Field>}
        <Field label={`Price per unit (${cur})`}><input className="input" type="number" min={0} step="any" value={price} style={{ width: 100 }} onChange={(e) => setPrice(e.target.value)} /></Field>
        <Field label="In" hint="the currency the supplier invoices in"><input className="input" list="buy-currencies" value={cur} maxLength={3} style={{ width: 70, textTransform: "uppercase" }}
          onChange={(e) => setCur(e.target.value.toUpperCase())} aria-label="Price currency" />
          <datalist id="buy-currencies">{known.map((c) => <option key={c} value={c} />)}</datalist></Field>
        {needRate && /^[A-Z]{3}$/.test(cur) && <Field label={`1 ${cur} =`} hint={`${own}; kept in the company's exchange rates`}>
          <input className="input" type="number" min={0} step="any" value={rate} style={{ width: 90 }} onChange={(e) => setRate(e.target.value)} aria-label={`${own} per ${cur}`} /></Field>}
        <Field label="Lead time" hint="days from order to dispatch"><input className="input" type="number" min={0} step="any" value={lt} style={{ width: 80 }} onChange={(e) => setLt(e.target.value)} /></Field>
        <Field label="Minimum order"><input className="input" type="number" min={0} step="any" value={moq} style={{ width: 90 }} onChange={(e) => setMoq(e.target.value)} /></Field>
      </div>
      {err && <div className="banner warning" role="alert">{err}</div>}
      <div className="row"><button className="btn primary" onClick={save}>Save</button><button className="btn ghost" onClick={done}>Cancel</button></div>
    </div>
  );
}

function ShipForm({ ds, product, place, done }: { ds: Dataset; product: string; place: string; done: () => void }) {
  const nm = names(ds);
  const origins = (ds.locations ?? []).filter((l) => STOCKING.includes(l.type) && l.id !== place);
  const [from, setFrom] = useState(origins.length === 1 ? origins[0].id : "");
  const [mode, setMode] = useState("truck_ftl");
  const [days, setDays] = useState("2");
  const [only, setOnly] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const lane = (ds.lanes ?? []).findIndex((l) => l.origin === from && l.destination === place);
  const existing = lane >= 0 ? ds.lanes![lane] : null;
  const save = () => {
    if (!from) return setErr("Choose where it ships from.");
    if (lane < 0 && !(num(days) >= 0)) return setErr("Transit days must be 0 or more.");
    store.update((d) => {
      if (lane >= 0) {
        const l = d.lanes![lane];
        if (l.products?.length && !l.products.includes(product)) l.products.push(product);
      } else {
        const id = newId(`${from}-${place}`, (d.lanes ?? []).map((x) => x.id), "LANE");
        add(d, "lanes", { id, origin: from, destination: place, modes: [{ mode, transit_days: num(days) }],
          ...(only ? { products: [product] } : {}) });
      }
    });
    done();
  };
  return (
    <div className="wz-form">
      <div className="qrow">
        <Field label="Ships from"><select className="select" value={from} onChange={(e) => setFrom(e.target.value)}>
          <option value="">Choose…</option>{origins.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}</option>)}</select></Field>
        {lane < 0 && <>
          <Field label="By"><select className="select" value={mode} onChange={(e) => setMode(e.target.value)}>{MODES.map((m) => <option key={m.mode} value={m.mode}>{m.label}</option>)}</select></Field>
          <Field label="Days in transit"><input className="input" type="number" min={0} step="0.5" value={days} style={{ width: 80 }} onChange={(e) => setDays(e.target.value)} /></Field>
        </>}
      </div>
      {from && existing && <p className="small muted">There is already a route from {nm.loc(from)}; {nm.prod(product)} will use it
        {existing.products?.length ? <> (it carries {existing.products.length} named product{existing.products.length === 1 ? "" : "s"}; {nm.prod(product)} is added to them)</> : null}.</p>}
      {from && lane < 0 && <>
        <div className="row wrap" role="radiogroup" aria-label="What the route carries">
          <label className="row small"><input type="radio" checked={!only} onChange={() => setOnly(false)} /> Every product can use this route</label>
          <label className="row small"><input type="radio" checked={only} onChange={() => setOnly(true)} /> Only {nm.prod(product)}</label>
        </div>
        <p className="small muted">This adds a route from {nm.loc(from)} to {nm.loc(place)}{only ? ` for ${nm.prod(product)} only; other products can be added to it later` : " for all products"}. Then set up how {nm.prod(product)} gets to {nm.loc(from)}.</p>
      </>}
      {err && <div className="banner warning" role="alert">{err}</div>}
      <div className="row"><button className="btn primary" onClick={save}>Save</button><button className="btn ghost" onClick={done}>Cancel</button></div>
    </div>
  );
}

/** Stock and simple rules at this place: on hand, safety stock, lot size. The full MRP settings are on the product-at-place page.
 *  Once the place has goods movements for the product, stock is the journal's: a new figure is posted as a count (N46). */
function StockForm({ ds, product, place, lp }: { ds: Dataset; product: string; place: string; lp?: LocationProduct }) {
  const nm = names(ds);
  const ss = lp?.safety_stock?.method ?? "none";
  const pol = lp?.lot_sizing?.policy ?? null;
  const lot = pol === null ? "" : pol === "POQ" ? `POQ${lp?.lot_sizing?.periods ?? 1}` : pol;
  const journal = (ds.movements ?? []).some((m) => m.location === place && m.product === product);
  const [count, setCount] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  type Loose = { on_hand?: number; safety_stock?: Record<string, unknown>; lot_sizing?: Record<string, unknown>; strategy?: string | null };
  const sells = ["FG", "SFG"].includes((ds.products ?? []).find((x) => x.id === product)?.type ?? "");
  const write = (patch: (x: Loose) => void) => store.update((d) => {
    const list = (d.location_products ??= []);
    let x = list.find((r) => r.location === place && r.product === product) as Loose | undefined;
    if (!x) { x = { location: place, product } as Loose; list.push(x as unknown as LocationProduct); }
    patch(x);
  });
  const setNum = (v: string, f: (x: Loose, n: number) => void) => { const n = num(v); if (n >= 0) write((x) => f(x, n)); };
  const setLot = (v: string) => write((x) => {
    const keep = { ...(x.lot_sizing ?? {}) };
    x.lot_sizing = v === "" ? { ...keep, policy: null } : v.startsWith("POQ") ? { ...keep, policy: "POQ", periods: Number(v.slice(3)) }
      : v === "FIXED" ? { ...keep, policy: "FIXED", fixed_qty: keep.fixed_qty ?? 100 } : { ...keep, policy: v };
  });
  const postCount = async () => {
    const n = num(count);
    if (!(n >= 0)) return setMsg("Enter the quantity counted (0 or more).");
    try {
      const out = await api.postActual(ds, "count", { counts: [{ location: place, product, qty: n }] });
      store.replace(out.dataset);
      setMsg(namesOf(out.dataset).text(out.report.message)); setCount("");
    } catch (e) { setMsg(e instanceof Error ? e.message : String(e)); }
  };
  return (
    <div className="wz-form wz-stock">
      <h4>Stock and ordering at {nm.loc(place)}</h4>
      <div className="qrow">
        {journal ? <Field label="Counted today" hint={<>stock follows the goods movements here ({(lp?.on_hand ?? 0).toLocaleString()} now); a count posts the difference</>}>
          <span className="row"><input className="input" type="number" min={0} step="any" value={count} style={{ width: 100 }} onChange={(e) => setCount(e.target.value)}
            aria-label={`Counted ${nm.prod(product)} at ${nm.loc(place)}`} />
          <button className="btn sm" disabled={count.trim() === ""} onClick={postCount}>Post the count</button></span></Field>
        : <Field label="On hand today"><input className="input" type="number" min={0} step="any" defaultValue={lp?.on_hand ?? 0} style={{ width: 100 }}
          onBlur={(e) => setNum(e.target.value, (x, n) => { x.on_hand = n; })} aria-label={`On hand of ${nm.prod(product)} at ${nm.loc(place)}`} /></Field>}
        <Field label="Safety stock"><select className="select" value={ss} onChange={(e) => write((x) => { x.safety_stock = { method: e.target.value, ...(e.target.value === "fixed" ? { qty: 0 } : e.target.value === "days_of_supply" ? { days: 7 } : {}) }; })}>
          <option value="none">None</option><option value="fixed">A fixed quantity</option><option value="days_of_supply">Days of cover</option>
          {!["none", "fixed", "days_of_supply"].includes(ss) && <option value={ss}>{ss.replace(/_/g, " ")}</option>}</select></Field>
        {ss === "fixed" && <Field label="Quantity"><input className="input" type="number" min={0} step="any" defaultValue={lp?.safety_stock?.qty ?? 0} style={{ width: 90 }}
          onBlur={(e) => setNum(e.target.value, (x, n) => { x.safety_stock = { ...(x.safety_stock ?? {}), method: "fixed", qty: n }; })} /></Field>}
        {ss === "days_of_supply" && <Field label="Days"><input className="input" type="number" min={0} step="any" defaultValue={lp?.safety_stock?.days ?? 7} style={{ width: 80 }}
          onBlur={(e) => setNum(e.target.value, (x, n) => { x.safety_stock = { ...(x.safety_stock ?? {}), method: "days_of_supply", days: n }; })} /></Field>}
        {sells && <Field label="Planned from" hint={lp?.strategy === "MTO" ? "made or bought only for orders taken; free stock is used first" : undefined}>
          <select className="select" value={lp?.strategy ?? ""} aria-label={`How ${nm.prod(product)} at ${nm.loc(place)} is planned`}
            onChange={(e) => write((x) => { x.strategy = e.target.value || null; })}>
            <option value="">the forecast and orders (the company's default)</option>
            <option value="MTS_CONSUME">the forecast, orders using it up</option>
            <option value="MTS">the forecast only (orders do not change it)</option>
            <option value="MTO">orders only: made to order</option>
            <option value="ATO">parts from the forecast, assembled to order</option>
          </select></Field>}
        <Field label="Each order covers"><select className="select" value={lot} onChange={(e) => setLot(e.target.value)} aria-label="Each order covers">
          <option value="">The company's default ({coverLabel(ds.settings as never)})</option>
          <option value="L4L">Exactly what's needed</option><option value="POQ1">A week's need</option>
          <option value="POQ2">Two weeks' need</option><option value="POQ4">Four weeks' need</option><option value="FIXED">Fixed batches</option>
          {!["", "L4L", "POQ1", "POQ2", "POQ4", "FIXED"].includes(lot) && <option value={lot}>{lot}</option>}</select></Field>
        {lot === "FIXED" && <Field label="Batch size"><input className="input" type="number" min={1} step="any" defaultValue={lp?.lot_sizing?.fixed_qty ?? 100} style={{ width: 90 }}
          onBlur={(e) => { const n = num(e.target.value); if (n > 0) write((x) => { x.lot_sizing = { ...(x.lot_sizing ?? {}), policy: "FIXED", fixed_qty: n }; }); }} /></Field>}
        <a className="btn sm ghost" href={href("material", product, place, "mrp1")}>All planning settings (MRP 1–4)</a>
      </div>
      {msg && <p className="small muted" role="status">{msg}</p>}
    </div>
  );
}
