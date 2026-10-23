// Enterprise 8.2: inventory policy in one table (docs/CONFORMANCE.md §1). Every product kept at a place, read the way
// a policy is set in the textbooks: its class by annual usage value and by variability, its rule (reorder point with a
// fixed quantity, reorder point up to a maximum, time-phased MRP, a DDMRP buffer), its review, the service target
// beside the one its class suggests, the safety stock and reorder point that target needs, and the service achieved.
// A policy is given to many products at once, a whole class or the ones chosen. Engine: scp/inventory/policy.
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, PolicyApplyInput, PolicyRow, PolicyView } from "../api/types";
import { Badge, Edits, MoreRows, Panel, ROW_LIMIT, StageHeader, StatTile } from "../components/ui";
import { day, money, pct, plural, qty } from "../lib/format";
import { namesOf, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { store, useStore } from "../state/store";

const SPREAD: Record<string, string> = { gamma: "gamma spread", poisson: "Poisson spread" };
const METHOD: Record<string, string> = { none: "none", fixed: "a fixed quantity", days_of_supply: "days of cover",
  service_level: "for a cycle service level", fill_rate: "for a fill rate" };
const key = (r: { location: string; product: string }) => `${r.location}|${r.product}`;

function usePolicy(ds: Dataset) {
  const [v, setV] = useState<PolicyView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.inventoryPolicy(ds).then((x) => { if (live) { setV(x); setErr(null); } },
      (e) => live && setErr(String(e).replace(/^Error:\s*/, "")));
    return () => { live = false; };
  }, [ds]);
  return { v, err };
}

