import { useState } from "react";
import type { Dataset, PayablesView } from "../api/types";
import { Edits, Empty, Panel } from "../components/ui";
import { day, exactMoney } from "../lib/format";
import { useSettlement, type CarrierBankEvent } from "../state/settlement";
import { store } from "../state/store";
import { CarrierBankAccounts, minorUnits } from "./CarrierBankAccounts";
import { CamtStatementImport } from "./CamtStatementImport";

type Worklist = PayablesView["carrier_bank"];
type Line = Worklist["lines"][number];
type Cash = Worklist["unmatched_cash"][number];
type Original = Worklist["reversible_cash"][number];
const cashKey = (item: Cash) => JSON.stringify([item.order, item.voucher]);
const today = () => new Date().toISOString().slice(0, 10);

function hasSourceReference(line: Line, cash: Original) {
  return cash.reference.toLowerCase() === line.reference.toLowerCase()
    || (line.trace_ids?.length === 1 && cash.source_trace_ids?.includes(line.trace_ids[0]));
}

function ReturnAllocation({ line, sources, currency, editable, submit }: {
  line: Line; sources: Original[]; currency: string; editable: boolean;
  submit: (event: Extract<CarrierBankEvent, { kind: "allocate_return" }>) => Promise<void>;
}) {
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [advice, setAdvice] = useState("");
  const chosen = sources.filter((cash) => cashKey(cash) in amounts);
  const legs = chosen.map((cash) => ({ original: { order: cash.order, voucher: cash.voucher },
    amount_minor: minorUnits(amounts[cashKey(cash)]) ?? 0 }));
  const directions = new Set(chosen.map((cash) => Math.sign(cash.amount_minor)));
  const fee = line.included_fee_minor ?? 0;
  const principal = legs.reduce((sum, leg, index) => sum - Math.sign(chosen[index].amount_minor) * leg.amount_minor, 0);
  const net = principal - fee;
  const needsAdvice = chosen.some((cash) => !hasSourceReference(line, cash));
  const valid = legs.length > 0 && legs.every((leg, index) => leg.amount_minor > 0 && leg.amount_minor <= chosen[index].remaining_minor)
    && directions.size === 1 && Number.isSafeInteger(net) && net === line.amount_minor && (!needsAdvice || advice.trim());

  if (!sources.length || line.unresolved_charges || !line.return_source_checked) return null;
  return <details>
    <summary>Allocate partial, grouped or changed-reference return</summary>
    <div className="stack">
      <label>Add original cash voucher <select className="input" value="" disabled={!editable || chosen.length >= 100}
        onChange={(event) => {
          const key = event.target.value;
          if (key) setAmounts((before) => ({ ...before, [key]: "" }));
        }}>
        <option value="">Choose a payment or refund</option>
        {sources.filter((cash) => !(cashKey(cash) in amounts)).map((cash) => <option key={cashKey(cash)} value={cashKey(cash)}>
          {cash.voucher} · {cash.carrier} · {cash.reference} · {exactMoney(cash.remaining_minor / 100, currency)} remaining
        </option>)}
      </select></label>
      {chosen.map((cash) => <div className="row wrap" key={cashKey(cash)} style={{ gap: 8 }}>
        <label>Principal for {cash.voucher} <input className="input" inputMode="decimal" value={amounts[cashKey(cash)]}
          disabled={!editable} onChange={(event) => setAmounts((before) => ({ ...before, [cashKey(cash)]: event.target.value }))} /></label>
        <span className="small">{exactMoney(cash.remaining_minor / 100, currency)} remaining</span>
        <button className="btn sm ghost" disabled={!editable} aria-label={`Remove ${cash.voucher}`} onClick={() => setAmounts((before) => {
          const next = { ...before };
          delete next[cashKey(cash)];
          return next;
        })}>Remove</button>
      </div>)}
      {needsAdvice && <label>Reviewed bank advice identifier <input className="input" maxLength={120} value={advice} disabled={!editable}
        onChange={(event) => setAdvice(event.target.value)} /></label>}
      <p className="small">Principal {exactMoney(principal / 100, currency)} · Included fees {exactMoney(fee / 100, currency)}
        · Net {exactMoney(net / 100, currency)} of {exactMoney(line.amount_minor / 100, currency)}</p>
      <button className="btn sm accent" disabled={!editable || !valid} onClick={() => submit({
        kind: "allocate_return", line: line.id, legs, ...(needsAdvice ? { advice: advice.trim() } : {}),
      })}>Post return allocation</button>
    </div>
  </details>;
}

