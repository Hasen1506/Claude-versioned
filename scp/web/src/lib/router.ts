// Hash routing: #/network, #/data/<type>/<id>, #/readiness, #/plan/<view>/<a>/<b>
import { useEffect, useState } from "react";

export type Route = string[];

function parse(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  return h ? h.split("/").map(decodeURIComponent) : [];
}

// BACK-01: a value typed into a field is kept when the field loses focus (every grid and form commits on blur). Moving to
// another page — a link, the browser's Back or Forward — took the field away without that blur, and the edit with it.
// The field is blurred first (capture: before the page changes), so what was typed is kept wherever the planner goes.
if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => {
    const a = document.activeElement as HTMLElement | null;
    if (a && a !== document.body && typeof a.blur === "function") a.blur();
  }, true);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function href(...parts: (string | undefined | null)[]): string {
  return "#/" + parts.filter((p): p is string => !!p).map(encodeURIComponent).join("/");
}

export function go(...parts: (string | undefined | null)[]) {
  window.location.hash = href(...parts);
}
