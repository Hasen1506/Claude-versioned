// "Send from here" (Phase Q): the server e-mails a document (the same page Print shows, attached) to the supplier's or
// customer's address, replies going to whoever sent it. Shown only for a company on the server whose server sends mail;
// otherwise the E-mail button beside it opens the planner's own mail program as before.
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuthConfig, MailInput } from "../api/types";
import { useStore } from "../state/store";
import { Edits } from "./ui";

let config: Promise<AuthConfig | null> | null = null;
/** Whether the server sends mail (asked once per page load). */
export function useServerMail(): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    config ??= api.authConfig().catch(() => null);
    let current = true;
    void config.then((c) => { if (current) setOn(!!c?.mail); });
    return () => { current = false; };
  }, []);
  return on;
}

/** "a@x.com; b@y.com" → ["a@x.com", "b@y.com"] */
export const addressList = (text: string) => text.split(/[,;\s]+/).map((a) => a.trim()).filter((a) => a.includes("@"));

export function ServerSend({ kind, docRef, to, subject, text, html, onSent }: {
  kind: MailInput["kind"]; docRef: string; to: string; subject: string; text: string; html: () => string;
  onSent?: () => unknown;
}) {
  const company = useStore((s) => s.company);
  const mail = useServerMail();
  const [open, setOpen] = useState(false);
  const [rcpt, setRcpt] = useState(to);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setRcpt(to), [to]);
  if (!company?.live || !mail || company.role === "viewer") return null;
  if (done) return <span className="small" role="status">Sent to {done}</span>;
  if (!open) return <Edits><button className="btn sm" onClick={() => setOpen(true)}
    title="The server e-mails the document, attached, to this address; replies come to you">Send from here</button></Edits>;
  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const list = addressList(rcpt);
    if (!list.length) return setErr("Enter the address to send it to.");
    setBusy(true);
    setErr(null);
    try {
      const row = await api.sendMail(company.id, { kind, ref: docRef, to: list, cc: [], subject, text, html: html() });
      if (row.status !== "sent") throw new Error(`the mail server did not take it: ${row.error || "no reason given"}`);
      setDone(list.join(", "));
      setOpen(false);
      await onSent?.();
    } catch (x) {
      setErr(x instanceof Error ? x.message : String(x));
    } finally {
      setBusy(false);
    }
  };
  return <form className="row wrap inline-form" style={{ gap: 6 }} onSubmit={send} aria-label={`Send ${docRef}`}>
    <input className="input" value={rcpt} onChange={(e) => setRcpt(e.target.value)} aria-label="Send to" placeholder="orders@supplier.com" style={{ minWidth: 200 }} />
    <button className="btn sm accent" disabled={busy}>{busy ? "Sending…" : "Send"}</button>
    <button type="button" className="btn sm ghost" onClick={() => setOpen(false)}>Cancel</button>
    {err && <span className="banner error small" role="alert" style={{ margin: 0 }}>{err}</span>}
  </form>;
}
