import { useState } from "react";
import type { Situation } from "../lib/situations";
import { SevIcon } from "./ui";

const SHOW = 5;

/** "Needs you": each situation says what is happening, why, and what can be done, with the items it covers. */
export function Situations({ list, title = "Needs you" }: { list: Situation[]; title?: string }) {
  const actionable = list.filter((s) => s.severity !== "info").length;
  return (
    <section className="needs" aria-label={title}>
      <div className="needs-head">
        <h2>{title}</h2>
        <span className="faint small">{list.length === 0 ? "nothing, the plan works as it stands" : `${actionable} to act on${list.length > actionable ? `, ${list.length - actionable} for information` : ""}`}</span>
      </div>
      {list.map((s) => <Row key={s.code} s={s} />)}
    </section>
  );
}

function Row({ s }: { s: Situation }) {
  const [all, setAll] = useState(false);
  const items = all ? s.items : s.items.slice(0, SHOW);
  return (
    <article className={`situation ${s.severity}`}>
      <div className="sit-icon"><SevIcon sev={s.severity} /></div>
      <div className="sit-body">
        <h3>{s.title}</h3>
        {s.why && <p className="muted">{s.why}</p>}
        {items.length > 0 && <ul className="sit-items">
          {items.map((it, i) => <li key={i}>{it.to ? <a href={it.to}>{it.label}</a> : it.label}{it.detail && <span className="faint"> · {it.detail}</span>}</li>)}
        </ul>}
        <div className="sit-actions">
          {s.items.length > SHOW && <button className="linkish" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${s.items.length}`}</button>}
          {s.actions.map((a) => <a key={a.to + a.label} href={a.to}>{a.label}</a>)}
        </div>
      </div>
    </article>
  );
}
