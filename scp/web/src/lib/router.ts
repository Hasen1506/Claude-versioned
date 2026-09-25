// Hash routing: #/network, #/data/<type>/<id>, #/readiness, #/plan/<view>/<a>/<b>
import { useEffect, useState } from "react";

export type Route = string[];

function parse(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  return h ? h.split("/").map(decodeURIComponent) : [];
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
