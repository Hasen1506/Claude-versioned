// People read names, not ids: "Chennai DC", not "DC-CHN". Tables show the name and keep the id on hover.
import { useMemo } from "react";
import { useStore } from "../state/store";
import { humanize } from "./format";
import type { Dataset } from "../api/types";

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Names of the dataset's places, products and machines, and `text` that puts them in place of ids in a message. */
export function namesOf(ds: Dataset | null | undefined) {
  const loc = new Map((ds?.locations ?? []).map((l) => [l.id, l.name || l.id]));
  const prod = new Map((ds?.products ?? []).map((p) => [p.id, p.name || p.id]));
  const res = new Map((ds?.resources ?? []).map((r) => [r.id, r.name || r.id]));
  const all = new Map<string, string>();
  for (const m of [res, loc, prod]) for (const [id, name] of m) if (name && name !== id) all.set(id, name);
  // an id is replaced only as a whole word ("PAN-24", not the "PAN-24" in "PAN-24-LID"), longest first; ids that
  // could be ordinary words (short, or lower-case letters only) are left alone
  const ids = [...all.keys()].filter((id) => id.length >= 3 && !/^[a-z]+$/.test(id)).sort((a, b) => b.length - a.length);
  const re = ids.length ? new RegExp(`(?<![\\w-])(${ids.map(escape).join("|")})(?![\\w-])`, "g") : null;
  return {
    loc: (id: string) => loc.get(id) ?? id,
    prod: (id: string) => prod.get(id) ?? id,
    res: (id: string) => res.get(id) ?? id,
    /** A place, product or machine by whichever it is. */
    any: (id: string) => all.get(id) ?? id,
    /** An engine message with names for ids and readable dates. */
    text: (msg: string) => humanize(re ? msg.replace(re, (id) => all.get(id) ?? id) : msg),
  };
}

export function useNames() {
  const ds = useStore((s) => s.dataset);
  return useMemo(() => namesOf(ds), [ds]);
}

/** A location's or product's name, with its id on hover. */
export function Loc({ id }: { id: string }) {
  return <span title={id}>{useNames().loc(id)}</span>;
}
export function Prod({ id }: { id: string }) {
  return <span title={id}>{useNames().prod(id)}</span>;
}
export function Res({ id }: { id: string }) {
  return <span title={id}>{useNames().res(id)}</span>;
}

/** An engine message with names for ids and readable dates. */
export function Msg({ text }: { text: string }) {
  return <>{useNames().text(text)}</>;
}
