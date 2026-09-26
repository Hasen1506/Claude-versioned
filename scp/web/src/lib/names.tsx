// People read names, not ids: "Chennai DC", not "DC-CHN". Tables show the name and keep the id on hover.
import { useMemo } from "react";
import { useStore } from "../state/store";

export function useNames() {
  const ds = useStore((s) => s.dataset);
  return useMemo(() => {
    const loc = new Map((ds?.locations ?? []).map((l) => [l.id, l.name || l.id]));
    const prod = new Map((ds?.products ?? []).map((p) => [p.id, p.name || p.id]));
    return { loc: (id: string) => loc.get(id) ?? id, prod: (id: string) => prod.get(id) ?? id };
  }, [ds]);
}

/** A location's or product's name, with its id on hover. */
export function Loc({ id }: { id: string }) {
  return <span title={id}>{useNames().loc(id)}</span>;
}
export function Prod({ id }: { id: string }) {
  return <span title={id}>{useNames().prod(id)}</span>;
}
