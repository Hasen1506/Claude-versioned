// Enterprise 7.4: the accounts (S/4 guide §15.1). The double-entry journal is made from what already happened to the
// goods and the money: every stock posting, supplier and customer invoice, payment, inter-company invoice and freight
// bill is a voucher with its debits and credits. Each company of the group keeps its own; the page shows the balances,
// who owes what, the journal itself and its checks against the documents, and makes Tally's import file.
// Engine: scp/accounting.
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { AccountingView, Dataset, Voucher } from "../api/types";
import { Badge, Edits, Empty, Panel, StageHeader, StatTile, Tabs } from "../components/ui";
import { day, exactMoney, money, plural } from "../lib/format";
import { Msg, useNames } from "../lib/names";
import { go, href } from "../lib/router";
import { download } from "../lib/tabular";
import { store, useStore } from "../state/store";

type View = "balances" | "parties" | "journal" | "checks" | "production" | "tally";
const NATURE: Record<string, string> = { asset: "What the company has", liability: "What it owes",
  equity: "Capital", income: "Income", expense: "Expenses" };

function useAccounts(ds: Dataset, start: string, end: string) {
  const [v, setV] = useState<AccountingView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    api.accounting(ds, start || undefined, end || undefined)
      .then((x) => { if (live) { setV(x); setErr(null); } }, (e) => live && setErr(String(e).replace(/^Error:\s*/, "")));
    return () => { live = false; };
  }, [ds, start, end]);
  return { v, err };
}

export function Accounts({ route }: { route: string[] }) {
  const ds = useStore((s) => s.dataset)!;
  const view = (route[1] as View) || "balances";
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [co, setCo] = useState("");
  const { v, err } = useAccounts(ds, start, end);
  const cur = ds.settings.currency;
  const company = v?.companies.find((c) => c.id === co) ?? v?.companies[0];
  const bad = v ? v.checks.filter((c) => !c.ok) : [];
  const head = <StageHeader title="Accounts" kicker="The books, made from what happened to the goods and the money."
    how={<>Every posting that changes the value of stock is a voucher, its other side chosen by what moved the goods: a
      purchase receipt against <b>goods received, not invoiced</b> (GR/IR) at the order's price, a delivery against the
      <b> cost of goods sold</b>, an issue to production into <b>work in progress</b>, a transfer into <b>stock in
      transit</b> until it arrives, a count difference, scrap or price difference to its own account. The supplier's
      invoice clears GR/IR against what is owed to the supplier with the input tax; the customer's invoice is a
      receivable against sales and the output tax; payments go through the bank. A transfer to another company of the
      group is a sale in its books and a purchase in the other's, settled when it is paid. The journal checks itself
      against the stock books and the open invoices, and is exported to Tally (Gateway of Tally → Import → Vouchers).</>}
    answer={v ? <>{plural(v.voucher_count, "voucher")} from {day(v.period_start)} to {day(v.period_end)}
      {v.companies.length > 1 ? ` in ${v.companies.length} companies` : ""};{" "}
      {bad.length ? `${plural(bad.length, "check")} do not agree` : "every check agrees with the documents"}.</> : undefined} />;
  return (
    <div>{head}<div className="content stack">
      <div className="row wrap">
        <label className="field-inline">From <input className="input sm" type="date" aria-label="Period from"
          value={start || v?.period_start || ""} onChange={(e) => setStart(e.target.value)} /></label>
        <label className="field-inline">to <input className="input sm" type="date" aria-label="Period to"
          value={end || v?.period_end || ""} onChange={(e) => setEnd(e.target.value)} /></label>
        {(start || end) && <button className="btn sm ghost" onClick={() => { setStart(""); setEnd(""); }}>Financial year to date</button>}
        {v && v.companies.length > 1 && <label className="field-inline">Company <select className="input sm" aria-label="Company"
          value={company?.id ?? ""} onChange={(e) => setCo(e.target.value)}>
          {v.companies.map((c) => <option key={c.id || "-"} value={c.id}>{c.name}</option>)}</select></label>}
      </div>
      <Tabs<View> value={view} onChange={(x) => go("accounts", x)} tabs={[
        { id: "balances", label: "Balances" },
        { id: "parties", label: "Who owes what", count: v ? v.parties.filter((p) => p.company === (company?.id ?? "") && Math.abs(p.balance) > 0.005).length || undefined : undefined },
        { id: "journal", label: "Journal", count: v ? v.vouchers.filter((x) => x.company === (company?.id ?? "")).length || undefined : undefined },
        { id: "checks", label: "Checks", count: bad.length || undefined },
        { id: "production", label: "Production WIP" },
        { id: "tally", label: "Tally" },
      ]} />
      {err && <div className="banner error" role="alert"><Badge sev="error">Could not make the journal</Badge>{err}</div>}
      {!v && !err && <p className="faint">Posting every movement and invoice…</p>}
      {v && v.notes.map((t) => <div key={t} className="banner info" role="note"><Msg text={t} /></div>)}
      {v && company && view === "balances" && <Balances v={v} co={company.id} cur={cur} />}
      {v && company && view === "parties" && <Parties v={v} co={company.id} cur={cur} />}
      {v && company && view === "journal" && <Journal v={v} co={company.id} cur={cur} />}
      {v && view === "checks" && <Checks v={v} cur={cur} />}
      {v && company && view === "production" && <ProductionWip ds={ds} v={v} co={company.id} />}
      {v && company && view === "tally" && <Tally ds={ds} v={v} co={company.id} start={start} end={end} />}
    </div></div>
  );
}

