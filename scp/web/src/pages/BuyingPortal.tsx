// Enterprise 7.2 on Buying: the supplier portal from our side. A link per supplier (on a company kept on the server),
// what that supplier sees on it, the shipping notices they sent with goods received against them in one step, and
// their UBL messages read in by hand (an OrderResponse or a DespatchAdvice that came by mail). Engine: scp/portal.
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, PortalAction, PortalActionInput, PortalLink, PortalView } from "../api/types";
import { Badge, Empty, Panel } from "../components/ui";
import { day, exactMoney, qty } from "../lib/format";
import { useLatest } from "../lib/latest";
import { Msg } from "../lib/names";
import { store, useStore } from "../state/store";

type Sev = "info" | "warning" | "ok" | "error";
const STATUS: Record<string, Sev> = { "to confirm": "warning", confirmed: "ok", changed: "info", "on the way": "info" };
const NOTICE: Record<string, Sev> = { "on the way": "info", received: "ok", cancelled: "error" };

const errText = (e: unknown) => String(e).replace(/^Error:\s*/, "");

function useStep() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async (action: PortalAction, extra: Partial<PortalActionInput> = {}) => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const before = store.get().dataset!;
      const out = await api.portalAct(before, action, extra);
      store.replace(out.dataset, before);
      setMsg(out.message);
      void Promise.all([store.run("purchasing"), store.run("plan")]);
      return true;
    } catch (e) {
      setErr(errText(e));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const banners = <>
    {msg && <div className="banner info" role="status"><Badge sev="ok">Done</Badge><span><Msg text={msg} /></span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setMsg(null)}>✕</button></div>}
    {err && <div className="banner error" role="alert"><Badge sev="error">Not done</Badge><span>{err}</span><span className="spacer" />
      <button className="btn sm ghost" aria-label="Dismiss" onClick={() => setErr(null)}>✕</button></div>}
  </>;
  return { busy, run, banners };
}
type Step = ReturnType<typeof useStep>;

export function PortalTab({ ds }: { ds: Dataset }) {
  const sent = useMemo(() => {
    const by = new Map<string, number>();
    for (const po of ds.purchase_orders ?? []) if (po.sent_on) by.set(po.supplier, (by.get(po.supplier) ?? 0) + 1);
    return by;
  }, [ds.purchase_orders]);
  const suppliers = (ds.locations ?? []).filter((l) => l.type === "supplier")
    .sort((a, b) => (sent.get(b.id) ?? 0) - (sent.get(a.id) ?? 0) || (a.name || a.id).localeCompare(b.name || b.id));
  const [supplier, setSupplier] = useState(suppliers[0]?.id ?? "");
  const { value: v, error } = useLatest<PortalView>(supplier ? () => api.portalView(ds, supplier) : null, [ds, supplier]);
  const step = useStep();
  if (!suppliers.length) return <Panel><Empty title="No suppliers">Add suppliers to the network first.</Empty></Panel>;
  return <div className="stack">
    <Panel>
      <p className="small muted" style={{ marginTop: 0 }}>A supplier with a link sees the order lines sent to them that are still open, and nothing
        else of ours. They confirm each line as asked or change it (less, later, or in two deliveries), and send dispatch advice when goods
        leave: the plan counts on what they confirm and on the arrival they advise, and the goods are received here against their advice.
        Their own system can do the same with UBL messages.</p>
      <label className="small">Supplier<br />
        <select className="select" value={supplier} onChange={(e) => setSupplier(e.target.value)} aria-label="Supplier">
          {suppliers.map((l) => <option key={l.id} value={l.id}>{l.name || l.id}{sent.get(l.id) ? ` · ${sent.get(l.id)} sent` : ""}</option>)}
        </select></label>
    </Panel>
    {step.banners}
    {error && <div className="banner error" role="alert"><Badge sev="error">Could not read what they see</Badge>{error}</div>}
    <Links supplier={supplier} name={suppliers.find((l) => l.id === supplier)?.name || supplier} />
    {v && <TheirView v={v} ds={ds} />}
    {v && <Notices v={v} ds={ds} step={step} />}
    <Message step={step} />
  </div>;
}

