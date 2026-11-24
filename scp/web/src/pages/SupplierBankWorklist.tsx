import { useState } from "react";
import type { Dataset, PayablesView } from "../api/types";
import { Badge, Edits, Panel } from "../components/ui";
import { day, exactMoney, moneyDigits } from "../lib/format";
import { useSettlement, type CarrierBankEvent } from "../state/settlement";
import { store } from "../state/store";
import { CamtStatementImport } from "./CamtStatementImport";
import { CarrierBankAccounts } from "./CarrierBankAccounts";

const today = () => new Date().toISOString().slice(0, 10);

export function SupplierBankWorklist({ bank, ds, currency }: {
  bank: PayablesView["carrier_bank"]; ds: Dataset; currency: string;
}) {
  const settlement = useSettlement("carrier_bank", "supplier");
  const [lineId, setLineId] = useState("");
  const [voucher, setVoucher] = useState("");
  const [on, setOn] = useState(today);
  const [originals, setOriginals] = useState<string[]>();
  const [message, setMessage] = useState<{ text: string; error: boolean }>();
  const [busy, setBusy] = useState(false);
  const factor = 10 ** moneyDigits(currency);
  const lines = bank.lines;
  const cash = bank.unmatched_supplier_cash ?? [];
  const periods = bank.periods;
  const line = lines.find((row) => row.id === lineId);
  const history = line?.history ?? [];
  const active = history.at(-1)?.supplier_payment;
  const period = line && periods.find((row) => row.period.line_ids.includes(line.id))?.period;
  const candidates = line && period && !line.requires_allocation ? cash.filter((item) => item.bank_account === period.account && item.amount_minor === line.amount_minor
    && item.date >= period.starts_on && item.date <= period.ends_on && item.date <= on) : [];
  const target = candidates.find((item) => item.voucher === voucher);
  const earliest = history.at(-1)?.date ?? line?.date ?? "";
  const permitted = on >= earliest && on > (ds.finance?.closed_through ?? "");
  const editable = settlement.live && !busy && !settlement.pending;

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

  return <Panel title="Supplier bank statements">
    <CarrierBankAccounts ds={ds} currency={currency} periods={periods} live={settlement.live} editable={editable}
      supplier record={record} />
    {settlement.live && <CamtStatementImport ds={ds} editable={editable} pending={settlement.pendingBankFile}
      originals={originals} setOriginals={setOriginals} record={record} />}
    {message && <div className={`banner ${message.error ? "error" : "info"}`} role={message.error ? "alert" : "status"}>{message.text}</div>}
    {settlement.pending && <Edits><button className="btn accent" disabled={busy || (settlement.pendingBankFile && !originals?.length)}
      onClick={() => record()}>Retry statement operation</button></Edits>}
    {!!lines.length && <>
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
            <td>{linked ? <Badge sev="ok">{linked.invoice}/{linked.payment_number}</Badge> : <Badge sev="warning">Unmatched</Badge>}</td>
          </tr>;
        })}</tbody>
      </table></div>
      {line && <div className="pad">
        <h3>{line.statement_line}</h3>
        {settlement.live && <Edits><div className="row wrap" style={{ gap: 8 }}>
          <label>Reconciliation date <input className="input" type="date" min={earliest} value={on}
            onChange={(e) => setOn(e.target.value)} /></label>
          {active ? <button className="btn ghost" disabled={!editable || !permitted}
            onClick={() => record({ kind: "release", line: line.id, version: history.length })}>Release supplier match</button>
            : <>
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
        {!active && !candidates.length && <p className="small">{line.requires_allocation
          ? "This bank entry contains grouped cash or charges and requires allocation."
          : "No available posting has this account, signed amount and statement period."}</p>}
        {!!history.length && <ol className="small" aria-label="Supplier match history">{history.map((event, index) =>
          <li key={index}>{day(event.date)} · {event.supplier_payment
            ? `Matched ${event.supplier_payment.invoice}/${event.supplier_payment.payment_number}` : "Released"}</li>)}</ol>}
      </div>}
    </>}
    {!!cash.length && <details className="pad"><summary>Unmatched supplier cash ({cash.length})</summary>
      <ul>{cash.map((item) => <li key={item.voucher}>
        {item.voucher} · {day(item.date)} · {item.bank_account} · {item.reference} · {exactMoney(item.amount_minor / factor, currency)}
      </li>)}</ul>
    </details>}
  </Panel>;
}
