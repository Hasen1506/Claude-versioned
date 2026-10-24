// Forecast value add (enterprise 4.2): every forecast release keeps what each layer said for each period: the naïve
// forecast, the statistical model, events and new products, and the planners' overrides. Once a period has sold, each
// layer is judged against its sales, in total, per product family and per planner, with the overrides that cost most.
import type { Dataset, ValueAddGroup } from "../api/types";
import { api } from "../api/client";
import { Badge, Empty, Panel } from "../components/ui";
import { day, pct, qty } from "../lib/format";
import { useLatest } from "../lib/latest";
import { namesOf } from "../lib/names";
import { go, href } from "../lib/router";
import { useStore } from "../state/store";

type Layer = "naive" | "statistical" | "adjusted" | "final";
const SHORT: Record<Layer, string> = { naive: "Naïve", statistical: "Statistical", adjusted: "Events and new products", final: "Consensus" };

/** Points of error a layer took off (+) or added (−). */
const sign = (v: number) => (Math.abs(v) < 0.0005 ? "" : v > 0 ? "+" : "−");
const pts = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${sign(v)}${(Math.abs(v) * 100).toFixed(1)} pts`);
const signed = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${sign(v)}${pct(Math.abs(v))}`);
const layer = (g: ValueAddGroup, l: Layer) => g.layers.find((x) => x.layer === l)!;
const tone = (v: number | null | undefined) => (v === null || v === undefined || Math.abs(v) < 0.0005 ? "" : v > 0 ? "good" : "bad");