function ProductionWip({ ds, v, co }: { ds: Dataset; v: AccountingView; co: string }) {
  const company = useStore((s) => s.company);
  const actor = useStore((s) => s.session?.user.email);
  const grants = ds.finance?.control_roles ?? {};
  const canPost = company?.live && (Object.keys(grants).length
    ? (grants.production_cost ?? []).some((email) => email.trim().toLowerCase() === actor?.trim().toLowerCase())
    : company.role === "owner");
  const nm = useNames();
  const [order, setOrder] = useState("");
  const [on, setOn] = useState("");
  const [reference, setReference] = useState("");
  const [amount, setAmount] = useState("");
  const [reversal, setReversal] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const retry = useRef<{ key: string; id: string } | null>(null);
  const rows = (v.production_wip ?? []).filter((row) => row.company === co);
  const current = rows.find((row) => row.order === order);
  const entries = (ds.production_cost_postings ?? []).filter((row) => row.order === order);
  const reversed = new Set(entries.map((row) => row.reversal_of));
  const originals = entries.filter((row) => !row.reversal_of && !reversed.has(row.id));
  const postingDate = on || v.period_end;
  const decimal = /^(\d{1,10})(?:\.(\d{1,2}))?$/.exec(amount.trim());
  const minor = decimal ? Number(decimal[1]) * 100 + Number((decimal[2] ?? "").padEnd(2, "0")) : 0;

  const post = async (action: "conversion" | "settle" | "reverse") => {
    if (!current || !reference.trim() || pending) return;
    const parameters = { order, reference: reference.trim(), ...(action === "conversion" ? { amount_minor: minor } : {}),
      ...(action === "reverse" ? { posting: reversal } : {}), ...(action === "settle" ? { confirm_actuals: reviewed } : {}) };
    const key = JSON.stringify([company?.id, action, postingDate, parameters]);
    const attempt = retry.current?.key === key ? retry.current : { key, id: crypto.randomUUID() };
    retry.current = attempt;
    setPending(true);
    setStatus("");
    setError("");
    try {
      const result = await store.postCompanyCommand({ id: attempt.id, kind: "production_cost", action,
        posting_date: postingDate, parameters });
      retry.current = null;
      setStatus(`Posted ${order} at company revision ${result.revision}.`);
      setAmount(""); setReference(""); setReversal(""); setReviewed(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  };
  if (!rows.length) return <Empty title="No production orders">Production WIP becomes available when a production order exists.</Empty>;
  const disabled = pending || !current || !postingDate || !reference.trim();
  return <>
    <Panel flush title="Work in progress by production order">
      <div className="table-wrap"><table className="t" aria-label="Work in progress by production order">
        <thead><tr><th>Order</th><th>Plant</th><th>Product</th><th>Completed</th><th className="num">WIP</th><th>Settlement</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.order}>
          <td>{row.order}</td><td>{nm.loc(row.location)}</td><td>{nm.prod(row.product)}</td>
          <td>{row.completed_on ? day(row.completed_on) : "Open"}</td>
          <td className="num">{balance(row.balance_minor / 100, v.currency)}</td>
          <td>{row.other_company_wip ? "Cross-company costs to reconcile"
            : row.settlement && (!row.completed_on || row.balance_minor !== 0) ? "Review settlement"
            : row.settlement ?? (row.completed_on && row.balance_minor ? "To settle" : "—")}</td>
        </tr>)}</tbody>
      </table></div>
    </Panel>
    {canPost && <Panel title="Post production costs">
      <Edits><div className="stack">
        <div className="row wrap">
          <label>Production order <select className="input sm" aria-label="Production order" value={order} disabled={pending}
            onChange={(e) => { setOrder(e.target.value); setReversal(""); setReviewed(false); }}>
            <option value="">Choose an order</option>
            {rows.map((row) => <option key={row.order} value={row.order}>{row.order}</option>)}
          </select></label>
          <label>Posting date <input className="input sm" type="date" value={postingDate} disabled={pending}
            onChange={(e) => setOn(e.target.value)} /></label>
          <label>Source or review reference <input className="input sm" required maxLength={120} value={reference}
            disabled={pending} onChange={(e) => setReference(e.target.value)} /></label>
        </div>
        <div className="row wrap">
          <label>Actual conversion cost ({v.currency}) <input className="input sm" inputMode="decimal" value={amount}
            disabled={pending} onChange={(e) => setAmount(e.target.value)} /></label>
          <button className="btn sm" disabled={disabled || minor <= 0 || !!current?.settlement}
            onClick={() => void post("conversion")}>Post conversion cost</button>
          <label><input type="checkbox" checked={reviewed} disabled={pending || !current?.completed_on}
            onChange={(e) => setReviewed(e.target.checked)} /> Actual costs reviewed</label>
          <button className="btn sm" disabled={disabled || !current?.completed_on || !current.balance_minor
            || !!current.settlement || current.other_company_wip || !reviewed} onClick={() => void post("settle")}>Settle WIP</button>
        </div>
        {originals.length > 0 && <div className="row wrap">
          <label>Posting to reverse <select className="input sm" aria-label="Posting to reverse" value={reversal} disabled={pending}
            onChange={(e) => setReversal(e.target.value)}>
            <option value="">Choose a posting</option>
            {originals.map((row) => <option key={row.id} value={row.id}>{row.date} · {row.kind} · {row.reference}</option>)}
          </select></label>
          <button className="btn sm" disabled={disabled || !reversal} onClick={() => void post("reverse")}>Reverse posting</button>
        </div>}
        {status && <div className="banner ok" role="status">{status}</div>}
        {error && <div className="banner error" role="alert">{error}</div>}
      </div></Edits>
    </Panel>}
  </>;
}

