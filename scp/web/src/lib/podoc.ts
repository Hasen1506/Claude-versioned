// The purchase order as a document to send (Q23): a page of its own to print, save as PDF or download, and the text of
// an e-mail to the supplier. Built from the order view and the company's data; nothing is sent from here.
import type { Dataset, PoView } from "../api/types";
import { exactMoney, qty } from "./format";
import { namesOf } from "./names";

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const long = (iso: string | null | undefined) =>
  iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "";

function parts(po: PoView, ds: Dataset) {
  const nm = namesOf(ds);
  const vendor = (ds.vendors ?? []).find((v) => v.supplier === po.supplier);
  const unit = (id: string) => (ds.products ?? []).find((p) => p.id === id)?.base_uom ?? "";
  const lines = po.lines.filter((l) => l.ordered > 1e-9);
  const place = (id: string | null | undefined) => (ds.locations ?? []).find((l) => l.id === id);
  return { nm, vendor, unit, lines, company: ds.settings.company_name || "Our company", place };
}

/** The addresses a purchase order prints and which of them are still empty (N69). */
export function poAddresses(po: PoView, ds: Dataset) {
  const { nm, place } = parts(po, ds);
  const s = ds.settings;
  const sup = place(po.supplier), to = place(po.location);
  const missing: { what: string; href: string }[] = [];
  if (!s.company_address?.trim()) missing.push({ what: "your company", href: "#/setup/company" });
  if (po.supplier && !sup?.address?.trim()) missing.push({ what: nm.loc(po.supplier), href: `#/data/locations/${encodeURIComponent(po.supplier)}` });
  if (!to?.address?.trim()) missing.push({ what: nm.loc(po.location), href: `#/data/locations/${encodeURIComponent(po.location)}` });
  return {
    company: { address: s.company_address?.trim() ?? "", tax: s.company_tax_id?.trim() ?? "" },
    supplier: { address: sup?.address?.trim() ?? "", tax: sup?.tax_id?.trim() ?? "" },
    deliver: { address: to?.address?.trim() ?? "", tax: to?.tax_id?.trim() ?? "" },
    missing,
  };
}

const lines = (text: string) => text ? `<div class="addr">${esc(text).replace(/\n/g, "<br>")}</div>` : "";
const taxLine = (tax: string) => tax ? `<div class="muted">Tax no. ${esc(tax)}</div>` : "";

