// 03 · Demand planning (IBP Demand analogue): statistical forecast competition per series, cleansing,
// segmentation, events, NPI, consensus overrides, and release as forecast demand for supply planning.
import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Dataset, ForecastModels, ForecastPoint, ForecastResult, ForecastSeries } from "../api/types";
import { BucketChart, type Mark, type Span } from "../components/charts";
import {
  Badge, cols, Empty, Panel, Provenance, Reading, SectionBand, SolverIO, StageHeader, StaleMark, StatTile, Tabs, RunButton, Term,
} from "../components/ui";
import { day, pct, qty } from "../lib/format";
import { go, href } from "../lib/router";
import { SchemaForm, type Obj } from "../schema/SchemaForm";
import { isStale, store, useStore } from "../state/store";

type View = "overview" | "series" | "consensus" | "settings";

const PATTERN_HELP: Record<string, string> = {
  smooth: "Regular demand, low size variation",
  erratic: "Regular timing, sizes vary a lot",
  intermittent: "Many zero periods, steady sizes",
  lumpy: "Many zero periods and variable sizes",
  none: "No history",
};

export function Demand({ route }: { route: string[] }) {
  const run = useStore((s) => s.runs.forecast);
  const fc = run.data;
  const stale = useStore((s) => isStale(s, "forecast"));
  const blocking = useStore((s) => s.validation?.blocking ?? false);
  const ds = useStore((s) => s.dataset)!;
  const view = ((route[1] as View) || "overview") as View;
  const [released, setReleased] = useState<ReleaseInfo | null>(null);
  const [releasing, setReleasing] = useState(false);

  const release = async () => {
    setReleasing(true);
    try {
      const r = await api.release(ds);
      store.replace(r.dataset);
      setReleased({ ...r.release, at: new Date().toLocaleTimeString("en-GB") });
      void store.run("forecast");
    } catch (e) {
      window.alert(`Release failed: ${String(e)}`);
    } finally {
      setReleasing(false);
    }
  };

  const head = (
    <StageHeader title="Demand" kicker="What customers will order, week by week, forecast from past sales. The supply plan uses it once you say so."
      how={<>For each location and product the engine backtests a set of forecasting models on past sales and keeps the best
        (lowest <Term t="WAPE" />). History is first cleansed of promotions and outliers; demand events lift the forecast, new products
        borrow a similar product's history, and consensus overrides adjust it. Using the forecast in the supply plan writes it into
        your demand data as forecast records (undoable).</>}
      right={<>
      {fc && <Provenance kind="solved" at={run.at} stale={stale} />}
      <RunButton running={run.running} has={!!fc} onClick={() => store.run("forecast")} disabled={blocking} />
      <button className="btn primary" onClick={release} disabled={!fc || !fc.ok || stale || releasing || run.running}
        title={stale ? "Recalculate first: the data changed" : "Writes this forecast into your demand data, replacing the forecast records there. Undo reverts it."}>
        {releasing ? "Saving…" : "Use this forecast in the supply plan"}
      </button></>} />
  );
  const body = (children: React.ReactNode) => <div>{head}<div className="content">{children}</div></div>;

  if (run.error) return body(<div className="banner error"><Badge sev="error">Forecast failed</Badge>{run.error}</div>);
  if (!fc) {
    return body(<div className="stack">
      <SolverIO answers="How much each customer or location will want, per week or month, with a range and a reason for every number."
        from="Sales history, demand events, NPI rules, consensus overrides, forecast settings."
        feeds="Forecast demand (PIRs) for supply planning, and forecast-error σ for safety stock." />
      <Panel><Empty title={blocking ? "Fix blocking readiness issues first" : (ds.history?.length ?? 0) === 0 ? "No sales history yet" : "No forecast yet"}>
        {blocking ? <a className="btn" href={href("readiness")}>Open readiness</a>
          : (ds.history?.length ?? 0) === 0 ? <><p>Add sales history (location, product, date, quantity) or NPI rules to forecast from.</p>
            <a className="btn" href={href("data", "history")}>Add history</a></>
          : <p>Run the forecast to see every series' leaderboard, cleansed history, forecast range and consensus grid.</p>}
      </Empty></Panel>
      <ForecastSettingsPanel ds={ds} />
    </div>);
  }
  if (!fc.ok) return body(<div className="banner error"><Badge sev="error">Not forecast</Badge>The dataset has blocking readiness issues. <a href={href("readiness")}>Review them</a>.</div>);

  return body(<>
    {stale && <StaleMark what="forecast" onRerun={() => store.run("forecast")} busy={run.running} />}
    {released && <ReleaseBanner info={released} ds={ds} onClose={() => setReleased(null)} />}
    <Tabs<View> value={view} onChange={(v) => go("demand", v)} tabs={[
      { id: "overview", label: "Overview" },
      { id: "series", label: "Series workbench", count: fc.series.length },
      { id: "consensus", label: "Consensus grid" },
      { id: "settings", label: "Forecast settings" },
    ]} />
    {view === "overview" && <Overview fc={fc} />}
    {view === "series" && <Workbench fc={fc} sel={route[2]} />}
    {view === "consensus" && <Consensus fc={fc} ds={ds} />}
    {view === "settings" && <ForecastSettingsPanel ds={ds} />}
  </>);
}

// ------------------------------------------------------------------------------------------------
interface ReleaseInfo {
  records: number; series: number; replaced: number; at: string;
  cv_suggestions: { location: string; product: string; current: number | null; suggested: number }[];
}

function ReleaseBanner({ info, ds, onClose }: { info: ReleaseInfo; ds: Dataset; onClose: () => void }) {
  const apply = () => store.update((d) => {
    for (const c of info.cv_suggestions) {
      const lp = d.location_products?.find((x) => x.location === c.location && x.product === c.product);
      if (lp?.safety_stock) lp.safety_stock.demand_cv = c.suggested;
    }
  });
  const applicable = info.cv_suggestions.filter((c) => ds.location_products?.some((x) => x.location === c.location && x.product === c.product));
  return (
    <div className="banner info">
      <Badge sev="ok">Released</Badge>
      <span>{info.records} forecast records for {info.series} series written to demand at {info.at} (replaced {info.replaced}).
        The supply plan is now stale. Undo reverts the release.</span>
      <span className="spacer" />
      {applicable.length > 0 && <button className="btn sm" onClick={apply}>Size safety stock from forecast error ({applicable.length} item{applicable.length === 1 ? "" : "s"})</button>}
      <a className="btn sm" href={href("plan")}>Open supply plan</a>
      <button className="btn sm ghost" onClick={onClose} aria-label="Dismiss">✕</button>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Overview({ fc }: { fc: ForecastResult }) {
  const s = fc.summary;
  const [cell, setCell] = useState<string | null>(null);
  const matrix = useMemo(() => {
    const m = new Map<string, number>();
    fc.series.forEach((x) => m.set(`${x.segment.abc}${x.segment.xyz}`, (m.get(`${x.segment.abc}${x.segment.xyz}`) ?? 0) + 1));
    return m;
  }, [fc]);
  const champions = Object.entries(s.champions).sort((a, b) => b[1] - a[1]);
  const maxC = Math.max(1, ...champions.map(([, v]) => v));
  const label = (id: string) => fc.series.find((x) => x.champion === id)?.champion_label ?? (id === "npi" ? "NPI curve" : id === "average" ? "Average (short history)" : id);
  const filtered = cell ? fc.series.filter((x) => `${x.segment.abc}${x.segment.xyz}` === cell) : fc.series;
  return (
    <div className="stack">
      <div className="grid-auto">
        <StatTile label="Series" value={s.series} sub={`${fc.periods.length} ${fc.period}s ahead`} />
        <StatTile label="Backtest WAPE" value={pct(s.wape)} sub="volume-weighted, champions" tone="hl" />
        <StatTile label="Bias" value={pct(s.bias)} sub={s.bias !== null && s.bias > 0 ? "over-forecast" : "under-forecast"} />
        <StatTile label="Value added vs naïve" value={s.fva === null ? "—" : `${(s.fva * 100).toFixed(1)} pts`} sub="WAPE points saved" />
        <StatTile label="Forecast volume" value={qty(s.total_final)} sub="units in horizon (released)" />
      </div>
      <Reading formula={<>WAPE = Σ|forecast − actual| ÷ Σ actual over rolling backtest origins; bias = Σ(forecast − actual) ÷ Σ actual;
        value added = naïve WAPE − champion WAPE.</>}
        soWhat={s.fva !== null && s.fva > 0 ? `The chosen models beat a naïve forecast by ${(s.fva * 100).toFixed(1)} WAPE points: the statistics are earning their keep.`
          : "The models do not beat a naïve forecast on this history. Check for structural breaks, or rely on consensus input."} />
      <div className="grid-2">
        <Panel title="ABC × XYZ segmentation">
          <div className="row" style={{ alignItems: "flex-start", gap: 18, flexWrap: "wrap" }}>
            <div className="matrix" style={{ gridTemplateColumns: "44px repeat(3, 64px)" }} role="grid" aria-label="ABC XYZ matrix">
              <div className="h" />{["X", "Y", "Z"].map((x) => <div key={x} className="h">{x}</div>)}
              {["A", "B", "C"].map((a) => (
                <Fragment key={a}>
                  <div className="h">{a}</div>
                  {["X", "Y", "Z"].map((x) => {
                    const k = `${a}${x}`;
                    const n = matrix.get(k) ?? 0;
                    return (
                      <div key={k} role="gridcell" onClick={() => n && setCell(cell === k ? null : k)}
                        style={{ cursor: n ? "pointer" : "default", background: cell === k ? "var(--hl)" : n ? "var(--surface)" : "var(--surface-2)",
                          color: cell === k ? "var(--on-hl)" : n ? "var(--text)" : "var(--text-3)" }}>{n || "·"}</div>
                    );
                  })}
                </Fragment>
              ))}
            </div>
            <div className="small muted" style={{ maxWidth: 320 }}>
              <b>ABC</b> ranks series by revenue share (A = top 80 %). <b>XYZ</b> ranks by forecast-error CV (X &lt; 0.5 &lt; Y &lt; 1.0 &lt; Z).
              Together they set the suggested service level: AX items get 98 %, CZ items 90 %. Click a cell to filter.
            </div>
          </div>
        </Panel>
        <Panel title="Champion models">
          <div className="bar-list">
            {champions.map(([id, n]) => (
              <div key={id} className="bar-row">
                <span className="small" title={label(id)} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label(id)}</span>
                <div className="bar-track"><div className="bar-fill" style={{ width: `${(n / maxC) * 100}%` }} /></div>
                <span className="num small">{n} series</span>
              </div>
            ))}
          </div>
          <div className="small muted" style={{ marginTop: 8 }}>Demand patterns: {Object.entries(s.patterns).map(([p, n]) => `${n} ${p}`).join(" · ")}</div>
        </Panel>
      </div>
      <FoundationPanel fc={fc} />
      <Panel flush title={<h3>{cell ? `Series in ${cell}` : "All series"}</h3>} actions={cell && <button className="btn sm" onClick={() => setCell(null)}>Clear filter</button>}>
        <SeriesTable series={filtered} />
      </Panel>
    </div>
  );
}

function FoundationPanel({ fc }: { fc: ForecastResult }) {
  const f = fc.foundation;
  const [models, setModels] = useState<ForecastModels | null>(null);
  useEffect(() => { api.forecastModels().then(setModels).catch(() => setModels(null)); }, []);
  const st = models?.foundation ?? f;
  return (
    <Panel title="Foundation model: Google TimesFM" actions={
      st.available ? <Badge sev="ok">Loaded</Badge> : st.enabled ? <Badge sev="warning">Enabled, not loaded</Badge> : <Badge>Off</Badge>}>
      <div className="small" style={{ maxWidth: 900 }}>
        <p style={{ marginTop: 0 }}>TimesFM is a pretrained time-series transformer that forecasts zero-shot. Here it is one more candidate in
          the competition, scored on the same backtest, so it only becomes a series' champion where it measurably beats the statistical
          models. It runs on the engine host, never in the browser.</p>
        <p className="muted" style={{ marginBottom: 0 }}><b>Status:</b> {st.detail.replace(/\.$/, "")}{st.license && <> · licence {st.license}</>}.
          {" "}TimesFM 2.5 weights are Apache-2.0; TimesFM 3.0 weights are non-commercial and refused by default.</p>
      </div>
    </Panel>
  );
}

function SeriesTable({ series }: { series: ForecastSeries[] }) {
  return (
    <div className="table-wrap" style={{ maxHeight: 460 }}>
      <table className="t nowrap">
        <thead><tr><th>Location</th><th>Product</th><th>ABC</th><th>XYZ</th><th>Pattern</th><th>Champion</th>
          <th className="num">WAPE</th><th className="num">Bias</th><th className="num">Value added</th><th className="num">Next 4 periods</th></tr></thead>
        <tbody>
          {series.map((s) => {
            const champ = s.leaderboard.find((m) => m.model === s.champion);
            const next = s.forecast.slice(0, 4).reduce((a, p) => a + p.final, 0);
            return (
              <tr key={s.key} className="clickable" onClick={() => go("demand", "series", s.key)}>
                <td>{s.location}</td><td><b>{s.product}</b></td>
                <td><Badge>{s.segment.abc}</Badge></td><td><Badge>{s.segment.xyz}</Badge></td>
                <td title={PATTERN_HELP[s.segment.pattern]}>{s.segment.pattern}{s.segment.lifecycle !== "mature" && <> · <span className="faint">{s.segment.lifecycle}</span></>}</td>
                <td>{s.champion_label}</td>
                <td className="num">{pct(champ?.wape)}</td>
                <td className="num">{pct(champ?.bias)}</td>
                <td className="num">{s.fva === null ? "—" : `${(s.fva * 100).toFixed(1)} pts`}</td>
                <td className="num">{qty(next)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function Workbench({ fc, sel }: { fc: ForecastResult; sel?: string }) {
  const [q, setQ] = useState("");
  const current = fc.series.find((s) => s.key === sel) ?? fc.series[0];
  const list = fc.series.filter((s) => !q || `${s.location} ${s.product}`.toLowerCase().includes(q.toLowerCase()));
  if (!current) return <Panel><Empty title="No series to forecast" /></Panel>;
  return (
    <div className="split" style={cols("minmax(220px, 280px) minmax(0, 1fr)")}>
      <Panel flush title={<input className="input" placeholder="Filter series…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter series" />}>
        <div className="table-wrap" style={{ maxHeight: "calc(100vh - 260px)" }}>
          <table className="t">
            <tbody>
              {list.map((s) => (
                <tr key={s.key} className={`clickable ${s.key === current.key ? "selected" : ""}`} onClick={() => go("demand", "series", s.key)}>
                  <td><b>{s.product}</b><div className="faint small">{s.location}</div></td>
                  <td className="num"><Badge>{s.segment.abc}{s.segment.xyz}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <SeriesDetail s={current} fc={fc} />
    </div>
  );
}

function SeriesDetail({ s, fc }: { s: ForecastSeries; fc: ForecastResult }) {
  const intervalSetting = useStore((x) => x.dataset?.forecasting?.interval);
  const hist = s.history;
  const fut = s.forecast;
  const short = (l: string) => l.replace(/^W\d+ /, "");
  const labels = [...hist.map((h) => short(h.label)), ...fut.map((p) => short(p.label))];
  const H = hist.length;
  const pad = (a: (number | null)[], before: number, after: number) => [...Array(before).fill(null), ...a, ...Array(after).fill(null)];
  const backtest = new Map<string, number>();
  s.backtest.filter((b) => b.step === 1).forEach((b) => backtest.set(b.start, b.forecast));
  const spans: Span[] = [];
  let open: Span | null = null;
  const eventAt = (i: number) => (i < H ? hist[i].flag === "event" ? hist[i].events.join(", ") : "" : fut[i - H].events.join(", "));
  labels.forEach((_, i) => {
    const e = eventAt(i);
    if (e && open && open.label === e && open.to === i - 1) open.to = i;
    else if (e) { open = { from: i, to: i, label: e }; spans.push(open); }
  });
  const marks: Mark[] = hist.flatMap((h, i) => h.flag ? [{ i, v: h.raw, shape: h.flag === "event" ? "triangle" : "cross",
    label: `${h.flag === "event" ? "Event" : "Outlier"}: ${qty(h.raw)} cleansed to ${qty(h.cleaned)}` } as Mark] : []);
  const interval = Math.round((intervalSetting ?? 0.8) * 100);
  const lo = (100 - interval) / 2;
  const champ = s.leaderboard.find((m) => m.model === s.champion);
  const flagged = hist.filter((h) => h.flag);
  return (
    <div className="stack" style={{ minWidth: 0 }}>
      <Panel title={<div className="row wrap" style={{ gap: 8 }}>
        <h3>{s.product} @ {s.location}</h3>
        <Badge sev="info">{s.segment.abc}{s.segment.xyz}</Badge><Badge>{s.segment.pattern}</Badge>
        {s.segment.lifecycle !== "mature" && <Badge sev="warning">{s.segment.lifecycle}</Badge>}
        <span className="faint small">Champion: <b>{s.champion_label || "—"}</b>{champ && <> · WAPE {pct(champ.wape)} · MASE {champ.mase?.toFixed(2)}</>}</span>
      </div>}>
        <BucketChart labels={labels} height={280} divider={H} dividerLabel="TODAY" spans={spans} marks={marks}
          series={[
            { name: "Actual (raw)", color: "var(--text-3)", values: pad(hist.map((h) => h.raw), 0, fut.length) },
            { name: "Cleansed", color: "var(--series-1)", values: pad(hist.map((h) => h.cleaned), 0, fut.length) },
            { name: "Backtest (1 ahead)", color: "var(--series-2)", kind: "dots", values: pad(hist.map((h) => backtest.get(h.start) ?? null), 0, fut.length) },
            { name: "Statistical", color: "var(--series-7)", dash: true, values: pad(fut.map((p) => p.statistical * p.event_factor), H, 0) },
            { name: "Consensus (final)", color: "var(--series-1)", dash: true, values: pad(fut.map((p) => p.final), H, 0) },
          ]}
          band={{ name: `P${lo}–P${100 - lo} range`, color: "var(--series-1)", lower: pad(fut.map((p) => p.lower), H, 0), upper: pad(fut.map((p) => p.upper), H, 0) }} />
        {s.notes.length > 0 && <div className="banner warning" style={{ marginTop: 10, marginBottom: 0 }}>{s.notes.join(" ")}</div>}
      </Panel>
      <div className="grid-2">
        <Panel flush title="Model leaderboard">
          <div className="table-wrap">
            <table className="t nowrap">
              <thead><tr><th>#</th><th>Model</th><th className="num">MASE</th><th className="num">WAPE</th><th className="num">Bias</th><th className="num">RMSE</th></tr></thead>
              <tbody>
                {s.leaderboard.map((m) => (
                  <tr key={m.model} className={m.model === s.champion ? "selected" : ""} title={m.reason}>
                    <td className="num">{m.rank ?? "—"}</td>
                    <td>{m.label}{!m.eligible && <div className="faint small">{m.reason}</div>}</td>
                    <td className="num">{m.mase?.toFixed(2) ?? "—"}</td><td className="num">{pct(m.wape)}</td>
                    <td className="num">{pct(m.bias)}</td><td className="num">{m.rmse === null ? "—" : qty(m.rmse)}</td>
                  </tr>
                ))}
                {!s.leaderboard.length && <tr><td colSpan={6} className="faint">No competition: {s.champion_label}</td></tr>}
              </tbody>
            </table>
          </div>
          <div style={{ padding: "0 12px 12px" }}>
            <Reading formula={<>MASE = MAE ÷ mean |yₜ − yₜ₋₁| (below 1 beats a naïve one-step forecast). Backtest: {fc.series.length ? "rolling origins spread over the last season" : ""}.</>}
              soWhat={s.fva !== null ? `${s.champion_label} saves ${(s.fva * 100).toFixed(1)} WAPE points over naïve on this series.` : undefined} />
          </div>
        </Panel>
        <Panel title="Segment & variability">
          <table className="t">
            <tbody>
              <tr><td>ABC (revenue share)</td><td className="num"><b>{s.segment.abc}</b> · {pct(s.segment.revenue_share)}</td></tr>
              <tr><td>XYZ (forecast-error CV)</td><td className="num"><b>{s.segment.xyz}</b> · {s.segment.error_cv?.toFixed(2) ?? "—"}</td></tr>
              <tr><td>Pattern (ADI / CV²)</td><td className="num"><b>{s.segment.pattern}</b> · {s.segment.adi?.toFixed(2) ?? "—"} / {s.segment.cv2?.toFixed(2) ?? "—"}</td></tr>
              <tr><td>σ of 1-period error</td><td className="num">{s.sigma_one_step === null ? "—" : qty(s.sigma_one_step)}</td></tr>
              <tr><td>Weekly demand CV → safety stock</td><td className="num"><b>{s.demand_cv_weekly?.toFixed(3) ?? "—"}</b></td></tr>
              <tr><td>Suggested service level</td><td className="num"><b>{pct(s.segment.suggested_service_level, 0)}</b></td></tr>
              {Object.entries(s.lifts).map(([k, v]) => <tr key={k}><td>Measured {k} lift</td><td className="num">{pct(v)}</td></tr>)}
            </tbody>
          </table>
          <Reading formula="ADI = periods ÷ non-zero periods; CV² = (σ ÷ μ of non-zero sizes)². Smooth < 1.32 ADI and < 0.49 CV²."
            soWhat="Safety stock uses the forecast error, not raw demand variance: a good forecast lowers the buffer you need." />
        </Panel>
      </div>
      <Panel flush title="Forecast by period">
        <PeriodTable s={s} />
      </Panel>
      {flagged.length > 0 && (
        <Panel flush title={`History cleansing (${flagged.length})`}>
          <div className="table-wrap" style={{ maxHeight: 260 }}>
            <table className="t nowrap">
              <thead><tr><th>Period</th><th>Reason</th><th className="num">Raw</th><th className="num">Cleansed</th><th>Events</th></tr></thead>
              <tbody>{flagged.map((h) => (
                <tr key={h.start}><td>{h.label}</td><td>{h.flag === "event" ? "Event / promo: baseline from neighbours" : "Outlier: clipped to robust bound"}</td>
                  <td className="num">{qty(h.raw)}</td><td className="num">{qty(h.cleaned)}</td><td>{h.events.join(", ")}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}

function PeriodTable({ s }: { s: ForecastSeries }) {
  return (
    <div className="table-wrap">
      <table className="t nowrap">
        <thead><tr><th>Period</th><th className="num">Statistical</th><th className="num">Event ×</th><th>Events</th>
          <th className="num">Cannibalised</th><th className="num">Override</th><th className="num">Final</th><th className="num">Range</th><th className="num">Released</th></tr></thead>
        <tbody>{s.forecast.map((p) => (
          <tr key={p.start}>
            <td>{p.label}{p.share < 1 && <span className="faint small"> ({Math.round(p.share * 100)}% in horizon)</span>}</td>
            <td className="num">{qty(p.statistical)}</td>
            <td className="num">{p.event_factor === 1 ? "" : p.event_factor.toFixed(2)}</td>
            <td>{p.events.join(", ")}</td>
            <td className="num">{p.cannibalised ? `−${qty(p.cannibalised)}` : ""}</td>
            <td className="num" title={p.override_reason}>{p.override === null ? "" : qty(p.override)}</td>
            <td className="num"><b>{qty(p.final)}</b></td>
            <td className="num faint">{qty(p.lower)}–{qty(p.upper)}</td>
            <td className="num">{qty(p.released_qty)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
/** The IBP-style planning grid: series × periods, with consensus overrides typed straight into cells. */
function Consensus({ fc, ds }: { fc: ForecastResult; ds: Dataset }) {
  const periods = fc.series[0]?.forecast ?? [];
  const totals = periods.map((_, i) => fc.series.reduce((a, s) => a + s.forecast[i].final, 0));
  const setOverride = (s: ForecastSeries, p: ForecastPoint, raw: string) => {
    const v = raw.trim() === "" ? null : Number(raw);
    if (v !== null && (!Number.isFinite(v) || v < 0)) return;
    store.update((d) => {
      d.overrides = (d.overrides ?? []).filter((o) => !(o.location === s.location && o.product === s.product && o.date >= p.start && o.date < p.end));
      if (v !== null) d.overrides.push({ location: s.location, product: s.product, date: p.start, qty: v, change: null, reason: "Consensus grid", author: "" });
    });
    void store.run("forecast");
  };
  return (
    <div className="stack">
      <div className="banner info">Type a quantity into a cell to set a consensus override for that period; clear it to fall back to the
        statistical forecast. The forecast re-runs after each edit. {ds.overrides?.length ?? 0} overrides in the dataset.</div>
      <Panel flush>
        <div className="table-wrap" style={{ maxHeight: "calc(100vh - 290px)" }}>
          <table className="t nowrap">
            <thead><tr><th className="stub">Series</th>{periods.map((p) => <th key={p.start} className="num">{p.label.replace(/^W\d+ /, "")}</th>)}</tr></thead>
            <tbody>
              {fc.series.map((s) => (
                <tr key={s.key}>
                  <td className="stub"><a href={href("demand", "series", s.key)}>{s.product}</a> <span className="faint small">{s.location}</span></td>
                  {s.forecast.map((p) => (
                    <td key={p.start} className={`num ${p.override !== null ? "edit" : ""}`} title={`Statistical ${qty(p.statistical * p.event_factor)}${p.override_reason ? ` · ${p.override_reason}` : ""}`}>
                      <input className="cell" defaultValue={p.override !== null ? String(Math.round(p.override)) : ""}
                        placeholder={qty(p.final)} aria-label={`${s.product} ${s.location} ${day(p.start)}`}
                        key={`${p.start}-${p.override}`}
                        onBlur={(e) => { if (e.target.value !== (p.override !== null ? String(Math.round(p.override)) : "")) setOverride(s, p, e.target.value); }}
                        onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
                    </td>
                  ))}
                </tr>
              ))}
              <tr className="emph"><td className="stub">Total</td>{totals.map((t, i) => <td key={i} className="num">{qty(t)}</td>)}</tr>
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------
function ForecastSettingsPanel({ ds }: { ds: Dataset }) {
  const [models, setModels] = useState<ForecastModels | null>(null);
  useEffect(() => { api.forecastModels().then(setModels).catch(() => setModels(null)); }, []);
  const schemaErrors = useStore((s) => s.schemaErrors);
  const errors: Record<string, string> = {};
  for (const e of schemaErrors) {
    const loc = e.loc[0] === "body" ? e.loc.slice(1) : e.loc;
    if (loc[0] === "forecasting") errors[loc.slice(1).join(".")] = e.msg;
  }
  return (
    <div className="grid-2" style={{ alignItems: "start" }}>
      <Panel title="Forecast settings">
        <SchemaForm defName="ForecastSettings" value={(ds.forecasting ?? {}) as unknown as Obj} errors={errors}
          onChange={(next) => store.update((d) => { d.forecasting = next as unknown as Dataset["forecasting"]; })} />
      </Panel>
      <Panel flush title="Model library">
        <table className="t">
          <tbody>
            {models?.models.map((m) => (
              <tr key={m.id}><td><b>{m.label}</b><div className="faint small">{m.family}</div></td><td className="small">{m.description}</td></tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <SectionBand title="How the competition works" />
      <div />
      <Reading formula="Each candidate forecasts H periods from K rolling origins spread over the last season. Errors are pooled; the lowest selection metric wins; exact ties go to the simpler model."
        soWhat="Intermittent series only compete among Croston/SBA/TSB and the baselines; smooth series never use the intermittent models." />
    </div>
  );
}