function Links({ supplier, name }: { supplier: string; name: string }) {
  const company = useStore((s) => s.company);
  const live = !!company?.live;
  const [made, setMade] = useState<PortalLink | null>(null);
  const [days, setDays] = useState(90);
  const [failed, setFailed] = useState<string | null>(null);
  const { value: list, show, error } = useLatest<PortalLink[]>(live ? () => api.portalLinks(company!.id) : null, [company?.id, live]);
  if (!live) {
    return <Panel title="Link for the supplier"><p className="small muted" style={{ margin: 0 }}>A link works on a company kept on the server, so what
      the supplier sends reaches it: sign in and keep this company there (Sign in and companies) to make one.</p></Panel>;
  }
  const mine = (list ?? []).filter((l) => l.supplier === supplier);
  const url = (token: string) => `${location.origin}${location.pathname}#/portal/${token}`;
  const e = failed ?? error;
  return <Panel title={`Link for ${name}`}>
    {made?.token && made.supplier === supplier && <div className="banner ok" role="status">
      <div><b>{made.supplier_name}</b>'s link, shown this once: send it to them now. It works until {day(made.expires_at.slice(0, 10))}.</div>
      <input className="input mono" readOnly value={url(made.token)} aria-label="The new link" onFocus={(ev) => ev.target.select()}
        style={{ width: "100%" }} />
      <button className="btn sm" onClick={() => { void navigator.clipboard?.writeText(url(made.token!)).catch(() => {}); }}>Copy the link</button>
    </div>}
    {mine.length > 0 && <div className="table-wrap"><table className="t" aria-label="Links">
      <thead><tr><th>Link</th><th>Made</th><th>Works until</th><th>Used</th><th>Status</th><th /></tr></thead>
      <tbody>{mine.map((l) => <tr key={l.id}>
        <td><b>{l.id}</b><div className="faint small mono">{l.prefix}…</div></td>
        <td className="small">{day(l.created_at.slice(0, 10))}<div className="faint">{l.created_by}</div></td>
        <td>{day(l.expires_at.slice(0, 10))}</td>
        <td className="small">{l.uses ? `${l.uses} times, last ${day(l.last_used!.slice(0, 10))}` : <span className="faint">not yet</span>}</td>
        <td><Badge sev={l.status === "live" ? "ok" : "error"}>{l.status}</Badge></td>
        <td>{l.status === "live" && <button className="btn sm ghost" aria-label={`Withdraw ${l.id}`} onClick={async () => {
          try { show(await api.revokePortalLink(company!.id, l.id)); setMade(null); } catch (x) { setFailed(errText(x)); }
        }}>Withdraw</button>}</td>
      </tr>)}</tbody>
    </table></div>}
    <div className="row wrap" style={{ gap: 8, alignItems: "flex-end", marginTop: 8 }}>
      <label className="small">Works for<br />
        <select className="select" value={days} onChange={(ev) => setDays(Number(ev.target.value))} aria-label="Link works for">
          <option value={30}>30 days</option><option value={90}>90 days</option><option value={180}>180 days</option><option value={365}>a year</option>
        </select></label>
      <button className="btn" onClick={async () => {
        setFailed(null);
        try { const l = await api.makePortalLink(company!.id, supplier, days); setMade(l); show(await api.portalLinks(company!.id)); }
        catch (x) { setFailed(errText(x)); }
      }}>Make a link</button>
      <span className="faint small">What they send is saved as your change, in the History. It stops working if you can no longer change this company.</span>
    </div>
    {e && <div className="banner error">{e}</div>}
  </Panel>;
}

