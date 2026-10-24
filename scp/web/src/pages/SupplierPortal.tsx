// Enterprise 7.2: the supplier's page, opened from the link a customer's planner sent (#/portal/<secret>). No sign-in
// and nothing of the customer's but this supplier's sent, open order lines: confirm them as asked or change them
// (quantity, date, two deliveries), send dispatch advice when goods leave, and see what was sent. Every step is
// saved to the customer's company at once. The secret goes in the X-Portal-Token header, never in a URL the server
// sees. Engine: scp/portal, scp/api/portal.py.
import { useCallback, useEffect, useState } from "react";
import type { ConfirmLine, NoticeLineInput, PortalLine, SupplierAnswer, SupplierView } from "../api/types";
import { Badge, Empty, Panel, ThemeSwitch } from "../components/ui";
import { day, exactMoney, qty } from "../lib/format";

const API = import.meta.env.VITE_API_ORIGIN || "";
type Sev = "info" | "warning" | "ok" | "error";
const STATUS: Record<string, Sev> = { "to confirm": "warning", confirmed: "ok", changed: "info", "on the way": "info" };

async function portal<T>(token: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}/api/portal${path}`, {
    method: body === undefined ? "GET" : "POST", credentials: "omit",
    headers: { "X-Portal-Token": token, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    const b = await res.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof b.detail === "string" ? b.detail : `the customer's server answered ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function orderXml(token: string, po: string) {
  const res = await fetch(`${API}/api/portal/order?po=${encodeURIComponent(po)}`, { credentials: "omit", headers: { "X-Portal-Token": token } });
  if (!res.ok) throw new Error(`order ${po} could not be read (${res.status})`);
  const url = URL.createObjectURL(new Blob([await res.text()], { type: "application/xml" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `${po}.xml` });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function SupplierPortal({ token }: { token: string }) {
  const [v, setV] = useState<SupplierView | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    portal<SupplierView>(token, "").then(setV, (e) => setFailed(String(e).replace(/^Error:\s*/, "")));
  }, [token]);
  const step = useCallback(async (path: string, body: unknown) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const a = await portal<SupplierAnswer>(token, path, body);
      setV(a.view);
      setMsg(a.message);
      return true;
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
      return false;
    } finally {
      setBusy(false);
    }
  }, [token]);
  if (failed) {
    return <Shell><Panel><Empty title="This link does not open anything">{failed}</Empty></Panel></Shell>;
  }
  if (!v) return <Shell><p className="faint" aria-live="polite">Opening your orders…</p></Shell>;
  const open = v.lines.filter((l) => l.open > 1e-9);
  return <Shell v={v}>
    {msg && <div className="banner info" role="status"><Badge sev="ok">Sent</Badge><span>{msg}</span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
    {err && <div className="banner error" role="alert"><Badge sev="error">Not sent</Badge><span>{err}</span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setErr(null)}>✕</button></div>}
    <Lines v={v} busy={busy} step={step} token={token} />
    {open.length > 0 && <Dispatch key={v.notices.length} v={v} lines={open} busy={busy} step={step} />}
    <Notices v={v} />
    <Panel title="From your own system">
      <p className="small" style={{ marginTop: 0 }}>Each order is also a UBL 2.1 <b>Order</b> (Peppol BIS Ordering): download it from the order
        lines above. Your system can answer with a UBL <b>OrderResponse</b> and send a <b>DespatchAdvice</b> when goods leave, by
        posting the XML to <code>{location.origin}{API}/api/portal/message</code> with the header <code>X-Portal-Token</code> set to
        this link's secret (the part after <code>#/portal/</code>). Name our order line in <code>OrderLineReference/LineID</code>.</p>
    </Panel>
  </Shell>;
}

function Shell({ v, children }: { v?: SupplierView; children: React.ReactNode }) {
  return <div className="portal">
    <header className="portal-head">
      <div>
        <div className="kicker">Supplier portal</div>
        <h1>{v ? <>Orders from {v.company || "your customer"}</> : "Your orders"}</h1>
        {v && <p className="muted" style={{ margin: 0 }}>For <b>{v.supplier_name}</b>. What you confirm here is what they plan with.
          This link works until {day(v.expires_at.slice(0, 10))}.</p>}
      </div>
      <ThemeSwitch />
    </header>
    <div className="content stack">{children}</div>
  </div>;
}