function Balances({ v, co, cur }: { v: AccountingView; co: string; cur: string }) {
  const rows = v.balances.filter((b) => b.company === co);
  const sum = (codes: string[]) => -rows.filter((b) => codes.includes(b.account)).reduce((a, b) => a + b.balance, 0);
  const sales = sum(["SALES", "IC_SALES"]);
  const cogs = -sum(["COGS", "IC_COGS"]);
  const c = v.companies.find((x) => x.id === co)!;
  const natures = ["asset", "liability", "equity", "income", "expense"];
  if (!rows.length) return <Empty title="Nothing posted">Stock movements, invoices and payments of {c.name} fill the journal.</Empty>;
  return <>
    <div className="grid-auto">
      <StatTile label="Sales to date" value={money(sales, cur)} sub={`${money(sum(["IC_SALES"]), cur)} of it to group companies`} />
      <StatTile label="Cost of goods sold" value={money(cogs, cur)} sub={sales ? `gross margin ${money(sales - cogs, cur)}` : "no sales invoiced yet"} />
      <StatTile label="Profit to date" value={money(c.profit, cur)} tone={c.profit < 0 ? "hl" : undefined} sub="income less expenses in the books" />
      <StatTile label="Stock in the books" value={money(-sum(["STOCK", "TRANSIT"]), cur)} sub={`${money(-sum(["TRANSIT"]), cur)} on the way`} />
    </div>
    <Panel flush title={`Trial balance of ${c.name} on ${day(v.period_end)}`}>
      <div className="table-wrap"><table className="t" aria-label="Trial balance">
        <thead><tr><th>Account</th><th>Tally group</th><th className="num">Debit in the period</th><th className="num">Credit in the period</th>
          <th className="num">Balance</th></tr></thead>
        <tbody>{natures.flatMap((n) => {
          const part = rows.filter((b) => b.nature === n);
          if (!part.length) return [];
          return [<tr key={n} className="subhead"><th colSpan={5}>{NATURE[n]}</th></tr>,
            ...part.map((b) => <tr key={b.account}>
              <td>{b.name}<div className="faint mono">{b.account}</div></td><td>{b.group}</td>
              <td className="num">{b.debit ? exactMoney(b.debit, cur) : "—"}</td><td className="num">{b.credit ? exactMoney(b.credit, cur) : "—"}</td>
              <td className="num">{balance(b.balance, cur)}</td></tr>)];
        })}
          <tr className="total"><th>Total</th><th></th><th className="num">{exactMoney(rows.reduce((a, b) => a + b.debit, 0), cur)}</th>
            <th className="num">{exactMoney(rows.reduce((a, b) => a + b.credit, 0), cur)}</th>
            <th className="num">{balance(rows.reduce((a, b) => a + b.balance, 0), cur)}</th></tr>
        </tbody>
      </table></div>
    </Panel>
  </>;
}

