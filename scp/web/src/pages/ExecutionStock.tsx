// Stock you can trace (Phase O): lots by batch and stock type with what can be done to them, the fields a receipt
// takes for batches and serial numbers, the firm orders a short receipt leaves short, physical inventory documents,
// and the company's stock rules.
import { useMemo, useState } from "react";
import { api, type PostExtra } from "../api/client";
import type { ActionReport, CountItem, Dataset, InventoryDoc, LotRow, PostAction, ShortOrder, StockRow, StockType } from "../api/types";
import { Badge, Edits, Panel, Reading } from "../components/ui";
import { day, plural, qty } from "../lib/format";
import { Loc, namesOf, Prod, useNames } from "../lib/names";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { store } from "../state/store";

/** Post through the engine, keep the new dataset, re-read the journal; the message in names and the whole report. */
export async function postAct(ds: Dataset, action: PostAction, extra: PostExtra = {}): Promise<{ text: string; report: ActionReport }> {
  const out = await api.postActual(ds, action, extra);
  store.replace(out.dataset, ds);
  await store.run("actuals");
  return { text: namesOf(out.dataset).text(out.report.message), report: out.report };
}

const TYPE_WORD: Record<string, string> = { unrestricted: "free to use", quality: "in inspection", blocked: "blocked" };

export const daysBetween = (a: string, b: string) =>
  Math.round((new Date(b + "T00:00:00Z").getTime() - new Date(a + "T00:00:00Z").getTime()) / 86_400_000);

/** A row has something more to show than one plain figure: batches, stock types, expiry, serials or a count running. */
export const hasDetail = (r: StockRow) =>
  r.lots.length > 0 || r.serials.length > 0 || !!r.counting || r.quality > 1e-6 || r.blocked > 1e-6;

/** The stock cells Phase O adds to the reconciliation table. */
export function StockTypeCells({ r }: { r: StockRow }) {
  const cell = (v: number, sev?: "warning" | "error") => Math.abs(v) > 1e-6
    ? (sev ? <Badge sev={sev}>{qty(v)}</Badge> : qty(v)) : <span className="faint">—</span>;
  return <>
    <td className="num">{cell(r.quality)}</td>
    <td className="num">{cell(r.blocked)}</td>
    <td className="num">{cell(r.expired, "warning")}</td>
    <td className="num">{cell(r.in_transit)}</td>
  </>;
}