export function CarrierBankWorklist({ bank, ds, currency }: { bank: Worklist; ds: Dataset; currency: string }) {
  const settlement = useSettlement("carrier_bank", "worklist");
  const [entity, setEntity] = useState("");
  const [account, setAccount] = useState("");
  const [file, setFile] = useState<string>();
  const [nativeFiles, setNativeFiles] = useState<string[]>();
  const [lineId, setLineId] = useState("");
  const [date, setDate] = useState(today);
  const [lateReason, setLateReason] = useState("");
  const [picked, setPicked] = useState<Set<string>>(() => new Set());
  const [originalKey, setOriginalKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean }>();
  const selected = bank.lines.find((line) => line.id === lineId);
  const closed = ds.finance?.closed_through ?? "";
  const late = !!selected?.reversal && !!closed && selected.date <= closed;
  const reversalDate = late ? date : selected?.date ?? "";
  const timing = selected && bank.timing?.find((item) => item.statement_line === selected.id);
  const periods = bank.periods ?? [];
  const selectedPeriod = selected && periods.find(({ period }) => period.line_ids.includes(selected.id))?.period;
  const history = selected?.history ?? [];
  const active = history.at(-1)?.targets ?? [];
  const candidates = selected && !selected.reversal ? bank.unmatched_cash.filter((cash) => cash.company === selected.company
    && (cash.bank_account ?? null) === (selectedPeriod?.account ?? null)
    && (!selectedPeriod || (cash.date >= selectedPeriod.starts_on && cash.date <= selectedPeriod.ends_on))
    && Math.sign(cash.amount_minor) === Math.sign(selected.amount_minor)
    && cash.reference.toLowerCase() === selected.reference.toLowerCase()) : [];
  const returnSources = selected?.reversal ? (bank.reversible_cash ?? []).filter((cash) => cash.company === selected.company
    && cash.bank_account === selected.account && (cash.original_bank_date ?? cash.date) <= selected.date
    && cash.eligible_from <= reversalDate) : [];
  const originals = selected?.return_source_checked && !selected.included_fee_minor && !selected.unresolved_charges ? returnSources.filter((cash) =>
    (cash.full_return_eligible ?? true)
    && cash.amount_minor === -selected.amount_minor && cash.reference.toLowerCase() === selected.reference.toLowerCase()) : [];
  const original = originals.find((cash) => cashKey(cash) === originalKey);
  const locked = !!selected && (bank.locked_lines ?? []).includes(selected.id);
  const selectedCash = candidates.filter((cash) => picked.has(cashKey(cash)));
  const total = selectedCash.reduce((sum, cash) => sum + cash.amount_minor, 0);
  const earliest = selected ? [history.at(-1)?.date ?? selected.date, ...selectedCash.map((cash) => cash.date)].sort().at(-1) ?? "" : "";
  const editable = settlement.live && !busy && !settlement.pending;
  const companyName = (id: string) => ds.entities?.find((entity) => entity.id === id)?.name || id || "Main company";
  const choose = (line: Line) => {
    setLineId(line.id);
    setPicked(new Set());
    setOriginalKey("");
    setLateReason("");
    const first = line.history?.at(-1)?.date ?? line.date;
    setDate(today() < first ? first : today());
  };
  const record = async (event?: CarrierBankEvent, postingDate = date) => {
    setBusy(true); setMessage(undefined);
    try {
      const reply = await (event ? settlement.post(postingDate, null, "", undefined, event) : settlement.retry(nativeFiles));
      const result = reply.result as { report: { message: string } };
      setMessage({ text: result.report.message, error: false });
      setPicked(new Set());
      setOriginalKey("");
      setLateReason("");
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
    {settlement.live && <CamtStatementImport ds={ds} editable={editable} pending={settlement.pendingBankFile}
      originals={nativeFiles} setOriginals={setNativeFiles} record={record} />}
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
    {settlement.pending && <Edits><button className="btn sm accent" disabled={busy || (settlement.pendingBankFile && !nativeFiles?.length)}
      onClick={() => record()}>Retry bank statement operation</button></Edits>}
    {message && <p className="small" role={message.error ? "alert" : "status"}>{message.text}</p>}
    {bank.lines.length ? <div className="table-wrap"><table className="t" aria-label="Imported bank statements">
      <thead><tr><th>Line</th><th>Company</th><th>Account</th><th>Date</th><th>Reference</th><th className="num">Amount</th><th>Match</th></tr></thead>
      <tbody>{bank.lines.map((line) => <tr key={line.id} className={line.id === lineId ? "selected" : ""}>
        <td><button className="btn sm ghost" onClick={() => choose(line)}>{line.statement_line}</button></td>
        <td>{companyName(line.company)}</td><td>{line.account}</td><td>{day(line.date)}</td><td>{line.reference}</td>
        <td className="num">{exactMoney(line.amount_minor / 100, currency)}</td>
        <td>{line.reversal ? (line.history?.length ? "Reversal posted" : "Bank reversal to review") :
          (line.history?.at(-1)?.targets.length ? `Matched (${line.history.at(-1)?.targets.length})` : "Unmatched")}</td>
      </tr>)}</tbody>
    </table></div> : <Empty title="No imported statement lines" />}
    {selected && <section className="stack">
      <h4>{selected.statement_line} · {selected.account}{selectedPeriod && ` · ${selectedPeriod.number}`}</h4>
      {timing && <p className="small">Bank booked {day(timing.bank_date)} · Posted {day(timing.posting_date)} · {timing.reason}</p>}
      {active.length ? <><ul>{active.map((item) => <li key={JSON.stringify(item)}>{item.voucher}</li>)}</ul>
        {!!selected.included_fee_minor && <p className="small">Bank fee {exactMoney(selected.included_fee_minor / 100, currency)} · {selected.id}/F</p>}</> :
        selected.reversal ? <>
          <p className="small">{late
            ? `The bank booked this return on ${day(selected.date)} in a closed period. Enter an open posting date and the reason.`
            : `The reversal posts on ${day(selected.date)} and reopens the carrier balance.`} Verify the original payment or refund against the bank statement.</p>
          {late && <Edits><div className="row wrap" style={{ gap: 8 }}>
            <label>Accounting posting date <input className="input" type="date" min={closed} value={date}
              onChange={(e) => setDate(e.target.value)} /></label>
            <label>Reason for posting after close <input className="input" value={lateReason} maxLength={200}
              onChange={(e) => setLateReason(e.target.value)} /></label>
          </div></Edits>}
          {originals.length ? <Edits><label>Original cash voucher <select className="input" value={originalKey} disabled={!editable}
            onChange={(e) => setOriginalKey(e.target.value)}>
            <option value="">Choose the original payment or refund</option>
            {originals.map((cash) => <option key={cashKey(cash)} value={cashKey(cash)}>
              {cash.voucher} · {cash.carrier} · {cash.original_line} · {exactMoney(cash.amount_minor / 100, currency)}
            </option>)}
          </select></label></Edits> : <p className="small">{!selected.return_source_checked
            ? "Reattach the exact original statement to verify this return's fees and references before posting."
            : selected.unresolved_charges
            ? "The statement contains ambiguous bank charge evidence. Review the original statement before posting."
            : "No individually matched carrier voucher has the same account, reference and opposite amount."}</p>}
          {settlement.live && <Edits><ReturnAllocation key={selected.id} line={selected} sources={returnSources} currency={currency}
            editable={editable && (!late || (date > closed && !!lateReason.trim()))}
            submit={(event) => record({ ...event, ...(late ? { late_reason: lateReason.trim() } : {}) }, reversalDate)} /></Edits>}
        </> : <>
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
      {locked && <p className="small">This allocation is retained with the posted bank reversal.</p>}
      {settlement.live && !locked && <Edits><div className="row wrap" style={{ gap: 8 }}>
        {selected.reversal ? <button className="btn sm accent" disabled={!editable || !original || (late && (date <= closed || !lateReason.trim()))}
          onClick={() => original && record({ kind: "reverse_cash", line: selected.id,
            original: { order: original.order, voucher: original.voucher }, ...(late ? { late_reason: lateReason.trim() } : {}) },
            reversalDate)}>Record bank reversal</button> : <>
        <label>Reconciliation date <input className="input" type="date" min={earliest} value={date} onChange={(e) => setDate(e.target.value)} /></label>
        {active.length ? <button className="btn sm" disabled={!editable || !date || date < earliest}
          onClick={() => record({ kind: "release", line: selected.id, version: history.length })}>Release allocation</button>
          : <button className="btn sm accent" disabled={!editable || !date || date < earliest || !selectedCash.length || total !== selected.amount_minor}
            onClick={() => record({ kind: "match", line: selected.id, version: history.length,
              targets: selectedCash.map(({ order, voucher }) => ({ order, voucher })) })}>Match selected vouchers</button>}
        </>}
      </div></Edits>}
      {!!history.length && <details><summary>Statement history</summary><ol>{history.map((entry, index) =>
        <li key={index}>{day(entry.date)} · {entry.targets.length ? entry.targets.map((item) => item.voucher).join(", ") : "Released"}
          {entry.allocation?.advice && ` · Bank advice ${entry.allocation.advice}`}</li>)}</ol></details>}
    </section>}
  </Panel>;
}
