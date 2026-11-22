import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import type { TransportActionInput } from "../api/types";
import { store, useStore } from "./store";

const SETTLEMENTS = {
  sales: { prefix: "scp.customer-payment.pending.v1", action: "pay", document: "id", amount: "amount", reference: "reference" },
  purchasing: { prefix: "scp.payment.pending.v1", action: "pay_invoice", document: "po", amount: "amount", reference: "reference" },
  transport: { prefix: "scp.carrier-bill.pending.v1", action: "settle", document: "order", amount: "billed", reference: "bill" },
  transportCredit: { prefix: "scp.carrier-credit.pending.v1", action: "credit", document: "order", amount: "", reference: "bill" },
  transportPayment: { prefix: "scp.carrier-payment.pending.v1", action: "pay_bill", document: "voucher", amount: "amount", reference: "reference" },
  transportBillEvent: { prefix: "scp.carrier-bill-event.pending.v1", action: "bill_event", document: "voucher", amount: "", reference: "" },
  carrier_bank: { prefix: "scp.carrier-bank.pending.v1", action: "record", document: "", amount: "", reference: "" },
};
type SettlementKind = keyof typeof SETTLEMENTS;
type SettlementAttempt = { key: string; id: string; details: string };
type CreditDetails = { credit_of: string; reason: string };
export type CarrierEventInput = NonNullable<TransportActionInput["event"]>;
export type CarrierBankEvent = { kind: "import"; company: string; account: string; csv: string }
  | { kind: "match"; line: string; version: number; targets: { order: string; voucher: string }[] }
  | { kind: "release"; line: string; version: number };
type SettlementEvent = CarrierEventInput | CarrierBankEvent;

function readAttempt(key: string): SettlementAttempt | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const attempt = JSON.parse(raw) as SettlementAttempt | null;
    return attempt?.key === key && typeof attempt.id === "string" && typeof attempt.details === "string" ? attempt : null;
  } catch {
    return null;
  }
}

/** A tab can resubmit the original financial operation even after the document shows as settled. */
export function useSettlement(kind: SettlementKind, document?: string, order?: string) {
  const config = SETTLEMENTS[kind];
  const credit = kind === "transportCredit";
  const billEvent = kind === "transportBillEvent";
  const bankEvent = kind === "carrier_bank";
  const label = credit ? "carrier credit" : billEvent ? "carrier event" : bankEvent ? "bank statement operation"
    : kind === "transport" ? "carrier bill" : "payment";
  const companyId = useStore((s) => s.company?.live ? s.company.id : null);
  const userId = useStore((s) => s.session?.user.id);
  const key = companyId && userId && document ? `${config.prefix}:${companyId}:${userId}:${document}${order ? `:${order}` : ""}` : null;
  const memory = useRef<SettlementAttempt | null>(null);
  const [, refresh] = useState(0);
  const pending = () => key && (memory.current?.key === key ? memory.current : readAttempt(key));
  const parameters = (amount: number | null, reference: string, correction?: CreditDetails, event?: SettlementEvent) => bankEvent
    ? { event }
    : billEvent ? { voucher: document, order, event }
    : credit
    ? { [config.document]: document, [config.reference]: reference, ...correction }
    : { [config.document]: document, [config.amount]: amount, [config.reference]: reference, ...(order ? { order } : {}) };

  function remember(attempt: SettlementAttempt) {
    memory.current = attempt;
    try { sessionStorage.setItem(attempt.key, JSON.stringify(attempt)); } catch { /* keep the active tab's copy */ }
    refresh((revision) => revision + 1);
  }

  function forget(attempt: SettlementAttempt) {
    if (memory.current?.id === attempt.id) memory.current = null;
    try { sessionStorage.removeItem(attempt.key); } catch { /* tab storage unavailable */ }
    refresh((revision) => revision + 1);
  }

  async function send(attempt: SettlementAttempt, date: string, input: ReturnType<typeof parameters>, retrying: boolean) {
    if (!companyId || !document || !date) throw new Error("Open the live document and choose the posting date.");
    if (!userId || store.get().session?.user.id !== userId) throw new Error(`Sign in again before posting the ${label}.`);
    remember(attempt);
    try {
      const reply = await store.postCompanyCommand(companyId, { kind: kind === "transportCredit" || kind === "transportPayment" || billEvent ? "transport" : kind,
        action: config.action, id: attempt.id, posting_date: date, parameters: input });
      forget(attempt);
      return reply;
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && ![408, 425, 429].includes(error.status)) {
        if (!retrying || error.status === 409 || error.status === 422) forget(attempt);
        throw error;
      }
      const title = label[0].toUpperCase() + label.slice(1);
      throw new Error(`${title} confirmation is unavailable. Retry the original ${label} to check or finish the posting.`);
    }
  }

  async function post(date?: string | null, amount: number | null = null, reference = "", correction?: CreditDetails, event?: SettlementEvent) {
    if (!userId) throw new Error(`Sign in again before posting the ${label}.`);
    if (!key || !date) throw new Error("Open the live document and choose the posting date.");
    reference = reference.trim();
    const input = parameters(amount, reference, correction, event);
    const details = JSON.stringify([date, input]);
    const previous = pending();
    if (previous && previous.details !== details) throw new Error(`Retry the unconfirmed ${label} before entering a new one.`);
    return send(previous || { key, id: crypto.randomUUID(), details }, date, input, !!previous);
  }

  async function retry() {
    const attempt = pending();
    if (!attempt) throw new Error(`No unconfirmed ${label} for this document.`);
    const [date, saved] = JSON.parse(attempt.details) as [string, Record<string, unknown>];
    const amount = credit || billEvent || bankEvent ? null : saved?.[config.amount];
    const reference = billEvent || bankEvent ? "" : saved?.[config.reference];
    const correction = credit && typeof saved?.credit_of === "string" && typeof saved?.reason === "string"
      ? { credit_of: saved.credit_of, reason: saved.reason } : undefined;
    const event = (billEvent || bankEvent) && saved?.event && typeof saved.event === "object" ? saved.event as SettlementEvent : undefined;
    if (typeof date !== "string" || typeof reference !== "string" || (amount !== null && typeof amount !== "number")
        || (credit && !correction) || ((billEvent || bankEvent) && !event)
        || JSON.stringify([date, parameters(amount, reference, correction, event)]) !== attempt.details) {
      throw new Error(`The saved ${label} details could not be verified.`);
    }
    return send(attempt, date, parameters(amount, reference, correction, event), true);
  }

  return { live: !!companyId, pending: !!pending(), post, retry };
}
