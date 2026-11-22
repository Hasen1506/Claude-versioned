import { useState } from "react";
import type { Dataset, PayablesView, TransportActionResponse } from "../api/types";
import { Edits } from "../components/ui";
import { day, exactMoney } from "../lib/format";
import { useSettlement, type CarrierEventInput } from "../state/settlement";
import { store } from "../state/store";

type Bill = PayablesView["carrier_bills"][number];
type Kind = CarrierEventInput["kind"];
const LABELS: Record<Kind, string> = {
  adjust_bill: "Post carrier credit", refund_bill: "Record carrier refund", match_bank: "Match bank statement",
  release_match: "Release bank match", landed_cost: "Allocate landed cost", reverse_landed: "Reverse landed cost",
};

export function CarrierBillEvents({ bill, ds, currency }: { bill: Bill; ds: Dataset; currency: string }) {
  const history = bill.events ?? [];
  const cash = bill.unreconciled_cash ?? [];
  const settlement = useSettlement("transportBillEvent", bill.voucher, bill.order);
  const [kind, setKind] = useState<Kind | "">("");
  const [on, setOn] = useState(ds.settings.planning_start > bill.date ? ds.settings.planning_start : bill.date);
  const [amount, setAmount] = useState("");
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [target, setTarget] = useState("");
  const [account, setAccount] = useState("");
  const [line, setLine] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; error: boolean }>();
  const order = ds.freight_orders?.find((fo) => fo.id === bill.order);
  const reversed = new Set(history.flatMap((event) => event.kind === "landed_cost" && event.reverses ? [event.reverses] : []));
  const allocated = history.flatMap((event, index) => event.kind === "landed_cost" && !event.reverses && !reversed.has(index + 1)
    ? [{ index: index + 1, receipt: event.receipt }] : []);
  const receipts = (ds.movements ?? []).filter((movement) => movement.type === "receipt" && !movement.reversal_of
    && movement.reference && order?.purchases?.includes(movement.reference) && movement.location === order.ship_to
    && !allocated.some((item) => item.receipt === movement.id));
  const matches = new Map<string, Extract<Bill["events"][number], { kind: "match_bank" }>>();
  for (const event of history) if (event.kind === "match_bank") {
    if (event.released) matches.delete(event.cash_voucher);
    else matches.set(event.cash_voucher, event);
  }
  const credited = history.reduce((total, event) => total + (event.kind === "adjust_bill" ? event.amount_minor : 0), 0);
  const choices: Kind[] = [];
  if (settlement.live && bill.events && order?.status === "settled" && !bill.credited_on && bill.carrier) {
    if (allocated.length) choices.push("reverse_landed");
    if (receipts.length && credited < Math.round(bill.amount * 100)) choices.push("landed_cost");
    if (!allocated.length && credited < Math.round(bill.amount * 100)) choices.push("adjust_bill");
    if (bill.open < 0) choices.push("refund_bill");
    if (cash.length) choices.push("match_bank");
    if (matches.size) choices.push("release_match");
  }
  const amountText = amount || (kind === "refund_bill" ? String(-bill.open) : "");
  const numericAmount = /^-?\d+(\.\d{1,2})?$/.test(amountText) ? Math.round(Number(amountText) * 100) : undefined;
  const minor = numericAmount !== undefined && Number.isSafeInteger(numericAmount) ? numericAmount : undefined;
  const ref = reference.trim();

  function input(): CarrierEventInput | undefined {
    switch (kind) {
      case "adjust_bill":
        return ref && reason.trim() && minor && minor > 0 ? { kind, reference: ref, reason: reason.trim(), amount_minor: minor } : undefined;
      case "refund_bill":
        return ref && minor && minor > 0 ? { kind, reference: ref, amount_minor: minor } : undefined;
      case "match_bank":
        return ref && cash.includes(target) && account.trim() && line.trim() && minor
          ? { kind, reference: ref, cash_voucher: target, account: account.trim(), statement_line: line.trim(), amount_minor: minor, currency }
          : undefined;
      case "release_match": {
        const match = matches.get(target);
        return match && { kind, cash_voucher: target, account: match.account, statement_line: match.statement_line };
      }
      case "landed_cost":
        return ref && receipts.some((movement) => movement.id === target) && minor !== undefined && minor >= 0
          ? { kind, receipt: target, service: ref, actual_minor: minor } : undefined;
      case "reverse_landed":
        return allocated.some((item) => String(item.index) === target) ? { kind, reverses: Number(target) } : undefined;
      default:
        return undefined;
    }
  }

  const event = input();
  async function record(retry: boolean) {
    setBusy(true); setMessage(undefined);
    try {
      const reply = await (retry ? settlement.retry() : settlement.post(on, null, "", undefined, event));
      await Promise.allSettled([store.run("purchasing"), store.run("plan")]);
      const result = reply.result as Pick<TransportActionResponse, "report">;
      setMessage({ text: result.report.message, error: false });
      setKind(""); setAmount(""); setReference(""); setTarget(""); setReason(""); setAccount(""); setLine("");
    } catch (error) {
      setMessage({ text: String(error).replace(/^Error:\s*/, ""), error: true });
    } finally {
      setBusy(false);
    }
  }
  const targets = kind === "landed_cost" ? receipts.map((r) => [r.id, `${r.id} · ${r.reference} · ${r.qty} ${r.product}`])
    : kind === "reverse_landed" ? allocated.map((r) => [String(r.index), r.receipt])
    : kind === "match_bank" ? cash.map((v) => [v, v]) : kind === "release_match" ? [...matches.keys()].map((v) => [v, v]) : [];
  const referenceLabel = kind === "landed_cost" ? "Accepted service reference" : kind === "adjust_bill" ? "Carrier credit number" : "Bank reference";

  return <>
    {!!history.length && <details><summary>Carrier history ({history.length})</summary><ul>{history.map((entry, index) => {
      let text: string;
      if (entry.kind === "landed_cost") {
        const change = (entry.actual_minor - entry.absorbed_minor) * (entry.reverses ? -1 : 1) / 100;
        text = `${entry.reverses ? "Reversed allocation" : "Landed cost"} ${entry.receipt} · ${entry.service} · ${exactMoney(change, currency)}`;
      } else if (entry.kind === "match_bank") {
        text = `${entry.released ? "Released match" : "Bank match"} ${entry.cash_voucher} · ${entry.account} · ${entry.statement_line}`;
      } else {
        text = `${entry.kind === "adjust_bill" ? "Carrier credit" : "Carrier refund"} ${entry.reference} · ${exactMoney(entry.amount_minor / 100, currency)}`;
      }
      return <li key={index}>{day(entry.date)} · {text}</li>;
    })}</ul></details>}
    {!!cash.length && <div className="small faint">Unmatched bank movements ({cash.length})</div>}
    <Edits>{settlement.pending && <button className="btn sm accent" disabled={busy} onClick={() => record(true)}
      aria-label={`Retry carrier event ${bill.voucher}`}>Retry carrier event</button>}{!!choices.length && <details>
      <summary>Carrier bill actions</summary>
      <div className="stack" style={{ gap: 6 }}>
        <label>Action <select className="input" value={kind} aria-label={`Carrier event ${bill.voucher}`}
          onChange={(e) => { setKind(e.target.value as Kind | ""); setTarget(""); setAmount(""); setReference(""); }}>
          <option value="">Choose an action</option>{choices.map((key) => <option key={key} value={key}>{LABELS[key]}</option>)}
        </select></label>
        {kind && <label>Date <input className="input" type="date" value={on} onChange={(e) => setOn(e.target.value)}
          aria-label={`Carrier event date ${bill.voucher}`} /></label>}
        {!!targets.length && <label>{kind === "landed_cost" ? "Goods receipt" : kind === "reverse_landed" ? "Allocation" : "Cash voucher"}
          <select className="input" aria-label={`Carrier event target ${bill.voucher}`} value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">Select</option>{targets.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>}
        {kind && kind !== "reverse_landed" && kind !== "release_match" && <>
          <label>{referenceLabel} <input className="input" maxLength={64} value={reference} onChange={(e) => setReference(e.target.value)}
            aria-label={`Carrier event reference ${bill.voucher}`} /></label>
          <label>{kind === "match_bank" ? "Signed statement amount" : kind === "landed_cost" ? "Eligible receipt charge" : "Amount"}
            <input className="input" type="number" step="0.01" value={amount}
            placeholder={kind === "refund_bill" ? String(-bill.open) : undefined} onChange={(e) => setAmount(e.target.value)}
            aria-label={`Carrier event amount ${bill.voucher}`} /></label>
        </>}
        {kind === "adjust_bill" && <label>Reason <input className="input" maxLength={200} value={reason} onChange={(e) => setReason(e.target.value)}
          aria-label={`Carrier credit reason ${bill.voucher}`} /></label>}
        {kind === "match_bank" && <>
          <label>Bank account <input className="input" maxLength={64} value={account} onChange={(e) => setAccount(e.target.value)}
            aria-label={`Statement account ${bill.voucher}`} /></label>
          <label>Statement line ID <input className="input" maxLength={64} value={line} onChange={(e) => setLine(e.target.value)}
            aria-label={`Statement line ${bill.voucher}`} /></label>
        </>}
        {kind && <button className="btn sm accent" disabled={busy || settlement.pending || !on || !event || !choices.includes(kind)}
          onClick={() => record(false)}>{LABELS[kind]}</button>}
      </div>
    </details>}</Edits>
    {message && <div className="small" role={message.error ? "alert" : "status"}>{message.text}</div>}
  </>;
}