/** The order as a stand-alone HTML page. */
export function poDocument(po: PoView, ds: Dataset): string {
  const { nm, vendor, unit, lines: items, company } = parts(po, ds);
  const addr = poAddresses(po, ds);
  const draft = po.approved ? "" : "Draft: not approved yet";
  const terms = [
    vendor?.payment_terms_days != null && `Payment ${vendor.payment_terms_days} days after invoice`,
    vendor?.incoterms && `Delivery terms ${vendor.incoterms}`,
    `Prices in ${po.currency}`,
  ].filter(Boolean) as string[];
  const rows = items.map((l, i) => `<tr><td>${(i + 1) * 10}</td><td><b>${esc(nm.prod(l.product))}</b><div class="id">${esc(l.product)}</div></td>
    <td class="num">${qty(l.ordered)} ${esc(unit(l.product))}</td><td class="num">${l.price != null ? esc(exactMoney(l.price, po.currency)) : "—"}</td>
    <td class="num">${esc(exactMoney(l.value, po.currency))}</td><td>${esc(long(l.due_date))}</td></tr>`).join("");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(po.id)} · ${esc(company)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #1b1f24; margin: 0; background: #fff; }
  .page { max-width: 760px; margin: 0 auto; padding: 32px 24px; }
  header { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; border-bottom: 2px solid #1b1f24; padding-bottom: 12px; }
  h1 { font-size: 22px; margin: 0; letter-spacing: .01em; }
  .addr { white-space: normal; } .muted { color: #5b6470; } .id { color: #5b6470; font-size: 11px; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .draft { display: inline-block; margin-top: 6px; padding: 2px 8px; border: 1px solid #b54708; color: #b54708; border-radius: 4px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 20px 0; }
  .grid h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #5b6470; margin: 0 0 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 7px 6px; border-bottom: 1px solid #d9dde3; vertical-align: top; }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #5b6470; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tfoot td { border-bottom: 0; font-weight: 700; }
  ul { padding-left: 18px; } footer { margin-top: 28px; font-size: 11px; color: #5b6470; }
  @media print { .page { padding: 0; } @page { margin: 18mm; } }
</style></head><body><div class="page">
<header><div><h1>${po.kind === "scheduling_agreement" ? "Delivery schedule" : "Purchase order"} ${esc(po.id)}</h1>${draft ? `<div class="draft">${draft}</div>` : ""}</div>
<div style="text-align:right"><b>${esc(company)}</b><div class="muted">Order date ${esc(long(po.order_date ?? po.sent_on))}</div>
${po.vendor_reference ? `<div class="muted">Your reference ${esc(po.vendor_reference)}</div>` : ""}</div></header>
<div class="grid">
  <div><h2>Supplier</h2><b>${esc(po.supplier ? nm.loc(po.supplier) : "—")}</b>${lines(addr.supplier.address)}${taxLine(addr.supplier.tax)}
    ${vendor?.contact ? `<div>${esc(vendor.contact)}</div>` : ""}${vendor?.email ? `<div>${esc(vendor.email)}</div>` : ""}${vendor?.phone ? `<div>${esc(vendor.phone)}</div>` : ""}</div>
  <div><h2>Deliver to</h2><b>${esc(nm.loc(po.location))}</b>${lines(addr.deliver.address)}</div>
  ${addr.company.address ? `<div><h2>Invoice to</h2><b>${esc(company)}</b>${lines(addr.company.address)}${taxLine(addr.company.tax)}</div>` : ""}
  <div><h2>Terms</h2>${terms.map((t) => `<div>${esc(t)}</div>`).join("")}</div>
</div>
<table><thead><tr><th>Line</th><th>Item</th><th class="num">Quantity</th><th class="num">Price</th><th class="num">Value</th><th>Deliver by</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td></td><td>Total</td><td></td><td></td><td class="num">${esc(exactMoney(po.value, po.currency))}</td><td></td></tr></tfoot></table>
${po.note ? `<p><b>Note:</b> ${esc(po.note)}</p>` : ""}
<p>Please confirm the quantities and delivery dates, quoting ${esc(po.id)} on every delivery note and invoice.</p>
<footer>${esc(company)} · ${esc(po.id)} · ${items.length} line${items.length === 1 ? "" : "s"}</footer>
</div></body></html>`;
}

/** Subject and body of an e-mail with the order in plain text. */
export function poEmail(po: PoView, ds: Dataset): { to: string; subject: string; body: string } {
  const { nm, vendor, unit, lines, company } = parts(po, ds);
  const addr = poAddresses(po, ds);
  const body = [
    `Hello${vendor?.contact ? ` ${vendor.contact}` : ""},`, "",
    `Please supply the following on ${po.kind === "scheduling_agreement" ? "scheduling agreement" : "purchase order"} ${po.id}, delivered to ${nm.loc(po.location)}${addr.deliver.address ? `, ${addr.deliver.address.split(/\n+/).map((x) => x.trim()).filter(Boolean).join(", ")}` : ""}:`, "",
    ...lines.map((l) => `- ${nm.prod(l.product)} (${l.product}): ${qty(l.ordered)} ${unit(l.product)}${l.price != null ? ` at ${exactMoney(l.price, po.currency)}` : ""}, by ${long(l.due_date)}`),
    "", `Total ${exactMoney(po.value, po.currency)}.`,
    "Please confirm quantities and delivery dates, and quote the order number on the delivery note and invoice.", "",
    "Regards,", company,
    ...addr.company.address.split(/\n+/).map((x) => x.trim()).filter(Boolean),
    ...(addr.company.tax ? [`Tax no. ${addr.company.tax}`] : []),
  ].join("\n");
  return { to: vendor?.email ?? "", subject: `${po.kind === "scheduling_agreement" ? "Delivery schedule" : "Purchase order"} ${po.id} from ${company}`, body };
}
