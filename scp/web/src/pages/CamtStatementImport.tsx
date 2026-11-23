import { useState } from "react";
import type { Dataset } from "../api/types";
import { Edits } from "../components/ui";
import type { CarrierBankEvent } from "../state/settlement";

export function CamtStatementImport({ ds, editable, pending, originals, setOriginals, record }: {
  ds: Dataset; editable: boolean; pending: boolean; originals?: string[]; setOriginals: (value?: string[]) => void;
  record: (event: CarrierBankEvent, date: string) => Promise<void>;
}) {
  const accounts = ds.carrier_bank_accounts ?? [];
  const [account, setAccount] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const selected = accounts.find((entry) => entry.id === account);
  if (!accounts.length) return null;

  function submit() {
    if (!selected || !originals?.length) return;
    const date = new Date().toISOString().slice(0, 10);
    const linked = selected.camt_source;
    return record(originals.length === 1
      ? { kind: linked ? "import_camt" : "link_camt_source", account: selected.id, xml: originals[0] }
      : { kind: linked ? "import_camt_pages" : "link_camt_pages", account: selected.id, files: originals }, date);
  }

  return <Edits><details open={pending || open} onToggle={(e) => setOpen(e.currentTarget.open)}>
    <summary>Import original camt.053 statement</summary>
    <p className="small">Choose all original XML files for one statement. Keep them in your bank archive.</p>
    {pending && <p className="small">Choose the same original files to retry the unconfirmed bank operation.</p>}
    <div className="row wrap" style={{ gap: 8 }}>
      <label>Account <select className="input" value={account} disabled={pending} aria-label="Original statement account"
        onChange={(e) => setAccount(e.target.value)}>
        <option value="">Choose</option>{accounts.map((entry) => <option key={entry.id} value={entry.id}>
          {entry.id} · {entry.company || "Main company"}</option>)}
      </select></label>
      <label>Original XML <input className="input" type="file" multiple accept=".xml,application/xml,text/xml" aria-label="Original camt.053 file"
        onChange={async (e) => {
          const control = e.currentTarget;
          const selection = control.files;
          const files = Array.from(selection ?? []);
          setOriginals(undefined); setError("");
          if (!files.length) return;
          if (files.length > 20 || files.reduce((total, file) => total + file.size, 0) > 256000) {
            setError("Choose at most 20 original camt.053 files totaling 256 KB or less.");
            return;
          }
          try {
            const contents = await Promise.all(files.map(async (file) =>
              new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer())));
            if (control.files === selection) setOriginals(contents);
          } catch {
            if (control.files === selection) setError("Choose valid UTF-8 XML files.");
          }
        }} /></label>
      <button className="btn sm accent" disabled={!editable || !selected || !originals?.length}
        onClick={submit}>{selected?.camt_source ? "Import original statement" : "Link bank source"}</button>
    </div>
    {selected && !selected.camt_source && <p className="small">Confirm the bank account on the original file before linking it.</p>}
    {error && <p className="small" role="alert">{error}</p>}
  </details></Edits>;
}