export function ValueAddView({ ds }: { ds: Dataset }) {
  const revision = useStore((s) => s.revision);
  const res = useLatest(() => api.valueAdd(ds), [revision]);
  const va = res.value;
  const nm = namesOf(ds);
  const unit = ds.forecasting?.period === "month" ? "month" : "week";

  const intro = (
    <Panel title="Forecast value add">
      <p className="small" style={{ maxWidth: "70ch" }}>
        Does each step of the forecast make it better? Every time the forecast is used in the supply plan, what each layer said for
        each {unit} is kept: the naïve forecast (last {unit}'s sales), the statistical model, the forecast after demand events and new
        products, and the consensus after the planners' overrides. Once a {unit} has sold, each layer is judged against its sales:
        how far it missed (<b>WAPE</b>, the misses over the sales) and which way (<b>bias</b>, over minus under). A layer adds value when
        it misses less than the one before it.
      </p>
      {va && <p className="small faint">Each {unit} is judged on the forecast as it stood {va.lag === 0 ? `in the ${unit} itself` : `${va.lag} ${unit}${va.lag > 1 ? "s" : ""} before it began`} (
        <a href={href("demand", "settings")}>forecast settings</a>, value-add lag).</p>}
    </Panel>
  );
  if (res.error) return <div className="stack">{intro}<div className="banner error"><Badge sev="error">Not worked out</Badge>{res.error}</div></div>;
  if (!va) return <div className="stack">{intro}<div className="banner info" role="status">Working out the value add…</div></div>;
  if (!va.measured) {
    return <div className="stack">{intro}<Panel><Empty title={va.waiting ? `${va.waiting} kept forecasts are waiting for their sales` : "No forecast kept yet"}>
      <p>{va.notes[0]}</p>
      {!va.waiting && <button className="btn" onClick={() => go("demand", "overview")}>Open the forecast</button>}
    </Empty></Panel></div>;
  }

  const t = va.total;
  const [naive, stat, adj, fin] = (["naive", "statistical", "adjusted", "final"] as Layer[]).map((l) => layer(t, l));
  const what = (v: number | null | undefined, name: string) =>
    v === null || v === undefined ? null : Math.abs(v) < 0.0005 ? <>{name} changed nothing</> : <>{name} {v > 0 ? "took off" : "added"} {(Math.abs(v) * 100).toFixed(1)} points of error</>;
  const until = va.measured_to ? day(new Date(new Date(`${va.measured_to}T00:00:00`).getTime() - 86_400_000).toISOString().slice(0, 10)) : "";

  return <div className="stack">
    {intro}
    <Panel title="All products">
      <p role="status" style={{ maxWidth: "75ch" }}>
        Judged on {qty(va.measured)} product-{unit}s that have sold ({qty(Math.round(t.actual))} units){until && <>, to {until}</>}: the consensus missed the sales by <b>{pct(fin.wape)}</b>
        {fin.bias !== null && fin.bias !== undefined && Math.abs(fin.bias) >= 0.005 && <> and ran <b>{fin.bias > 0 ? "high" : "low"} by {pct(Math.abs(fin.bias))}</b></>}.
        {" "}The statistical model missed by {pct(stat.wape)} against {pct(naive.wape)} for the naïve forecast; {what(adj.value_add, "events and new products")};
        {" "}{what(fin.value_add, "the planners' overrides")}.
      </p>
      <div className="table-wrap"><table className="t" aria-label="Layers">
        <thead><tr><th>Layer</th><th className="num">Forecast</th><th className="num">Missed by</th><th className="num">Bias</th><th className="num">Value added</th></tr></thead>
        <tbody>
          {t.layers.map((l) => <tr key={l.layer}>
            <td>{l.label}</td><td className="num">{qty(Math.round(l.forecast))}</td>
            <td className="num">{pct(l.wape)}</td><td className="num">{signed(l.bias)}</td>
            <td className={`num ${tone(l.value_add)}`}>{l.layer === "naive" ? <span className="faint">yardstick</span> : pts(l.value_add)}</td>
          </tr>)}
        </tbody>
      </table></div>
      {va.waiting > 0 && <p className="small faint">{qty(va.waiting)} kept forecasts are for {unit}s that have not sold yet.</p>}
      {va.notes.map((n) => <p key={n} className="small faint">{n}</p>)}
    </Panel>

    {va.tracking.length > 0 && <Panel title="Forecasts that keep missing one way"
      actions={<span className="small faint">tracking signal over the last {qty(Math.max(...va.tracking.map((x) => x.periods)))} {unit}s</span>}>
      <p className="small" style={{ maxWidth: "75ch" }}>
        The running sum of each series' misses (forecast − sales) over their average size. Misses that cancel keep it near 0; a
        forecast that is high, or low, every {unit} walks it toward the number of {unit}s. At ±{qty(va.tracking_limit)} or beyond it is
        biased: look at the series before the next release.{" "}
        <b>{va.biased ? `${va.biased} of ${va.tracking.length} series ${va.biased === 1 ? "is" : "are"} biased.` : `None of ${va.tracking.length} series is biased.`}</b>
      </p>
      <div className="table-wrap"><table className="t" aria-label="Tracking signal">
        <thead><tr><th>Product</th><th className="num">{unit === "week" ? "Weeks" : "Months"}</th><th className="num">Sold</th><th className="num">Forecast</th>
          <th className="num">Average miss</th><th className="num">Tracking signal</th></tr></thead>
        <tbody>
          {va.tracking.slice(0, 25).map((x) => <tr key={`${x.location}|${x.product}`}>
            <td><a href={href("demand", "series", `${x.location}|${x.product}`)}>{nm.prod(x.product)}</a> <span className="faint small">{nm.loc(x.location)}</span></td>
            <td className="num">{x.periods}</td><td className="num">{qty(Math.round(x.actual))}</td><td className="num">{qty(Math.round(x.forecast))}</td>
            <td className="num">{qty(Math.round(x.mad))}</td>
            <td className={`num ${x.biased ? "bad" : ""}`}>{x.signal > 0 ? "+" : x.signal < 0 ? "−" : ""}{Math.abs(x.signal).toFixed(1)}
              {x.biased && <div className="small">{x.direction === "over" ? "forecast too high" : "forecast too low"}</div>}</td>
          </tr>)}
        </tbody>
      </table></div>
      {va.tracking.length > 25 && <p className="small faint">The 25 furthest from 0 of {va.tracking.length}.</p>}
    </Panel>}

    <Panel title="By planner" actions={<span className="small faint">on the {unit}s each planner overrode</span>}>
      {va.planners.length ? <div className="table-wrap"><table className="t" aria-label="By planner">
        <thead><tr><th>Planner</th><th className="num">Overrides</th><th className="num">Closer to the sales</th><th className="num">Missed before</th>
          <th className="num">Missed after</th><th className="num">Value added</th><th className="num">Bias after</th></tr></thead>
        <tbody>
          {va.planners.map((g) => { const a = layer(g, "adjusted"), f = layer(g, "final"); return <tr key={g.key}>
            <td>{g.label}</td><td className="num">{g.overrides}</td><td className="num">{g.improved} of {g.overrides}</td>
            <td className="num">{pct(a.wape)}</td><td className="num">{pct(f.wape)}</td><td className={`num ${tone(f.value_add)}`}>{pts(f.value_add)}</td>
            <td className="num">{signed(f.bias)}</td></tr>; })}
        </tbody>
      </table></div> : <p className="small faint">No {unit} that has sold was overridden.</p>}
    </Panel>

    <Panel title="By product family">
      <div className="table-wrap"><table className="t" aria-label="By product family">
        <thead><tr><th>Family</th><th className="num">Sold</th>{(["naive", "statistical", "adjusted", "final"] as Layer[]).map((l) => <th key={l} className="num">{SHORT[l]}</th>)}
          <th className="num">Overrides added</th><th className="num">Consensus bias</th></tr></thead>
        <tbody>
          {va.families.map((g) => <tr key={g.key}>
            <td>{g.label}</td><td className="num">{qty(Math.round(g.actual))}</td>
            {(["naive", "statistical", "adjusted", "final"] as Layer[]).map((l) => <td key={l} className="num">{pct(layer(g, l).wape)}</td>)}
            <td className={`num ${tone(layer(g, "final").value_add)}`}>{pts(layer(g, "final").value_add)}</td><td className="num">{signed(layer(g, "final").bias)}</td>
          </tr>)}
        </tbody>
      </table></div>
    </Panel>

    {va.costly.length > 0 && <Panel title="The overrides that cost most">
      <div className="table-wrap"><table className="t" aria-label="Costly overrides">
        <thead><tr><th>{unit === "week" ? "Week" : "Month"}</th><th>Product</th><th>Planner</th><th className="num">Sold</th><th className="num">Before</th><th className="num">Override</th><th className="num">Extra miss</th></tr></thead>
        <tbody>
          {va.costly.map((c) => <tr key={`${c.location}|${c.product}|${c.start}`}>
            <td style={{ whiteSpace: "nowrap" }}>{day(c.start)}</td><td>{nm.prod(c.product)} <span className="faint small">{nm.loc(c.location)}</span></td><td>{c.author}</td>
            <td className="num">{qty(Math.round(c.actual))}</td><td className="num">{qty(Math.round(c.adjusted))}</td><td className="num">{qty(Math.round(c.final))}</td>
            <td className="num bad">{qty(Math.round(c.cost))}</td>
          </tr>)}
        </tbody>
      </table></div>
    </Panel>}

    <Panel title={unit === "week" ? "Week by week" : "Month by month"}>
      <div className="table-wrap"><table className="t" aria-label="By period">
        <thead><tr><th>{unit === "week" ? "Week of" : "Month"}</th><th className="num">Sold</th><th className="num">Statistical missed</th><th className="num">Consensus missed</th></tr></thead>
        <tbody>
          {va.periods.map((p) => <tr key={p.start}>
            <td style={{ whiteSpace: "nowrap" }}>{unit === "week" ? day(p.start) : p.label}</td><td className="num">{qty(Math.round(p.actual))}</td>
            <td className="num">{pct(p.statistical_wape)}</td><td className="num">{pct(p.final_wape)}</td>
          </tr>)}
        </tbody>
      </table></div>
    </Panel>
  </div>;
}
