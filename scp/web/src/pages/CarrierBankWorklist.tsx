import { useState } from "react";
import type { Dataset, PayablesView } from "../api/types";
import { Edits, Empty, Panel } from "../components/ui";
import { day, exactMoney } from "../lib/format";
import { useSettlement, type CarrierBankEvent } from "../state/settlement";
import { store } from "../state/store";
import { CarrierBankAccounts } from "./CarrierBankAccounts";

type Worklist = PayablesView["carrier_bank"];
type Line = Worklist["lines"][number];
type Cash = Worklist["unmatched_cash"][number];
const cashKey = (item: Cash) => JSON.stringify([item.order, item.voucher]);
const today = () => new Date().toISOString().slice(0, 10);

export function CarrierBankWorklist({ bank, ds, currency }: { bank: Worklist; ds: Dataset; currency: string }) {
  const settlement = useSettlement("carrier_bank", "worklist");
  const [entity, setEntity] = useState("");
  const [account, setAccount] = useState("");
  const [file, setFile] = useState<string>();
  const [lineId, setLineId] = useState("");
  const [date, setDate] = useState(today);
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean }>();
  const selected = bank.lines.find((line) => line.id === lineId);
  const periods = bank.periods ?? [];
  const selectedPeriod = selected && periods.find(({ period }) => period.line_ids.includes(selected.id))?.period;
  const history = selected?.history ?? [];
  const active = history.at(-1)?.targets ?? [];
  const candidates = selected ? bank.unmatched_cash.filter((cash) => cash.company === selected.company
    && (cash.bank_account ?? null) === (selectedPeriod?.account ?? null)
    && (!selectedPeriod || (cash.date >= selectedPeriod.starts_on && cash.date <= selectedPeriod.ends_on))
    && Math.sign(cash.amount_minor) === Math.sign(selected.amount_minor)
    && cash.reference.toLowerCase() === selected.reference.toLowerCase()) : [];
  const selectedCash = candidates.filter((cash) => picked.has(cashKey(cash)));
  const total = selectedCash.reduce((sum, cash) => sum + cash.amount_minor, 0);
  const earliest = selected ? [history.at(-1)?.date ?? selected.date, ...selectedCash.map((cash) => cash.date)].sort().at(-1) ?? "" : "";
  const editable = settlement.live && !busy && !settlement.pending;
  const companyName = (id: string) => ds.entities?.find((entity) => entity.id === id)?.name || id || "Main company";
  const choose = (line: Line) => {
    setLineId(line.id);
    setPicked(new Set());
    const first = line.history?.at(-1)?.date ?? line.date;
    setDate(today() < first ? first : today());
  };
  const record = async (event?: CarrierBankEvent, postingDate = date) => {
    setBusy(true); setMessage(undefined);
    try {
      const reply = await (event ? settlement.post(postingDate, null, "", undefined, event) : settlement.retry());
      const result = reply.result as { report: { message: string } };
      setMessage({ text: result.report.message, error: false });
      setPicked(new Set());
      if (event?.kind === "import") setFile(undefined);
      await store.run("purchasing");
    } catch (error) {
      setMessage({ text: String(error).replace(/^Error:\s*/, ""), error: true });
    } finally {
      setBusy(false);
    }
  };
  if (!settlement.live && !bank.lines.length && !periods.length) return null;

  return <Panel title="Carrier bank statements">
    <CarrierBankAccounts ds={ds} currency={currency} periods={periods} live={settlement.live} editable={editable} record={record} />
    {settlement.live && <Edits><details>
      <summary>Import statement CSV</summary>
      <p className="small">Use <code>line,date,reference,amount,currency</code> with ISO dates, unique line IDs, and signed amounts.</p>
      <div className="row wrap" style={{ gap: 8 }}>
        <label>Company <select className="input" value={entity} aria-label="Statement company" onChange={(e) => setEntity(e.target.value)}>
          <option value="">Main company</option>{(ds.entities ?? []).map((item) => <option key={item.id} value={item.id}>{item.name || item.id}</option>)}
        </select></label>
        <label>Bank account <input className="input" maxLength={64} value={account} aria-label="Import bank account"
          onChange={(e) => setAccount(e.target.value)} /></label>
        <label>CSV file <input className="input" type="file" accept=".csv,text/csv" aria-label="Bank statement CSV"
          onChange={async (e) => {
            const control = e.currentTarget;
            const selectedFile = control.files?.[0];
            setFile(undefined); setMessage(undefined);
            if (!selectedFile) return;
            if (selectedFile.size > 256000) {
              setMessage({ text: "Choose a CSV file smaller than 256 KB.", error: true });
              return;
            }
            try {
              const contents = await selectedFile.text();
              if (control.files?.[0] === selectedFile) setFile(contents);
            } catch {
              setMessage({ text: "Could not read the selected CSV file.", error: true });
            }
          }} /></label>
        <button className="btn sm accent" disabled={!editable || !account.trim() || !file}
          onClick={() => file && record({ kind: "import", company: entity, account: account.trim(), csv: file }, today())}>Import statement</button>
      </div>
    </details></Edits>}
    {settlement.pending && <Edits><button className="btn sm accent" disabled={busy} onClick={() => record()}>Retry bank statement operation</button></Edits>}
    {message && <p className="small" role={message.error ? "alert" : "status"}>{message.text}</p>}
    {bank.lines.length ? <div className="table-wrap"><table className="t" aria-label="Imported bank statements">
      <thead><tr><th>Line</th><th>Company</th><th>Account</th><th>Date</th><th>Reference</th><th className="num">Amount</th><th>Match</th></tr></thead>
      <tbody>{bank.lines.map((line) => <tr key={line.id} className={line.id === lineId ? "selected" : ""}>
        <td><button className="btn sm ghost" onClick={() => choose(line)}>{line.statement_line}</button></td>
        <td>{companyName(line.company)}</td><td>{line.account}</td><td>{day(line.date)}</td><td>{line.reference}</td>
        <td className="num">{exactMoney(line.amount_minor / 100, currency)}</td>
        <td>{line.history?.at(-1)?.targets.length ? `Matched (${line.history.at(-1)?.targets.length})` : "Unmatched"}</td>
      </tr>)}</tbody>
    </table></div> : <Empty title="No imported statement lines" />}
    {selected && <section className="stack">
      <h4>{selected.statement_line} · {selected.account}{selectedPeriod && ` · ${selectedPeriod.number}`}</h4>
      {active.length ? <ul>{active.map((item) => <li key={JSON.stringify(item)}>{item.voucher}</li>)}</ul> : <>
        {candidates.length ? <Edits>{candidates.map((cash) => <label className="row" key={cashKey(cash)}>
          <input type="checkbox" checked={picked.has(cashKey(cash))} aria-label={`Select cash voucher ${cash.voucher}`}
            onChange={(e) => setPicked((before) => {
              const next = new Set(before);
              if (e.target.checked) next.add(cashKey(cash));
              else next.delete(cashKey(cash));
              return next;
            })} /> {cash.voucher} · {cash.carrier} · {exactMoney(cash.amount_minor / 100, currency)}
        </label>)}</Edits> : <p className="small">No unmatched carrier vouchers share this bank reference and direction.</p>}
        {!!selectedCash.length && <p className="small">Selected {exactMoney(total / 100, currency)} of {exactMoney(selected.amount_minor / 100, currency)}</p>}
      </>}
      {settlement.live && <Edits><div className="row wrap" style={{ gap: 8 }}>
        <label>Reconciliation date <input className="input" type="date" min={earliest} value={date} onChange={(e) => setDate(e.target.value)} /></label>
        {active.length ? <button className="btn sm" disabled={!editable || !date || date < earliest}
          onClick={() => record({ kind: "release", line: selected.id, version: history.length })}>Release allocation</button>
          : <button className="btn sm accent" disabled={!editable || !date || date < earliest || !selectedCash.length || total !== selected.amount_minor}
            onClick={() => record({ kind: "match", line: selected.id, version: history.length,
              targets: selectedCash.map(({ order, voucher }) => ({ order, voucher })) })}>Match selected vouchers</button>}
      </div></Edits>}
      {!!history.length && <details><summary>Statement history</summary><ol>{history.map((entry, index) =>
        <li key={index}>{day(entry.date)} · {entry.targets.length ? entry.targets.map((item) => item.voucher).join(", ") : "Released"}</li>)}</ol></details>}
    </section>}
  </Panel>;
}