function balance(x: number, cur: string) {
  if (Math.abs(x) < 0.005) return "0";
  return x > 0 ? `${exactMoney(x, cur)} Dr` : `${exactMoney(-x, cur)} Cr`;
}

function Parties({ v, co, cur }: { v: AccountingView; co: string; cur: string }) {
  const rows = v.parties.filter((p) => p.company === co && Math.abs(p.balance) > 0.005);
  if (!rows.length) return <Empty title="Nobody owes anything">Every invoice of the period is paid, and nothing is owed to suppliers or carriers.</Empty>;
  const kind: Record<string, string> = { RECEIVABLES: "customer", PAYABLES: "supplier or carrier", IC_RECEIVABLES: "group company",
    IC_PAYABLES: "group company" };
  return <Panel flush title={`Who owes what on ${day(v.period_end)}`}>
    <div className="table-wrap"><table className="t" aria-label="Who owes what">
      <thead><tr><th>Who</th><th>Account</th><th className="num">Owes us</th><th className="num">We owe</th></tr></thead>
      <tbody>{rows.map((p) => <tr key={`${p.account}-${p.party}`}>
        <td><b>{p.party_name}</b><div className="faint">{kind[p.account]}</div></td><td>{p.name}</td>
        <td className="num">{p.balance > 0 ? exactMoney(p.balance, cur) : "—"}</td>
        <td className="num">{p.balance < 0 ? exactMoney(-p.balance, cur) : "—"}</td></tr>)}</tbody>
    </table></div>
  </Panel>;
}

function Journal({ v, co, cur }: { v: AccountingView; co: string; cur: string }) {
  const nm = useNames();
  const [acc, setAcc] = useState("");
  const [find, setFind] = useState("");
  const names = useMemo(() => Object.fromEntries(v.accounts.map((a) => [a.code, a.name])), [v]);
  const q = find.trim().toLowerCase();
  const shown = v.vouchers.filter((x) => x.company === co && (!acc || x.lines.some((l) => l.account === acc))
    && (!q || `${x.number} ${x.document} ${x.narration}`.toLowerCase().includes(q))).slice(0, 200);
  const used = [...new Set(v.vouchers.filter((x) => x.company === co).flatMap((x) => x.lines.map((l) => l.account)))];
  return <Panel flush title="The journal, latest first" actions={<div className="row">
    <input className="input sm" placeholder="Find a voucher or document" aria-label="Find a voucher" value={find} onChange={(e) => setFind(e.target.value)} />
    <select className="input sm" aria-label="Account" value={acc} onChange={(e) => setAcc(e.target.value)}>
      <option value="">Every account</option>{used.map((a) => <option key={a} value={a}>{names[a] ?? a}</option>)}</select></div>}>
    {!shown.length ? <div className="pad"><Empty title="No vouchers">Nothing in the period{acc ? " on that account" : ""}.</Empty></div> :
      <div className="table-wrap"><table className="t" aria-label="Journal">
        <thead><tr><th>Date</th><th>Voucher</th><th>What</th><th>Account</th><th className="num">Debit</th><th className="num">Credit</th></tr></thead>
        <tbody>{shown.flatMap((x: Voucher) => x.lines.map((l, i) => <tr key={`${x.number}-${x.type}-${i}`} className={i === 0 ? "group-start" : undefined}>
          {i === 0 && <><td rowSpan={x.lines.length}>{day(x.date)}</td>
            <td rowSpan={x.lines.length} className="mono">{x.number}<div className="faint">{x.type}</div></td>
            <td rowSpan={x.lines.length}><Msg text={x.narration} /></td></>}
          <td>{names[l.account] ?? l.account}{l.party ? <span className="faint"> · {nm.loc(l.party)}</span> : null}</td>
          <td className="num">{l.debit ? exactMoney(l.debit, cur) : ""}</td><td className="num">{l.credit ? exactMoney(l.credit, cur) : ""}</td>
        </tr>))}</tbody>
      </table></div>}
    {v.voucher_count > shown.length && !acc && !q && <p className="faint pad">The latest 200 are shown; the CSV on the Tally tab has every one.</p>}
  </Panel>;
}

