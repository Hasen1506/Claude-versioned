// The monthly S&OP cycle (enterprise 4.1, S/4 guide §4): data → demand review → supply review → pre-S&OP →
// executive S&OP, each step with an owner, signed off in order, each sign-off freezing the company as a plan version
// with its figures (volume and revenue against the budget).
import { useState } from "react";
import { api } from "../api/client";
import type { Cycle, CycleFigures, CycleStep, Dataset } from "../api/types";
import { Badge, Edits, Empty, Panel, StageHeader } from "../components/ui";
import { money, pct, qty } from "../lib/format";
import { useLatest } from "../lib/latest";
import { href } from "../lib/router";
import { useStore } from "../state/store";

const HELP: Record<string, string> = {
  data: "Is the data fit to plan on? Sales history in, stock and open orders current, no blocking problems.",
  demand: "Agree the demand plan: the released forecast and the orders, month by month, against the budget.",
  supply: "Can the network supply it? The capacity plan, solved month by month, against the demand and the budget.",
  pre: "Settle the gaps: what to do where the plan falls short of demand or budget, and what the executive meeting decides.",
  exec: "Approve the plan the business runs on, and decide what pre-S&OP left open. This closes the month.",
};
const MINUTES = new Set(["pre", "exec"]);

const thisMonth = (iso: string) => iso.slice(0, 7);
function nextMonth(m: string): string {
  const [y, mo] = m.split("-").map(Number);
  return mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, "0")}`;
}
const monthName = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: "long", year: "numeric" });
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

export function CycleView({ ds }: { ds: Dataset }) {
  const company = useStore((s) => s.company);
  const revision = useStore((s) => s.revision);
  const list = useLatest(() => api.cycles(), [company?.id]);
  const [pick, setPick] = useState<string | null>(null);
  const cycles = list.value ?? [];
  const cid = pick && cycles.some((c) => c.id === pick) ? pick : cycles[0]?.id ?? null;
  const cyc = useLatest(cid ? () => api.cycle(cid) : null, [cid]);
  const [month, setMonth] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const suggested = cycles.length ? nextMonth(cycles.map((c) => c.month).sort().at(-1)!) : thisMonth(ds.settings.planning_start);
  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      const c = await api.newCycle(month || suggested);
      list.reload();
      setPick(c.id);
      cyc.show(c);
      setMonth("");
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  };

  const head = (
    <Panel title="Monthly S&OP cycle" actions={<Edits><div className="row wrap">
      <label className="row small">Month
        <input type="month" aria-label="Cycle month" value={month || suggested} onChange={(e) => setMonth(e.target.value)} /></label>
      <button className="btn sm" onClick={start} disabled={busy}>Start the {monthName(month || suggested)} cycle</button>
    </div></Edits>}>
      <p className="small" style={{ margin: 0, maxWidth: "70ch" }}>
        Once a month the plan is agreed in five steps, each signed off by its owner in order: the data, the demand review,
        the supply review, pre-S&OP and the executive meeting. Each sign-off keeps the company as it was signed (a plan
        version) with its figures, so the month can be followed from the first demand number to the approved plan, against
        the budget.</p>
      {cycles.length > 0 && <div className="row wrap" style={{ marginTop: 10 }} role="tablist" aria-label="Cycles">
        {cycles.map((c) => <button key={c.id} role="tab" aria-selected={c.id === cid} className={`btn sm ${c.id === cid ? "" : "ghost"}`}
          onClick={() => setPick(c.id)}>{monthName(c.month)} · {c.status === "closed" ? "closed" : `${c.signed} of 5`}</button>)}
      </div>}
      {(err || list.error) && <div className="banner error" style={{ marginTop: 10 }}><Badge sev="error">Not done</Badge>{err ?? list.error}</div>}
    </Panel>
  );
  if (!cid) return <div className="stack">{head}<Panel><Empty title="No cycle yet">
    Start this month's cycle: its first step checks the data. {ds.budgets?.length ? null : <>Add the year's budget under <a href={href("data", "budgets")}>Budgets</a> to set the plan against it.</>}
  </Empty></Panel></div>;
  return <div className="stack">{head}
    {cyc.error && <div className="banner error"><Badge sev="error">Not read</Badge>{cyc.error}</div>}
    {cyc.value && <CycleBody key={cyc.value.id} c={cyc.value} ds={ds} revision={revision}
      onChange={(c) => { cyc.show(c); list.reload(); }} onDrop={() => { setPick(null); list.reload(); }} />}
  </div>;
}

function CycleBody({ c, ds, revision, onChange, onDrop }: {
  c: Cycle; ds: Dataset; revision: number; onChange: (c: Cycle) => void; onDrop: () => void;
}) {
  const company = useStore((s) => s.company);
  const [sel, setSel] = useState<string>(c.next ?? "exec");
  // units or revenue: kept for the cycle, so the next step (a new panel) shows what was chosen
  const [unit, setUnit] = useState<Unit>("qty");
  const step = c.steps.find((s) => s.step === sel) ?? c.steps[0];
  const members = useLatest(company ? () => api.members(company.id) : null, [company?.id]);
  const mayOwn = !company || company.role === "owner";
  const signedAny = c.steps.some((s) => s.version_id);
  const [err, setErr] = useState<string | null>(null);
  const act = async (fn: () => Promise<Cycle>) => {
    setErr(null);
    try {
      const n = await fn();
      onChange(n);
      // a step just signed: on to the next one
      if (n.next && n.steps.find((x) => x.step === sel)?.status === "signed" && step.status !== "signed") setSel(n.next);
    } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };
  return <>
    <ol className="cycle-track" aria-label="Steps">
      {c.steps.map((s, i) => <li key={s.step}>
        <button className={`cycle-step ${s.step === sel ? "on" : ""} ${s.status}`} onClick={() => setSel(s.step)} aria-current={s.step === sel ? "step" : undefined}>
          <span className="faint small">{i + 1}</span> <b>{s.label}</b>
          <span className="small">{s.status === "signed" ? <Badge sev="ok">Signed</Badge> : s.step === c.next ? <Badge sev="warning">Next</Badge> : <span className="faint">Waits</span>}</span>
          <span className="small faint">{s.status === "signed" ? `${s.signed_by} · ${when(s.signed_at)}` : s.owner || "No owner"}</span>
        </button></li>)}
    </ol>
    {err && <div className="banner error"><Badge sev="error">Not done</Badge>{err}</div>}
    <StepPanel key={`${c.id}/${step.step}/${step.status}`} c={c} s={step} ds={ds} revision={revision} act={act} unit={unit} setUnit={setUnit}
      owners={members.value?.filter((m) => m.role !== "viewer").map((m) => m.email) ?? null} mayOwn={mayOwn} />
    {c.steps.some((s) => s.figures) && <Journey c={c} />}
    <Panel title="What happened">
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        {c.log.map((x, i) => <li key={i}>{when(x.at)} · {x.actor} · {x.action}{x.detail ? `: ${x.detail}` : ""}</li>)}
      </ul>
      {!signedAny && <Edits><button className="btn sm ghost" style={{ marginTop: 8 }}
        onClick={() => api.dropCycle(c.id).then(onDrop, (e) => setErr(String(e instanceof Error ? e.message : e)))}>Delete this cycle</button></Edits>}
    </Panel>
  </>;
}

function StepPanel({ c, s, ds, revision, act, owners, mayOwn, unit, setUnit }: {
  c: Cycle; s: CycleStep; ds: Dataset; revision: number; act: (fn: () => Promise<Cycle>) => Promise<void>;
  owners: string[] | null; mayOwn: boolean; unit: Unit; setUnit: (u: Unit) => void;
}) {
  const isNext = s.step === c.next;
  const live = useLatest(isNext ? () => api.cycleFigures(ds, s.step) : null, [s.step, isNext, revision]);
  const f = s.status === "signed" ? s.figures : live.value;
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const run = (fn: () => Promise<Cycle>) => { setBusy(true); act(fn).finally(() => setBusy(false)); };
  const blocked = s.step === "data" && !!f && f.blocking > 0;
  return <Panel title={<>{s.label} <span className="faint small">· {monthName(c.month)}</span></>}>
    <div className="stack">
      <p className="small" style={{ margin: 0, maxWidth: "70ch" }}>{HELP[s.step]}</p>
      <Edits><div className="row wrap small">
        <span>Owner</span>
        {owners ? <select aria-label="Step owner" value={s.owner} disabled={!mayOwn}
          onChange={(e) => act(() => api.stepOwner(c.id, s.step, e.target.value))}>
          <option value="">{s.step === "exec" ? "Nobody (an owner of the company signs)" : "Nobody (anyone who plans signs)"}</option>
          {[...new Set([...owners, ...(s.owner ? [s.owner] : [])])].map((m) => <option key={m} value={m}>{m}</option>)}
        </select> : <input aria-label="Step owner" defaultValue={s.owner} placeholder="Who owns it" maxLength={200}
          onBlur={(e) => e.target.value !== s.owner && act(() => api.stepOwner(c.id, s.step, e.target.value))} />}
        {!mayOwn && <span className="faint">An owner of the company says who owns each step.</span>}
      </div></Edits>
      {s.status === "signed" && <div className="banner info"><Badge sev="ok">Signed</Badge>
        <span>By {s.signed_by}, {when(s.signed_at)}.{s.note && <> “{s.note}”</>} The company as signed is kept as
          {" "}<a href={href("versions")}>plan version {s.version_id}</a>.</span></div>}
      {!isNext && s.status !== "signed" && <p className="faint small" style={{ margin: 0 }}>{c.steps.find((x) => x.step === c.next)?.label} comes first.</p>}
      {isNext && live.error && <div className="banner error"><Badge sev="error">Figures not worked out</Badge>{live.error}</div>}
      {isNext && !f && !live.error && <p className="faint small" style={{ margin: 0 }}>Working out the figures{s.step === "supply" || s.step === "pre" || s.step === "exec" ? " (solving the capacity plan)" : ""}…</p>}
      {f && <Figures f={f} frozen={s.status === "signed"} unit={unit} setUnit={setUnit} />}
      {isNext && <Edits><div className="stack" style={{ gap: 8 }}>
        <label className="small">{MINUTES.has(s.step) ? "What was decided (kept with the sign-off)" : "Note (optional)"}
          <textarea aria-label="Sign-off note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} style={{ width: "100%" }}
            placeholder={MINUTES.has(s.step) ? "e.g. third shift on line 1 from November; kettle budget cut by 5 %" : ""} /></label>
        <div className="row wrap">
          <button className="btn" disabled={busy || !f || blocked || (MINUTES.has(s.step) && !note.trim())}
            onClick={() => run(() => api.signStep(c.id, s.step, ds, note))}>{busy ? "Signing…" : `Sign off ${s.label.toLowerCase()}`}</button>
          {blocked && <span className="small">Fix the {f!.blocking} blocking problem{f!.blocking > 1 ? "s" : ""} first: <a href={href("readiness")}>open readiness</a>.</span>}
        </div></div></Edits>}
      {s.status === "signed" && <Edits><div className="row wrap">
        <input aria-label="Why reopen" placeholder="Why reopen it" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: "1 1 220px" }} />
        <button className="btn sm ghost" disabled={busy || !reason.trim()} onClick={() => run(() => api.reopenStep(c.id, s.step, reason))}>
          Reopen{s.step !== "exec" ? " (and the steps after it)" : ""}</button>
      </div></Edits>}
    </div>
  </Panel>;
}

type Unit = "qty" | "revenue";

function Figures({ f, frozen, unit, setUnit }: { f: CycleFigures; frozen: boolean; unit: Unit; setUnit: (u: Unit) => void }) {
  const supply = f.months.some((m) => m.supply_qty !== null && m.supply_qty !== undefined);
  const fmt = (v: number) => (unit === "qty" ? qty(Math.round(v)) : money(v, f.currency));
  const pick = (m: { budget_qty: number; budget_revenue: number; demand_qty: number; demand_revenue: number; supply_qty?: number | null; supply_revenue?: number | null }) => ({
    budget: unit === "qty" ? m.budget_qty : m.budget_revenue,
    demand: unit === "qty" ? m.demand_qty : m.demand_revenue,
    supply: unit === "qty" ? m.supply_qty ?? null : m.supply_revenue ?? null,
  });
  const rows = f.months.map((m) => ({ key: m.month, label: m.label, ...pick(m) }));
  const tot = rows.reduce((a, r) => ({ budget: a.budget + r.budget, demand: a.demand + r.demand, supply: a.supply + (r.supply ?? 0) }),
    { budget: 0, demand: 0, supply: 0 });
  const gap = (plan: number, budget: number) => (budget > 0 ? `${plan >= budget ? "+" : "−"}${pct(Math.abs(plan - budget) / budget)}` : "");
  const plan = (r: { demand: number; supply: number | null }) => (supply ? r.supply ?? 0 : r.demand);
  const table = (title: string, items: { key: string; label: string; budget: number; demand: number; supply: number | null }[], total: boolean) => (
    <div className="table-wrap"><table className="t" aria-label={title}>
      <thead><tr><th>{title}</th><th className="num">Budget</th><th className="num">Demand plan</th>{supply && <th className="num">Supply plan</th>}<th className="num">Against budget</th></tr></thead>
      <tbody>
        {items.map((r) => <tr key={r.key}><td style={{ whiteSpace: "nowrap" }}>{r.label}</td><td className="num">{fmt(r.budget)}</td><td className="num">{fmt(r.demand)}</td>
          {supply && <td className="num">{fmt(r.supply ?? 0)}</td>}<td className="num">{gap(plan(r), r.budget)}</td></tr>)}
        {total && <tr className="total"><td><b>Total</b></td><td className="num"><b>{fmt(tot.budget)}</b></td><td className="num"><b>{fmt(tot.demand)}</b></td>
          {supply && <td className="num"><b>{fmt(tot.supply)}</b></td>}<td className="num"><b>{gap(supply ? tot.supply : tot.demand, tot.budget)}</b></td></tr>}
      </tbody></table></div>
  );
  return <div className="stack" style={{ gap: 10 }}>
    <div className="row wrap small">
      <div className="seg" role="group" aria-label="Show">
        <button className={unit === "qty" ? "on" : ""} onClick={() => setUnit("qty")}>Units</button>
        <button className={unit === "revenue" ? "on" : ""} onClick={() => setUnit("revenue")}>Revenue</button>
      </div>
      <span className="faint">{frozen ? "As signed." : "The company as it is now: what signing records."}</span>
      {f.fill_rate !== null && f.fill_rate !== undefined && <span>Supplied: <b>{pct(f.fill_rate)}</b> of demand{f.limits.length ? <>, held back by {f.limits.join("; ")}</> : null}.</span>}
      {f.step === "data" && <span>{f.blocking ? <Badge sev="error">{f.blocking} blocking</Badge> : <Badge sev="ok">No blocking problems</Badge>} {f.warnings} warnings{f.history_to ? `; sales history to ${f.history_to}` : "; no sales history"}.</span>}
    </div>
    {table("Month", rows, true)}
    {f.families.length > 1 && table("Product family", f.families.map((x) => ({ key: x.family, label: x.family || "No family / the company", ...pick(x) })), false)}
    {(f.unpriced.length > 0 || f.notes.length > 0) && <ul className="small faint" style={{ margin: 0, paddingLeft: 18 }}>
      {f.unpriced.length > 0 && <li>No selling price for {f.unpriced.join(", ")}: their units count, their revenue does not.</li>}
      {f.months.some((m) => m.share < 1) && <li>A month only partly inside the plan counts that part of its budget.</li>}
      {f.notes.map((n) => <li key={n}>{n}</li>)}
    </ul>}
  </div>;
}

/** The month's path: each signed step's plan against the budget, demand review to executive. */
function Journey({ c }: { c: Cycle }) {
  const signed = c.steps.filter((s) => s.figures && s.step !== "data");
  if (!signed.length) return null;
  const cur = signed[0].figures!.currency;
  const sum = (f: CycleFigures, k: "budget_qty" | "budget_revenue" | "demand_qty" | "demand_revenue" | "supply_qty" | "supply_revenue") =>
    f.months.reduce((a, m) => a + ((m[k] as number | null | undefined) ?? 0), 0);
  return <Panel flush title="Through the month: the plan against the budget, step by step">
    <div className="table-wrap"><table className="t">
      <thead><tr><th>Step</th><th className="num">Units planned</th><th className="num">Budget</th><th className="num">Revenue planned</th><th className="num">Budget</th><th className="num">Supplied</th><th>Kept as</th></tr></thead>
      <tbody>{signed.map((s) => {
        const f = s.figures!;
        const supply = f.fill_rate !== null && f.fill_rate !== undefined;
        const units = sum(f, supply ? "supply_qty" : "demand_qty");
        const rev = sum(f, supply ? "supply_revenue" : "demand_revenue");
        return <tr key={s.step}><td>{s.label}{s.status !== "signed" && <span className="faint small"> (reopened)</span>}</td>
          <td className="num">{qty(Math.round(units))}</td><td className="num">{qty(Math.round(sum(f, "budget_qty")))}</td>
          <td className="num">{money(rev, cur)}</td><td className="num">{money(sum(f, "budget_revenue"), cur)}</td>
          <td className="num">{supply ? pct(f.fill_rate!) : "—"}</td><td className="mono small">{s.version_id}</td></tr>;
      })}</tbody></table></div>
  </Panel>;
}

/** The monthly S&OP cycle as a page of its own (Enterprise 8.4, N351): the owner signs off the month here, not under
 *  the capacity plan's tabs. */
export function SopCyclePage() {
  const ds = useStore((s) => s.dataset)!;
  return (
    <div>
      <StageHeader title="S&OP cycle" kicker="Agreeing the month's plan, one signed-off step at a time, from the first demand number to the executive meeting." />
      <div className="content"><CycleView ds={ds} /></div>
    </div>
  );
}