function Lines({ v, busy, step, token }: { v: SupplierView; busy: boolean; step: (p: string, b: unknown) => Promise<boolean>; token: string }) {
  const [draft, setDraft] = useState<Record<string, { qty?: string; date?: string; qty2?: string; date2?: string }>>({});
  const [ref, setRef] = useState("");
  const set = (id: string, k: "qty" | "date" | "qty2" | "date2", val: string) =>
    setDraft((d) => ({ ...d, [id]: { ...d[id], [k]: val } }));
  const answer = (l: PortalLine): ConfirmLine => {
    const d = draft[l.order] ?? {};
    const q = d.qty ? Number(d.qty) : undefined;
    if (d.qty2 && d.date2) {
      return { order: l.order, parts: [{ date: d.date || l.due_date, qty: q ?? l.ordered - Number(d.qty2) }, { date: d.date2, qty: Number(d.qty2) }] };
    }
    return { order: l.order, ...(q !== undefined ? { qty: q } : {}), ...(d.date ? { date: d.date } : {}) };
  };
  const pos = [...new Set(v.lines.map((l) => l.po))];
  if (!v.lines.length) return <Panel><Empty title="No open orders">Nothing sent to you is waiting.</Empty></Panel>;
  const toConfirm = v.lines.filter((l) => l.status === "to confirm");
  return <Panel flush title="Your open order lines">
    <div className="table-wrap"><table className="t" aria-label="Your order lines">
      <thead><tr><th>Order line</th><th>Goods</th><th className="num">Ordered</th><th className="num">Price</th><th>Wanted by</th>
        <th>Your confirmation</th><th>Status</th><th /></tr></thead>
      <tbody>{v.lines.map((l) => {
        const d = draft[l.order] ?? {};
        return <tr key={l.order}>
          <td><b>{l.order}</b><div className="faint small">to {l.deliver_to_name}</div></td>
          <td>{l.product_name}<div className="faint small">{l.their_part ? `your part ${l.their_part}` : l.product}</div></td>
          <td className="num">{qty(l.ordered)} {l.unit.toLowerCase()}{l.received > 0 && <div className="faint small">{qty(l.received)} received</div>}</td>
          <td className="num">{l.price != null ? exactMoney(l.price, v.currency) : "—"}</td>
          <td>{day(l.due_date)}</td>
          <td className="small">
            {l.confirmations.length > 0 ? l.confirmations.map((c) => <div key={c.date}>{qty(c.qty)} on {day(c.date)}</div>)
              : l.confirmed_date ? <div>{qty(l.confirmed_qty ?? l.ordered)} on {day(l.confirmed_date)}</div> : <span className="faint">not yet</span>}
            {l.on_the_way > 0 && <div className="faint">{qty(l.on_the_way)} on the way</div>}
            <div className="row wrap" style={{ gap: 4, marginTop: 4 }}>
              <input className="input sm" type="number" min={0} step="any" style={{ width: 90 }} aria-label={`Quantity ${l.order}`}
                placeholder={qty(l.confirmed_qty ?? l.ordered)} value={d.qty ?? ""} onChange={(e) => set(l.order, "qty", e.target.value)} />
              <input className="input sm" type="date" style={{ width: 150 }} aria-label={`Date ${l.order}`} value={d.date ?? ""} onChange={(e) => set(l.order, "date", e.target.value)} />
            </div>
            <details><summary className="faint">in two deliveries</summary>
              <div className="row wrap" style={{ gap: 4 }}>
                <input className="input sm" type="number" min={0} step="any" style={{ width: 90 }} aria-label={`Second quantity ${l.order}`}
                  value={d.qty2 ?? ""} onChange={(e) => set(l.order, "qty2", e.target.value)} />
                <input className="input sm" type="date" style={{ width: 150 }} aria-label={`Second date ${l.order}`} value={d.date2 ?? ""} onChange={(e) => set(l.order, "date2", e.target.value)} />
              </div></details>
          </td>
          <td><Badge sev={STATUS[l.status] ?? "info"}>{l.status}</Badge></td>
          <td><button className="btn sm" disabled={busy} aria-label={`Confirm ${l.order}`} onClick={async () => {
            if (await step("/respond", { reference: ref, lines: [answer(l)] })) setDraft((x) => ({ ...x, [l.order]: {} }));
          }}>{d.qty || d.date || d.qty2 ? "Send the change" : "Confirm as asked"}</button></td>
        </tr>;
      })}</tbody>
    </table></div>
    <div className="row wrap" style={{ gap: 8, padding: 12 }}>
      <input className="input" maxLength={64} style={{ maxWidth: 260 }} placeholder="Your confirmation number" aria-label="Your confirmation number" value={ref}
        onChange={(e) => setRef(e.target.value)} />
      {toConfirm.length > 1 && <button className="btn" disabled={busy}
        onClick={() => step("/respond", { reference: ref, lines: toConfirm.map((l) => ({ order: l.order })) })}>
        Confirm all {toConfirm.length} as asked</button>}
      <span className="spacer" />
      {pos.map((po) => <button key={po} className="btn sm ghost" onClick={() => void orderXml(token, po)}
        aria-label={`Order ${po} as UBL`}>{po} as UBL XML</button>)}
    </div>
  </Panel>;
}