export function InventoryPolicy({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const { v, err } = usePolicy(ds);
  const cell = route[1] ?? "";
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [done, setDone] = useState<string | null>(null);
  const [find, setFind] = useState("");
  const cur = ds.settings.currency;
  const shown = useMemo(() => (v?.rows ?? []).filter((r) => !cell || r.abc + (r.xyz ?? "–") === cell), [v, cell]);
  const listed = useMemo(() => {
    const q = find.trim().toLowerCase();
    if (!q) return shown;
    const nm = namesOf(ds);
    return shown.filter((r) => [r.product, r.location, nm.prod(r.product), nm.loc(r.location)].some((x) => x.toLowerCase().includes(q)));
  }, [shown, find, ds]);
  const page = listed.slice(0, ROW_LIMIT);
  const head = <StageHeader title="Inventory policy" kicker="How each product is kept in stock: its class, its rule, its service target and the stock that target needs."
    how={<>Each product kept at a place is classed by its <b>annual usage value</b> (a year's demand at its unit value:
      the products making the first {pct(ds.forecasting?.abc_a ?? 0.8, 0)} of the value are A, up to
      {" "}{pct(ds.forecasting?.abc_b ?? 0.95, 0)} B, the rest C) and by the <b>variability</b> its safety stock is
      sized with (the weekly coefficient of variation: below {ds.forecasting?.xyz_x ?? 0.5} X, below {ds.forecasting?.xyz_y ?? 1} Y,
      else Z). Each ABC-XYZ class suggests a cycle service level (Set up → Master data → forecasting settings changes
      the table). For a service target the safety stock is <b>SS = z · √((L + R)·σ²_d + d̄²·σ²_L)</b>, with L the lead
      time, R the review period, σ_d the spread of daily demand and σ_L of the lead time; for a fill rate, the k whose
      expected shortage per cycle is (1 − β) of the order. That reads demand over L + R as normal; where it varies
      widely (a CV over 0.5) a gamma spread with the same mean and σ fits better, and a slow mover sold a few at a
      time is Poisson. The reorder point that keeps it is <b>s = d̄ · (L + R) + SS</b>.
      A product on a reorder point with a review period is ordered on review days only (every R days, Mondays unless
      another day is given): each order covers what falls short until the next review's order can arrive.
      What is achieved is the share of the customer orders shipped from the place in the last {v?.window_days ?? 91} days
      that arrived in full by the date the customer asked for. The numbers are the supply plan's own: the same demand
      rate, lead time and safety stock.</>}
    answer={v?.ok ? <>{plural(v.rows.length, "product")} kept at places; {v.below_suggestion
      ? `${plural(v.below_suggestion, "target")} below what its class suggests` : "every target at or above its class's suggestion"}
      {v.short_of_target ? `, ${v.short_of_target} short of its target` : ""}.</> : undefined} />;
  if (err) return <div>{head}<div className="content"><div className="banner error" role="alert"><Badge sev="error">Not shown</Badge>{err}</div></div></div>;
  if (!v) return <div>{head}<div className="content"><p className="faint">Reading each product's policy…</p></div></div>;
  if (!v.ok) return <div>{head}<div className="content"><div className="banner error"><Badge sev="error">Not shown</Badge>
    The data has problems that stop planning. <a href={href("readiness")}>Open the data check</a>.</div></div></div>;
  const toggle = (k: string) => setSel((s) => { const n = new Set(s); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const allShown = page.length > 0 && page.every((r) => sel.has(key(r)));
  return (
    <div>{head}<div className="content stack">
      <div className="grid-auto">
        <StatTile label="Safety stock held" value={money(v.safety_stock_value, cur)} sub="at unit value, every product at its place" />
        <StatTile label="Below their class" value={v.below_suggestion} sub="cycle service targets under the class's suggestion" />
        <StatTile label="Reorder points off" value={v.reorder_off} sub="more than 10 % from d̄·(L + R) + SS" />
        <StatTile label="Short of their target" value={v.short_of_target} sub={`orders in full on time, last ${v.window_days} days`} />
      </div>
      {done && <div className="banner ok" role="status"><Badge sev="ok">Done</Badge>{done}</div>}
      <Panel title="By class" flush>
        <div className="table-wrap"><table className="t" aria-label="Classes">
          <thead><tr><th>Class</th><th className="num">Products</th><th className="num">Safety stock</th>
            <th className="num">Suggested target</th><th>Targets set</th><th className="num">Achieved</th></tr></thead>
          <tbody>{v.cells.map((c) => (
            <tr key={c.cell} className={`clickable${cell === c.cell ? " selected" : ""}`} onClick={() => go("policy", cell === c.cell ? "" : c.cell)}>
              <td><b>{c.cell}</b></td><td className="num">{c.rows}</td><td className="num">{money(c.safety_stock_value, cur)}</td>
              <td className="num">{c.suggested != null ? pct(c.suggested, 0) : "—"}</td>
              <td className="small">{c.targets.length ? c.targets.map((t) => pct(t, 0)).join(", ") : <span className="faint">none</span>}</td>
              <td className="num">{c.achieved != null ? <>{pct(c.achieved, 0)} <span className="faint small">of {c.orders}</span></> : <span className="faint">no orders</span>}</td>
            </tr>))}</tbody>
        </table></div>
      </Panel>
      <Apply v={v} ds={ds} keys={[...sel]} cell={cell} shown={shown} onDone={(m) => { setDone(m); setSel(new Set()); }} />
      <Panel title={cell ? `Class ${cell}` : "Every product kept at a place"} flush
        actions={<div className="row" style={{ gap: 8 }}>
          <input className="input sm" placeholder="Find a product or place" aria-label="Find a product or place" value={find} onChange={(e) => setFind(e.target.value)} />
          {cell && <button className="btn sm ghost" onClick={() => go("policy")}>Show every class</button>}</div>}>
        <div className="table-wrap"><table className="t" aria-label="Inventory policy">
          <thead><tr>
            <th><Edits><input type="checkbox" aria-label="Choose every product shown" checked={allShown}
              onChange={() => setSel((s) => { const n = new Set(s); for (const r of page) { if (allShown) n.delete(key(r)); else n.add(key(r)); } return n; })} /></Edits></th>
            <th>Product at a place</th><th>Class</th><th>Rule</th><th className="num">Safety stock</th><th>Service target</th>
            <th className="num">Reorder point</th><th className="num">On hand</th><th className="num">Achieved</th></tr></thead>
          <tbody>{page.map((r) => <Row key={key(r)} r={r} cur={cur} chosen={sel.has(key(r))} onToggle={() => toggle(key(r))} />)}</tbody>
        </table></div>
        <MoreRows shown={page.length} total={listed.length} what="products" how="Find a product or choose a class to narrow the list." />
      </Panel>
    </div></div>
  );
}

function Row({ r, cur, chosen, onToggle }: { r: PolicyRow; cur: string; chosen: boolean; onToggle: () => void }) {
  const nm = useNames();
  const low = r.target_kind === "cycle" && r.suggested != null && r.target != null && r.target < r.suggested - 1e-9;
  const short = r.achieved != null && r.target != null && r.achieved < r.target - 1e-9;
  return (
    <tr>
      <td><Edits><input type="checkbox" aria-label={`Choose ${nm.prod(r.product)} at ${nm.loc(r.location)}`} checked={chosen} onChange={onToggle} /></Edits></td>
      <td><a href={href("material", r.product, r.location)}>{nm.prod(r.product)}</a><div className="faint small">{nm.loc(r.location)}</div>
        {r.notes.map((n) => <div key={n} className="small warn-text">{n}</div>)}</td>
      <td><b>{r.abc}{r.xyz ?? "–"}</b><div className="faint small">{r.cv != null ? `CV ${r.cv.toFixed(2)}, ${r.cv_from}` : "no demand"}</div>
        <div className="faint small">{money(r.usage_value, cur)} a year</div></td>
      <td>{r.rule_label}<div className="faint small">{r.review_days > 0 ? `reviewed every ${qty(r.review_days)} days${r.next_review ? `, next on ${day(r.next_review)}` : ""}` : r.rule === "mrp" ? "each plan" : "continuous review"}
        {r.order_qty != null && r.rule !== "none" ? `; orders about ${qty(r.order_qty)} (${r.lot})` : ""}{r.order_up_to != null ? `; up to ${qty(r.order_up_to)}` : ""}</div></td>
      <td className="num">{qty(r.safety_stock)}<div className="faint small">{METHOD[r.method] ?? r.method}{r.distribution !== "normal" ? `, ${SPREAD[r.distribution] ?? r.distribution}` : ""}</div>
        {r.safety_stock_value > 0 && <div className="faint small">{money(r.safety_stock_value, cur)}</div>}</td>
      <td>{r.target != null ? <>{pct(r.target, 1)} <span className="faint small">{r.target_kind === "fill" ? "fill rate" : "cycle"}{r.target_from === "company" ? ", company default" : ""}</span></> : <span className="faint">none</span>}
        {r.suggested != null && <div className={`small ${low ? "warn-text" : "faint"}`}>class {r.abc}{r.xyz} suggests {pct(r.suggested, 0)}</div>}</td>
      <td className="num">{r.reorder_point != null ? qty(r.reorder_point) : <span className="faint">—</span>}
        {r.suggested_reorder_point != null && <div className="faint small">suggested {qty(r.suggested_reorder_point)}</div>}</td>
      <td className="num">{qty(r.on_hand)}{r.cover_days != null && <div className="faint small">{qty(r.cover_days)} days</div>}</td>
      <td className="num">{r.achieved != null ? <span className={short ? "neg-text" : ""}>{pct(r.achieved, 0)}</span> : <span className="faint">—</span>}
        <div className="faint small">{r.orders ? `${r.served} of ${r.orders} orders` : "no orders"}</div></td>
    </tr>
  );
}

function Apply({ v, ds, keys, cell, shown, onDone }: { v: PolicyView; ds: Dataset; keys: string[]; cell: string;
  shown: PolicyRow[]; onDone: (msg: string) => void }) {
  const [method, setMethod] = useState("");
  const [target, setTarget] = useState("");
  const [suggested, setSuggested] = useState(false);
  const [days, setDays] = useState("");
  const [fixed, setFixed] = useState("");
  const [review, setReview] = useState("");
  const [reviewFrom, setReviewFrom] = useState("");
  const [rop, setRop] = useState(false);
  const [rule, setRule] = useState("");
  const [spread, setSpread] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const to = keys.length ? keys : cell ? shown.map(key) : [];
  const what = keys.length ? plural(keys.length, "chosen product") : cell ? `every product in class ${cell} (${shown.length})` : "";
  const apply = async () => {
    setBusy(true);
    setErr(null);
    try {
      const input: PolicyApplyInput = { keys: to };
      if (method) input.method = method as PolicyApplyInput["method"];
      if (suggested) input.service_level = "suggested";
      else if (target.trim()) input.service_level = Number(target) / 100;
      if (method === "days_of_supply") input.days = Number(days);
      if (method === "fixed") input.qty = Number(fixed);
      if (review.trim()) input.review_period_days = Number(review);
      if (reviewFrom) input.review_from = reviewFrom;
      if (rule) input.rule = rule as PolicyApplyInput["rule"];
      if (spread) input.distribution = spread as PolicyApplyInput["distribution"];
      if (rop) input.reorder_point = "suggested";
      const out = await api.inventoryPolicyApply(ds, input);
      store.replace(out.dataset, ds);
      onDone(namesOf(out.dataset).text(out.message));
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };
  const statistical = !method || method === "service_level" || method === "fill_rate";
  return (
    <Panel title="Give a policy">
      <Edits><div className="stack" style={{ gap: 8 }}>
        <p className="small faint">{what ? `For ${what}. Only what is filled in changes; the rest of each product's policy stays.`
          : "Choose products in the table, or a class above, to give them one policy."}</p>
        <div className="row wrap" style={{ gap: 12 }}>
          <label className="field-inline">Safety stock <select className="input sm" aria-label="Safety stock method" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="">as it is</option><option value="service_level">for a cycle service level</option>
            <option value="fill_rate">for a fill rate</option><option value="days_of_supply">days of cover</option>
            <option value="fixed">a fixed quantity</option><option value="none">none</option></select></label>
          {method === "days_of_supply" && <label className="field-inline">Days <input className="input sm" inputMode="decimal" aria-label="Days of cover" value={days} onChange={(e) => setDays(e.target.value)} style={{ width: 70 }} /></label>}
          {method === "fixed" && <label className="field-inline">Quantity <input className="input sm" inputMode="decimal" aria-label="Fixed safety stock" value={fixed} onChange={(e) => setFixed(e.target.value)} style={{ width: 90 }} /></label>}
          {statistical && <label className="field-inline">Target % <input className="input sm" inputMode="decimal" aria-label="Service target %" value={target} disabled={suggested}
            onChange={(e) => setTarget(e.target.value)} style={{ width: 70 }} /></label>}
          {statistical && <label className="row small"><input type="checkbox" checked={suggested} onChange={(e) => setSuggested(e.target.checked)} />its class's suggestion</label>}
          {statistical && <label className="field-inline">Demand spread <select className="input sm" aria-label="Demand spread" value={spread} onChange={(e) => setSpread(e.target.value)}>
            <option value="">as it is</option><option value="normal">normal</option><option value="gamma">gamma (varies widely)</option>
            <option value="poisson">Poisson (slow, a few at a time)</option></select></label>}
          <label className="field-inline">Ordered by <select className="input sm" aria-label="Rule" value={rule} onChange={(e) => setRule(e.target.value)}>
            <option value="">the rule it has</option><option value="reorder_point">a reorder point (s, set to the suggestion)</option>
            <option value="mrp">time-phased MRP</option></select></label>
          <label className="field-inline">Review every <input className="input sm" inputMode="decimal" aria-label="Review period in days" value={review} onChange={(e) => setReview(e.target.value)} style={{ width: 60 }} /> days</label>
          {review.trim() !== "" && Number(review) > 0 && <label className="field-inline">from <input className="input sm" type="date" aria-label="A review day" value={reviewFrom} onChange={(e) => setReviewFrom(e.target.value)} /></label>}
          <label className="row small"><input type="checkbox" checked={rop} onChange={(e) => setRop(e.target.checked)} />the suggested reorder point</label>
          <button className="btn primary sm" disabled={busy || !to.length} onClick={apply}>{busy ? "Applying…" : `Apply to ${plural(to.length, "product")}`}</button>
        </div>
        {err && <div className="banner error" role="alert"><Badge sev="error">Not applied</Badge>{err}</div>}
        {v.rows.length > 0 && !to.length && <p className="small faint">Tip: click a class above, then Apply, to give the whole class its suggested target.</p>}
      </div></Edits>
    </Panel>
  );
}
