import { useRef, useState } from "react";
import { api } from "../api/client";
import type { Dataset, SupplierInvoiceView } from "../api/types";
import { Badge, Edits } from "../components/ui";
import { exactMoney, moneyDigits } from "../lib/format";
import { store, useStore } from "../state/store";
import { minorUnits } from "./CarrierBankAccounts";

type Party = { name: string; bic: string; iban: string; local_account: string };
const blankParty: Party = { name: "", bic: "", iban: "", local_account: "" };
const blankRouting = { debtor: blankParty, creditor: blankParty };
const today = () => new Date().toISOString().slice(0, 10);

function AccountDetails({ label, party, setParty }: {
  label: string; party: Party; setParty: (value: Party) => void;
}) {
  const fields = [["name", "Name", 140], ["bic", "Bank BIC", 11], ["iban", "IBAN", 34], ["local_account", "Local account", 34]] as const;
  return <fieldset>
    <legend>{label}</legend>
    <div className="row wrap" style={{ gap: 8 }}>{fields.map(([field, title, maxLength]) =>
      <label key={field}>{title} <input className="input" aria-label={`${label} ${title}`} autoComplete="off" maxLength={maxLength}
        value={party[field]} onChange={(e) => setParty({ ...party, [field]: field === "bic" || field === "iban"
          ? e.target.value.toUpperCase().replace(/\s/g, "") : e.target.value })} /></label>)}
    </div>
  </fieldset>;
}

