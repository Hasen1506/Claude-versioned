// The inter-company tax invoice (Enterprise 7.3) as a page to print in three copies: what GST rule 46 asks a tax
// invoice to show — the number and date from the seller's series, both registrations' names, addresses and GSTINs,
// the place of supply, each line's description, HSN code, quantity, unit, taxable value and rate, CGST and SGST or
// IGST, the total, and the signature. A credit note (rule 53) shows the same and names what it credits. Built from
// the group view; nothing is sent from here.
import type { Dataset, IcInvoiceRow } from "../api/types";
import { exactMoney, qty } from "./format";

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const long = (iso: string | null | undefined) =>
  iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "";
const COPIES = ["Original for the recipient", "Duplicate for the transporter", "Triplicate for the supplier"];
const pct = (r: number) => `${Math.round(r * 10000) / 100} %`;

/** The invoice or credit note as a stand-alone HTML page: three copies, one to a printed page. */
export function icInvoiceDocument(inv: IcInvoiceRow, ds: Dataset): string {
  const cur = ds.settings.currency;
  const credit = inv.kind === "credit_note";
  const title = credit ? "Credit note" : "Tax invoice";
  const split = inv.split === "cgst_sgst";
  const addr = (t?: string | null) => t ? `<div>${esc(t).replace(/\n/g, "<br>")}</div>` : "";
  const taxCells = (rate: number, tax: number) => split
    ? `<td class="num">${pct(rate / 2)}</td><td class="num">${esc(exactMoney(Math.round(tax * 50) / 100, cur))}</td>
       <td class="num">${pct(rate / 2)}</td><td class="num">${esc(exactMoney(tax - Math.round(tax * 50) / 100, cur))}</td>`
    : `<td class="num">${pct(rate)}</td><td class="num">${esc(exactMoney(tax, cur))}</td>`;
  const head = split ? "<th class=\"num\">CGST</th><th class=\"num\">Amount</th><th class=\"num\">SGST</th><th class=\"num\">Amount</th>"
    : `<th class="num">${inv.split === "igst" ? "IGST" : "Tax"}</th><th class="num">Amount</th>`;
  const rows = inv.lines.map((l, i) => `<tr><td>${i + 1}</td><td><b>${esc(l.product_name)}</b><div class="id">${esc(l.product)} · ${esc(l.order)}</div></td>
    <td>${esc(l.hsn || "—")}</td><td class="num">${qty(l.qty)} ${esc(l.unit)}</td><td class="num">${esc(exactMoney(l.price, cur))}</td>
    <td class="num">${esc(exactMoney(l.net, cur))}</td>${taxCells(l.tax_rate, l.tax)}</tr>`).join("");
  const blanks = split ? "<td></td><td class=\"num\">" + esc(exactMoney(inv.cgst, cur)) + "</td><td></td><td class=\"num\">" + esc(exactMoney(inv.sgst, cur)) + "</td>"
    : `<td></td><td class="num">${esc(exactMoney(inv.tax, cur))}</td>`;
  const copy = (label: string) => `<section class="copy">
<header><div><h1>${title} ${esc(inv.id)}</h1><div class="muted">${credit ? "Section 34 of the CGST Act · rule 53" : "Section 31 of the CGST Act · rule 46"} · supply between companies of one group</div></div>
<div class="right"><div class="tag">${esc(label)}</div><div>Date ${esc(long(inv.date))}</div><div>Place of supply ${esc(inv.place_of_supply || "—")}</div></div></header>
<div class="grid">
  <div><h2>Supplier</h2><b>${esc(inv.seller_name)}</b>${addr(inv.seller_address)}<div>GSTIN ${esc(inv.seller_gstin || "—")}</div><div class="muted">Shipped from ${esc(inv.ship_from_name)}</div></div>
  <div><h2>Recipient</h2><b>${esc(inv.buyer_name)}</b>${addr(inv.buyer_address)}<div>GSTIN ${esc(inv.buyer_gstin || "—")}</div><div class="muted">Delivered to ${esc(inv.ship_to_name)}</div></div>
</div>
<div class="table-wrap"><table><thead><tr><th>#</th><th>Goods</th><th>HSN</th><th class="num">Quantity</th><th class="num">Rate</th><th class="num">Taxable value</th>${head}</tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td></td><td>Total</td><td></td><td></td><td></td><td class="num">${esc(exactMoney(inv.net, cur))}</td>${blanks}</tr>
<tr><td></td><td colspan="4">${credit ? "Credited" : "Invoice value"}, tax included</td><td class="num">${esc(exactMoney(inv.total, cur))}</td>${split ? "<td colspan=\"4\"></td>" : "<td colspan=\"2\"></td>"}</tr></tfoot></table></div>
${credit ? `<p>Credits the goods taken back on ${esc([...new Set(inv.lines.map((l) => l.movement))].join(", "))}, at the price they were invoiced at.</p>` : ""}
${inv.note ? `<p><b>Note:</b> ${esc(inv.note)}</p>` : ""}
<div class="sign"><div>Received by (recipient)</div><div>For ${esc(inv.seller_name)}: authorised signatory</div></div>
</section>`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(inv.id)} · ${esc(inv.seller_name)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #1b1f24; margin: 0; background: #fff; }
  .copy { max-width: 820px; margin: 0 auto; padding: 32px 24px; page-break-after: always; }
  .copy:last-child { page-break-after: auto; }
  header { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; border-bottom: 2px solid #1b1f24; padding-bottom: 12px; }
  h1 { font-size: 22px; margin: 0; } .right { text-align: right; } .muted { color: #5b6470; }
  .tag { display: inline-block; padding: 2px 8px; border: 1px solid #1b1f24; border-radius: 4px; font-weight: 600; margin-bottom: 4px; }
  .id { color: #5b6470; font-size: 11px; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 20px 0; }
  .grid h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #5b6470; margin: 0 0 4px; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 7px 6px; border-bottom: 1px solid #d9dde3; vertical-align: top; }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #5b6470; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tfoot td { border-bottom: 0; font-weight: 700; }
  .sign { display: flex; justify-content: space-between; gap: 24px; margin-top: 48px; flex-wrap: wrap; }
  .sign div { border-top: 1px solid #1b1f24; padding-top: 4px; min-width: 220px; }
  @media print { .copy { padding: 0; } @page { margin: 16mm; } }
</style></head><body>${COPIES.map(copy).join("")}</body></html>`;
}