/** The lots at one place, and what can be done with them: release from inspection, block, unblock, scrap. */
export function LotsDetail({ r, ds, asOf, onDone }: { r: StockRow; ds: Dataset; asOf: string; onDone: (msg: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const lots: LotRow[] = r.lots.length ? r.lots
    : [{ batch: null, stock_type: "unrestricted", qty: r.unrestricted, made_on: null, expires_on: null, expired: false }];
  const act = async (key: string, action: PostAction, extra: PostExtra) => {
    setBusy(key);
    setErr(null);
    try { onDone((await postAct(ds, action, { location: r.location, product: r.product, ...extra })).text); }
    catch (e) { setErr(String(e)); }
    finally { setBusy(null); }
  };
  const move = (l: LotRow, to: StockType) => act(`${l.batch}|${l.stock_type}|${to}`, "move",
    { qty: l.qty, batch: l.batch, stock_type: l.stock_type as StockType, to_type: to });
  return (
    <div className="stack" style={{ gap: 8, padding: "6px 4px" }}>
      {r.counting && <div className="small"><Badge sev="info">counting</Badge> {r.counting} counts this: postings for it wait until the count is posted
        (<a href="#/execution/count">Count stock</a>).</div>}
      <Edits>
        <table className="t" style={{ width: "auto" }}>
          <thead><tr><th>Batch</th><th>Stock</th><th className="num">Quantity</th><th>Made</th><th>Expires</th><th /></tr></thead>
          <tbody>
            {lots.filter((l) => Math.abs(l.qty) > 1e-6).map((l) => {
              const key = `${l.batch}|${l.stock_type}`;
              const left = l.expires_on ? daysBetween(asOf, l.expires_on) : null;
              return (
                <tr key={key}>
                  <td>{l.batch ?? <span className="faint" title="Stock recorded without a batch, such as an opening balance">no batch</span>}</td>
                  <td>{TYPE_WORD[l.stock_type] ?? l.stock_type}</td>
                  <td className="num">{qty(l.qty)}</td>
                  <td>{l.made_on ? day(l.made_on) : ""}</td>
                  <td>{l.expires_on ? <>{day(l.expires_on)}{" "}
                    {l.expired ? <Badge sev="warning">expired</Badge> : left !== null && left <= 7 ? <Badge sev="info">{plural(left, "day")} left</Badge> : null}</> : ""}</td>
                  <td className="nowrap">
                    {l.qty > 0 && l.stock_type === "quality" && <button className="btn sm" disabled={!!busy} onClick={() => move(l, "unrestricted")}
                      title="It passed inspection: free to use">Release</button>}{" "}
                    {l.qty > 0 && l.stock_type !== "blocked" && <button className="btn sm ghost" disabled={!!busy} onClick={() => move(l, "blocked")}
                      title="Hold it back: damaged, recalled or waiting for a decision. Planning does not count it">Block</button>}{" "}
                    {l.qty > 0 && l.stock_type === "blocked" && <button className="btn sm" disabled={!!busy} onClick={() => move(l, "unrestricted")}
                      title="Free to use again">Unblock</button>}{" "}
                    {l.qty > 0 && <button className="btn sm ghost" disabled={!!busy}
                      onClick={() => act(`${key}|scrap`, "scrap", { qty: l.qty, batch: l.batch, stock_type: l.stock_type as StockType })}
                      title="Post it as scrapped: it leaves stock">Scrap</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Edits>
      {r.expired > 1e-6 && <div className="row" style={{ gap: 8 }}><span className="small">{qty(r.expired)} {r.expired === 1 ? "is" : "are"} past the expiry date:
        planning no longer counts {r.expired === 1 ? "it" : "them"}.</span>
        <Edits><button className="btn sm accent" disabled={!!busy} onClick={() => act("expired", "scrap_expired", {})}>Scrap what has expired</button></Edits></div>}
      {r.serials.length > 0 && <div className="small"><span className="muted">Serial numbers here ({r.serials.length}):</span>{" "}
        <span className="mono">{r.serials.slice(0, 40).join(", ")}{r.serials.length > 40 ? " …" : ""}</span></div>}
      {err && <div className="banner error"><Badge sev="error">Not posted</Badge>{err}</div>}
      <div className="faint small">These are the batches there are now, this week's postings included. A change to stock that was there before
        {" "}{day(ds.settings.planning_start)} is dated the day before, so the plan starts from it at once; goods that came in this week change this week.</div>
    </div>
  );
}

/** What a receipt says about the goods: batch, expiry and the supplier's batch for a product kept by batch, and one
 *  serial number per unit for a serialised one (left empty: numbered by the system). */
export interface LotInput { batch: string; expires_on: string; supplier_batch: string; serials: string }
export const NO_LOT: LotInput = { batch: "", expires_on: "", supplier_batch: "", serials: "" };

export function lotExtra(v: LotInput): PostExtra {
  const serials = v.serials.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
  return { batch: v.batch.trim() || null, expires_on: v.expires_on || null, supplier_batch: v.supplier_batch.trim() || null,
    serials: serials.length ? serials : null };
}

export function LotFields({ ds, product, value, onChange, receiving }: { ds: Dataset; product: string; value: LotInput;
  onChange: (v: LotInput) => void; receiving: boolean }) {
  const p = (ds.products ?? []).find((x) => x.id === product);
  if (!p) return null;
  const batches = p.batches ?? !!p.shelf_life_days;
  if (!batches && !p.serial_numbers) return null;
  const set = (k: keyof LotInput) => (e: React.ChangeEvent<HTMLInputElement>) => onChange({ ...value, [k]: e.target.value });
  return (
    <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
      {batches && <>
        <label className="small muted">Batch <input className="input" style={{ width: 130 }} value={value.batch} onChange={set("batch")}
          placeholder={receiving ? "new, numbered" : "first expiring"} aria-label={`Batch of ${p.name || p.id}`} /></label>
        {receiving && <label className="small muted">Expires <input className="input" type="date" style={{ width: 160 }} value={value.expires_on} onChange={set("expires_on")}
          aria-label="Expires on" title={p.shelf_life_days ? `Empty: the day it is received plus ${p.shelf_life_days} days` : undefined} /></label>}
        {receiving && <label className="small muted">Supplier's batch <input className="input" style={{ width: 120 }} value={value.supplier_batch} onChange={set("supplier_batch")} /></label>}
      </>}
      {p.serial_numbers && <label className="small muted" style={{ flex: "1 1 260px" }}>Serial numbers <input className="input" style={{ width: "100%" }}
        value={value.serials} onChange={set("serials")} placeholder={receiving ? "empty: numbered for you" : "empty: the first ones in"}
        aria-label="Serial numbers" /></label>}
    </div>
  );
}

/** The firm orders a short receipt leaves without enough parts (R16), each with the offer to shorten it. */
export function ShortOrders({ list, ds, onDone }: { list: ShortOrder[]; ds: Dataset; onDone: (msg: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  const nm = useNames();
  if (!list.length) return null;
  const shorten = async (s: ShortOrder) => {
    setBusy(s.order);
    setErr(null);
    try {
      onDone((await postAct(ds, "shorten", { order: s.order, qty: s.can_make })).text);
      setDone(new Set([...done, s.order]));
    } catch (e) { setErr(String(e)); } finally { setBusy(null); }
  };
  return (
    <div className="banner warning" role="status" style={{ display: "block" }}>
      <div className="row" style={{ gap: 8 }}><Badge sev="warning">Can no longer run in full</Badge>
        <span>{plural(list.length, "firm order")} {list.length === 1 ? "needs" : "need"} more than there is and is coming.</span></div>
      <table className="t" style={{ marginTop: 8, width: "auto" }}>
        <thead><tr><th>Order</th><th>Makes</th><th>Short of</th><th className="num">Needs</th><th className="num">Has</th><th className="num">Can make</th><th /></tr></thead>
        <tbody>
          {list.map((s) => (
            <tr key={`${s.order}|${s.part}`}>
              <td><b>{s.order}</b></td><td><Prod id={s.product} /> {qty(s.qty)}</td><td><Prod id={s.part} /> at <Loc id={s.location} /></td>
              <td className="num">{qty(s.needs)}</td><td className="num">{qty(s.available)}</td><td className="num"><b>{qty(s.can_make)}</b></td>
              <td>{done.has(s.order) ? <Badge sev="ok">shortened</Badge>
                : <Edits><button className="btn sm" disabled={!!busy || s.can_make <= 0} onClick={() => shorten(s)}
                  title={s.can_make <= 0 ? "Nothing of it can be made: cancel it or find the parts" : `Make ${nm.prod(s.product)} ${qty(s.can_make)} instead of ${qty(s.qty)}; its parts in proportion`}>
                  Shorten to {qty(s.can_make)}</button></Edits>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {err && <div className="small" style={{ color: "var(--error-text)" }}>{err}</div>}
      <div className="small muted" style={{ marginTop: 6 }}>Or leave them and find the rest: plan again, and the plan buys what is missing.</div>
    </div>
  );
}

// ---- physical inventory ---------------------------------------------------------------------------------
/** Physical inventory documents (≈ MI01/MI04/MI07): count a place's stock on a day against the book stock frozen when
 *  the document is made, with postings for it held until the differences are posted. */
export function PhysicalInventory({ ds, nodes }: { ds: Dataset; nodes: [string, string][] }) {
  const nm = useNames();
  const start = ds.settings.planning_start;
  const places = useMemo(() => [...new Set(nodes.map((n) => n[0]))].sort((a, b) => nm.loc(a).localeCompare(nm.loc(b))), [nodes, nm]);
  const [place, setPlace] = useState("");
  const [group, setGroup] = useState("");
  const [on, setOn] = useState(() => { const d = new Date(start + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - 1); return d.toISOString().slice(0, 10); });
  const [block, setBlock] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const docs = (ds.inventory_docs ?? []);
  const open = docs.filter((d) => d.status === "open");
  const groups = [...new Set((ds.products ?? []).map((p) => p.family).filter(Boolean))] as string[];
  const fam = new Map((ds.products ?? []).map((p) => [p.id, p.family ?? ""]));
  const chosen = nodes.filter(([l, p]) => l === place && (!group || fam.get(p) === group));
  const run = async (action: PostAction, extra: PostExtra) => {
    setBusy(true);
    setErr(null);
    try { setMsg((await postAct(ds, action, extra)).text); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  return (
    <Panel title="Physical inventory" actions={<span className="faint small">Count a whole place on a day, against the stock the books froze</span>}>
      <Edits><div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
        <select className="input" style={{ width: 220 }} value={place} onChange={(e) => setPlace(e.target.value)} aria-label="Place to count">
          <option value="">Choose a place…</option>
          {places.map((l) => <option key={l} value={l}>{nm.loc(l)}</option>)}
        </select>
        {groups.length > 0 && <select className="input" style={{ width: 180 }} value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Product group">
          <option value="">Every product</option>
          {groups.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>}
        <label className="small muted">Count date <input type="date" className="input" style={{ width: 160 }} value={on} onChange={(e) => setOn(e.target.value)} /></label>
        <label className="small"><input type="checkbox" checked={block} onChange={(e) => setBlock(e.target.checked)} /> Hold postings for these until the count is posted</label>
        <span className="spacer" />
        <button className="btn sm accent" disabled={busy || !chosen.length} onClick={() => run("count_doc",
          { nodes: chosen.map(([location, product]) => ({ location, product })), date: on, block })}>
          {chosen.length ? `Start counting ${plural(chosen.length, "product")}` : "Start counting"}</button>
      </div></Edits>
      {msg && <div className="banner info" style={{ marginTop: 10 }}><Badge sev="ok">Done</Badge><span>{msg}</span><span className="spacer" />
        <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
      {err && <div className="banner error" style={{ marginTop: 10 }}><Badge sev="error">Not done</Badge>{err}</div>}
      {open.map((d) => <CountSheet key={d.id} d={d} busy={busy} run={run} />)}
      {!open.length && <p className="small muted" style={{ marginTop: 10 }}>No count is under way.
        {docs.length > 0 && <> Last: {docs.slice(-3).reverse().map((d) => `${d.id} (${d.status}, ${day(d.date)})`).join(", ")}.</>}</p>}
    </Panel>
  );
}

function CountSheet({ d, busy, run }: { d: InventoryDoc; busy: boolean; run: (a: PostAction, e: PostExtra) => Promise<void> }) {
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [book, setBook] = useState(false);
  const key = (i: CountItem) => `${i.location}|${i.product}|${i.batch ?? ""}|${i.stock_type}`;
  const items = d.items ?? [];
  const counted = items.filter((i) => i.counted !== null && i.counted !== undefined).length;
  const changed = Object.entries(edits).filter(([, v]) => v.trim() !== "" && Number.isFinite(Number(v)) && Number(v) >= 0);
  const save = () => run("count_enter", { doc: d.id, counts: changed.map(([k, v]) => {
    const [location, product, batch, stock_type] = k.split("|");
    return { location, product, batch: batch || null, stock_type: stock_type as StockType, qty: Number(v) };
  }) }).then(() => setEdits({}));
  return (
    <div className="stack" style={{ marginTop: 12, gap: 8 }}>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        <b>{d.id}</b><span className="muted small">count on {day(d.date)} · {counted} of {plural(items.length, "line")} counted
          {d.block && " · postings held"}</span>
        <span className="spacer" />
        <label className="small"><input type="checkbox" checked={book} onChange={(e) => setBook(e.target.checked)} /> Show the book stock</label>
        <Edits><>
          <button className="btn sm" disabled={busy || !changed.length} onClick={save}>Save {changed.length ? plural(changed.length, "count") : "counts"}</button>{" "}
          <button className="btn sm accent" disabled={busy || counted < items.length} onClick={() => run("count_post", { doc: d.id })}
            title={counted < items.length ? "Count every line first" : "Post the differences against the frozen book stock"}>Post differences</button>{" "}
          <button className="btn sm ghost" disabled={busy} onClick={() => run("count_cancel", { doc: d.id })}>Cancel the count</button>
        </></Edits>
      </div>
      <Edits><div className="table-wrap" style={{ maxHeight: 420 }}>
        <table className="t">
          <thead><tr><th>Product</th><th>Batch</th><th>Stock</th>{book && <th className="num">Book (frozen)</th>}<th className="num">Counted</th>
            {book && <th className="num">Difference</th>}</tr></thead>
          <tbody>
            {items.map((i) => {
              const k = key(i);
              const v = edits[k] ?? (i.counted ?? "").toString();
              const n = v === "" ? null : Number(v);
              return (
                <tr key={k}>
                  <td><Prod id={i.product} /></td><td>{i.batch ?? <span className="faint">no batch</span>}</td><td>{TYPE_WORD[i.stock_type ?? "unrestricted"]}</td>
                  {book && <td className="num">{qty(i.book_qty)}</td>}
                  <td className="num"><input className="input" type="number" min={0} step="any" style={{ width: 110, textAlign: "right" }} value={v}
                    onChange={(e) => setEdits({ ...edits, [k]: e.target.value })} aria-label={`Counted ${i.product} ${i.batch ?? ""}`} /></td>
                  {book && <td className="num">{n === null ? "" : n - i.book_qty === 0 ? <span className="faint">0</span> : <Badge sev="warning">{n > i.book_qty ? "+" : ""}{qty(n - i.book_qty)}</Badge>}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div></Edits>
      <div className="faint small">The book stock was frozen when counting started: postings since then do not change the difference.</div>
    </div>
  );
}

// ---- the company's stock rules ------------------------------------------------------------------------------
export function StockRules({ ds }: { ds: Dataset }) {
  return (
    <details className="panel" style={{ padding: "10px 14px" }}>
      <summary><b>Stock rules</b> <span className="muted small">stock below zero, stock in inspection, the firm zone, delivery tolerance</span></summary>
      <div style={{ marginTop: 10 }}>
        <SchemaForm defName="ExecutionSettings" value={(ds.execution ?? {}) as unknown as Obj}
          onChange={(next) => store.update((d) => { d.execution = next as unknown as Dataset["execution"]; })} />
      </div>
      <Reading soWhat="Refusing keeps the journal honest but stops a posting until its receipt is in; counting as found keeps the plan and the journal in step without a count. Stock in quality inspection is counted by default, as SAP's planning does." />
    </details>
  );
}
