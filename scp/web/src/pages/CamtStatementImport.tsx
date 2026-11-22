import { useState } from "react";
import type { Dataset } from "../api/types";
import { Edits } from "../components/ui";
import type { CarrierBankEvent } from "../state/settlement";

export function CamtStatementImport({ ds, editable, pending, xml, setXml, record }: {
  ds: Dataset; editable: boolean; pending: boolean; xml?: string; setXml: (value?: string) => void;
  record: (event: CarrierBankEvent, date: string) => Promise<void>;
}) {
  const accounts = ds.carrier_bank_accounts ?? [];
  const [account, setAccount] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const selected = accounts.find((entry) => entry.id === account);
  if (!accounts.length) return null;

  return <Edits><details open={pending || open} onToggle={(e) => setOpen(e.currentTarget.open)}>
    <summary>Import original camt.053 statement</summary>
    <p className="small">Keep the original XML in your bank archive. This worklist records its checksum and the booked statement details.</p>
    {pending && <p className="small">Choose the same file to retry the unconfirmed bank operation.</p>}
    <div className="row wrap" style={{ gap: 8 }}>
      <label>Account <select className="input" value={account} disabled={pending} aria-label="Original statement account"
        onChange={(e) => setAccount(e.target.value)}>
        <option value="">Choose</option>{accounts.map((entry) => <option key={entry.id} value={entry.id}>
          {entry.id} · {entry.company || "Main company"}</option>)}
      </select></label>
      <label>Original XML <input className="input" type="file" accept=".xml,application/xml,text/xml" aria-label="Original camt.053 file"
        onChange={async (e) => {
          const control = e.currentTarget;
          const file = control.files?.[0];
          setXml(undefined); setError("");
          if (!file) return;
          if (file.size > 256000) {
            setError("Choose an original camt.053 file of at most 256 KB.");
            return;
          }
          try {
            const contents = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
            if (control.files?.[0] === file) setXml(contents);
          } catch {
            if (control.files?.[0] === file) setError("Choose a valid UTF-8 XML file.");
          }
        }} /></label>
      <button className="btn sm accent" disabled={!editable || !selected || !xml}
        onClick={() => selected && xml && record({
          kind: selected.camt_source ? "import_camt" : "link_camt_source", account: selected.id, xml,
        }, new Date().toISOString().slice(0, 10))}>{selected?.camt_source ? "Import original statement" : "Link bank source"}</button>
    </div>
    {selected && !selected.camt_source && <p className="small">Confirm the bank account on the original file before linking it.</p>}
    {error && <p className="small" role="alert">{error}</p>}
  </details></Edits>;
}
