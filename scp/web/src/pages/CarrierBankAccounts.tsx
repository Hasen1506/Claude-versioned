import { useState } from "react";
import type { Dataset, PayablesView } from "../api/types";
import { Badge, Edits } from "../components/ui";
import { day, exactMoney } from "../lib/format";
import type { CarrierBankEvent } from "../state/settlement";

const today = () => new Date().toISOString().slice(0, 10);
type Accounts = NonNullable<Dataset["carrier_bank_accounts"]>;
type Periods = PayablesView["carrier_bank"]["periods"];

export function carrierPostingAccounts(ds: Dataset, company: string, date: string): Accounts {
  return (ds.carrier_bank_accounts ?? []).filter((account) => account.company === company && account.starts_on <= date);
}

function minorUnits(input: string) {
  const amount = input.trim();
  if (!/^[+-]?\d{1,13}(\.\d{1,2})?$/.test(amount)) return undefined;
  const [whole, fraction = ""] = amount.replace(/^[+-]/, "").split(".");
  const absolute = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return amount.startsWith("-") ? -absolute : absolute;
}

export function CarrierBankAccounts({ ds, currency, periods, live, editable, record }: {
  ds: Dataset; currency: string; periods: Periods; live: boolean; editable: boolean;
  record: (event: CarrierBankEvent, date: string) => Promise<void>;
}) {
  const accounts = ds.carrier_bank_accounts ?? [];
  const [opening, setOpening] = useState({ id: "", company: "", start: today(), balance: "" });
  const [period, setPeriod] = useState({ account: "", number: "", start: "", end: "", opening: "", closing: "", count: "" });
  const [file, setFile] = useState<string>();
  const [fileError, setFileError] = useState("");
  const openingMinor = minorUnits(opening.balance);
  const from = minorUnits(period.opening);
  const to = minorUnits(period.closing);
  const count = /^\d{1,3}$/.test(period.count) ? Number(period.count) : undefined;
  const validOpening = /^[A-Z0-9][A-Z0-9_-]{0,31}$/.test(opening.id) && opening.start && openingMinor !== undefined;
  const validStatement = period.account && period.number.trim() && period.start && period.end >= period.start
    && from !== undefined && to !== undefined && count !== undefined && count <= 500 && file;

  return <>
    {live && <Edits>
      <details><summary>Register carrier bank account</summary>
        <p className="small">Use the approved opening balance immediately before the first statement date.</p>
        <div className="row wrap" style={{ gap: 8 }}>
          <label>Company <select className="input" value={opening.company} aria-label="Bank account company"
            onChange={(e) => setOpening({ ...opening, company: e.target.value })}>
            <option value="">Main company</option>{(ds.entities ?? []).map((e) => <option key={e.id} value={e.id}>{e.name || e.id}</option>)}
          </select></label>
          <label>Account ID <input className="input" maxLength={32} value={opening.id} aria-label="Registered bank account ID"
            onChange={(e) => setOpening({ ...opening, id: e.target.value.toUpperCase() })} /></label>
          <label>First date <input className="input" type="date" value={opening.start} aria-label="Bank account first date"
            onChange={(e) => setOpening({ ...opening, start: e.target.value })} /></label>
          <label>Opening balance ({currency}) <input className="input" inputMode="decimal" value={opening.balance}
            aria-label="Bank account opening balance" onChange={(e) => setOpening({ ...opening, balance: e.target.value })} /></label>
          <button className="btn sm accent" disabled={!editable || !validOpening} onClick={() => openingMinor !== undefined &&
            record({ kind: "register_account", id: opening.id, company: opening.company, starts_on: opening.start,
              opening_minor: openingMinor }, today())}>Register account</button>
        </div>
      </details>
      {!!accounts.length && <details><summary>Import account statement period</summary>
        <p className="small">Take the dates, balances and row count from the source statement. Upload its normalized
          <code> line,date,reference,amount,currency</code> CSV.</p>
        <div className="row wrap" style={{ gap: 8 }}>
          <label>Account <select className="input" value={period.account} aria-label="Statement period account"
            onChange={(e) => setPeriod({ ...period, account: e.target.value })}>
            <option value="">Choose</option>{accounts.filter((account) => !account.camt_source)
              .map((account) => <option key={account.id} value={account.id}>{account.id} · {account.company || "Main company"}</option>)}
          </select></label>
          <label>Statement number <input className="input" maxLength={64} value={period.number}
            onChange={(e) => setPeriod({ ...period, number: e.target.value })} /></label>
          <label>From <input className="input" type="date" value={period.start} aria-label="Statement period start"
            onChange={(e) => setPeriod({ ...period, start: e.target.value })} /></label>
          <label>Through <input className="input" type="date" value={period.end} min={period.start} aria-label="Statement period end"
            onChange={(e) => setPeriod({ ...period, end: e.target.value })} /></label>
          <label>Opening balance <input className="input" inputMode="decimal" value={period.opening}
            aria-label="Statement period opening balance" onChange={(e) => setPeriod({ ...period, opening: e.target.value })} /></label>
          <label>Closing balance <input className="input" inputMode="decimal" value={period.closing}
            aria-label="Statement period closing balance" onChange={(e) => setPeriod({ ...period, closing: e.target.value })} /></label>
          <label>Source rows <input className="input" inputMode="numeric" value={period.count}
            onChange={(e) => setPeriod({ ...period, count: e.target.value })} /></label>
          <label>CSV file <input className="input" type="file" accept=".csv,text/csv" aria-label="Statement period CSV"
            onChange={async (e) => {
              const control = e.currentTarget;
              const selected = control.files?.[0];
              setFile(undefined); setFileError("");
              if (!selected) return;
              if (selected.size > 256000) {
                setFileError("Choose a CSV of at most 256 KB.");
                return;
              }
              try {
                const contents = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await selected.arrayBuffer());
                if (control.files?.[0] === selected) setFile(contents);
              } catch {
                if (control.files?.[0] === selected) setFileError("Choose a valid UTF-8 CSV.");
              }
            }} /></label>
          <button className="btn sm accent" disabled={!editable || !validStatement}
            onClick={() => file && from !== undefined && to !== undefined && count !== undefined && record({
              kind: "import_period", account: period.account, number: period.number.trim(), starts_on: period.start,
              ends_on: period.end, opening_minor: from, closing_minor: to, line_count: count, csv: file,
            }, today())}>Import period</button>
        </div>
        {fileError && <p className="small" role="alert">{fileError}</p>}
      </details>}
    </Edits>}
    {!!periods.length && <div className="table-wrap"><table className="t" aria-label="Carrier bank account reconciliation">
      <thead><tr><th>Statement</th><th>Account</th><th>Dates</th><th className="num">Statement opening</th>
        <th className="num">Ledger opening</th><th className="num">Statement closing</th><th className="num">Ledger closing</th><th>Reconciliation</th></tr></thead>
      <tbody>{periods.map((row) => <tr key={row.period.id}>
        <td>{row.period.number}{row.period.camt_source && <details className="small">
          <summary>Original camt.053</summary>
          {row.period.camt_source.originals?.length
            ? <ul>{row.period.camt_source.originals.map((file) => <li key={file.file_sha256}>
              <div>{file.message_id} · {file.pages.length === 1 ? "Page" : "Pages"} {file.pages.join(", ")}</div>
              <code>{file.file_sha256}</code>
            </li>)}</ul>
            : <><div>{row.period.camt_source.message_id}</div><code>{row.period.file_sha256}</code></>}
        </details>}</td><td>{row.period.account}</td><td>{day(row.period.starts_on)} – {day(row.period.ends_on)}</td>
        {[row.period.opening_minor, row.ledger_opening_minor, row.period.closing_minor, row.ledger_closing_minor]
          .map((value, i) => <td className="num" key={i}>{exactMoney(value / 100, currency)}</td>)}
        <td><Badge sev={row.reconciled ? "ok" : "warning"}>{row.reconciled ? (row.has_timing ? "Reconciled with timing" : "Reconciled") : "Review differences"}</Badge>
          {row.has_timing && <details className="small">
            <summary>Timing adjustments</summary>
            <div>Opening {exactMoney(row.opening_timing_minor / 100, currency)}</div>
            <div>Closing {exactMoney(row.closing_timing_minor / 100, currency)}</div>
          </details>}
          {(row.unmatched_lines.length > 0 || row.unmatched_vouchers.length > 0) && <details className="small">
            <summary>{row.unmatched_lines.length} statement lines · {row.unmatched_vouchers.length} cash vouchers</summary>
            {!!row.unmatched_lines.length && <div>Statement lines · {row.unmatched_lines.join(", ")}</div>}
            {!!row.unmatched_vouchers.length && <div>Cash vouchers · {row.unmatched_vouchers.join(", ")}</div>}
          </details>}</td>
      </tr>)}</tbody>
    </table></div>}
  </>;
}
