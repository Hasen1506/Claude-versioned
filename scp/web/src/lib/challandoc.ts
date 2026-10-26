// The job-work delivery challan (Enterprise 7.1) as a page to print in three copies: what GST rule 55 asks a
// challan to show for goods sent to a job worker under section 143 — the challan number and date, both parties'
// names, addresses and GSTINs, the place of supply, each item's HSN code, quantity, unit and taxable value, and the
// signature. Built from the job-work view and the company's data; nothing is sent from here.
import type { ChallanRow, Dataset } from "../api/types";
import { exactMoney, qty } from "./format";

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const long = (iso: string | null | undefined) =>
  iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "";
const COPIES = ["Original for the job worker", "Duplicate for the transporter", "Triplicate for the sender"];

/** The challan as a stand-alone HTML page: three copies, one to a printed page. */
export function challanDocument(c: ChallanRow, ds: Dataset): string {
  const s = ds.settings;
  const company = s.company_name || "Our company";
  const place = (id: string) => (ds.locations ?? []).find((l) => l.id === id);
  const jw = place(c.job_worker), from = place(c.ship_from);
  const cur = s.currency;
  const total = c.lines.reduce((a, l) => a + l.qty * l.value, 0);
  const addr = (t?: string | null) => t ? `<div>${esc(t).replace(/\n/g, "<br>")}</div>` : "";
  const rows = c.lines.map((l, i) => `<tr><td>${i + 1}</td><td><b>${esc(l.product_name)}</b><div class="id">${esc(l.product)}</div></td>
    <td>${esc(l.hsn || "—")}</td><td class="num">${qty(l.qty)} ${esc(l.unit)}</td><td class="num">${esc(exactMoney(l.value, cur))}</td>
    <td class="num">${esc(exactMoney(l.qty * l.value, cur))}</td><td>${l.capital_goods ? "Capital goods" : "Inputs"}</td></tr>`).join("");
  const copy = (label: string) => `<section class="copy">
<header><div><h1>Delivery challan ${esc(c.id)}</h1><div class="muted">For job work, section 143 of the CGST Act · rule 55</div></div>
<div class="right"><div class="tag">${esc(label)}</div><div>Date ${esc(long(c.sent_on))}</div>
${c.vehicle ? `<div>Vehicle ${esc(c.vehicle)}</div>` : ""}<div>For order ${esc(c.order)}${c.order_product_name ? ` (${esc(c.order_product_name)})` : ""}</div></div></header>
<div class="grid">
  <div><h2>From</h2><b>${esc(company)}</b>${addr(from?.address || s.company_address)}<div>GSTIN ${esc(c.ship_from_gstin || "—")}</div></div>
  <div><h2>To the job worker</h2><b>${esc(c.job_worker_name)}</b>${addr(jw?.address)}<div>GSTIN ${esc(c.job_worker_gstin || "—")}</div></div>
</div>
<table><thead><tr><th>#</th><th>Goods</th><th>HSN</th><th class="num">Quantity</th><th class="num">Value each</th><th class="num">Taxable value</th><th>Type</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td></td><td>Total</td><td></td><td></td><td></td><td class="num">${esc(exactMoney(total, cur))}</td><td></td></tr></tfoot></table>
<p>Sent for job work without payment of tax. To come back within one year (inputs) or three years (capital goods) of
the date above; what does not is treated as supplied to the job worker on that date.${c.charge ? ` Job charge ${esc(exactMoney(c.charge, cur))} per unit processed.` : ""}</p>
${c.note ? `<p><b>Note:</b> ${esc(c.note)}</p>` : ""}
<div class="sign"><div>Received by (job worker)</div><div>For ${esc(company)}: authorised signatory</div></div>
</section>`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(c.id)} · ${esc(company)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #1b1f24; margin: 0; background: #fff; }
  .copy { max-width: 760px; margin: 0 auto; padding: 32px 24px; page-break-after: always; }
  .copy:last-child { page-break-after: auto; }
  header { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; border-bottom: 2px solid #1b1f24; padding-bottom: 12px; }
  h1 { font-size: 22px; margin: 0; } .right { text-align: right; } .muted { color: #5b6470; }
  .tag { display: inline-block; padding: 2px 8px; border: 1px solid #1b1f24; border-radius: 4px; font-weight: 600; margin-bottom: 4px; }
  .id { color: #5b6470; font-size: 11px; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 20px 0; }
  .grid h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #5b6470; margin: 0 0 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 7px 6px; border-bottom: 1px solid #d9dde3; vertical-align: top; }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #5b6470; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tfoot td { border-bottom: 0; font-weight: 700; }
  .sign { display: flex; justify-content: space-between; gap: 24px; margin-top: 48px; }
  .sign div { border-top: 1px solid #1b1f24; padding-top: 4px; min-width: 220px; }
  @media print { .copy { padding: 0; } @page { margin: 16mm; } }
</style></head><body>${COPIES.map(copy).join("")}</body></html>`;
}
