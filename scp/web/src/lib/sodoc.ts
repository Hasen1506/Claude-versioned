// The documents a customer receives (Phase M): the order confirmation, the invoice and the credit note, each a page of its
// own to print, save as PDF or download, and the text of an e-mail; and (N124) the statement of account and the payment
// reminder. Built from the selling view and the company's data; nothing is sent from here.
import type { Dataset, InvoiceView, OrderView } from "../api/types";
import { exactMoney, qty } from "./format";
import { namesOf } from "./names";

type Inv = NonNullable<Dataset["invoices"]>[number];

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
const long = (iso: string | null | undefined) =>
  iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "";
const block = (text: string) => text ? `<div>${esc(text).replace(/\n/g, "<br>")}</div>` : "";
const oneLine = (text: string) => text.split(/\n+/).map((x) => x.trim()).filter(Boolean).join(", ");

function parts(ds: Dataset, customer: string) {
  const nm = namesOf(ds);
  const place = (ds.locations ?? []).find((l) => l.id === customer);
  const cust = (ds.customers ?? []).find((c) => c.customer === customer);
  const unit = (id: string) => (ds.products ?? []).find((p) => p.id === id)?.base_uom ?? "";
  const s = ds.settings;
  return {
    nm, cust, unit, company: s.company_name || "Our company", currency: s.currency ?? "INR",
    from: { address: s.company_address?.trim() ?? "", tax: s.company_tax_id?.trim() ?? "" },
    to: { name: nm.loc(customer), address: place?.address?.trim() ?? "", tax: place?.tax_id?.trim() ?? "" },
  };
}

/** The places a customer document prints and which of them have no address yet. */
export function customerAddresses(ds: Dataset, customer: string): { what: string; href: string }[] {
  const p = parts(ds, customer);
  const missing: { what: string; href: string }[] = [];
  if (!p.from.address) missing.push({ what: "your company", href: "#/setup/company" });
  if (!p.to.address) missing.push({ what: p.to.name, href: `#/data/locations/${encodeURIComponent(customer)}` });
  return missing;
}

