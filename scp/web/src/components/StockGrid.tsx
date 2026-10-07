// Opening stock as one grid: every product down, every stocking place across, on hand in each cell. Type, paste a
// block from Excel, fill right (Ctrl+R) or copy down (Ctrl+D). A product-place whose stock follows the goods movements
// is read-only here: a count is posted on its card instead, so the journal stays the record (UX audit: stock was entered
// per card only, with no count grid).
import { useMemo, useState, type ClipboardEvent, type KeyboardEvent } from "react";
import type { Dataset, LocationProduct } from "../api/types";
import { cell, fillKey, parseGrid, pasteNote, placeBlock } from "../lib/gridpaste";
import { store } from "../state/store";
import { Edits, Panel } from "./ui";

const ROWS = 200;

export function StockGrid({ ds, onClose }: { ds: Dataset; onClose: () => void }) {
  const places = useMemo(() => (ds.locations ?? []).filter((l) => l.type !== "supplier" && l.type !== "customer"), [ds]);
  const products = useMemo(() => (ds.products ?? []).slice(0, ROWS), [ds]);
  const lps = useMemo(() => new Map((ds.location_products ?? []).map((x) => [`${x.location}|${x.product}`, x])), [ds]);
  const journal = useMemo(() => new Set((ds.movements ?? []).map((m) => `${m.location}|${m.product}`)), [ds]);
  const [note, setNote] = useState<string | null>(null);

  const write = (cells: { r: number; c: number; v: number }[]) => {
    const ok = cells.filter(({ r, c }) => !journal.has(`${places[c].id}|${products[r].id}`));
    if (ok.length) store.update((d) => {
      const list = (d.location_products ??= []);
      for (const { r, c, v } of ok) {
        const loc = places[c].id, prod = products[r].id;
        let x = list.find((y) => y.location === loc && y.product === prod);
        if (!x) { x = { location: loc, product: prod } as LocationProduct; list.push(x); }
        x.on_hand = v;
      }
    });
    return { n: ok.length, ro: cells.length - ok.length };
  };
  const paste = (e: ClipboardEvent<HTMLInputElement>, r: number, c: number) => {
    const block = parseGrid(e.clipboardData.getData("text/plain"));
    if (!block) return;
    e.preventDefault();
    const { writes, skipped, clipped } = placeBlock(block, r, c, products.length, places.length);
    const { n, ro } = write(writes);
    setNote(pasteNote(n, skipped + ro, clipped) + (ro ? " Cells kept by goods movements take a count instead." : ""));
  };
  const fill = (e: KeyboardEvent<HTMLInputElement>, r: number, c: number) => {
    const how = fillKey(e);
    if (!how) return false;
    e.preventDefault();
    const v = cell(e.currentTarget.value);
    if (Number.isNaN(v)) return true;
    const cells = how === "right" ? places.map((_, j) => ({ r, c: j, v })).filter((x) => x.c >= c)
      : products.map((_, i) => ({ r: i, c, v })).filter((x) => x.r >= r);
    const { n, ro } = write(cells);
    setNote(pasteNote(n, ro, 0));
    return true;
  };

  return (
    <Panel flush title={<h3>Stock on hand, every product at every place</h3>}
      actions={<button className="btn sm ghost" onClick={onClose}>Close the grid</button>}>
      <p className="small muted" style={{ padding: "0 14px" }}>Type what is on the shelf today, or paste a block copied from Excel.
        <kbd>Ctrl</kbd>+<kbd>R</kbd> fills a value to the right, <kbd>Ctrl</kbd>+<kbd>D</kbd> copies it down.</p>
      {note && <p className="small" role="status" style={{ padding: "0 14px" }}>{note}</p>}
      <Edits><div className="table-wrap">
        <table className="t dp" aria-label="Stock on hand grid">
          <thead><tr><th className="dp-stub">Product</th>{places.map((l) => <th key={l.id} className="num">{l.name || l.id}</th>)}</tr></thead>
          <tbody>{products.map((p, r) => (
            <tr key={p.id}><td className="dp-stub"><b>{p.name || p.id}</b></td>
              {places.map((l, c) => {
                const k = `${l.id}|${p.id}`, v = lps.get(k)?.on_hand ?? 0, ro = journal.has(k);
                return <td key={l.id} className="num dp-cell">
                  <input className="dp-in" inputMode="decimal" defaultValue={v ? String(v) : ""} key={`${k}|${v}`} readOnly={ro}
                    title={ro ? "Stock here follows the goods movements: post a count on its card" : undefined}
                    aria-label={`On hand of ${p.name || p.id} at ${l.name || l.id}`}
                    onPaste={(e) => paste(e, r, c)}
                    onKeyDown={(e) => { if (fill(e, r, c)) return; if (e.key === "Enter") e.currentTarget.blur(); }}
                    onBlur={(e) => {
                      if (ro) return;
                      const n = cell(e.target.value);
                      if (Number.isNaN(n)) { e.target.value = v ? String(v) : ""; return; }
                      if (Math.abs(n - v) > 1e-9) write([{ r, c, v: n }]);
                    }} />
                </td>;
              })}</tr>))}</tbody>
        </table>
      </div></Edits>
    </Panel>
  );
}
