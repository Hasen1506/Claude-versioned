import { useState } from "react";
import type { Dataset, PayablesView, SupplierInvoiceView } from "../api/types";
import { Badge, Edits, Panel } from "../components/ui";
import { day, exactMoney, moneyDigits } from "../lib/format";
import { useSettlement, type CarrierBankEvent } from "../state/settlement";
import { store } from "../state/store";
import { CamtStatementImport } from "./CamtStatementImport";
import { CarrierBankAccounts, minorUnits } from "./CarrierBankAccounts";
import { SupplierPaymentInstructions } from "./SupplierPaymentInstructions";

const today = () => new Date().toISOString().slice(0, 10);

type ClearingEvent = Extract<CarrierBankEvent, { kind: "clear_supplier_statement" }>;
type ReturnEvent = Extract<CarrierBankEvent, { kind: "return_supplier_statement" }>;
type StatementLine = PayablesView["carrier_bank"]["lines"][number];

function SupplierClearingForm({ line, invoices, editable, submit }: {
  line: StatementLine; invoices: SupplierInvoiceView[];
  editable: boolean; submit: (event: ClearingEvent) => void;
}) {
  const [amounts, setAmounts] = useState<Record<string, { invoice: string; bank: string }>>({});
  const [reason, setReason] = useState("");
  const digits = moneyDigits(line.currency);
  const fee = line.supplier_debit?.included_fee_minor ?? 0;
  const principal = -line.amount_minor - fee;
  const selected = invoices.filter((invoice) => amounts[invoice.id]);
  const parsed = selected.map((invoice) => {
    const entered = amounts[invoice.id];
    const local = invoice.currency === line.currency;
    return { invoice: invoice.id, invoice_minor: minorUnits(entered.invoice, moneyDigits(invoice.currency)) ?? 0,
      bank_minor: minorUnits(local ? entered.invoice : entered.bank, digits) ?? 0 };
  });
  const allocated = parsed.reduce((total, row) => total + row.bank_minor, 0);
  const ready = parsed.length > 0 && parsed.length <= 100 && parsed.every((row) => row.invoice_minor > 0 && row.bank_minor > 0)
    && allocated === principal && reason.trim();
  return <Edits><details>
    <summary>Post and clear supplier invoices</summary>
    <p className="small">Bank principal {exactMoney(principal / 10 ** digits, line.currency)}{fee
      ? ` · Included fee ${exactMoney(fee / 10 ** digits, line.currency)}` : ""} · Allocated {exactMoney(allocated / 10 ** digits, line.currency)}</p>
    <label>Supplier invoice <select className="input" value="" disabled={!editable} onChange={(e) => {
      const invoice = invoices.find((item) => item.id === e.target.value);
      if (invoice) setAmounts({ ...amounts, [invoice.id]: { invoice: invoice.open.toFixed(moneyDigits(invoice.currency)), bank: "" } });
    }}><option value="">Choose an open invoice</option>{invoices.filter((invoice) => !amounts[invoice.id]).map((invoice) =>
      <option key={invoice.id} value={invoice.id}>{invoice.id} · {invoice.supplier} · {exactMoney(invoice.open, invoice.currency)}</option>)}</select></label>
    {selected.map((invoice) => <div className="row wrap" key={invoice.id} style={{ gap: 8 }}>
      <label>{invoice.id} cash ({invoice.currency}) <input className="input" inputMode="decimal" value={amounts[invoice.id].invoice}
        onChange={(e) => setAmounts({ ...amounts, [invoice.id]: { ...amounts[invoice.id], invoice: e.target.value } })} /></label>
      {invoice.currency !== line.currency && <label>{invoice.id} bank cash ({line.currency}) <input className="input" inputMode="decimal"
        value={amounts[invoice.id].bank} onChange={(e) => setAmounts({ ...amounts,
          [invoice.id]: { ...amounts[invoice.id], bank: e.target.value } })} /></label>}
      <button className="btn sm ghost" onClick={() => setAmounts(Object.fromEntries(Object.entries(amounts)
        .filter(([id]) => id !== invoice.id)))}>Remove {invoice.id}</button>
    </div>)}
    <div className="row wrap" style={{ gap: 8 }}>
      <label>Allocation evidence <input className="input" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <button className="btn accent" disabled={!editable || !ready} onClick={() => submit({
        kind: "clear_supplier_statement", line: line.id, reason: reason.trim(), allocations: parsed,
      })}>Post supplier clearing</button>
    </div>
  </details></Edits>;
}