function page(title: string, company: string, body: string): string {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(title)} · ${esc(company)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; color: #1b1f24; margin: 0; background: #fff; }
  .page { max-width: 760px; margin: 0 auto; padding: 32px 24px; }
  header { display: flex; justify-content: space-between; gap: 24px; flex-wrap: wrap; border-bottom: 2px solid #1b1f24; padding-bottom: 12px; }
  h1 { font-size: 22px; margin: 0; letter-spacing: .01em; }
  .muted { color: #5b6470; } .id { color: #5b6470; font-size: 11px; font-family: ui-monospace, Menlo, Consolas, monospace; }
  .flag { display: inline-block; margin-top: 6px; padding: 2px 8px; border: 1px solid #b54708; color: #b54708; border-radius: 4px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 20px 0; }
  .grid h2 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #5b6470; margin: 0 0 4px; }
  table { width: 100%; border-collapse: collapse; margin-top: 8px; }
  th, td { text-align: left; padding: 7px 6px; border-bottom: 1px solid #d9dde3; vertical-align: top; }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: #5b6470; }
  .num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
  tfoot td { border-bottom: 0; } tfoot tr.total td { font-weight: 700; border-top: 2px solid #1b1f24; }
  footer { margin-top: 28px; font-size: 11px; color: #5b6470; }
  @media print { .page { padding: 0; } @page { margin: 18mm; } }
</style></head><body><div class="page">${body}</div></body></html>`;
}

/** The order confirmation: what was ordered, at what price, and when each line is promised. */
export function confirmationDocument(o: OrderView, ds: Dataset): string {
  const p = parts(ds, o.customer);
  const lines = o.lines.filter((l) => !l.cancelled || l.delivered > 0);
  const rows = lines.map((l) => {
    const n = l.id.split("/")[1] ?? "10";
    const disc = l.discount > 1e-9 && l.list_price != null
      ? `<div class="muted">${esc(exactMoney(l.list_price, p.currency))} less ${Math.round(l.discount * 1000) / 10} %</div>` : "";
    return `<tr><td>${esc(n)}</td><td><b>${esc(p.nm.prod(l.product))}</b><div class="id">${esc(l.product)}</div></td>
      <td class="num">${qty(l.qty)} ${esc(p.unit(l.product))}</td>
      <td class="num">${l.price != null ? esc(exactMoney(l.price, p.currency)) : "—"}${disc}</td>
      <td class="num">${l.value != null ? esc(exactMoney(l.value, p.currency)) : "—"}</td>
      <td>${esc(long(l.promised ?? l.date))}${l.promised && l.promised > l.date ? `<div class="muted">asked for ${esc(long(l.date))}</div>` : ""}</td></tr>`;
  }).join("");
  const tax = p.cust?.tax_rate ?? ds.sales?.tax_rate ?? 0;
  const net = o.value ?? 0;
  const body = `<header><div><h1>Order confirmation ${esc(o.id)}</h1>${o.credit_block ? `<div class="flag">Held: awaiting credit release</div>` : ""}</div>
<div style="text-align:right"><b>${esc(p.company)}</b>${block(p.from.address)}<div class="muted">Order date ${esc(long(o.order_date))}</div>
${o.customer_ref ? `<div class="muted">Your order ${esc(o.customer_ref)}</div>` : ""}</div></header>
<div class="grid">
  <div><h2>Customer</h2><b>${esc(p.to.name)}</b>${block(p.to.address)}${p.to.tax ? `<div class="muted">Tax no. ${esc(p.to.tax)}</div>` : ""}
    ${p.cust?.contact ? `<div>${esc(p.cust.contact)}</div>` : ""}</div>
  <div><h2>Terms</h2><div>Payment: ${esc(o.payment_terms)}</div>${p.cust?.incoterms ? `<div>Delivery ${esc(p.cust.incoterms)}</div>` : ""}
    <div>Prices in ${esc(p.currency)}, before tax</div></div>
</div>
<table><thead><tr><th>Line</th><th>Item</th><th class="num">Quantity</th><th class="num">Price</th><th class="num">Value</th><th>Delivery</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td></td><td>Net</td><td></td><td></td><td class="num">${esc(exactMoney(net, p.currency))}</td><td></td></tr>
${tax ? `<tr><td></td><td>Tax ${Math.round(tax * 1000) / 10} %</td><td></td><td></td><td class="num">${esc(exactMoney(net * tax, p.currency))}</td><td></td></tr>` : ""}
<tr class="total"><td></td><td>Total</td><td></td><td></td><td class="num">${esc(exactMoney(net * (1 + tax), p.currency))}</td><td></td></tr></tfoot></table>
<p>Thank you for your order. Please quote ${esc(o.id)} in any correspondence.</p>
<footer>${esc(p.company)}${p.from.tax ? ` · Tax no. ${esc(p.from.tax)}` : ""} · ${esc(o.id)}</footer>`;
  return page(`Order confirmation ${o.id}`, p.company, body);
}

/** An invoice or a credit note. */
export function invoiceDocument(inv: Inv, ds: Dataset): string {
  const p = parts(ds, inv.customer);
  const credit = inv.kind === "credit_note";
  const amt = (x: { qty: number; price: number }) => Math.round(x.qty * x.price * 100) / 100;
  const net = inv.lines.reduce((a, l) => a + amt(l), 0);
  const tax = Math.round(net * (inv.tax_rate ?? 0) * 100) / 100;
  const paid = (inv.payments ?? []).reduce((a, x) => a + x.amount + (x.discount ?? 0), 0);
  const rows = inv.lines.map((l, i) => `<tr><td>${(i + 1) * 10}</td><td><b>${esc(p.nm.prod(l.product))}</b><div class="id">${esc(l.product)}${l.order ? ` · order ${esc(l.order)}` : ""}</div></td>
    <td class="num">${qty(l.qty)} ${esc(p.unit(l.product))}</td><td class="num">${esc(exactMoney(l.price, p.currency))}</td>
    <td class="num">${esc(exactMoney(amt(l), p.currency))}</td></tr>`).join("");
  const terms = credit ? "" : `<div>Due ${esc(long(inv.due_date))}</div>${inv.discount && inv.discount_date
    ? `<div>${Math.round(inv.discount * 1000) / 10} % off (${esc(exactMoney((net + tax) * inv.discount, p.currency))}) if paid by ${esc(long(inv.discount_date))}</div>` : ""}`;
  const title = `${credit ? "Credit note" : "Invoice"} ${inv.id}`;
  const body = `<header><div><h1>${esc(title)}</h1>${inv.cancelled ? `<div class="flag">Cancelled</div>` : ""}</div>
<div style="text-align:right"><b>${esc(p.company)}</b>${block(p.from.address)}${p.from.tax ? `<div class="muted">Tax no. ${esc(p.from.tax)}</div>` : ""}
<div class="muted">Date ${esc(long(inv.date))}</div>${inv.reference ? `<div class="muted">For invoice ${esc(inv.reference)}</div>` : ""}</div></header>
<div class="grid">
  <div><h2>${credit ? "Credited to" : "Bill to"}</h2><b>${esc(p.to.name)}</b>${block(p.to.address)}${p.to.tax ? `<div class="muted">Tax no. ${esc(p.to.tax)}</div>` : ""}</div>
  <div><h2>${credit ? "Why" : "Payment"}</h2>${credit ? `<div>${esc(inv.note || "Goods returned")}</div>` : terms}</div>
</div>
<table><thead><tr><th>Line</th><th>Item</th><th class="num">Quantity</th><th class="num">Price</th><th class="num">Amount</th></tr></thead>
<tbody>${rows}</tbody>
<tfoot><tr><td></td><td>Net</td><td></td><td></td><td class="num">${esc(exactMoney(net, p.currency))}</td></tr>
<tr><td></td><td>Tax ${Math.round((inv.tax_rate ?? 0) * 1000) / 10} %</td><td></td><td></td><td class="num">${esc(exactMoney(tax, p.currency))}</td></tr>
<tr class="total"><td></td><td>${credit ? "Credited" : "Total"}</td><td></td><td></td><td class="num">${esc(exactMoney(net + tax, p.currency))}</td></tr>
${paid > 0 ? `<tr><td></td><td>${credit ? "Paid out" : "Paid"}</td><td></td><td></td><td class="num">${esc(exactMoney(paid, p.currency))}</td></tr>` : ""}</tfoot></table>
${credit ? "" : `<p>Please quote ${esc(inv.id)} with your payment.</p>`}
<footer>${esc(p.company)} · ${esc(inv.id)}</footer>`;
  return page(title, p.company, body);
}

/** What a customer owes on a day: their unpaid invoices and credit notes not paid out, and how long overdue. */
export function openItems(invoices: InvoiceView[], customer: string) {
  const items = invoices.filter((i) => i.customer === customer && i.status !== "cancelled" && i.open > 0.005)
    .sort((a, b) => a.due_date.localeCompare(b.due_date) || a.id.localeCompare(b.id));
  const sign = (i: InvoiceView) => (i.kind === "credit_note" ? -1 : 1);
  const owed = items.reduce((a, i) => a + sign(i) * i.open, 0);
  const overdue = items.filter((i) => i.status === "overdue");
  const ages: [string, (d: number) => boolean][] = [["not yet due", (d) => d === 0], ["1–30 days", (d) => d >= 1 && d <= 30],
    ["31–60 days", (d) => d > 30 && d <= 60], ["61–90 days", (d) => d > 60 && d <= 90], ["over 90 days", (d) => d > 90]];
  const aging = ages.map(([label, f]) => ({ label, amount: items.filter((i) => f(i.days_overdue)).reduce((a, i) => a + sign(i) * i.open, 0) }));
  return { items, owed, overdue, overdueAmount: overdue.reduce((a, i) => a + i.open, 0), aging };
}

/** The statement of account (what the customer owes, by document and by age) or, with ``reminder``, the payment reminder
 * of that number for the overdue invoices. */
export function statementDocument(customer: string, invoices: InvoiceView[], asOf: string, ds: Dataset, reminder = 0): string {
  const p = parts(ds, customer);
  const o = openItems(invoices, customer);
  const items = reminder ? o.overdue : o.items;
  const m = (x: number) => esc(exactMoney(x, p.currency));
  const rows = items.map((i) => {
    const credit = i.kind === "credit_note";
    return `<tr><td><b>${esc(i.id)}</b><div class="muted">${credit ? "credit note" : "invoice"}</div></td><td>${esc(long(i.date))}</td>
      <td>${credit ? "" : esc(long(i.due_date))}</td><td class="num">${m((credit ? -1 : 1) * i.total)}</td>
      <td class="num">${m((credit ? -1 : 1) * i.open)}</td><td class="num">${i.days_overdue ? `${i.days_overdue} days` : ""}</td></tr>`;
  }).join("");
  const total = reminder ? o.overdueAmount : o.owed;
  const title = reminder ? (reminder === 1 ? "Payment reminder" : `Payment reminder ${reminder}`) : "Statement of account";
  const payBy = new Date(new Date(asOf + "T00:00:00").getTime() + 7 * 86400_000).toISOString().slice(0, 10);
  const words = !reminder ? `<p>This is what we have open for you on ${esc(long(asOf))}. If your records differ, please tell us.</p>`
    : reminder === 1 ? `<p>Our records show the invoices below as unpaid past their due date. Perhaps they were overlooked: please pay
      ${m(total)} by ${esc(long(payBy))}, quoting the invoice numbers. If you have paid in the last few days, thank you, and please disregard this.</p>`
    : `<p>Despite our earlier reminder${reminder > 2 ? "s" : ""}, the invoices below are still unpaid. Please pay ${m(total)} by ${esc(long(payBy))}.
      If there is a reason they are not paid, please tell us at once${reminder >= 3 ? `; otherwise we must hold further deliveries until they are` : ""}.</p>`;
  const aging = reminder ? "" : `<table><thead><tr>${o.aging.map((a) => `<th class="num">${esc(a.label)}</th>`).join("")}</tr></thead>
<tbody><tr>${o.aging.map((a) => `<td class="num">${m(a.amount)}</td>`).join("")}</tr></tbody></table>`;
  const body = `<header><div><h1>${esc(title)}</h1></div>
<div style="text-align:right"><b>${esc(p.company)}</b>${block(p.from.address)}${p.from.tax ? `<div class="muted">Tax no. ${esc(p.from.tax)}</div>` : ""}
<div class="muted">Date ${esc(long(asOf))}</div></div></header>
<div class="grid">
  <div><h2>Customer</h2><b>${esc(p.to.name)}</b>${block(p.to.address)}${p.cust?.contact ? `<div>${esc(p.cust.contact)}</div>` : ""}</div>
  <div><h2>${reminder ? "Overdue" : "Owed"}</h2><div style="font-size:18px;font-weight:700">${m(total)}</div>${!reminder && o.overdueAmount > 0
    ? `<div class="muted">of which overdue ${m(o.overdueAmount)}</div>` : ""}</div>
</div>
${words}
<table><thead><tr><th>Document</th><th>Date</th><th>Due</th><th class="num">Amount</th><th class="num">Open</th><th class="num">Overdue</th></tr></thead>
<tbody>${rows || `<tr><td colspan="6" class="muted">Nothing open.</td></tr>`}</tbody>
<tfoot><tr class="total"><td>${reminder ? "Overdue" : "Owed"}</td><td></td><td></td><td></td><td class="num">${m(total)}</td><td></td></tr></tfoot></table>
${aging}
<footer>${esc(p.company)} · ${esc(title)} · ${esc(long(asOf))}</footer>`;
  return page(`${title} ${p.to.name}`, p.company, body);
}

/** Subject and body of an e-mail with the order confirmation or invoice in plain text. */
export function customerEmail(ds: Dataset, customer: string, subject: string, intro: string, lines: string[], end: string[]) {
  const p = parts(ds, customer);
  const body = [`Hello${p.cust?.contact ? ` ${p.cust.contact}` : ""},`, "", intro, "", ...lines, "", ...end, "", "Regards,", p.company,
    ...(p.from.address ? [oneLine(p.from.address)] : [])].join("\n");
  return { to: p.cust?.email ?? "", subject: `${subject} from ${p.company}`, body };
}