function Dispatch({ v, lines, busy, step }: { v: SupplierView; lines: PortalLine[]; busy: boolean; step: (p: string, b: unknown) => Promise<boolean> }) {
  const today = new Date().toISOString().slice(0, 10);
  const [send, setSend] = useState<Record<string, { on: boolean; qty: string; batch: string; exp: string }>>({});
  const [shipped, setShipped] = useState(v.as_of > today ? v.as_of : today);
  const [arrives, setArrives] = useState("");
  const [lr, setLr] = useState("");
  const row = (l: PortalLine) => send[l.order] ?? { on: false, qty: "", batch: "", exp: "" };
  const upd = (id: string, p: Partial<{ on: boolean; qty: string; batch: string; exp: string }>) =>
    setSend((s) => ({ ...s, [id]: { ...(s[id] ?? { on: false, qty: "", batch: "", exp: "" }), ...p } }));
  const picked = lines.filter((l) => row(l).on);
  const left = (l: PortalLine) => Math.max(0, (l.confirmed_qty ?? l.ordered) - l.received - l.on_the_way);
  return <Panel flush title="Send dispatch advice">
    <p className="small muted" style={{ margin: "0 12px" }}>When goods leave you: what is on the lorry, its batches, and when it arrives. The customer plans
      with the arrival date and receives the goods against your advice.</p>
    <div className="table-wrap"><table className="t" aria-label="What is on the lorry">
      <thead><tr><th /><th>Order line</th><th>Goods</th><th className="num">Left to send</th><th>Quantity</th><th>Your batch</th><th>Expires</th></tr></thead>
      <tbody>{lines.map((l) => { const r = row(l); return <tr key={l.order}>
        <td><input type="checkbox" aria-label={`Ship ${l.order}`} checked={r.on} onChange={(e) => upd(l.order, { on: e.target.checked })} /></td>
        <td><b>{l.order}</b></td><td>{l.product_name}</td><td className="num">{qty(left(l))} {l.unit.toLowerCase()}</td>
        <td><input className="input sm" type="number" min={0} step="any" style={{ width: 90 }} aria-label={`Shipped quantity ${l.order}`}
          placeholder={qty(left(l))} value={r.qty} onChange={(e) => upd(l.order, { qty: e.target.value, on: true })} /></td>
        <td><input className="input sm" maxLength={40} style={{ width: 110 }} aria-label={`Batch ${l.order}`} value={r.batch}
          onChange={(e) => upd(l.order, { batch: e.target.value })} /></td>
        <td><input className="input sm" type="date" style={{ width: 150 }} aria-label={`Expires ${l.order}`} value={r.exp} onChange={(e) => upd(l.order, { exp: e.target.value })} /></td>
      </tr>; })}</tbody>
    </table></div>
    <div className="row wrap" style={{ gap: 8, padding: 12, alignItems: "end" }}>
      <label className="small">Shipped on<br /><input className="input" type="date" value={shipped} onChange={(e) => setShipped(e.target.value)} /></label>
      <label className="small">Arrives on<br /><input className="input" type="date" value={arrives} onChange={(e) => setArrives(e.target.value)}
        placeholder="by the usual transit" /></label>
      <label className="small">Lorry receipt or dispatch note<br /><input className="input" maxLength={64} value={lr} onChange={(e) => setLr(e.target.value)} /></label>
      <button className="btn" disabled={busy || !picked.length} onClick={() => step("/dispatch", {
        shipped_on: shipped || null, arrives_on: arrives || null, reference: lr,
        lines: picked.map((l): NoticeLineInput => { const r = row(l); return { order: l.order, qty: r.qty ? Number(r.qty) : null, batch: r.batch || null, expires_on: r.exp || null }; }),
      })}>Send dispatch advice</button>
      <span className="faint small">No arrival date: the usual transit from you.</span>
    </div>
  </Panel>;
}

function Notices({ v }: { v: SupplierView }) {
  if (!v.notices.length) return null;
  return <Panel flush title="Your dispatch advice">
    <div className="table-wrap"><table className="t" aria-label="Your dispatch advice">
      <thead><tr><th>Advice</th><th>Shipped</th><th>Arrives</th><th>Goods</th><th>Status</th></tr></thead>
      <tbody>{v.notices.map((n) => <tr key={n.id}>
        <td><b>{n.id}</b>{n.reference && <div className="faint small">{n.reference}</div>}</td><td>{day(n.shipped_on)}</td><td>{day(n.arrives_on)}</td>
        <td className="small">{n.lines.map((x) => <div key={x.order}>{qty(x.qty)} on {x.order}{x.batch ? `, batch ${x.batch}` : ""}</div>)}</td>
        <td><Badge sev={n.status === "received" ? "ok" : n.status === "cancelled" ? "error" : "info"}>{n.status}</Badge></td>
      </tr>)}</tbody>
    </table></div>
  </Panel>;
}