function Checks({ v, cur }: { v: AccountingView; cur: string }) {
  const name = (id: string) => v.companies.find((c) => c.id === id)?.name ?? id;
  return <Panel flush title={`The journal against the documents, on ${day(v.period_end)}`}>
    <div className="table-wrap"><table className="t" aria-label="Checks">
      <thead><tr>{v.companies.length > 1 && <th>Company</th>}<th>Check</th><th className="num">The journal</th><th className="num">The documents</th><th></th></tr></thead>
      <tbody>{v.checks.map((c) => <tr key={`${c.company}-${c.what}`}>
        {v.companies.length > 1 && <td>{name(c.company)}</td>}<td>{c.what}{c.why && <div className="faint">{c.why}</div>}</td>
        <td className="num">{exactMoney(c.journal, cur)}</td><td className="num">{exactMoney(c.expected, cur)}</td>
        <td>{c.ok ? <Badge sev="ok">agrees</Badge> : <Badge sev="error">differs</Badge>}</td></tr>)}</tbody>
    </table></div>
  </Panel>;
}

function Tally({ ds, v, co, start, end }: { ds: Dataset; v: AccountingView; co: string; start: string; end: string }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const c = v.companies.find((x) => x.id === co)!;
  const ledgers = (ds.finance?.ledgers ?? {}) as Record<string, string>;
  const setLedger = (code: string, name: string) => store.update((d) => {
    const f = { ...(d.finance ?? {}) } as NonNullable<Dataset["finance"]>;
    const l = { ...((f.ledgers ?? {}) as Record<string, string>) };
    if (name.trim()) l[code] = name; else delete l[code];
    f.ledgers = l;
    d.finance = f;
  });
  const save = async (format: "tally" | "csv") => {
    setBusy(true); setErr(null);
    try {
      const out = await api.accountingExport(ds, format, co, start || undefined, end || undefined);
      download(out.name, out.text, format === "csv" ? "text/csv" : "application/xml");
    } catch (e) {
      setErr(String(e).replace(/^Error:\s*/, ""));
    } finally {
      setBusy(false);
    }
  };
  return <>
    <Panel title={`Tally's file for ${c.name}`} actions={<div className="row">
      <button className="btn sm primary" disabled={busy} onClick={() => save("tally")}>Download the Tally file</button>
      <button className="btn sm" disabled={busy} onClick={() => save("csv")}>Download the journal (CSV)</button></div>}>
      {err && <div className="banner error" role="alert"><Badge sev="error">Not made</Badge>{err}</div>}
      <p>{plural(c.vouchers, "voucher")} from {day(v.period_start)} to {day(v.period_end)} for the company <b>{c.tally_name}</b> in
        Tally, with the ledgers they post to (customers and suppliers by name, under Sundry Debtors and Sundry Creditors).
        In Tally Prime: <i>Gateway of Tally → Import → Vouchers</i>, then choose the file. A debit is a negative amount,
        as Tally keeps it; a ledger that does not exist yet is created under the group shown below.</p>
      {co === "" && <Edits><label className="field">Company name in Tally
        <input className="input" aria-label="Company name in Tally" placeholder={ds.settings.company_name || ""}
          value={ds.finance?.tally_company ?? ""} maxLength={120}
          onChange={(e) => store.update((d) => { d.finance = { ...(d.finance ?? {}), tally_company: e.target.value } as NonNullable<Dataset["finance"]>; })} />
      </label></Edits>}
      {co !== "" && <p className="faint">Its name in Tally is its name here: change it under <a href={href("data", "entities")}>Companies</a>.</p>}
    </Panel>
    <Panel flush title="Ledger names in Tally">
      <div className="table-wrap"><table className="t" aria-label="Ledger names">
        <thead><tr><th>Account</th><th>Tally group</th><th>Ledger in Tally</th></tr></thead>
        <tbody>{v.accounts.map((a) => <tr key={a.code}>
          <td>{a.name}<div className="faint mono">{a.code}</div></td><td>{a.group}</td>
          <td><Edits><input className="input sm" aria-label={`Tally ledger for ${a.name}`} placeholder={a.name}
            value={ledgers[a.code] ?? ""} maxLength={120} onChange={(e) => setLedger(a.code, e.target.value)} /></Edits></td>
        </tr>)}</tbody>
      </table></div>
    </Panel>
  </>;
}
