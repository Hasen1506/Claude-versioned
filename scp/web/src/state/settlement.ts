import { useRef, useState } from "react";
import { ApiError } from "../api/client";
import { store, useStore } from "./store";

type SettlementKind = "sales" | "purchasing";
type PaymentAttempt = { key: string; id: string; details: string };

function readAttempt(key: string): PaymentAttempt | null {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const attempt = JSON.parse(raw) as PaymentAttempt | null;
    return attempt?.key === key && typeof attempt.id === "string" && typeof attempt.details === "string" ? attempt : null;
  } catch {
    return null;
  }
}

/** A tab can resubmit the original financial operation even after the invoice shows as settled. */
export function useSettlement(kind: SettlementKind, invoice?: string) {
  const companyId = useStore((s) => s.company?.live ? s.company.id : null);
  const userId = useStore((s) => s.session?.user.id);
  const key = companyId && userId && invoice
    ? `${kind === "purchasing" ? "scp.payment.pending.v1" : "scp.customer-payment.pending.v1"}:${companyId}:${userId}:${invoice}`
    : null;
  const memory = useRef<PaymentAttempt | null>(null);
  const [, refresh] = useState(0);
  const pending = () => key && (memory.current?.key === key ? memory.current : readAttempt(key));
  const parameters = (amount: number | null, reference: string) =>
    ({ [kind === "sales" ? "id" : "po"]: invoice, amount, reference });

  function remember(attempt: PaymentAttempt) {
    memory.current = attempt;
    try { sessionStorage.setItem(attempt.key, JSON.stringify(attempt)); } catch { /* keep the active tab's copy */ }
    refresh((revision) => revision + 1);
  }

  function forget(attempt: PaymentAttempt) {
    if (memory.current?.id === attempt.id) memory.current = null;
    try { sessionStorage.removeItem(attempt.key); } catch { /* tab storage unavailable */ }
    refresh((revision) => revision + 1);
  }

  async function send(attempt: PaymentAttempt, date: string, amount: number | null, reference: string, retrying: boolean) {
    if (!companyId || !invoice || !date) throw new Error("Open the live invoice and choose the payment date.");
    if (!userId || store.get().session?.user.id !== userId) throw new Error("Sign in again before posting the payment.");
    remember(attempt);
    try {
      const reply = await store.postCompanyCommand(companyId, { kind, action: kind === "sales" ? "pay" : "pay_invoice",
        id: attempt.id, posting_date: date, parameters: parameters(amount, reference) });
      forget(attempt);
      return reply;
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && ![408, 425, 429].includes(error.status)) {
        if (!retrying || error.status === 409 || error.status === 422) forget(attempt);
        throw error;
      }
      throw new Error("Payment confirmation is unavailable. Retry the original payment to check or finish the posting.");
    }
  }

  async function post(date?: string | null, amount: number | null = null, reference = "") {
    if (!userId) throw new Error("Sign in again before posting the payment.");
    if (!key || !date) throw new Error("Open the live invoice and choose the payment date.");
    reference = reference.trim();
    const details = JSON.stringify([date, parameters(amount, reference)]);
    const previous = pending();
    if (previous && previous.details !== details) throw new Error("Retry the unconfirmed payment before entering a new one.");
    return send(previous || { key, id: crypto.randomUUID(), details }, date, amount, reference, !!previous);
  }

  async function retry() {
    const attempt = pending();
    if (!attempt) throw new Error("No unconfirmed payment for this invoice.");
    const [date, saved] = JSON.parse(attempt.details) as [string, { amount: number | null; reference: string }];
    if (typeof date !== "string" || typeof saved?.reference !== "string"
        || (saved.amount !== null && typeof saved.amount !== "number")
        || JSON.stringify([date, parameters(saved.amount, saved.reference)]) !== attempt.details) {
      throw new Error("The saved payment details could not be verified.");
    }
    return send(attempt, date, saved.amount, saved.reference, true);
  }

  return { live: !!companyId, pending: !!pending(), post, retry };
}