export function SupplierPaymentInstructions({ ds, invoices, currency }: {
  ds: Dataset; invoices: SupplierInvoiceView[]; currency: string;
}) {
  const company = useStore((s) => s.company);
  const actor = useStore((s) => s.session?.user.email.trim().toLowerCase());
  const [routing, setRouting] = useState(blankRouting);
  const [account, setAccount] = useState("");
  const [on, setOn] = useState(today);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState("");
  const [statusXml, setStatusXml] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean }>();
  const previous = useRef<{ serialized: string; id: string }>();
  const instructions = ds.supplier_payment_instructions ?? [];
  const current = instructions.find((row) => row.id === selected);
  const accounts = (ds.carrier_bank_accounts ?? []).filter((row) => !!row.camt_source);
  const entity = accounts.find((row) => row.id === account)?.company;
  const digits = moneyDigits(currency);
  const granted = company?.live && typeof actor === "string"
    && (ds.finance?.control_roles?.payments ?? []).some((email) => email.trim().toLowerCase() === actor);
  const reserved = new Set(instructions.filter((row) => !row.cancelled_on && !row.statement_line && !row.rejection)
    .flatMap((row) => row.legs.map((leg) => leg.invoice)));
  const choices = invoices.filter((row) => row.open > 0 && row.currency === currency && !reserved.has(row.id)
    && ["to pay", "released"].includes(row.status)
    && (ds.supplier_invoices?.find((invoice) => invoice.id === row.id)?.entity ?? "") === entity);
  const added = choices.filter((row) => amounts[row.id] !== undefined);
  const legs = added.map((row) => ({ invoice: row.id, amount_minor: minorUnits(amounts[row.id], digits) ?? 0 }));
  const verifiedFields = [routing.debtor, routing.creditor].every((party) => party.name.trim()
    && !!party.iban !== !!party.local_account && /^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$/.test(party.bic));
  const pending = current && !current.approved_on && !current.cancelled_on;
  const awaitingBank = current?.approved_on && !current.statement_line && !current.rejection;
  const canDownload = awaitingBank && current.approved_by === actor;

  async function dispatch(action: "propose_supplier_payment" | "approve_supplier_payment" | "cancel_supplier_payment" | "reject_supplier_payment") {
    if (!granted || !company) return;
    const event = action === "propose_supplier_payment" ? { kind: action, account, legs, execute_on: on, routing }
      : action === "approve_supplier_payment" ? { kind: action, instruction: selected, routing }
      : action === "reject_supplier_payment" ? { kind: action, instruction: selected, xml: statusXml }
      : { kind: action, instruction: selected };
    const postingDate = today();
    const serialized = JSON.stringify({ company: company.id, actor, postingDate, event });
    const id = previous.current?.serialized === serialized ? previous.current.id : crypto.randomUUID();
    previous.current = { serialized, id };
    setBusy(true); setMessage(undefined);
    try {
      const reply = await store.postCompanyCommand(company.id, { kind: "carrier_bank", action, id, posting_date: postingDate, parameters: { event } });
      const report = (reply.result as { report: { message: string } }).report;
      setMessage({ text: report.message, error: false });
      previous.current = undefined;
      setStatusXml("");
      if (action === "propose_supplier_payment") {
        setAmounts({});
        setRouting(blankRouting);
      }
    } catch (error) {
      setMessage({ text: String(error).replace(/^Error:\s*/, ""), error: true });
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    if (!company || !current || !canDownload) return;
    setBusy(true); setMessage(undefined);
    try {
      const file = await api.supplierPaymentFile(company.id, current.id, routing);
      const url = URL.createObjectURL(new Blob([file.xml], { type: "application/xml" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setRouting(blankRouting);
      setMessage({ text: `Downloaded ${file.filename}. SHA-256 ${file.sha256}`, error: false });
    } catch (error) {
      setMessage({ text: String(error).replace(/^Error:\s*/, ""), error: true });
    } finally {
      setBusy(false);
    }
  }

  if (!granted && !instructions.length) return null;
  return <details className="pad"><summary>Supplier payment instructions</summary>
    {message && <div className={`banner ${message.error ? "error" : "info"}`} role={message.error ? "alert" : "status"}>{message.text}</div>}
    {instructions.length > 0 && <div className="table-wrap">
      <table className="t" aria-label="Supplier payment instructions">
        <thead><tr><th>Instruction</th><th>Supplier</th><th>Execution date</th><th>Amount</th><th>Status</th></tr></thead>
        <tbody>{instructions.map((row) => <tr key={row.id}>
          <td><button className="btn sm ghost" onClick={() => { setSelected(row.id); setRouting(blankRouting); setStatusXml(""); }}>{row.id}</button></td>
          <td>{row.supplier}</td><td>{row.execute_on}</td>
          <td>{exactMoney(row.legs.reduce((sum, leg) => sum + leg.amount_minor, 0) / 10 ** digits, row.currency)}</td>
          <td><Badge sev={row.cancelled_on ? "info" : row.approved_on ? "ok" : "warning"}>{row.statement_line ? "Booked"
            : row.rejection ? "Rejected by bank" : row.cancelled_on ? "Cancelled" : row.approved_on ? "Approved" : "Proposed"}</Badge></td>
        </tr>)}</tbody>
      </table>
    </div>}
    {granted && <Edits>
      {current && <div>
        <p className="small">{current.legs.map((leg) => `${leg.invoice} · ${exactMoney(leg.amount_minor / 10 ** digits, current.currency)}`).join(", ")}</p>
        <p className="small">Proposed by {current.proposed_by}{current.approved_by ? ` · Approved by ${current.approved_by}` : ""}</p>
        {current.rejection && <p className="small">Bank message {current.rejection.message} · {current.rejection.reason} · {current.rejection.date}</p>}
        <button className="btn ghost" onClick={() => { setSelected(""); setRouting(blankRouting); }}>New instruction</button>
        {pending && <button className="btn ghost" disabled={busy} onClick={() => dispatch("cancel_supplier_payment")}>Cancel proposal</button>}
      </div>}
      {!current && <>
        <div className="row wrap" style={{ gap: 8 }}>
          <label>Paying bank account <select className="input" value={account} onChange={(e) => { setAccount(e.target.value); setAmounts({}); }}>
            <option value="">Choose a camt.053-linked account</option>{accounts.map((row) => <option key={row.id}>{row.id}</option>)}
          </select></label>
          <label>Requested execution date <input className="input" type="date" min={today()} value={on} onChange={(e) => setOn(e.target.value)} /></label>
          <label>Invoice for instruction <select className="input" value="" onChange={(e) => {
            const row = choices.find((invoice) => invoice.id === e.target.value);
            if (row) setAmounts({ ...amounts, [row.id]: row.open.toFixed(digits) });
          }}><option value="">Choose an open invoice</option>{choices.filter((row) => amounts[row.id] === undefined).map((row) =>
            <option key={row.id} value={row.id}>{row.id} · {row.supplier} · {exactMoney(row.open, currency)}</option>)}</select></label>
        </div>
        {added.map((row) => <div className="row wrap" key={row.id} style={{ gap: 8 }}>
          <label>{row.id} transfer amount <input className="input" inputMode="decimal" value={amounts[row.id]} onChange={(e) =>
            setAmounts({ ...amounts, [row.id]: e.target.value })} /></label>
          <button className="btn sm ghost" onClick={() => setAmounts(Object.fromEntries(Object.entries(amounts).filter(([id]) => id !== row.id)))}>
            Remove {row.id}</button>
        </div>)}
      </>}
      {(!current || (pending && current.proposed_by !== actor) || canDownload) && <>
        <p className="small">Use verified bank routing details. An approved file is downloaded for submission through your bank.</p>
        <AccountDetails label="Debtor" party={routing.debtor} setParty={(debtor) => setRouting({ ...routing, debtor })} />
        <AccountDetails label="Creditor" party={routing.creditor} setParty={(creditor) => setRouting({ ...routing, creditor })} />
      </>}
      {!current && <button className="btn accent" disabled={busy || !account || !verifiedFields || on < today() || !legs.length
        || legs.some((leg) => leg.amount_minor <= 0) || new Set(added.map((row) => row.supplier)).size !== 1}
        onClick={() => dispatch("propose_supplier_payment")}>Propose payment instruction</button>}
      {pending && current.proposed_by !== actor && <button className="btn accent" disabled={busy || !verifiedFields}
        onClick={() => dispatch("approve_supplier_payment")}>Approve payment instruction</button>}
      {canDownload && <button className="btn accent" disabled={busy || !verifiedFields} onClick={download}>Download bank payment file</button>}
      {awaitingBank && current.proposed_by !== actor && <details>
        <summary>Import final bank rejection</summary>
        <label>pain.002.001.10 status file <input type="file" accept=".xml,application/xml,text/xml" onChange={async (e) => {
          const file = e.target.files?.[0];
          if (file && file.size > 256_000) {
            setMessage({ text: "Choose a bank status file of at most 256,000 bytes.", error: true });
            setStatusXml("");
          } else {
            try { setStatusXml(file ? await file.text() : ""); } catch { setStatusXml(""); }
          }
        }} /></label>
        <button className="btn accent" disabled={busy || !statusXml} onClick={() => dispatch("reject_supplier_payment")}>Record bank rejection</button>
      </details>}
    </Edits>}
  </details>;
}