function SupplierReturnForm({ line, originals, ds, editable, submit }: {
  line: StatementLine; originals: StatementLine[]; ds: Dataset;
  editable: boolean; submit: (event: ReturnEvent) => void;
}) {
  const [original, setOriginal] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const source = originals.find((row) => row.id === original);
  const candidates = (source?.history?.[0]?.supplier_clearing?.postings ?? []).flatMap((item) => {
    const payments = ds.supplier_invoices?.find((inv) => inv.id === item.invoice)?.payments ?? [];
    const posted = payments[item.payment_number - 1]?.statement_cash;
    return !posted || payments.some((entry) => entry.reverses === item.payment_number) ? []
      : [{ item, voucher: `${item.invoice}/${item.payment_number}`, amount: posted.bank_minor }];
  });
  const selected = candidates.filter((row) => picked.includes(row.voucher));
  const total = selected.reduce((sum, row) => sum + row.amount, 0);
  const principal = line.amount_minor + (line.included_fee_minor ?? 0);
  const money = (amount: number) => exactMoney(amount / 10 ** moneyDigits(line.currency), line.currency);
  return <Edits><details>
    <summary>Reopen invoices for this bank return</summary>
    <p className="small">Returned principal {money(principal)} · Selected {money(total)}</p>
    <label>Original supplier debit <select className="input" value={original} disabled={!editable} onChange={(e) => {
      setOriginal(e.target.value); setPicked([]);
    }}><option value="">Choose the original debit</option>{originals.map((row) =>
      <option key={row.id} value={row.id}>{row.statement_line} · {row.reference} · {day(row.date)}</option>)}</select></label>
    {candidates.map((row) => <div key={row.voucher}><label><input type="checkbox" checked={picked.includes(row.voucher)}
      onChange={(e) => setPicked(e.target.checked ? [...picked, row.voucher] : picked.filter((voucher) => voucher !== row.voucher))} />
      {row.voucher} · {money(row.amount)}</label></div>)}
    <div className="row wrap" style={{ gap: 8 }}>
      <label>Return evidence <input className="input" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
      <button className="btn accent" disabled={!editable || !original || !reason.trim() || total !== principal} onClick={() => submit({
        kind: "return_supplier_statement", line: line.id, original, reason: reason.trim(), payments: selected.map((row) => row.item),
      })}>Post supplier return</button>
    </div>
  </details></Edits>;
}

