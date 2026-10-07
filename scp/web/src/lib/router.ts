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
// The address has already changed when hashchange fires: while the field is blurred, the screen being left is the one
// in view (leavingScreen), so the edit's undo step belongs to the screen it was typed on, not the one gone to.
let leaving: string | null = null;
/** The screen being left while a hash change blurs its field, else null. */
export function leavingScreen(): string | null { return leaving; }
const firstPart = (url: string) => (url.split("#")[1] ?? "").replace(/^\/?/, "").split("/")[0] || "home";
if (typeof window !== "undefined") {
  window.addEventListener("hashchange", (e) => {
    const a = document.activeElement as HTMLElement | null;
    if (!a || a === document.body || typeof a.blur !== "function") return;
    leaving = firstPart(e.oldURL);
    try { a.blur(); } finally { leaving = null; }
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