function TheirView({ v, ds }: { v: PortalView; ds: Dataset }) {
  const [err, setErr] = useState<string | null>(null);
  const pos = [...new Set(v.lines.map((l) => l.po))];
  const xml = async (po: string) => {
    setErr(null);
    try {
      const text = await api.orderXml(ds, po);
      const url = URL.createObjectURL(new Blob([text], { type: "application/xml" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `${po}.xml` });
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setErr(errText(e)); }
  };
  return <Panel flush title={`What ${v.supplier_name} sees`}>
    {v.lines.length === 0 ? <Empty title="No open orders sent to them">Send a purchase order first; only sent orders are on the link.</Empty> :
      <div className="table-wrap"><table className="t" aria-label="What the supplier sees">
        <thead><tr><th>Order line</th><th>Goods</th><th className="num">Ordered</th><th className="num">Price</th><th>Wanted by</th>
          <th>Confirmed</th><th className="num">On the way</th><th>Status</th></tr></thead>
        <tbody>{v.lines.map((l) => <tr key={l.order}>
          <td><b>{l.order}</b><div className="faint small">{l.po}</div></td>
          <td>{l.product_name}{l.their_part && <div className="faint small">their part {l.their_part}</div>}</td>
          <td className="num">{qty(l.ordered)} {l.unit.toLowerCase()}</td>
          <td className="num">{l.price != null ? exactMoney(l.price, v.currency) : "—"}</td>
          <td>{day(l.due_date)}</td>
          <td className="small">{l.confirmations.length > 0 ? l.confirmations.map((c) => <div key={c.date}>{qty(c.qty)} on {day(c.date)}</div>)
            : l.confirmed_date ? `${qty(l.confirmed_qty ?? l.ordered)} on ${day(l.confirmed_date)}` : <span className="faint">not yet</span>}</td>
          <td className="num">{l.on_the_way ? qty(l.on_the_way) : "—"}</td>
          <td><Badge sev={STATUS[l.status] ?? "info"}>{l.status}</Badge></td>
        </tr>)}</tbody>
      </table></div>}
    {pos.length > 0 && <div className="row wrap" style={{ gap: 8, padding: 12 }}>
      <span className="small muted">For their system:</span>
      {pos.map((po) => <button key={po} className="btn sm ghost" onClick={() => void xml(po)} aria-label={`${po} as UBL`}>{po} as UBL Order</button>)}
    </div>}
    {err && <div className="banner error">{err}</div>}
  </Panel>;
}

function Notices({ v, ds, step }: { v: PortalView; ds: Dataset; step: Step }) {
  const [on, setOn] = useState(ds.settings.planning_start);
  return <Panel flush title="Shipping notices">
    {v.notices.length === 0 ? <Empty title="No dispatch advice from them yet" /> :
      <div className="table-wrap"><table className="t" aria-label="Shipping notices">
        <thead><tr><th>Notice</th><th>Shipped</th><th>Arrives</th><th>Goods</th><th>Status</th><th /></tr></thead>
        <tbody>{v.notices.map((n) => <tr key={n.id}>
          <td><b>{n.id}</b>{n.reference && <div className="faint small">their {n.reference}</div>}</td>
          <td>{day(n.shipped_on)}</td><td>{day(n.arrives_on)}</td>
          <td className="small">{n.lines.map((x) => <div key={x.order}>{qty(x.qty)} on {x.order}{x.batch ? `, batch ${x.batch}` : ""}
            {x.expires_on ? `, expires ${day(x.expires_on)}` : ""}</div>)}</td>
          <td><Badge sev={NOTICE[n.status] ?? "info"}>{n.status}</Badge></td>
          <td>{n.status === "on the way" && <div className="row wrap" style={{ gap: 4 }}>
            <button className="btn sm" disabled={step.busy} aria-label={`Receive ${n.id}`}
              onClick={() => void step.run("receive", { id: n.id, date: on })}>Goods received</button>
            <button className="btn sm ghost" disabled={step.busy} aria-label={`Cancel ${n.id}`}
              onClick={() => void step.run("cancel", { id: n.id })}>Will not come</button></div>}</td>
        </tr>)}</tbody>
      </table></div>}
    {v.notices.some((n) => n.status === "on the way") && <div className="row wrap" style={{ gap: 8, padding: 12, alignItems: "flex-end" }}>
      <label className="small">Received on<br />
        <input className="input" type="date" value={on} onChange={(e) => setOn(e.target.value)} aria-label="Received on" /></label>
      <span className="faint small">Each line is received on its order with the batch they advised; a short delivery is received on the order itself.</span>
    </div>}
  </Panel>;
}

function Message({ step }: { step: Step }) {
  const [xml, setXml] = useState("");
  return <Panel title="A message from their system">
    <p className="small muted" style={{ marginTop: 0 }}>A UBL <b>OrderResponse</b> (lines accepted, changed or rejected) or <b>DespatchAdvice</b>
      (what is on the lorry) that came by mail: paste it or choose the file. With a link, their system sends it here itself.</p>
    <textarea className="input mono" rows={6} style={{ width: "100%" }} value={xml} onChange={(e) => setXml(e.target.value)}
      aria-label="UBL message" placeholder="<DespatchAdvice xmlns=…" />
    <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>
      <input type="file" accept=".xml,application/xml,text/xml" aria-label="UBL file" onChange={async (e) => {
        const f = e.target.files?.[0];
        if (f) setXml(await f.text());
      }} />
      <button className="btn" disabled={step.busy || !xml.trim()} onClick={async () => {
        if (await step.run("message", { xml })) setXml("");
      }}>Read the message</button>
    </div>
  </Panel>;
}