export function SupplierBankWorklist({ bank, ds, currency, invoices }: {
  bank: PayablesView["carrier_bank"]; ds: Dataset; currency: string; invoices: SupplierInvoiceView[];
}) {
  const settlement = useSettlement("carrier_bank", "supplier");
  const [lineId, setLineId] = useState("");
  const [voucher, setVoucher] = useState("");
  const [on, setOn] = useState(today);
  const [originals, setOriginals] = useState<string[]>();
  const [message, setMessage] = useState<{ text: string; error: boolean }>();
  const [busy, setBusy] = useState(false);
  const digits = moneyDigits(currency);
  const factor = 10 ** digits;
  const domestic = digits !== 2;
  const lines = bank.lines.filter((row) => !row.history?.some((event) => event.targets.length)
    && (domestic || !!row.supplier_debit || row.reversal));
  const cash = bank.unmatched_supplier_cash ?? [];
  const periods = bank.periods;
  const line = lines.find((row) => row.id === lineId);
  const history = line?.history ?? [];
  const active = history.at(-1)?.supplier_payment;
  const cleared = history[0]?.supplier_clearing;
  const period = line && periods.find((row) => row.period.line_ids.includes(line.id))?.period;
  const candidates = line && period && !line.requires_allocation ? cash.filter((item) => item.bank_account === period.account && item.amount_minor === line.amount_minor
    && item.date >= period.starts_on && item.date <= period.ends_on && item.date <= on) : [];
  const target = candidates.find((item) => item.voucher === voucher);
  const earliest = history.at(-1)?.date ?? line?.date ?? "";
  const permitted = on >= earliest && on > (ds.finance?.closed_through ?? "");
  const editable = settlement.live && !busy && !settlement.pending;
  const instruction = line && (ds.supplier_payment_instructions ?? []).find((item) =>
    item.id.toLowerCase() === line.reference.trim().toLowerCase());
  const canPost = !!line?.supplier_debit && !line.supplier_debit.unresolved_charges && !history.length
    && permitted && line.date > (ds.finance?.closed_through ?? "");
  const eligible = invoices.filter((invoice) => invoice.open > 0 && ["to pay", "released"].includes(invoice.status)
    && (ds.supplier_invoices?.find((item) => item.id === invoice.id)?.entity ?? "") === line?.company);
  const possibleOriginals = line?.reversal && line.return_source_checked && !line.unresolved_charges && !history.length
    && permitted && line.date > (ds.finance?.closed_through ?? "") ? lines.filter((source) =>
    source.account === line.account && source.date <= line.date && !source.reversal && source.history?.[0]?.supplier_clearing
    && (source.reference.normalize("NFKC").toLowerCase() === line.reference.normalize("NFKC").toLowerCase()
      || (source.trace_ids ?? []).some((trace) => line.trace_ids?.includes(trace)))) : [];

  async function record(event?: CarrierBankEvent, postingDate = on) {
    setBusy(true);
    setMessage(undefined);
    try {
      const reply = await (event ? settlement.post(postingDate, null, "", undefined, event) : settlement.retry(originals));
      setMessage({ text: (reply.result as { report: { message: string } }).report.message, error: false });
      setVoucher("");
      await store.run("purchasing");
    } catch (error) {
      setMessage({ text: String(error).replace(/^Error:\s*/, ""), error: true });
    } finally {
      setBusy(false);
    }
  }

  if (!settlement.live && !lines.length && !periods.length) return null;

  const statementRows = <>
      <div className="table-wrap"><table className="t" aria-label="Supplier statement lines">
        <thead><tr><th>Statement line</th><th>Bank date</th><th>Account</th><th>Bank reference</th>
          <th className="num">Cash</th><th>Match</th></tr></thead>
        <tbody>{lines.map((row) => {
          const linked = row.history?.at(-1)?.supplier_payment;
          return <tr key={row.id} className={row.id === lineId ? "selected" : undefined}>
            <td><button className="btn sm ghost" onClick={() => {
              setLineId(row.id); setVoucher("");
              setOn([today(), row.date, row.history?.at(-1)?.date ?? ""].sort().at(-1) ?? today());
            }}>{row.statement_line}</button></td>
            <td>{day(row.date)}</td><td>{row.account}</td><td>{row.reference}</td>
            <td className="num">{exactMoney(row.amount_minor / factor, currency)}</td>
            <td>{linked ? <Badge sev="ok">{linked.invoice}/{linked.payment_number}</Badge>
              : row.history?.[0]?.supplier_clearing ? <Badge sev="ok">Posted and reconciled</Badge> : <Badge sev="warning">Unmatched</Badge>}</td>
          </tr>;
        })}</tbody>
      </table></div>
      {line && <div className="pad">
        <h3>{line.statement_line}</h3>
        {settlement.live && !cleared && <Edits><div className="row wrap" style={{ gap: 8 }}>
          <label>Reconciliation date <input className="input" type="date" min={earliest} value={on}
            onChange={(e) => setOn(e.target.value)} /></label>
          {active ? <button className="btn ghost" disabled={!editable || !permitted}
            onClick={() => record({ kind: "release", line: line.id, version: history.length })}>Release supplier match</button>
            : domestic && <>
              <label>Recorded supplier cash <select className="input" value={voucher} onChange={(e) => setVoucher(e.target.value)}>
                <option value="">Choose a posting</option>
                {candidates.map((item) => <option key={item.voucher} value={item.voucher}>
                  {item.voucher} · {item.reference} · {exactMoney(item.amount_minor / factor, currency)}
                </option>)}
              </select></label>
              <button className="btn accent" disabled={!editable || !permitted || !target} onClick={() => target && record({
                kind: "match_supplier_payment", line: line.id, version: history.length,
                target: { invoice: target.invoice, payment_number: target.payment_number },
              })}>Match supplier cash</button>
            </>}
        </div></Edits>}
        {canPost && settlement.live && !instruction && <SupplierClearingForm key={line.id} line={line} invoices={eligible}
          editable={editable} submit={record} />}
        {!!possibleOriginals.length && settlement.live && <SupplierReturnForm key={line.id} line={line} originals={possibleOriginals}
          ds={ds} editable={editable} submit={record} />}
        {canPost && settlement.live && instruction?.approved_on && !instruction.statement_line && !instruction.rejection && <Edits>
          <button className="btn accent" disabled={!editable} onClick={() => record({
            kind: "clear_supplier_statement", line: line.id, instruction: instruction.id, reason: "Matched the approved instruction to the booked bank debit.",
          })}>Confirm booked instruction {instruction.id}</button>
        </Edits>}
        {!active && !cleared && !candidates.length && !canPost && !possibleOriginals.length && <p className="small">{line.supplier_debit?.unresolved_charges
          ? "The bank statement includes ambiguous charges. Resolve the bank evidence before clearing."
          : line.requires_allocation
          ? "This bank entry contains grouped cash or charges and requires allocation."
          : "No available posting has this account, signed amount and statement period."}</p>}
        {!!history.length && <ol className="small" aria-label="Supplier match history">{history.map((event, index) =>
          <li key={index}>{day(event.date)} · {event.supplier_payment
            ? `Matched ${event.supplier_payment.invoice}/${event.supplier_payment.payment_number}` : event.supplier_clearing
              ? `Posted ${event.supplier_clearing.postings.map((item) => `${item.invoice}/${item.payment_number}`).join(", ")} · ${event.supplier_clearing.reason}`
              : "Released"}</li>)}</ol>}
      </div>}
  </>;

  return <Panel title="Supplier bank statements">
    {domestic && <CarrierBankAccounts ds={ds} currency={currency} periods={periods} live={settlement.live} editable={editable}
      supplier record={record} />}
    {domestic && settlement.live && <CamtStatementImport ds={ds} editable={editable} pending={settlement.pendingBankFile}
      originals={originals} setOriginals={setOriginals} record={record} />}
    <SupplierPaymentInstructions ds={ds} invoices={invoices} currency={currency} />
    {message && <div className={`banner ${message.error ? "error" : "info"}`} role={message.error ? "alert" : "status"}>{message.text}</div>}
    {settlement.pending && <Edits><button className="btn accent" disabled={busy || (settlement.pendingBankFile && !originals?.length)}
      onClick={() => record()}>Retry statement operation</button></Edits>}
    {!!lines.length && (domestic ? statementRows : <details className="pad">
      <summary>Review supplier statement entries</summary>
      {statementRows}
    </details>)}
    {!!cash.length && <details className="pad"><summary>Unmatched supplier cash ({cash.length})</summary>
      <ul>{cash.map((item) => <li key={item.voucher}>
        {item.voucher} · {day(item.date)} · {item.bank_account} · {item.reference} · {exactMoney(item.amount_minor / factor, currency)}
      </li>)}</ul>
    </details>}
  </Panel>;
}
