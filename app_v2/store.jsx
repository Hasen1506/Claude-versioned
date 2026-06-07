// ════════════════════════════════════════════════════════════════════════
// store.jsx — the WIRING SUBSTRATE for app_v2.
//
// Bridges the static prototype (mock `M`) to the REAL Flask backend
// (app.py + the PuLP/CBC solvers). Three pieces, all on `window`:
//
//   1. apiPost / apiGet  — one fetch wrapper, normalized errors + safe JSON.
//   2. useSolve(endpoint, buildPayload) — the {solving,result,error,run} pattern
//      that index.html repeats ~20×, factored into one hook.
//   3. appStore + useStore/useConfig/usePlanning/useCalendar — the live app state,
//      seeded in the REAL backend shape (a subset of index.html's defaultState).
//      Same external-store idiom as `profileStore` in lib.jsx (plain object +
//      subscriber Set + localStorage), so no React context / provider is needed
//      and every standalone stage function can read/write it.
//
// The state is grown SLICE BY SLICE as each stage is wired (setup → products →
// …). A field stays on mock `M` until its stage's wiring pass moves it here.
// Loaded right after lib.jsx (uses the React hook aliases it defines) and before
// data.jsx, so it has zero dependency on `M` at module-eval time.
// ════════════════════════════════════════════════════════════════════════

// ── 1. API client ─────────────────────────────────────────────────────────
async function _safeJson(r){ try{ return await r.json(); }catch(e){ return null; } }
async function apiPost(path, body){
  const r = await fetch(path, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body||{}) });
  const data = await _safeJson(r);
  if(!r.ok || !data || data.error){
    const err = new Error((data && data.error) || `${path} failed (HTTP ${r.status})`);
    err.status = r.status; err.data = data; throw err;
  }
  return data;
}
async function apiGet(path){
  const r = await fetch(path);
  const data = await _safeJson(r);
  if(!r.ok || !data || data.error){ throw new Error((data && data.error) || `${path} failed (HTTP ${r.status})`); }
  return data;
}

// ── 2. useSolve — solve-state hook (busy / result / error / run) ───────────
// run() resolves with the data and also stashes it; pass an explicit payload to
// override buildPayload(). ranAt is a Date for the Provenance/AsOf stamp.
//   opts.solveKey (LP-C — tab hydration): when given, this tab HYDRATES from the
//   cross-stage solve cache (solveResults[key]) until it runs its own solve, and
//   a successful run writes back to the cache. So after a full-loop run (which
//   caches every step) every tab keyed to a step shows the fresh chained number
//   without being re-run by hand — the full payoff of the W7 cache.
function useSolve(endpoint, buildPayload, opts){
  opts = opts || {};
  const key = opts.solveKey || null;
  const [solving, setSolving] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState(null);
  const [ranAt,   setRanAt]   = useState(null);
  // subscribe to the cache for this key (dummy key when unused — hooks stay unconditional).
  const cache = useSolveResult(key || '__nokey__');
  useEffect(()=>{
    // hydrate from the cache as a FALLBACK: only when this tab hasn't solved
    // locally yet (result == null). The tab's own run() always takes precedence.
    if(key && cache.result && !result){ setResult(cache.result); setRanAt(cache.ranAt || null); }
  }, [key, cache.result]); // eslint-disable-line
  const run = async (override)=>{
    setSolving(true); setError(null);
    try{
      const payload = (override!==undefined) ? override : (buildPayload ? buildPayload() : {});
      const data = await apiPost(endpoint, payload);
      setResult(data); setRanAt(new Date());
      if(key) cacheSolve(key, data);          // keep the cross-stage cache fresh
      return data;
    }catch(e){ setError(e.message || String(e)); setResult(null); throw e; }
    finally{ setSolving(false); }
  };
  const reset = ()=>{ setResult(null); setError(null); setRanAt(null); };
  return { solving, result, error, ranAt, run, reset };
}

// ── 3. appStore — live app state (real backend shape) ──────────────────────
// Seed = a faithful subset of index.html's `defaultState`, holding the firm's
// own TPAC figures so the wired Setup screen looks identical to the mock.
const _STATE_SEED = {
  config: {
    companyName:'Tata Precision Auto Components Pvt. Ltd.',
    currency:'₹', currencyName:'INR', currencyRate:1,
    taxRate:25.17, serviceLevel:0.95,
    // G-I2 — ABC-differentiated cycle-service targets. A global serviceLevel is wrong:
    // a high-value/critical A-item warrants a tighter fill than a long-tail C-item. The
    // per-SKU policy uses serviceLevelForSku() = abcService[sku.abc] ?? serviceLevel, so a
    // class-A SKU sizes safety stock at a higher z than a class-C one. B=0.95 == the global
    // default ⇒ B-items unchanged. The aggregated loop keeps the single global α.
    abcService:{ A:0.98, B:0.95, C:0.90 },
    // G-S3 — single-origin / single-supplier RM-spend concentration cap (share above which
    // the supply base is flagged as a resilience risk). Drives originConcentration() flags.
    originConcentrationCap:0.6,
    // G-P4 — production labor envelope (0 = unbounded ⇒ machine-constrained only, default).
    // headcount × 40 h/wk = regular labor budget; OT (capped) rides on top. A tight headcount
    // forces overtime to meet the hard demand, then infeasible if OT is also capped.
    prodLaborHeadcountCap:0, prodLaborOtCapHrs:0,
    // G-P2 — service-driven horizon-end cover for the aggregate S&OP plan. OFF by default
    // (enabled=false ⇒ no end_cover param sent ⇒ the plan may end at zero, byte-identical).
    // When ON, the aggregate floor I_T ≥ z(serviceLevel)·σ(agg_demand)·√cover_periods is
    // applied so the plan doesn't drain terminal stock. cover_periods = periods of demand-σ.
    planEndCoverEnabled:false, planEndCoverPeriods:1,
    // Inventory holding spread (% / yr) ABOVE the cost of capital — storage,
    // insurance, obsolescence, shrink. The full carry rate = blended WACC (live,
    // from Finance) + this spread (see carryRate()); seed 12.8 ⇒ ≈24%/yr total
    // at the seed WACC, so default procurement/policy economics are unchanged.
    invHoldingSpread:12.8,
    gstRegistered:true, city:'Chennai', plantState:'TN',
    // MSMED Act classification inputs — the tier is DERIVED from these (see msmeTier()).
    annualTurnoverCr:38.40,   // ₹ Cr
    investmentCr:9.40,        // ₹ Cr (plant & machinery)
    // FX table (₹ per 1 unit), as-of stamp; every $→₹ reads this.
    fxRates:{ USD:84.20, EUR:91.40, JPY:0.563 },
    fxAsOf:'30 May 2026 · 14:32 IST',
    // G-N3 — per-item STORAGE CLASS override (item → 'ambient'|'cold'|'hazmat'). Empty
    // ⇒ every item is ambient ⇒ node utilisation collapses to the single-cube number.
    storageClass:{},
    // G-SC1 — average FG inventory cover (weeks) used to amortise the SOLVED carry rate
    // into a per-unit holding cost in the TCO view. Governance knob; the RATE is solved.
    tcoCoverWeeks:6,
  },
  planning: {
    timeGrain:'week', horizonLength:52, startDate:'2026-06-01',
    workDaysPerWeek:6, indianHolidays:true,
    // G-P3 — net productive hours per shift (after breaks). With shifts (per line) and
    // workDaysPerWeek this makes available MACHINE-HOURS legible: Σmachines × shifts ×
    // hrsPerShift × workDays × OEE. A plant-wide default; lines vary by their own shifts.
    hrsPerShift:8,
    frozenWeeks:4, slushyWeeks:12,
    // Production-schedule fence (weeks): the MILP horizon for production /
    // procurement / linecap / montecarlo. A schedule is a fence (frozen+slushy
    // detail), NOT the full planning horizon — so this is a GOVERNED knob, not a
    // magic 13. Clamped to [4, this] off horizonLength in productionScheduleHorizon().
    productionScheduleWeeks:13,
  },
  // /api/calc/calendar output lands here (total_working_days, total_holidays, …).
  calendar: { result:null, computedAt:null },
  // per-SKU editable cost inputs (setup + labour); rollup derives material from BOM.
  // Empty until the user edits — reads fall back to seed defaults in useProductCosts().
  productCosts: {},
  // Network master data (nodes/lanes/suppliers/contracts/onHand). DEFINE-stage
  // single source of truth that the transport + procurement solvers read from.
  // Seeded LAZILY from mock `M` (see getNetwork) — empty here so we never
  // duplicate the figures; a slice key is populated only once it's edited.
  network: {},
  // KEYSTONE: per-SKU forecast demand series, written by the Demand stage when a
  // forecast solves (setItemDemand). The single source the procurement / production /
  // transport / capital LP payloads read via getItemDemand / getFinishedDemand —
  // so every downstream solver plans the SAME demand the forecast produced.
  // Empty until a forecast lands; reads fall back to M.products[].demand spread evenly.
  demand: {},
  // Imported / like-modeled HISTORY per SKU (W9 · D-7). histImports[sku] =
  // { grain, series, importedAt, source }. historyFor() prefers this over the seed
  // M.historyAt when the grain matches — so the forecast competes on REAL uploaded data.
  histImports: {},
  // G-I1 — production yield CONFIRMATIONS per SKU: yieldConfirmations[sku] =
  // [{started, good, ts, note}]. The MEASURED rolling yield = Σgood/Σstarted over
  // these batches replaces the typed-seed planning yield in every solve (skuYield()),
  // so yield becomes measured-from-the-floor, not assumed. Empty default ⇒ every solve
  // falls back to the typed M.products[].yield ⇒ byte-identical until a batch is logged.
  yieldConfirmations: {},
  // ── Orchestration foundations (W0 · P1, P2) ──────────────────────────────
  // solves: per-solver freshness ledger { <solveKey>: {stale, ranAt} }. A solve
  // goes STALE when an input it depends on (SOLVE_DEPS) changes; cleared when it
  // re-runs. Drives the "re-solve to trust these numbers" affordance per tab.
  solves: {},
  // events: append-only audit trail of every plan-changing action (override /
  // cancel / replan / actuals / commit). Never mutated or deleted.
  events: [],
  // ── Demand-shaping inputs (W1 · D-1/D-3) ─────────────────────────────────
  // Governed, per-SKU FORECAST inputs (distinct from `demand`, the committed
  // output). demandInputs[sku] = { promos:[{fidx,kind,lift}], lifecycle: phase|null }.
  // promos feed the forecast ML promo regressor; lifecycle is an OPT-IN phase tag
  // (null = no shaping — the default; the forecast already reflects recent demand).
  // Editing these never rewrites committed `demand` on its own — the forecast is
  // re-run / lifecycle is explicitly applied — so no number changes silently.
  demandInputs: {},
  // holidays: global ISO date list fed to the forecast calendar features so the
  // engine can down/up-weight known non-working / surge days.
  holidays: [],
  // ── Sourcing inputs (W2 · S-1/S-2) ───────────────────────────────────────
  // Governed, per-PART procurement inputs keyed by part code. Empty until edited;
  // reads fall back to sourcingDefault(bomRow) (honest seed provenance, overridable
  // — D-DEC-1 seeded-with-override). sourcing[part] = { imported, dutyFreightPct,
  // unitsPerTruck, costPerTruck }. dutyFreightPct lifts the part's raw cost into a
  // LANDED cost the procurement/policy MILP plans against (S-1); the truck fields
  // drive the stepwise inbound-freight curve (S-2, D-DEC-3 option b).
  sourcing: {},
  // ── Per-SKU BOM qty overrides (Ph2 · R7) ─────────────────────────────────
  // bomOverrides[sku][part] = { qty }. Empty until a planner tunes one FG's usage
  // of a part. The flat M.bom stays the PARTS MASTER (cost/lead/MOQ — shared); this
  // layer makes the qty-per genuinely per-product. Read via bomForSku() / _skuQty().
  bomOverrides: {},
  // ── Cross-stage solve-result cache (W7 · orchestration) ──────────────────
  // The latest result of each solver, keyed by solveKey, so a DOWNSTREAM stage
  // can read an UPSTREAM solve's real output without re-running it (each tab's
  // useSolve is local). markSolved(key, result) writes here; getSolveResult /
  // useSolveResult read it. This is what lets Risk simulate the SAME production
  // schedule Production solved, and lets runFullLoop() chain one solve into the
  // next on ONE dataset (W7 acceptance). { <solveKey>: {result, ranAt} }.
  solveResults: {},
  // ── Scenario engine (W10/W11 · Platform L4) ──────────────────────────────
  // Named branches of the input model + their last solved KPIs. list[id] =
  // { id, name, note, parent, createdAt, inputs:{<slice snapshots>}, kpis, ranAt }.
  // `active` = which branch the live working set currently mirrors ('base' = the
  // unsaved live edits). See §4½ — branch · run (transparent) · compare · merge.
  scenarios: { list:{}, order:[], active:'base' },
};

const appStore = {
  s: (()=>{ try{ const raw=localStorage.getItem('es_state'); const s = raw?JSON.parse(raw):null;
    // ── Ph2 migrations (run once on load, idempotent) ──────────────────────
    // Service-level dedup: fold the legacy config.serviceLevelOverride into the
    // single canonical config.serviceLevel, then drop it. (Setup + Sourcing now
    // edit one shared field; effServiceLevel reads serviceLevel.)
    if(s && s.config && ('serviceLevelOverride' in s.config)){
      const had = s.config.serviceLevelOverride;
      if(had!=null && had!=='') s.config.serviceLevel = Number(had);
      delete s.config.serviceLevelOverride;
      // audit the one-time migration into the existing events[] (logEvent isn't defined
      // yet at IIFE time, so append a matching record directly to the loaded trail).
      if(Array.isArray(s.events)){
        s.events.push({ id: s.events.length ? s.events[s.events.length-1].id+1 : 1,
          type:'migration', target:'serviceLevelOverride→serviceLevel',
          detail:{ folded: (had!=null && had!=='') ? Number(had) : null }, ts:new Date().toISOString() });
      }
    }
    return s; }catch(e){ return null; } })(),
  subs: new Set(),
  get(){ if(!this.s){ this.s = JSON.parse(JSON.stringify(_STATE_SEED)); } return this.s; },
  // patch is shallow-merged per top-level slice: set({config:{taxRate:18}}) keeps the
  // rest of config intact. Pass a whole slice to replace deeper structures.
  set(patch){
    const cur = this.get(); const next = { ...cur };
    for(const k of Object.keys(patch)){
      next[k] = (patch[k] && typeof patch[k]==='object' && !Array.isArray(patch[k]) && cur[k] && typeof cur[k]==='object')
        ? { ...cur[k], ...patch[k] } : patch[k];
    }
    this.s = next;
    try{ localStorage.setItem('es_state', JSON.stringify(next)); }catch(e){}
    this.subs.forEach(f=>f());
  },
  reset(){ this.s = JSON.parse(JSON.stringify(_STATE_SEED));
    try{ localStorage.removeItem('es_state'); }catch(e){} this.subs.forEach(f=>f()); },
  // replace: overwrite whole slices (no per-slice merge). Used by the scenario engine
  // so applying a scenario's input snapshot DROPS keys absent from it (true isolation) —
  // set() would leave a stale SKU/part behind. Persists + notifies like set().
  replace(patch){
    const next = { ...this.get() };
    for(const k of Object.keys(patch)) next[k] = patch[k];
    this.s = next;
    try{ localStorage.setItem('es_state', JSON.stringify(next)); }catch(e){}
    this.subs.forEach(f=>f());
  },
};

// useStore(selector?) — subscribes; returns the whole state or a selected slice.
// patch() shallow-merges a slice. Re-renders any component that reads it on change.
function useStore(selector){
  const [,force] = useState(0);
  useEffect(()=>{ const f=()=>force(x=>x+1); appStore.subs.add(f); return ()=>appStore.subs.delete(f); }, []);
  const state = appStore.get();
  return { state: selector ? selector(state) : state, patch:(p)=>appStore.set(p), store:appStore };
}
// thin per-slice helpers. setX flags the matching SOLVE_DEPS source stale so the
// recompute DAG (§4a) fires automatically from the write site — no stage has to
// remember to invalidate. (calendar is a derived cache, not a solver input.)
function useConfig(){   const { state, patch } = useStore(s=>s.config);   return { config:state,   setConfig:(p)=>{ patch({config:p}); configTokens(p).forEach(markStale); } }; }
function usePlanning(){  const { state, patch } = useStore(s=>s.planning); return { planning:state, setPlanning:(p)=>{ patch({planning:p}); markStale('planning'); } }; }
function useCalendar(){  const { state, patch } = useStore(s=>s.calendar); return { calendar:state, setCalendar:(p)=>patch({calendar:p}) }; }
// per-SKU cost inputs with seed-default fallback; patch merges this one SKU only.
function useProductCosts(sku, dflt){
  const { state, patch } = useStore(s=>s.productCosts||{});
  const costs = { ...dflt, ...(state[sku]||{}) };
  return { costs, setCosts:(p)=>{ patch({ productCosts:{ [sku]:{ ...costs, ...p } } }); markStale('productCosts'); } };
}

// ── Network master data — appStore slice with lazy mock-`M` fallback ───────
// Each array stays on mock `M` until edited, at which point the edited array
// lives in appStore.network[key]. getNetwork() is the plain (hook-free) reader
// so a buildPayload() in any solver stage (transport/procurement) can pull the
// same merged topology without a React hook.
const _NET_KEYS = ['nodes','lanes','suppliers','contracts','onHand','scheduledReceipts'];
function getNetwork(){
  const slice = appStore.get().network || {};
  const M = window.M || {};
  const out = {};
  for(const k of _NET_KEYS) out[k] = slice[k] || M[k] || [];
  return out;
}
// scheduledReceiptsLocked(): the open / in-transit POs (network.scheduledReceipts) mapped
// to the procurement MILP's locked_pos schema {part, qty, releaseDate}. procurement.py
// (T6) books each as an exogenous RM arrival at releaseDate+lead and re-optimises only the
// residual gap — so an inbound PO NETS DOWN the planned buy (MRP stops re-ordering what's
// already on the water). Needs horizon_start_date in params for the date→period math.
function scheduledReceiptsLocked(){
  const M = window.M || {};
  // procurement.py matches locked_pos by the part's payload `name` (= M.bom[].name, the
  // descriptive name bomParts sends), NOT the code — so translate code→name here, else
  // the lock is silently skipped (name_to_gidx miss). Falls back to the raw value.
  const nameByCode = {}; (M.bom||[]).forEach(b=>{ nameByCode[b.part]=b.name; });
  return (getNetwork().scheduledReceipts || [])
    .map(r=>({ part:(nameByCode[r.part] || r.part), qty:Number(r.qty)||0, releaseDate:r.releaseDate }))
    .filter(r=>r.part && r.qty>0 && r.releaseDate);
}
function useNetwork(){
  const { state, patch } = useStore(s=>s.network||{});
  const M = window.M || {};
  const network = {};
  for(const k of _NET_KEYS) network[k] = state[k] || M[k] || [];
  return { network, setNetwork:(p)=>{ patch({ network:{ ...state, ...p } }); markStale('network'); } };
}

// firmOrderDemand(sku,T): the contracted FIRM (status==='firm') MTO order book for a
// SKU, bucketed into T periods by DUE DATE — lumpy, the way real make-to-order demand
// arrives. periodDays = horizonDays/T (so a due date maps to the same bucket whatever
// T or grain the caller asks for, matching the seed's annual/T convention). Past-due →
// bucket 0; beyond the window → last bucket. Returns null when the SKU has no firm
// orders (so the caller falls through to the seed). 'planned' orders are NOT a
// commitment and are excluded — same rule as _firmOrderFloor in profitmixPayload.
function firmOrderDemand(sku, T){
  const M = window.M || {};
  const orders = (M.orders || []).filter(o=>o.sku===sku && o.status==='firm');
  if(!orders.length) return null;
  const pl = appStore.get().planning || {};
  const start = new Date(pl.startDate || '2026-06-01');
  const grainDays = pl.timeGrain==='week'?7 : pl.timeGrain==='day'?1 : 30;
  const horizonDays = Math.max(1, Number(pl.horizonLength) || 52) * grainDays;
  const periodDays = Math.max(1, horizonDays / T);
  const series = Array(T).fill(0);
  for(const o of orders){
    const due = new Date(o.due);
    let idx = 0;
    if(!isNaN(due.getTime()) && !isNaN(start.getTime()))
      idx = Math.floor((due - start) / (periodDays * 86400000));
    idx = Math.max(0, Math.min(T-1, idx));    // clamp into the window
    series[idx] += Math.max(0, Number(o.qty) || 0);
  }
  return series;
}
// ── Demand series (KEYSTONE) — the shared per-SKU forecast the solvers plan to ──
// getItemDemand(sku,T): the forecast series the Demand stage wrote, resampled to T
// periods. When no forecast is committed yet, FALL BACK with forecast-consumption
// (G-D1): demand[t] = max(seed-spread[t], firm-order[t]) — the standard APS rule that
// firm orders CONSUME the forecast, and when they exceed it the contracted order wins.
// This is what makes a pure-MTO SKU (firm orders, no forecast) reach the production /
// procurement schedule instead of silently planning to a flat seed that ignores its
// order book. (Once the planner commits a forecast, that committed series is used as-is
// — extending consumption onto the committed path is a separate, baseline-moving change.)
// setItemDemand(sku,series): the Demand stage calls this when a forecast solves.
function getItemDemand(sku, T){
  T = Math.max(1, T || 12);
  const stored = (appStore.get().demand || {})[sku];
  const M = window.M || {};
  let series;
  if(stored && stored.length){ series = stored; }
  else {
    const p = (M.products || []).find(x=>x.sku===sku);
    const annual = p ? p.demand : 1200;
    const seed = Array(T).fill(Math.round(annual / T));
    const firm = firmOrderDemand(sku, T);          // contracted MTO book (or null)
    series = firm ? seed.map((v,i)=>Math.max(v, firm[i])) : seed;
  }
  const out = [];
  for(let i=0;i<T;i++) out.push(Math.max(0, Math.round(series[i % series.length] || 0)));
  return out;
}
function setItemDemand(sku, series){
  if(!sku || !Array.isArray(series) || !series.length) return;
  const slice = { ...(appStore.get().demand || {}) };
  slice[sku] = series.map(v=>Math.max(0, Math.round(v||0)));
  appStore.set({ demand:slice });
  markStale('demand');   // every downstream solver now plans to stale demand
}
function getFinishedDemand(T){
  const M = window.M || {};
  return (M.products || []).filter(p=>p.cat==='Finished')
    .map(p=>({ sku:p.sku, name:p.name, demand:getItemDemand(p.sku, T) }));
}

// ── Demand commit semantics (per-tab domain fix · Demand D-1) ──────────────
// Visiting a SKU auto-runs the forecast, which populates a WORKING demand series
// so downstream solvers always have a number to plan against. But an auto-forecast
// is a PROPOSAL, not a commitment — merely viewing a SKU must NOT count as the
// planner committing its number to the plant. A SKU is COMMITTED only when an
// explicit commit-class action is recorded in the immutable event log: an explicit
// forecast-commit, an override, a demand-sensing replan, lifecycle shaping, or an
// NPI prior. DemCommit and the portfolio worklist test THIS, not "demand[sku] exists".
const DEMAND_COMMIT_EVENTS = new Set(['forecast_commit','override','replan','lifecycle','npi_likemodel']);
function demandCommitEvent(code, events){
  if(!code || !Array.isArray(events)) return null;
  for(let i=events.length-1; i>=0; i--){ const e=events[i];
    if(e && e.target===code && DEMAND_COMMIT_EVENTS.has(e.type)) return e; }
  return null;
}
function isDemandCommitted(code, events){ return !!demandCommitEvent(code, events); }

// ── Imported / like-modeled HISTORY (W9 · D-7 CSV import, NPI like-modeling) ──
// histImports[sku] = { grain, series:[...], importedAt, source }. When present and
// its grain matches the requested grain, historyFor() returns it INSTEAD of the
// seed M.historyAt — so the forecast engine competes models on the user's REAL
// uploaded history (D-7) or an analog-scaled NPI prior. Tagged by grain so a
// monthly upload never masquerades as a daily series (honest — switch grain to
// forecast on it). Editing re-flags demand stale so the forecast re-runs.
function getHistoryImport(sku){ return (appStore.get().histImports || {})[sku] || null; }
function setHistoryImport(sku, rec){
  if(!sku) return;
  const cur = { ...(appStore.get().histImports || {}) };
  if(rec) cur[sku] = rec; else delete cur[sku];
  appStore.set({ histImports: cur });
  markStale('demand');
}
function useHistoryImport(sku){
  const { state } = useStore(s=>s.histImports || {});
  return { imp: state[sku] || null, setImp:(rec)=>setHistoryImport(sku, rec) };
}
// ── G-I1 · measured yield from production confirmations ──────────────────────
// A real shop measures yield = good ÷ started off the floor, not by assuming a
// number. measuredYield(sku) is the rolling ratio over all logged confirmation
// batches (Σgood/Σstarted); null when none ⇒ planning keeps the typed seed.
function getYieldConfirmations(sku){ return (appStore.get().yieldConfirmations || {})[sku] || []; }
function measuredYield(sku){
  const conf = getYieldConfirmations(sku);
  let started=0, good=0;
  for(const c of conf){ started += Number(c.started)||0; good += Number(c.good)||0; }
  return started > 0 ? Math.max(0.01, Math.min(1, good/started)) : null;
}
// skuYield(p, fallback): the yield EVERY solve should plan with — the measured
// rolling yield when confirmations exist, else the typed seed M.products[].yield,
// else the call-site fallback. No confirmations ⇒ returns the same seed as before
// ⇒ byte-identical. (Routing yieldPct overrides still win at their own call site.)
function skuYield(p, fallback){
  fallback = (fallback!=null) ? fallback : 0.95;
  const seed = (p && p.yield!=null && p.yield!=='') ? Number(p.yield) : fallback;
  const m = (p && p.sku) ? measuredYield(p.sku) : null;
  return (m!=null) ? m : seed;
}
function logYieldConfirmation(sku, started, good, note){
  started = Number(started)||0; good = Number(good)||0;
  if(!sku || started<=0) return;
  good = Math.max(0, Math.min(started, good));   // good can't exceed started
  const cur = { ...(appStore.get().yieldConfirmations || {}) };
  cur[sku] = [ ...(cur[sku]||[]), { started, good, ts:new Date().toISOString(), note:note||'' } ];
  appStore.set({ yieldConfirmations: cur });
  markStale('productCosts');   // re-stale every yield-consuming solve (cascades to montecarlo)
  logEvent('confirm', 'yield-confirmation', { sku, started, good, measured: measuredYield(sku) });
}
function clearYieldConfirmations(sku){
  // NOTE: appStore.set shallow-MERGES per slice, so deleting a key here would be undone
  // by the merge re-spreading the old key. Reset to [] instead — measuredYield treats an
  // empty list as "no data" (started=0 ⇒ null ⇒ falls back to the typed seed).
  const cur = { ...(appStore.get().yieldConfirmations || {}) };
  if(sku) cur[sku] = []; else { for(const k of Object.keys(cur)) cur[k] = []; }
  appStore.set({ yieldConfirmations: cur });
  markStale('productCosts');
  logEvent('confirm', 'yield-confirmation-clear', { sku: sku||'ALL' });
}
function useYieldConfirmations(sku){
  const { state } = useStore(s=>s.yieldConfirmations || {});
  return { confirmations: state[sku] || [], measured: measuredYield(sku),
    log:(started,good,note)=>logYieldConfirmation(sku,started,good,note),
    clear:()=>clearYieldConfirmations(sku) };
}
// historyFor(sku, grain): the history the forecast should consume — imported series
// when one exists at THIS grain, else the seed M.historyAt. Single resolver used by
// fcPayload + the loop forecast step so every forecast path honors an import.
function historyFor(sku, grain){
  const imp = getHistoryImport(sku);
  if(imp && imp.grain === grain && Array.isArray(imp.series) && imp.series.length) return imp.series.slice();
  const M = window.M || {};
  return (typeof M.historyAt === 'function') ? M.historyAt(sku, grain) : [];
}
// parseHistoryCsv(text): tolerant CSV/TSV → {rows:[{date?,val}], hasDates, error}.
// Detects a delimiter, skips a header row, and reads the LAST numeric column as the
// value (a leading parseable date column is captured for bucketing). Real ingestion,
// not a mock — the planner pastes their own series.
function parseHistoryCsv(text){
  const out = { rows:[], hasDates:false, error:null };
  const lines = String(text||'').split(/\r?\n/).map(l=>l.trim()).filter(l=>l.length);
  if(!lines.length){ out.error = 'empty input'; return out; }
  const delim = lines[0].indexOf('\t')>=0 ? '\t' : lines[0].indexOf(';')>=0 ? ';' : ',';
  const _num = (s)=>{ const v = Number(String(s).replace(/[, ]/g,'')); return isFinite(v)?v:null; };
  // Require a date-ish token (4-digit year or a -/ separator), so a bare integer
  // like "1" or "200" is never misread as a date (it's a value, not a column-0 date).
  const _date = (s)=>{ s=String(s).trim(); if(!/\d{4}|[-/]/.test(s)) return null; const d = new Date(s); return isNaN(d.getTime()) ? null : d; };
  // RFC-4180 quote-aware split: a delimiter INSIDE "..." is literal, so an Excel/
  // Sheets export of a thousands-grouped value ("1,200") stays one field, not two.
  const _split = (ln)=>{ const c=[]; let cur='', q=false;
    for(let i=0;i<ln.length;i++){ const ch=ln[i];
      if(ch==='"'){ if(q && ln[i+1]==='"'){ cur+='"'; i++; } else q=!q; }
      else if(ch===delim && !q){ c.push(cur); cur=''; } else cur+=ch; }
    c.push(cur); return c.map(x=>x.trim()); };
  lines.forEach((ln, i)=>{
    const cells = _split(ln);
    const d = cells.length>1 ? _date(cells[0]) : null;
    // dated row: column 0 is a real date ⇒ the value is the REST of the line, so an
    // UNQUOTED thousands-grouped value (2024-01-01,1,200) survives the comma-strip in
    // _num. (An unquoted value-ONLY thousands number stays ambiguous — quote it.)
    const val = d ? _num(cells.slice(1).join(delim)) : _num(cells[cells.length-1]);
    if(val==null){ if(i===0) return; /* header */ return; }   // skip non-numeric (header/junk)
    if(d) out.hasDates = true;
    out.rows.push({ date:d, val });
  });
  if(!out.rows.length) out.error = 'no numeric rows found';
  return out;
}
// bucketHistory(rows, hasDates, grain): roll the parsed rows up to the target grain.
// With dates → group by ISO month / ISO week / day (summing values in a bucket),
// chronologically. Without dates → take the values in file order (the planner's own
// pre-bucketed series). Returns a flat numeric array the forecast consumes.
function bucketHistory(rows, hasDates, grain){
  if(!hasDates) return rows.map(r=>Math.max(0, Math.round(r.val)));
  const key = (d)=>{
    if(grain==='monthly') return d.getUTCFullYear()+'-'+String(d.getUTCMonth()+1).padStart(2,'0');
    if(grain==='weekly'){ const t=new Date(Date.UTC(d.getUTCFullYear(),d.getUTCMonth(),d.getUTCDate()));
      const day=(t.getUTCDay()+6)%7; t.setUTCDate(t.getUTCDate()-day);
      return t.getUTCFullYear()+'-W'+String(Math.ceil(((t-new Date(Date.UTC(t.getUTCFullYear(),0,1)))/86400000+1)/7)).padStart(2,'0'); }
    return d.toISOString().slice(0,10);   // daily
  };
  const buckets = new Map();
  rows.slice().sort((a,b)=>a.date-b.date).forEach(r=>{ const k=key(r.date); buckets.set(k, (buckets.get(k)||0)+r.val); });
  return Array.from(buckets.values()).map(v=>Math.max(0, Math.round(v)));
}

// ── Multi-SKU ingestion (Demand · per-tab pass) — LONG and WIDE ───────────────
// Real ERP/BI exports arrive UNIFIED in two shapes; parseMultiSkuCsv auto-detects
// BOTH, groups by SKU, matches codes against the product master, and returns rows
// the importer buckets to the active grain and writes to histImports[sku] for EVERY
// product in ONE paste:
//   • WIDE / pivot  — sku down the side, DATES across the top (sku,2024-01,2024-02…);
//     how planners live in Excel/IBP. Each row = a product; the date columns are its series.
//   • LONG / tidy   — sku,date,value; EXTRA dimension columns (plant/channel/customer)
//     are ignored, and multiple rows per sku+date SUM to total demand (correct aggregation).
// Unknown codes are surfaced, not silently dropped. A plain ≤2-col date,value/value-only
// file is neither → the single-series path still owns it. Value-column pick prefers a
// QUANTITY name (units/qty/demand) over a generic value/amount/revenue.
function parseMultiSkuCsv(text){
  const out = { bySku:{}, order:[], layout:null, skuCol:null, dateCol:null, valCol:null, periods:0, hasHeader:false, error:null, unknown:[] };
  const lines = String(text||'').split(/\r?\n/).map(l=>l.trim()).filter(l=>l.length);
  if(lines.length < 2){ out.error='need a header + at least one row'; return out; }
  const delim = lines[0].indexOf('\t')>=0 ? '\t' : lines[0].indexOf(';')>=0 ? ';' : ',';
  const _num = (s)=>{ const v = Number(String(s).replace(/[, ]/g,'')); return isFinite(v)?v:null; };
  const _date = (s)=>{ s=String(s).trim(); if(!/\d{4}|[-/]/.test(s)) return null; const d=new Date(s); return isNaN(d.getTime())?null:d; };
  const _split = (ln)=>{ const c=[]; let cur='', q=false; for(let i=0;i<ln.length;i++){ const ch=ln[i];
    if(ch==='"'){ if(q&&ln[i+1]==='"'){cur+='"';i++;} else q=!q; } else if(ch===delim&&!q){ c.push(cur); cur=''; } else cur+=ch; }
    c.push(cur); return c.map(x=>x.trim()); };
  const grid = lines.map(_split);
  const ncol = Math.max(...grid.map(r=>r.length));
  if(ncol < 3){ out.error='not a multi-product file (need a sku column + date/value columns)'; return out; }
  const head = grid[0].map(s=>String(s).toLowerCase());
  const known = new Set(((window.M&&M.products)||[]).map(p=>p.sku));

  // ── WIDE / pivot: header row has a label column + ≥2 DATE columns (sku × periods) ──
  const headDateCols = grid[0].map((c,i)=> _date(c)!=null ? i : -1).filter(i=>i>=0);
  if(headDateCols.length >= 2){
    let skuCol = head.findIndex(h=>/sku|item|product|code|material|part|fg|name/.test(h));
    if(skuCol<0) skuCol = grid[0].findIndex((c,i)=> !headDateCols.includes(i) && _num(c)==null);   // first non-date label col
    if(skuCol<0) skuCol = 0;
    const hdates = headDateCols.map(i=>_date(grid[0][i]));
    grid.slice(1).forEach(r=>{ const sku=String(r[skuCol]||'').trim(); if(!sku) return;
      headDateCols.forEach((ci,k)=>{ const v=_num(r[ci]); if(v==null) return;
        if(!out.bySku[sku]){ out.bySku[sku]=[]; out.order.push(sku); }
        out.bySku[sku].push({ date:hdates[k], val:v }); }); });
    if(out.order.length){ out.layout='wide'; out.hasHeader=true; out.skuCol=skuCol; out.periods=headDateCols.length;
      out.unknown=out.order.filter(s=>!known.has(s)); return out; }
  }

  // ── LONG / tidy: sku,date,value (extra dims ignored; dup sku+date rows sum) ──
  out.hasHeader = grid[0].some(c=>/sku|item|product|code|material|part|fg|date|period|month|week|qty|quantit|unit|demand|sales|value|volume|amount|sold/.test(String(c).toLowerCase())) && !grid[0].some(c=>_date(c)!=null);
  const body = out.hasHeader ? grid.slice(1) : grid;
  if(!body.length){ out.error='no data rows'; return out; }
  const findCol = (re)=> out.hasHeader ? head.findIndex(h=>re.test(h)) : -1;
  let skuCol  = findCol(/sku|item|product|code|material|part|fg/);
  let dateCol = findCol(/date|period|month|week|day|time/);
  let valCol  = findCol(/qty|quantit|unit|demand|sold|volume/);   // prefer a QUANTITY column
  if(valCol<0) valCol = findCol(/sales|value|amount|revenue/);    // fall back to a generic value column
  const colMostly = (idx, test)=>{ let n=0,t=0; body.forEach(r=>{ const v=r[idx]; if(v!=null&&v!==''){ t++; if(test(v)) n++; } }); return t && n/t>=0.8; };
  if(dateCol<0) for(let c=0;c<ncol;c++){ if(colMostly(c, s=>_date(s)!=null)){ dateCol=c; break; } }
  if(valCol<0)  for(let c=0;c<ncol;c++){ if(c!==dateCol && colMostly(c, s=>_num(s)!=null)){ valCol=c; break; } }
  if(skuCol<0)  for(let c=0;c<ncol;c++){ if(c!==dateCol && c!==valCol && colMostly(c, s=>_num(s)==null && _date(s)==null)){ skuCol=c; break; } }
  if(skuCol<0 || dateCol<0 || valCol<0){ out.error='could not detect sku / date / value columns'; return out; }
  body.forEach(r=>{ const sku=String(r[skuCol]||'').trim(); const d=_date(r[dateCol]); const v=_num(r[valCol]);
    if(!sku || d==null || v==null) return;
    if(!out.bySku[sku]){ out.bySku[sku]=[]; out.order.push(sku); }
    out.bySku[sku].push({ date:d, val:v }); });
  if(!out.order.length){ out.error='no sku rows parsed'; return out; }
  out.layout='long'; out.skuCol=skuCol; out.dateCol=dateCol; out.valCol=valCol;
  out.unknown = out.order.filter(s=>!known.has(s));
  return out;
}
// Write a detected multi-SKU map to histImports[sku] for every KNOWN product, bucketed
// to the active grain. Returns the list of SKUs actually written (unknown codes skipped).
function importManyHistory(bySku, grain){
  const known = new Set(((window.M&&M.products)||[]).map(p=>p.sku));
  const cur = { ...(appStore.get().histImports || {}) };
  const written = [];
  Object.keys(bySku||{}).forEach(sku=>{ if(!known.has(sku)) return;
    const series = bucketHistory(bySku[sku], true, grain);
    if(series.length){ cur[sku] = { grain, series, importedAt:new Date().toISOString(), source:'csv-multi' }; written.push(sku); } });
  if(written.length){ appStore.set({ histImports: cur }); markStale('demand'); }
  return written;
}

// ── Demand-shaping inputs (W1 · D-1/D-3) — governed per-SKU forecast inputs ──
// getDemandInputs(sku): hook-free reader so fcPayload() can pull promos/lifecycle
// without a React hook. Always returns a fully-shaped object (never undefined).
function getDemandInputs(sku){
  const di = (appStore.get().demandInputs || {})[sku] || {};
  return { promos: di.promos || [], lifecycle: di.lifecycle || null };
}
function useDemandInputs(sku){
  const { state, patch } = useStore(s=>s.demandInputs||{});
  const cur = state[sku] || {};
  const di = { promos: cur.promos || [], lifecycle: cur.lifecycle || null };
  // merge this one SKU only; arrays in `p` replace wholesale (intended for promos).
  return { di, setDI:(p)=>patch({ demandInputs:{ [sku]:{ ...di, ...p } } }) };
}
function useHolidays(){
  const { state, patch } = useStore(s=>s.holidays||[]);
  return { holidays: state || [], setHolidays:(arr)=>patch({ holidays: Array.isArray(arr)?arr:[] }) };
}

// ── Sourcing inputs (W2 · S-1 landed cost, S-2 stepwise freight) ───────────
// sourcingDefault(bomRow): the SEED sourcing terms for a part (provenance=seed
// until the user overrides any field). Honest, documented assumptions — not
// fabricated solver output:
//   · imported  — only the POSCO bearing-alloy billet (RM-BRG18) is imported in
//     the seed dataset (matches the landed-cost worked example); the rest are
//     domestic. The user flips this per part.
//   · dutyFreightPct — a seed estimate of the duty + inbound-freight uplift that
//     turns a part's quoted cost into its LANDED cost (0 for domestic). The real
//     per-import build-up lives in the Landed Cost card; this is the planning knob.
//   · unitsPerTruck / costPerTruck — the stepwise inbound-freight lot: a truck
//     holds `unitsPerTruck` and costs `costPerTruck` whether full or not, so
//     freight = ⌈qty / unitsPerTruck⌉ × costPerTruck (a real step function).
function sourcingDefault(bomRow){
  const b = bomRow || {};
  const imported = b.part === 'RM-BRG18';     // POSCO import (seed assumption)
  const moq = Number(b.moq) || 1000;
  return {
    imported,
    dutyFreightPct: imported ? 12 : 0,        // seed: duty+freight uplift to landed
    unitsPerTruck: Math.max(1000, moq * 4),   // seed: a truckload ≈ 4 MOQ lots
    costPerTruck: imported ? 55000 : 16000,   // seed: container vs domestic haul (₹)
    // G-S3 — explicit origin + HS-code master (was just a boolean + flat %). The HS code
    // grounds the duty (BCD lookup), the origin drives FTA concessions + supplier/origin
    // CONCENTRATION caps, and the quote currency drives the FX re-price (fxFactor).
    origin: imported ? 'KR' : 'IN',           // ISO country of origin (KR = POSCO/South Korea)
    hsCode: imported ? '7224.90' : '',        // alloy-steel semi-finished (HS heading)
    quoteCcy: imported ? 'USD' : 'INR',
  };
}
// G-S3 — HS heading → basic-customs-duty (BCD) %, and FTA origins → duty concession.
// India CEPA/FTA (e.g. Korea) zero-rates many alloy-steel lines; the lookup GROUNDS the
// duty number instead of a bare typed %. Seed table — extend as the parts master grows.
const HS_BCD = { '7224':7.5, '7208':10, '8482':7.5, '3403':10, '7318':10 };   // by 4-digit heading
const FTA_ORIGINS = { KR:0.5, JP:0.5, IN:0 };   // origin → BCD concession fraction (CEPA)
const COUNTRY_NAME = { IN:'India', KR:'South Korea', JP:'Japan', CN:'China', DE:'Germany', US:'United States' };
function hsDuty(src){
  const hs = String((src && src.hsCode) || '').replace(/\./g,'').slice(0,4);
  const bcd = HS_BCD[hs];
  if(bcd==null) return { bcd:null, concession:0, dutyPct:null, hs };
  const conc = FTA_ORIGINS[(src && src.origin) || 'IN'] || 0;
  return { bcd, concession:conc, dutyPct: Math.round(bcd*(1-conc)*10)/10, hs };
}
// G-S3 — origin / supplier CONCENTRATION: each origin country's (and supplier's) share of
// total RM LANDED spend (qty_per × landed × … proxied by qty×landed), flagged against a
// governed cap. This is the procurement `extras` "supplier/FX concentration cap" wired real.
function originConcentration(bom){
  const rows = (bom || (window.M && M.bom) || []);
  const cap = Number((appStore.get().config||{}).originConcentrationCap) || 0.6;
  const byOrigin = {}, bySupplier = {}; let total = 0;
  rows.forEach(b=>{ const src = getSourcing(b.part, b);
    const spend = (Number(b.qty)||0) * effLandedCost(b.cost, src) * (Number(b.moq)||1);   // value proxy
    total += spend;
    const o = src.origin || 'IN'; byOrigin[o] = (byOrigin[o]||0) + spend;
    const s = b.sup || '—';       bySupplier[s] = (bySupplier[s]||0) + spend;
  });
  const share = (m)=> Object.entries(m).map(([k,v])=>({ k, v, pct: total? v/total : 0 })).sort((a,b)=>b.pct-a.pct);
  const origins = share(byOrigin), suppliers = share(bySupplier);
  return { cap, total, origins, suppliers,
    originBreaches: origins.filter(o=>o.pct>cap), supplierBreaches: suppliers.filter(s=>s.pct>cap) };
}
// getSourcing(part, bomRow): non-reactive read (seed merged under stored override)
// for payload builders. provenance: 'user' if any field was overridden, else 'seed'.
function getSourcing(part, bomRow){
  const stored = (appStore.get().sourcing || {})[part] || {};
  const seed = sourcingDefault(bomRow);
  return { ...seed, ...stored, _prov: Object.keys(stored).length ? 'user' : 'seed' };
}
// useSourcing(part, bomRow): reactive editor binding. Editing re-flags the supply
// solves (procurement/policy/rolling) stale via the 'sourcing' source.
function useSourcing(part, bomRow){
  const { state, patch } = useStore(s=>s.sourcing||{});
  const stored = state[part] || {};
  const seed = sourcingDefault(bomRow);
  const src = { ...seed, ...stored, _prov: Object.keys(stored).length ? 'user' : 'seed' };
  return { src, setSrc:(p)=>{ patch({ sourcing:{ [part]:{ ...stored, ...p } } }); markStale('sourcing'); } };
}
// SS-D — landed cost ↔ LIVE FX table. An imported part's ₹ cost tracks the
// rate of its quote currency; the seed ₹ cost IS the as-of-base value (FX_BASE =
// the seeded config.fxRates). fxFactor = current rate ÷ base rate, so editing the
// FX table in Finance/Setup (config.fxRates) re-prices every imported part's landed
// cost — one source of truth for $→₹, which then re-flows the procurement MILP,
// the policy autopilot, MEIO and the MC cost shocks. Domestic parts → factor 1.
const FX_BASE = { USD:84.20, EUR:91.40, JPY:0.563 };
function fxFactor(src){
  if(!(src && src.imported)) return 1;
  const ccy = (src.quoteCcy) || 'USD';
  const cur = Number(((appStore.get().config||{}).fxRates||{})[ccy]);
  const base = FX_BASE[ccy];
  if(!cur || !base) return 1;
  return cur / base;
}
// G-S1 — per-part DETAILED landed-cost build-up (PER UNIT), mirroring the backend
// finance.py calc_landed_cost math EXACTLY so the planning value the MILP uses
// reconciles to the FOB→plant-gate rollup (the assertion). Opt-in via
// src.landedDetail.on — ABSENT for every part in the seed dataset, so effLandedCost
// below stays on the flat dutyFreightPct path ⇒ golden path byte-identical. When ON,
// it REPLACES the coarse flat % with FOB×FX + freight + insurance + BCD(HS) + SWS +
// CHA + inland, with IGST recoverable as ITC (net of the credit = the correct
// planning value). FX is live: FOB is converted at the current quote-ccy rate, so
// editing config.fxRates re-prices the detailed build-up too (consistent with fxFactor).
function landedRate(ccy){
  if(!ccy || ccy==='INR') return 1;
  const cur = Number(((appStore.get().config||{}).fxRates||{})[ccy]);
  return cur || FX_BASE[ccy] || 1;
}
function landedBuildup(src){
  const d = src && src.landedDetail;
  if(!d || !d.on) return null;
  const r2 = (x)=> Math.round(x*100)/100;
  const rate = landedRate((src && src.quoteCcy) || 'USD');
  const fobInr   = (Number(d.fobUnit)||0) * rate;
  const insurance= fobInr * (Number(d.insurancePct)||0) / 100;
  const cif      = fobInr + (Number(d.freightPerUnit)||0) + insurance;
  // BCD grounded by the HS code + FTA origin (hsDuty); falls back to a typed bcdPct.
  const duty   = (typeof hsDuty==='function') ? hsDuty(src) : { dutyPct:null };
  const bcdPct = (duty.dutyPct!=null) ? duty.dutyPct : (Number(d.bcdPct)||0);
  const bcd    = cif * bcdPct / 100;
  const swsPct = (d.swsPct!=null) ? Number(d.swsPct) : 10;
  const sws    = bcd * swsPct / 100;
  const igstPct= (d.igstPct!=null) ? Number(d.igstPct) : 18;
  const igst   = (cif + bcd + sws) * igstPct / 100;   // recoverable as ITC → excluded below
  const cha    = Number(d.chaPerUnit)||0, inland = Number(d.inlandPerUnit)||0;
  const netLanded = cif + bcd + sws + cha + inland;   // net of recoverable IGST
  return { rate, fobInr:r2(fobInr), insurance:r2(insurance), cif:r2(cif), bcdPct,
    bcd:r2(bcd), swsPct, sws:r2(sws), igstPct, igst:r2(igst), cha, inland, netLanded:r2(netLanded) };
}
// Seed the detailed build-up from the part's current economics so turning it ON is
// roughly continuous with the flat-% landed cost it replaces (then the user refines).
function landedDetailSeed(rawCost, src){
  const r2 = (x)=> Math.round(x*100)/100;
  const rate = landedRate((src && src.quoteCcy) || 'USD');
  const cost = Number(rawCost)||0;
  return { on:true,
    fobUnit: r2(cost / (rate || 1)),        // back out FOB in the quote currency
    freightPerUnit: r2(cost * 0.04),        // ~4% ocean freight seed
    insurancePct: 0.5,
    chaPerUnit: r2(cost * 0.01),            // clearing/CHA seed
    inlandPerUnit: r2(cost * 0.02),         // inland-to-plant seed
    swsPct: 10, igstPct: 18 };
}
// effLandedCost(rawCost, src): quoted cost → landed cost the MILP plans against.
// Detailed per-part build-up wins when present (G-S1); otherwise the duty+freight %
// uplift × live FX factor. At seed FX the factor is 1 and no part carries a build-up ⇒
// landed is byte-identical to the pre-G-S1 value, so nothing changes until a planner
// edits a rate or turns on a part's detailed build-up.
function effLandedCost(rawCost, src){
  const bu = landedBuildup(src);
  if(bu) return bu.netLanded;
  const pct = Number(src && src.dutyFreightPct) || 0;
  return Math.round(Number(rawCost||0) * (1 + pct/100) * fxFactor(src) * 100) / 100;
}
// freightSteps(qty, src): the stepwise inbound-freight lot. Returns the truck count,
// total freight, amortised per-unit freight, and where the NEXT truck tips in — so
// the UI can show "one more unit ⇒ a whole extra truck" honestly.
function freightSteps(qty, src){
  const cap = Math.max(1, Number(src && src.unitsPerTruck) || 1);
  const per = Number(src && src.costPerTruck) || 0;
  const q = Math.max(0, Number(qty) || 0);
  const trucks = q > 0 ? Math.ceil(q / cap) : 0;
  const cost = trucks * per;
  return { trucks, cost, perUnit: q > 0 ? cost / q : 0,
    cap, costPerTruck: per, fillPct: trucks > 0 ? (q / (trucks * cap)) * 100 : 0,
    nextStepAt: trucks * cap + 1, marginalTruck: per };
}
// D6 — EXTERNAL-SIGNAL DRIVERS. Planning-cadence external indices (NOT MES/IoT
// telemetry — the in-fit replacement): a commodity-price index re-prices BOM
// material, a port-congestion bump lengthens inbound lead time, and the FX table
// (SS-D, fxFactor above) re-prices imported parts. All three are real SOLVER
// DRIVERS — they flow into the procurement / policy / rolling / MEIO payloads via
// bomParts and (because they live on config) re-flag those solves stale on edit.
// config.signals seeds at the NEUTRAL point (0% / 0d) so the schema is byte-identical
// to pre-D6 until a planner moves an index. In-DNA twin of fxFactor.
function signals(){ return (appStore.get().config || {}).signals || {}; }
function commodityFactor(){ const p = Number(signals().commodityIndexPct) || 0; return 1 + p/100; }
// port congestion in DAYS → whole PERIODS of extra inbound lead (rounded to the
// planning grain; a sub-period delay honestly doesn't shift a monthly MILP bucket).
function portDelayPeriods(periodDays){ const d = Number(signals().portDelayDays) || 0; return d>0 ? Math.round(d/(periodDays||30)) : 0; }

// bomParts(periodDays): map mock `M.bom` rows → the procurement solver's part
// schema (one shared illustrative BOM — documented limitation). Reused by Sourcing
// + Console. Lead time on `M.bom` is in DAYS; the solver counts in PERIODS, so we
// convert by the period length (30d monthly / 7d weekly) — otherwise a 14-day lead
// reads as 14 months and the part can never arrive within the horizon. D6: the
// commodity index scales material cost and the port-congestion bump adds lead.
function bomParts(periodDays){
  const M = window.M || {};
  const pd = periodDays || 30;
  const cf = commodityFactor(), portP = portDelayPeriods(pd);
  return (M.bom || []).map(b=>({
    name:b.name, cost:Math.round(b.cost * cf * 100)/100, qty_per:b.qty,
    lead_time:Math.max(1, Math.round(b.lt / pd) + portP),
    moq:b.moq, hold_pct:b.hold, ordering_cost:(Number(b.S)||120), scrap_factor:(Number(b.scrap)||0.01), rm_shelf:b.shelf,
    // size order/storage caps off the MOQ so a single MOQ lot is always orderable
    // and storable (defaults of 9999 go infeasible against a 10 000-unit bolt MOQ).
    max_order:Math.max(b.moq * 5, 50000), rm_capacity:Math.max(b.moq * 3, 50000),
  }));
}

// ── Ph2 · per-SKU BOM (R7 real fix) ──────────────────────────────────────────
// The flat M.bom is the PARTS MASTER (intrinsic attrs: cost, lead time, MOQ,
// supplier, scrap — a steel bar's cost is the part's, not the FG's). WHICH parts a
// finished good uses and HOW MUCH per unit is per-product — that lives in M.skuBom
// {sku→[{part,qty}]}. bomForSku(sku) joins them + a thin per-SKU qty override layer
// (state.bomOverrides[sku][part].qty) so a planner can tune one FG's usage without
// touching the part master or the other FGs. qty is the genuinely per-SKU attribute;
// the rest stay shared (editPartAttr, which correctly affects every FG using the part).
function _skuQty(sku, partId, fallback){
  const o = (((appStore.get().bomOverrides||{})[sku]||{})[partId]||{}).qty;
  return (o!=null && o!=='') ? Number(o) : fallback;
}
function bomForSku(sku){
  const M = window.M || {};
  const master = {}; (M.bom||[]).forEach(b=>{ master[b.part]=b; });
  const lines = (M.skuBom||{})[sku] || [];
  return lines.map(ln=>{
    const m = master[ln.part] || { part:ln.part, name:ln.part, cost:0, lt:0, moq:0, S:0, hold:0, shelf:999, sup:'', scrap:0.01 };
    const qtySeed = Number(ln.qty)||0;
    const qty = _skuQty(sku, ln.part, qtySeed);
    return { part:ln.part, name:m.name, qty, qtySeed, qtyOver:(qty!==qtySeed),
             cost:m.cost, lt:m.lt, moq:m.moq, S:m.S, hold:m.hold, shelf:m.shelf, sup:m.sup, scrap:(Number(m.scrap)||0.01) };
  });
}
// editPartQty(sku, part, val): per-SKU qty override (R7). '' clears → back to the
// skuBom seed. Flags the procurement family stale ('bom' is a SOLVE_DEPS token) and
// is consumed by bomForSku (display + material rollup) AND montecarloPayload's per-SKU
// costed bill — so the edit is REAL, not decorative.
function editPartQty(sku, part, val){
  const cur = appStore.get().bomOverrides || {};
  const skuOv = { ...(cur[sku]||{}) };
  const partOv = { ...(skuOv[part]||{}) };
  if(val===''||val==null) delete partOv.qty; else partOv.qty = Number(val);
  if(Object.keys(partOv).length) skuOv[part]=partOv; else delete skuOv[part];
  appStore.set({ bomOverrides: { ...cur, [sku]: skuOv } });
  try{ markStale('bom'); }catch(e){}
  try{ logEvent('override', sku+'/'+part, { qty:val }); }catch(e){}
}

// transportPayload(): outbound lanes (from the network topology) each carry the
// finished-goods flow for one period. Tonnage = monthly FG units × an assumed
// unit weight (TPAC bearings ≈ 3 kg — the one documented assumption, since the
// mock lanes carry no weights); value = units × price. Shared by Console + Logistics.
const _UNIT_WEIGHT_KG = 3.0;   // fallback avg finished-bearing shipping weight
// LG-2 — per-SKU shipping weight (kg/unit). Seed masses for the TPAC bearing range
// (a hub bearing is heavier than a seal cartridge); honest seed provenance, edit when
// real BOM masses land. Replaces the flat 3 kg/unit so a lane's tonnage reflects its
// actual SKU MIX, not a portfolio average.
const _SKU_WEIGHT_KG = { 'TPA-4471':3.4, 'TPA-3215':1.9, 'TPA-9904':2.6, 'TPA-2188':4.1, 'TPA-5540':3.0, 'TPA-7722':2.2 };
function skuWeightKg(sku){ return _SKU_WEIGHT_KG[sku] || _UNIT_WEIGHT_KG; }
// (R13) the ONE volume authority (m³/unit) — Products shows it and Network derives
// storage utilisation from it (Σ vol·on-hand / node cube). Was a duplicate hardcode
// in products.jsx `ex` alongside a SECOND, conflicting weight table; unified here so
// weight & volume have a single source, like every other master attribute.
const _SKU_VOL_M3 = { 'TPA-4471':0.0021, 'TPA-3215':0.0009, 'TPA-9904':0.0006, 'TPA-2188':0.0042, 'TPA-5540':0.0031, 'TPA-7722':0.0005 };
function skuVolM3(sku){ return _SKU_VOL_M3[sku] || 0; }
// G-N3 — STORAGE CLASS capacity. A single node "cube" is a §1.5 category error: a
// cold-chain SKU and an ambient SKU physically can't share the same m³. Each item
// carries a storage class (ambient/cold/hazmat, default ambient); each node can declare
// capacity PER CLASS (node.classCaps). Utilisation is then computed per class, not as a
// lump. DEFAULT (no config.storageClass override + no node.classCaps): the ambient class
// holds the whole node cube and the others are 0 ⇒ the prior single-bar number exactly.
const STORAGE_CLASSES = ['ambient','cold','hazmat'];
const STORAGE_CLASS_LABEL = { ambient:'Ambient', cold:'Cold chain', hazmat:'Hazmat' };
function storageClassFor(item){
  const ov = ((appStore.get().config||{}).storageClass||{})[item];
  return (ov && STORAGE_CLASSES.indexOf(ov)>=0) ? ov : 'ambient';
}
// nodeClassCap(node, cls): the node's m³ capacity for a class. With explicit classCaps,
// use them; WITHOUT any classCaps the whole node.capacity is ambient (cold/hazmat = 0),
// so an un-classed node behaves exactly as the single-cube model did.
function nodeClassCap(node, cls){
  const cc = node && node.classCaps;
  if(cc && cc[cls]!=null && cc[cls]!=='') return Number(cc[cls])||0;
  if(!cc) return cls==='ambient' ? (Number(node && node.capacity)||0) : 0;
  return 0;
}
// nodeStorageUtil(node): per-class {used (m³), cap, pct} from opening on-hand × volume,
// grouped by each item's storage class.
function nodeStorageUtil(node){
  const vol = (typeof skuVolM3==='function') ? skuVolM3 : (()=>0);
  const onHand = getNetwork().onHand || [];
  const out = {}; STORAGE_CLASSES.forEach(c=> out[c] = { used:0, cap:nodeClassCap(node,c), pct:0 });
  onHand.filter(o=>o.loc===node.id).forEach(o=>{
    const cls = storageClassFor(o.item);
    out[cls].used += (Number(o.qty)||0) * vol(o.item);
  });
  STORAGE_CLASSES.forEach(c=>{ out[c].pct = out[c].cap>0 ? out[c].used/out[c].cap*100 : 0; });
  return out;
}
// ── G-SC1 · SOLVED COST VIEWS ────────────────────────────────────────────────
// costWaterfallLive(): the total-cost build-up by category, read from the LIVE cached
// solves (procurement cost_breakdown + transport total) instead of the seed
// M.costWaterfall. Holding is the residual (total − the explicit categories) = the
// inventory carrying cost the objective charged but doesn't itemise; so the categories
// sum to the solved total by construction (the assertion). Returns null when procurement
// isn't cached yet ⇒ the card falls back to the illustrative seed (honest).
function costWaterfallLive(){
  const sr = appStore.get().solveResults || {};
  const proc = sr.procurement && sr.procurement.result;
  if(!proc || !proc.cost_breakdown) return null;
  const cb = proc.cost_breakdown;
  const tr = sr.transport && sr.transport.result;
  const trCost = tr ? (Number(tr.total_cost)||0) : 0;
  const explicit = ['material_purchase','ordering_admin','production_setup','production_variable','fixed_overhead','milk_run','expiry_writeoff']
    .reduce((s,k)=> s + (Number(cb[k])||0), 0);
  const holding = Math.max(0, (Number(cb.total)||0) - explicit);   // residual = carrying cost
  const cats = [
    { k:'Material',   v:Number(cb.material_purchase)||0 },
    { k:'Ordering',   v:Number(cb.ordering_admin)||0 },
    { k:'Setup',      v:Number(cb.production_setup)||0 },
    { k:'Conversion', v:Number(cb.production_variable)||0 },
    { k:'Holding',    v:holding },
    { k:'Overhead',   v:Number(cb.fixed_overhead)||0 },
    { k:'Milk-run',   v:Number(cb.milk_run)||0 },
    { k:'Expiry',     v:Number(cb.expiry_writeoff)||0 },
    { k:'Transport',  v:trCost },
  ].filter(c=>c.v>0.005);
  const total = (Number(cb.total)||0) + trCost;
  return { cats, total, hasTransport:!!tr };
}
// tcoPerSku(): per-finished-SKU total cost of ownership, each component DERIVED from a
// solved/governed/measured source (not the M.tco seed): unit = product cost; quality =
// the extra material to net one good unit at the MEASURED yield (G-I1); ordering = the
// master per-PO cost S (G-S2) amortised over committed annual demand; holding = the
// SOLVED carry rate (carryRate ← WACC, FIN-8) × unit × the governed cover; obsolescence =
// salvage write-down ONLY when shelf life < cover (0 for durable parts — honest). TCO is
// the exact sum of the five, so TCO == Σ components holds by construction.
function tcoPerSku(){
  const cfg = appStore.get().config || {};
  const carry = (typeof carryRate==='function') ? carryRate(cfg) : 0.24;
  const coverYears = Math.max(0, Number(cfg.tcoCoverWeeks)||6) / 52;
  const coverDays = coverYears * 365;
  const fin = ((window.M&&M.products)||[]).filter(p=>p.cat==='Finished');
  const r2 = x=>Math.round(x*100)/100;
  return fin.map(p=>{
    const unit = Number(p.cost)||0;
    const annual = (typeof getItemDemand==='function') ? getItemDemand(p.sku,12).reduce((a,b)=>a+(+b||0),0) : (Number(p.demand)||0);
    const yld = (typeof skuYield==='function') ? skuYield(p,0.97) : (Number(p.yield)||0.97);
    const bom = (typeof bomForSku==='function') ? (bomForSku(p.sku)||[]) : [];
    const orderingS = bom.reduce((s,b)=> s + (Number(b.S)||0), 0);
    const hold = r2(carry * unit * coverYears);
    const order = annual>0 ? r2(orderingS/annual) : 0;
    const quality = r2(unit * (1/Math.max(0.01,yld) - 1));
    const salvage = (p.salvage!=null && p.salvage!=='') ? Number(p.salvage) : 0.8;
    const shelfDays = Number(p.shelf)||365;
    const spoilFrac = coverDays>0 ? Math.max(0, 1 - shelfDays/coverDays) : 0;   // 0 for durables (shelf ≫ cover)
    const obsol = r2(unit * (1-salvage) * spoilFrac);
    const tco = r2(unit + hold + order + quality + obsol);
    return { sku:p.sku, unit:r2(unit), hold, order, quality, obsol, tco, yieldUsed:yld };
  });
}
function transportPayload(){
  const M = window.M || {};
  const net = getNetwork();
  const outbound = (net.lanes||[]).filter(l=>l.direction==='outbound');
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  // LG-2 — per-SKU monthly flow, its own weight, and value (not a flat avg price).
  const skuFlows = fin.map(p=>{ const monthly = getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12;
    return { sku:p.sku, monthly, weightKg:skuWeightKg(p.sku), price:Number(p.price)||1850 }; });
  const totalMonthly = skuFlows.reduce((s,f)=>s+f.monthly, 0);
  const totalWeight  = skuFlows.reduce((s,f)=>s+f.monthly*f.weightKg, 0);   // mix-accurate tonnage
  const totalValue   = skuFlows.reduce((s,f)=>s+f.monthly*f.price, 0);
  const nLanes = outbound.length || 1;
  // spread the FG flow across the outbound lanes, but each lane now carries the real
  // mix-weighted tonnage/value (even lane split — the topology has no per-lane SKU map).
  const shipments = (outbound.length?outbound:[{from:'PLANT',to:'DC',mode:'FTL'}]).map(l=>({
    name:`${l.from}→${l.to}`, origin:l.from, destination:l.to,
    weight_kg:Math.max(30, Math.round(totalWeight / nLanes)),
    volume_cbm:Math.max(0.1, +((totalMonthly / nLanes) * 0.004).toFixed(1)),
    value:Math.round(totalValue / nLanes), deadline_days:7,
  }));
  // G-L1 — feed transport.py's embedded DC→customer min-cost transportation LP (origins/
  // destinations/cost_matrix). The last outbound echelon (DC→customer lanes) is the real
  // ALLOCATION decision: which DC serves each customer. Previously unsent ⇒ the LP never ran
  // and the UI showed an even demand-spread; now the split is COST-OPTIMISED. cost = lane
  // rate × km (a consistent relative ₹/unit proxy across modes). Each DC's supply is set to
  // total demand so it CAN serve all (Σsupply ≥ demand ⇒ always feasible, never degrades the
  // transport status) and cost alone drives the pick — the classic min-cost assignment.
  const nodeById = {}; (M.nodes||[]).forEach(n=>{ nodeById[n.id]=n; });
  const custLanes = outbound.filter(l=>{ const t=nodeById[l.to]; return t && t.type==='customer'; });
  let allocFields = {};
  if(custLanes.length){
    const originIds = [...new Set(custLanes.map(l=>l.from))];
    const destIds   = [...new Set(custLanes.map(l=>l.to))];
    const totalUnits = Math.max(1, Math.round(totalMonthly));
    const laneCost = {}; custLanes.forEach(l=>{ laneCost[l.from+'>'+l.to] = (Number(l.rate)||1) * (Number(l.km)||1); });
    const BIGM = 1e7;
    allocFields = {
      origins:      originIds.map(id=>({ id, name:(nodeById[id]||{}).name||id, supply: totalUnits })),
      destinations: destIds.map(id=>({ id, name:(nodeById[id]||{}).name||id, demand: Math.round(totalUnits/destIds.length) })),
      cost_matrix:  originIds.map(oi=> destIds.map(dj=> laneCost[oi+'>'+dj] != null ? laneCost[oi+'>'+dj] : BIGM)),
    };
  }
  // sku_flows surfaced so the Logistics tab can show the per-SKU outbound breakdown.
  // (NOTE: transport.py's stockout_risk_factor weights an air-vs-sea tradeoff, but it only
  // bites when a shipment carries demand-sensing fields — current_stock/daily_consumption/
  // demand_spike. Outbound FG lanes don't carry those, so we DON'T pretend to drive it here;
  // it lives in the Anatomy-Lab extras until per-lane spike sensing is wired.)
  return { shipments, ...allocFields, params:{ sku_flows: skuFlows.map(f=>({ sku:f.sku, monthly_units:Math.round(f.monthly),
    weight_kg_per_unit:f.weightKg, monthly_weight_kg:Math.round(f.monthly*f.weightKg) })) } };
}

// ── Production schedule (W3) — REAL /api/solve/production payload ───────────
// finishedWeeklyDemand(sku,planning,T): the committed FORECAST series at the
// planning weekly grain, sliced to the schedule horizon T. Pulling the full
// horizon first (then slicing) keeps weekly demand at annual/52 — getItemDemand
// alone would spread the whole year across just T periods and inflate it ~4×.
function finishedWeeklyDemand(sku, planning, T){
  const full = Math.max(T||1, Number(planning && planning.horizonLength) || 52);
  return getItemDemand(sku, full).slice(0, T);
}
// productionScheduleHorizon: the MILP fence (weeks) for production / procurement /
// linecap / montecarlo. A schedule is a fence (frozen+slushy detail), not the full
// year, and 6 SKUs × 3 lines × 52 wk × binaries is a needlessly large MIP. The
// fence is GOVERNED by planning.productionScheduleWeeks (default 13, set in Setup)
// — no longer a magic 13. We take min(horizonLength, fence) so a short horizon
// still shrinks the schedule, then floor at 4 (a sub-4-week MPS is degenerate).
// HORIZON CONTRACT: this is one solver's DECLARED basis; see horizon contract in
// GOLDEN_JOURNEY_SPEC.md — each solver runs its own basis off horizonLength+grain.
function productionScheduleHorizon(planning){
  const fence = Math.max(1, Number(planning && planning.productionScheduleWeeks) || 13);
  return Math.max(4, Math.min(Number(planning && planning.horizonLength) || fence, fence));
}
// productionPayload(planning, opts) → the production MILP input. opts.laborRate
// (₹/hr, governed seed→override) prices overtime + idle-week shutdowns;
// opts.shutdownPct sets the utilization floor for a shutdown candidate.
// Each FG is PINNED to its assigned line via a single routing op carrying its
// real cycle time — so the solver schedules it where it actually runs, at the
// SKU's own cycle×OEE×hours throughput (no fabricated per-line capacity).
function productionPayload(planning, opts){
  const M = window.M || {};
  opts = opts || {};
  const T = productionScheduleHorizon(planning);
  const wdays = Math.max(1, Number(planning.workDaysPerWeek) || 6);
  const hrsPerShift = 8;
  const hrsPerPeriod = wdays * hrsPerShift;                 // weekly available hrs/line
  const rate = Number(opts.laborRate) || 0;
  const timePhased = !!opts.timePhased;                      // PR-A — opt-in MPS that tracks the curve
  const route = opts.routing || {};                         // PR-B — governed per-SKU cycle/line/yield
  const fin = (M.products || []).filter(p=>p.cat==='Finished');
  // PR-B — resolve each FG's effective routing: governed override (config.prodRouting[sku])
  // falls back to the mock master. Provenance for the override is shown in ProdCycle.
  const eff = (p)=>{
    const ov = route[p.sku] || {};
    const cyc  = (ov.cycle != null && ov.cycle !== '') ? Number(ov.cycle) : p.cycle;
    const line = ov.line || p.line;
    const yld  = (ov.yieldPct != null && ov.yieldPct !== '') ? Number(ov.yieldPct)/100 : skuYield(p, 0.95);   // G-I1 measured ?? seed
    return { cyc, line, yld };
  };
  const products = fin.map(p=>{
    const dem = finishedWeeklyDemand(p.sku, planning, T);
    const e = eff(p);
    const prod = {
      name: p.sku,
      required_qty: dem.reduce((a,b)=>a+b, 0),
      oee: p.oee, yield_pct: e.yld, setup_cost: 50,
      routing: [{ line_id: e.line, cycleTimeMin: e.cyc, parallelism: 1,
                  yieldPct: e.yld * 100 }],
    };
    if(timePhased) prod.demand_by_period = dem;               // PR-A — per-period demand curve
    return prod;
  });
  // sequence-dependent setup matrix (M.changeover is in HOURS → ×60 to minutes).
  // PR-D — emit a PER-LINE changeover sub-matrix over only the SKUs pinned to that line,
  // not one global 4×4 averaged across every line. A line running one SKU has no changeover;
  // a line running 2+ gets the asymmetric pairs that actually occur on it.
  const coSkus = M.changeoverSkus || [];   // canonical FG order (data.jsx) — no stale 4-SKU literal
  const coIdx = {}; coSkus.forEach((s,i)=>{ coIdx[s] = i; });
  const skuLine = {}; fin.forEach(p=>{ skuLine[p.sku] = eff(p).line; });
  const subMatrix = (skus)=>{
    const m = {};
    skus.forEach(a=>{ m[a] = {}; skus.forEach(b=>{
      const v = ((M.changeover[coIdx[a]] || [])[coIdx[b]]);
      if(typeof v === 'number') m[a][b] = v * 60; }); });
    return m;
  };
  const lines = (M.lines || []).map(l=>{
    const bn = (l.stages || []).find(s=>s.bottleneck) || (l.stages || [])[0] || {};
    const lineSkus = coSkus.filter(s => skuLine[s] === l.id);   // PR-D — only this line's SKUs
    const ln = { id: l.id, name: l.name,
      capacity: Math.round((l.cap || 0) / 4.33),             // u/mo → u/week
      oee: l.oee, changeover_matrix: subMatrix(lineSkus), changeover_mins: 30,
      workers_per_shift: bn.w || bn.m || 1, shifts_per_day: Number(l.shifts) || 1 };
    if(rate > 0) ln.hourly_rate = rate;                       // priced OT + shutdown
    return ln;
  });
  return { products, lines,
    labor_cost_mode: rate > 0 ? 'hourly' : 'per_unit',
    // G-P4 — org-wide labor envelope (headcount → regular labor-hours budget, weekly OT cap).
    // 0 = unbounded ⇒ the existing per-line machine cap is the only ceiling (byte-identical default).
    workforce: { hourly_headcount_cap: Number(opts.laborHeadcountCap) || 0,
                 ot_cap_hrs: Number(opts.laborOtCapHrs) || 0 },
    params: { periods: T, hrs_per_period: hrsPerPeriod, hours_per_shift: hrsPerShift,
      horizon_start_date: planning.startDate,
      time_phased: timePhased,                                // PR-A
      holding_cost_per_unit: Number(opts.holdingCost) || 0,   // PR-A — penalizes early build
      campaign_min_run: Number(opts.campaignMinRun) || 0,     // PR-4 — campaign min-run lever
      shutdown_threshold_pct: Number(opts.shutdownPct) || 25, rehire_notice_hrs: 80 } };
}

// ── Monte Carlo on the COMMITTED plan (W6 · R-1) ───────────────────────────
// productionPlanBySku(prodResult, T): fold the production MILP's gantt[] into a
// per-SKU per-period build array — the exact schedule that will execute, so the
// risk sim REPLAYS it (policy='plan') instead of re-deriving a base-stock policy
// the MILP never chose. Returns {} when no production solve is cached.
function productionPlanBySku(prodResult, T){
  const out = {};
  const g = (prodResult && prodResult.gantt) || [];
  g.forEach(e=>{
    const k = e.product, t = e.period;
    if(k == null || t == null) return;
    if(!out[k]) out[k] = Array(T).fill(0);
    if(t < T) out[k][t] += Number(e.quantity)||0;
  });
  return out;
}
// montecarloPayload(planning, opts): the /api/solve/montecarlo input. Each finished
// SKU carries its committed demand curve, its landed-cost BOM (so material-cost
// shocks hit the real costed bill), and — when a production solve is cached — its
// committed build plan (R-1: simulate the plan of record, not a textbook policy).
// opts.corr (demand↔cost correlation), opts.serviceLevel, opts.nRuns are governed.
function montecarloPayload(planning, opts){
  const M = window.M || {};
  opts = opts || {};
  const T = productionScheduleHorizon(planning);            // align with the production schedule
  const prod = opts.prodResult || getSolveResult('production');
  const planBySku = productionPlanBySku(prod, T);
  // MN-D — per-SKU costed bill. Each finished SKU's cost shocks now hit ONLY the
  // parts it actually consumes (from M.skuBom), at that SKU's own qty_per — so a
  // material-price spike on a part used by 3 of 6 SKUs raises cost for those 3, not
  // the whole portfolio uniformly (which the single shared BOM did). landed_cost
  // carries the duty/freight % AND the live FX factor (SS-D). Falls back to the
  // shared M.bom when a SKU has no skuBom cohort (honest, fully compatible).
  const _bomRow = (partId)=> (M.bom || []).find(b=>b.part===partId) || {};
  const _sharedParts = (M.bom || []).map(b=>{
    const src = getSourcing(b.part, b);
    return { name:b.part, landed_cost: effLandedCost(b.cost, src), cost_cv:0.05, qty_per:b.qty };
  });
  const skuParts = (sku)=>{
    const lines = (M.skuBom || {})[sku];
    if(!lines || !lines.length) return _sharedParts;
    return lines.map(ln=>{ const b=_bomRow(ln.part); const src=getSourcing(ln.part, b);
      return { name:ln.part, landed_cost: effLandedCost(b.cost, src), cost_cv:0.05, qty_per:_skuQty(sku, ln.part, Number(ln.qty)||0) }; });
  };
  const fin = (M.products || []).filter(p=>p.cat==='Finished');
  // RK-A — uniform plan-mode coverage. If ANY SKU has a committed schedule, give
  // EVERY SKU a plan so the whole portfolio simulates under ONE policy (=plan):
  // an unbuilt SKU falls back to its committed demand series as its build plan
  // (build-to-demand) rather than silently dropping to base-stock for that SKU
  // (which produced a mixed policy in a single run). With no production solve at
  // all, no SKU gets a plan → base-stock for all (consistent).
  const anyPlan = Object.keys(planBySku).length > 0;
  const products = fin.map(p=>{
    const dem = finishedWeeklyDemand(p.sku, planning, T);
    const planArr = planBySku[p.sku] || (anyPlan ? dem : null);  // real schedule, else demand-as-plan
    return {
      name: p.sku,
      demand: dem,
      mape_pct: Number(p.mape) || 12,
      capacity: Math.round((dem.reduce((a,b)=>a+b,0)/Math.max(T,1)) * 3),  // generous per-period cap
      setup_cost: 50,
      variable_cost: Number(p.cost) || 0,
      sell_price: Number(p.price) || 0,
      shelf_life: Math.max(1, Math.round((Number(p.shelf)||365)/7)),       // days → weeks
      yield_pct: skuYield(p, 0.95),                                        // G-I1 measured ?? seed
      salvage_rate: Number(p.salvage) || 0.8,
      parts: skuParts(p.sku),                                              // MN-D — per-SKU costed bill
      init_inventory: 0,
      ...(planArr ? { production_plan: planArr } : {}),
    };
  });
  // RK-D — apply a stochastic production lead-time lag ONLY in plan mode (a committed
  // schedule that mis-times a build against a shock is then penalised). Governed via
  // opts.prodLeadTime (weeks) / opts.prodLeadCv; 0 = legacy same-period receipt.
  const ltMean = anyPlan ? (opts.prodLeadTime != null ? Number(opts.prodLeadTime) : 1) : 0;
  const ltCv = opts.prodLeadCv != null ? Number(opts.prodLeadCv) : 0.5;
  return { products, n_runs: Number(opts.nRuns) || 500,
    params: { periods: T, periods_per_year: 52,
      // carry_rate from governed WACC + holding spread (carryRate), not a 0.24 constant.
      carry_rate: (typeof carryRate==='function') ? carryRate(appStore.get().config) : 0.24,
      service_level: Number(opts.serviceLevel) || (M && 0.95),
      corr_demand_cost: (opts.corr != null ? Number(opts.corr) : 0.4),
      policy: opts.policy || 'auto',
      prod_lead_time: ltMean, prod_lead_time_cv: ltCv,
      plan_committed: anyPlan } };
}

// ── End-to-end loop orchestrator (W7 · the loop → L3) ──────────────────────
// runFullLoop({planning,opts,onStep}) chains the planning solves on ONE dataset,
// in dependency order, CACHING each result so the next step reads the previous
// step's real output (Kinaxis-style "run the whole plan"): committed demand →
// procurement (landed-cost MILP) → aggregate S&OP → production schedule →
// capital (line-capacity NPV) → Monte-Carlo risk on the just-built schedule.
// Each step's payload is the SAME builder the owning tab uses, so the loop can
// never diverge from what a tab would solve. Returns a per-step log
// [{key,label,ok,ms,summary,error}]; onStep(partialLog) streams progress to the UI.
// Loop-local payload builders. Self-contained (call only store primitives + the
// global tab helpers that exist at run time: partsWithSourcing, planParam,
// PLAN_PARAMS, lineRegistryCapacity, linecapPayload) so the chain runs whole even
// if a tab hasn't mounted. Each reads the SAME committed demand / landed BOM the
// tabs use, and downstream steps receive the upstream result (prev) — one dataset.
function _loopProcurementPayload(planning){
  const M = window.M || {};
  const pd = planning.timeGrain==='week'?7:planning.timeGrain==='day'?1:30;
  const grain = planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly';
  const parts = (typeof partsWithSourcing==='function') ? partsWithSourcing(pd) : bomParts(pd);
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const products = fin.map(p=>{ const dem = getItemDemand(p.sku,12);
    return { name:p.sku, demand:dem, capacity:Math.max(400, Math.ceil(Math.max(...dem)*1.5)),
      variable_cost:p.cost, sell_price:p.price, yield_pct:skuYield(p,0.97), parts }; });   // G-I1 measured ?? seed
  const _cfg = appStore.get().config || {};
  return { products, params:{ periods:12, time_grain:grain,
    service_level:_cfg.serviceLevel || 0.95,
    // carry_rate from governed WACC + holding spread (carryRate), not a 0.24 constant.
    carry_rate:(typeof carryRate==='function') ? carryRate(_cfg) : 0.24,
    // G-N1 — open/in-transit POs net the buy; needs horizon_start_date for the date math.
    horizon_start_date: planning.startDate,
    locked_pos: scheduledReceiptsLocked() } };
}
// Per-SKU hands-on LABOR fraction — the share of the machine cycle a WORKER is actually
// occupied (the rest is automated, unattended machine time). 1.0 = fully manual (worker
// busy the whole cycle, the default ⇒ unchanged behaviour); 0.2 = a highly-automated cell
// a worker only loads/unloads. config.skuLaborFrac{sku→0..1}. THIS is the field that makes
// the aggregate's LABOR weighting correct: machine cycle ≠ worker-time when automation varies.
function skuLaborFrac(sku){
  const cfg = (typeof appStore!=='undefined') ? (appStore.get().config||{}) : {};
  const v = (cfg.skuLaborFrac||{})[sku];
  return (v==null || v==='') ? 1.0 : Math.max(0, Math.min(1, Number(v)));
}
// Per-SKU WORKER-minutes per unit = machine cycle × hands-on fraction. The honest labor
// content the people-bound aggregate plan should weight by (NOT raw machine cycle).
function skuWorkerMin(p){ return Math.max(0, (Number(p.cycle)||0) * skuLaborFrac(p.sku)); }
// Aggregate labor-content weights — REPLACES the flat labor_hours_per_unit:1 that silently
// treated every SKU as equal capacity load. The aggregate constraint is P ≤ rate·WORKERS
// (people-bound), so each SKU is weighted by its WORKER-time per unit (cycle × hands-on
// fraction — an automated SKU with a long machine cycle but little attention weighs LESS).
// CRITICAL reconciliation (why it's not a blind drop-in): aggregate.py expresses rate_per_worker
// in these SAME weighted units, so raw minutes would compare a minutes demand against a
// units/worker rate. The weights are therefore DEMAND-WEIGHTED MEAN-NORMALISED to 1.0 — the
// aggregate-unit scale (and thus the rate_per_worker = 30 u/worker calibration) is provably
// preserved; only the MIX of LABOR consumption shifts. Flat 1.0 when no cycle data ⇒ default.
function aggLaborWeights(fg){
  const items = (fg||[]).map(p=>({ sku:p.sku, dem:Math.max(0, Number(p.demand)||0),
    hrs:Math.max(0, skuWorkerMin(p)/60) }));        // WORKER-hours/unit (not machine cycle)
  const dTot = items.reduce((s,i)=>s+i.dem,0);
  const wbar = dTot ? items.reduce((s,i)=>s+i.dem*i.hrs,0)/dTot : 0;   // demand-weighted mean labor content
  const w = {};
  items.forEach(i=>{ w[i.sku] = (wbar>0 && i.hrs>0) ? Math.round((i.hrs/wbar)*1000)/1000 : 1.0; });
  return w;
}
// Network FG on-hand → aggregate opening inventory, expressed in the LABOR-WEIGHTED
// units aggregate.py's inventory balance actually carries (agg_demand is Σ qty·weight,
// so a raw physical sum would be subtly wrong whenever the on-hand MIX skews labor-heavy
// or labor-light — same dimensional consistency as the demand side). The plan already
// knows what Network holds, so it auto-reconciles rather than asking the user to retype.
// Returns the physical sum (the headline "what you hold") AND the labor-weighted
// equivalent (the worker-time yardstick the solver consumes) — both, transparently.
function networkOpeningInv(){
  const M = window.M || {};
  const fg = (M.products||[]).filter(p=>p.cat==='Finished');
  const lw = aggLaborWeights(fg);
  const net = (typeof getNetwork==='function') ? getNetwork() : {};
  const bySku = {};
  (net.onHand||[]).forEach(o=>{ if(o && o.item!=null) bySku[o.item] = (bySku[o.item]||0) + (Number(o.qty)||0); });
  let phys = 0, weighted = 0;
  fg.forEach(p=>{ const q = bySku[p.sku]||0; phys += q; weighted += q * (lw[p.sku]!=null?lw[p.sku]:1); });
  return { phys: Math.round(phys), weighted: Math.round(weighted) };
}
// planOpeningInv(config): the effective t=0 opening inventory the solver uses — an
// explicit override (config.planParams.init_inventory) WINS; otherwise the Network FG
// on-hand converted to the labor-weighted units the aggregate balance carries. Single
// source of truth for the live aggregate payload (plan.jsx) and the cross-stage loop.
function planOpeningInv(config){
  const pp = (config && config.planParams) || {};
  if (pp.init_inventory!=null && pp.init_inventory!=='') return Number(pp.init_inventory);
  return networkOpeningInv().weighted;
}
// G-P2 — service-driven horizon-end cover params for the aggregate solve. Returns {}
// when the feature is OFF (config.planEndCoverEnabled falsy) ⇒ no end_cover_* sent ⇒
// the aggregate plan may end at zero (byte-identical default). When ON, hands the
// solver the service level + cover periods; aggregate.py computes the actual floor
// from its OWN labor-weighted agg_demand (I_T ≥ z·σ·√periods) — the only place the
// labor-weighted σ exists. Single source for BOTH the live Plan tab and the loop.
function aggEndCoverParams(cfg){
  cfg = cfg || (appStore.get().config || {});
  if(!cfg.planEndCoverEnabled) return {};
  return {
    end_cover_service: Number(cfg.serviceLevel) || 0.95,
    end_cover_periods: Math.max(1, Number(cfg.planEndCoverPeriods) || 1),
  };
}
function _loopAggregatePayload(planning){
  const M = window.M || {};
  const cfg = appStore.get().config || {};
  const pp = (window.PLAN_PARAMS) || {};
  const pget = (k, d)=> (typeof planParam==='function' ? planParam(cfg, k) : ((cfg.planParams||{})[k] ?? pp[k] ?? d));
  const rate = pget('rate_per_worker', 30) || 1;
  const lineCap = (typeof lineRegistryCapacity==='function') ? lineRegistryCapacity()
                : (M.lines||[]).reduce((s,l)=>s+(l.cap||0),0);
  const fg = (M.products||[]).filter(p=>p.cat==='Finished');
  const months = (M.aggregate && M.aggregate.months) || [];
  const periods = months.length || 6;
  const slice = appStore.get().demand || {};
  const totAnnual = fg.reduce((s,p)=>s+(p.demand||0),0) || 1;
  const wfCeiling = Math.max((pget('min_workforce',5)||5)+1, Math.round(lineCap/rate));
  const lw = aggLaborWeights(fg);
  return { products: fg.map(p=>({ name:p.sku,
      // B-13 — consume the COMMITTED demand series (getItemDemand — the SAME source
      // procurement + production read) whenever a planner has edited/committed it, so a
      // demand change actually moves the S&OP plan. The Model Map's "forecast ← committed
      // series, wired:true" contract (data.jsx) was previously unmet: the loop planned the
      // static seed master p.demand × the seed month-envelope and IGNORED demand edits, so
      // demand what-ifs silently never moved plan cost. An UNcommitted SKU falls back to the
      // seed-seasonality reslice ⇒ the baseline plan is byte-identical to before the fix.
      forecast: (slice[p.sku] && slice[p.sku].length)
        ? getItemDemand(p.sku, periods)
        : months.map(mo=>Math.max(0, Math.round(mo.dem*(p.demand||0)/totAnnual))),
      labor_hours_per_unit: lw[p.sku] != null ? lw[p.sku] : 1 })),
    params:{ periods, init_workforce:pget('init_workforce',35),
      init_inventory: planOpeningInv(cfg),                          // auto-reconciled from Network FG on-hand (labor-weighted), override wins
      rate_per_worker:rate, reg_cost_per_unit:pget('reg_cost_per_unit',120),
      ot_cost_per_unit:pget('ot_cost_per_unit',180), holding_cost_per_unit:pget('holding_cost_per_unit',24),
      backorder_cost_per_unit:pget('backorder_cost_per_unit',300), hire_cost:pget('hire_cost',8000),
      fire_cost:pget('fire_cost',12000), wage_per_worker:pget('wage_per_worker',22000),
      max_ot_pct:pget('max_ot_pct',0.2), min_workforce:pget('min_workforce',5),
      max_workforce:wfCeiling, allow_backorder:pget('allow_backorder',1),
      ...aggEndCoverParams(cfg) } };   // G-P2 — service-driven end-cover (no-op when OFF)
}
function _loopLinecapPayload(prevAgg){
  // reuse the Plan tab's exact builder when the aggregate result is available
  // (its sku_plans give the disaggregated per-line load); else fall back to a
  // committed-demand build so the chain still produces a real ₹ line dual.
  if(prevAgg && typeof linecapPayload==='function') return linecapPayload(prevAgg);
  const M = window.M || {};
  const lines = (M.lines||[]).map(l=>({ id:l.id, name:l.name, cap:Number(l.cap)||0 }));
  const skus = (M.products||[]).filter(p=>p.cat==='Finished').map(p=>({
    name:p.sku, line:p.line, demand:Math.round(getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12),
    lost_margin_per_unit:Math.max(0,(p.price||0)-(p.cost||0)) }));
  return { lines, skus, params:{} };
}
// LP-A — forecast-first loop step 0. Re-run the demand model competition on each
// finished SKU's real history (M.historyAt) and WRITE the winning series back into
// the committed demand slice (setItemDemand), so every downstream loop step plans
// to FRESH demand truth — the loop closes the demand half, not just supply→risk.
function _loopForecastPayload(planning){
  const M = window.M || {};
  const grain = planning.timeGrain==='week'?'weekly':planning.timeGrain==='day'?'daily':'monthly';
  const holidays = appStore.get().holidays || [];
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const products = fin.map(p=>{
    const hist = historyFor(p.sku, grain);   // W9 — honor an imported / like-modeled history
    const di = getDemandInputs(p.sku);
    const promo_periods = (di.promos||[]).map(x=> hist.length + (x.fidx|0)).filter(x=>x>=0);
    return { name:p.sku, history:hist, promo_periods };
  });
  return { products, params:{
    h_periods: (typeof M.horizonFor==='function') ? M.horizonFor(grain) : 12,
    time_grain: grain,
    season_length: (typeof M.seasonFor==='function') ? M.seasonFor(grain) : undefined,
    horizon_start_date: (M.calendar && M.calendar.start) || undefined,
    holidays: (holidays && holidays.length) ? holidays : undefined } };
}
// LP-B — the loop's production step plans with the SAME governed opts the Production
// tab uses (laborRate, shutdown threshold, time-phasing, holding cost, per-SKU
// routing), read from config. Without this the loop silently used solver defaults,
// so the chained schedule could diverge from what the tab would actually solve.
function productionOptsFromConfig(config){
  config = config || appStore.get().config || {};
  const eff = (v,seed)=> (v!=null && v!=='') ? Number(v) : seed;
  return {
    laborRate:   eff(config.prodLaborRate, 120),
    shutdownPct: eff(config.prodShutdownPct, 25),
    timePhased:  !!config.prodTimePhased,
    holdingCost: eff(config.prodHoldingCost, 2),
    campaignMinRun: eff(config.prodCampaignMinRun, 0),   // PR-4
    routing:     config.prodRouting || {},
    // G-P4 — optional labor envelope: org-wide headcount cap (× 40 h/wk = regular labor
    // budget) and a weekly OT-hours cap. 0 = unbounded ⇒ schedule is machine-constrained
    // only (byte-identical default). A tight headcount forces OT (then infeasible if OT capped).
    laborHeadcountCap: eff(config.prodLaborHeadcountCap, 0),
    laborOtCapHrs:     eff(config.prodLaborOtCapHrs, 0),
  };
}
const LOOP_STEPS = [
  { key:'forecast', label:'Demand — model competition (re-forecast)',
    endpoint:'/api/forecast', build:(pl)=>_loopForecastPayload(pl),
    after:(r)=>{ (r.products||[]).forEach(op=>{ const lb=op.leaderboard||[];
      const w = lb.find(l=>l.model===(op.winner||op.recommendation)) || lb.find(l=>l.status==='ok'&&l.forecast) || lb[0];
      if(w && w.forecast && w.forecast.length) setItemDemand(op.name, w.forecast); }); },
    summary:(r)=>`${(r.products||[]).length} SKUs re-forecast${r.reconciliation?' · reconciled':''}` },
  { key:'procurement', label:'Procurement — landed-cost MILP',
    endpoint:'/api/solve/procurement', build:(pl)=>_loopProcurementPayload(pl),
    summary:(r)=>`${r.status||'solved'} · ${(r.materials||[]).length} parts` },
  { key:'aggregate', label:'Aggregate plan — Hax–Meal S&OP',
    endpoint:'/api/solve/aggregate', build:(pl)=>_loopAggregatePayload(pl),
    summary:(r)=>`strategy ${r.strategy||'?'} · ${(r.periods||[]).length} periods` },
  { key:'production', label:'Production schedule — finite-capacity',
    endpoint:'/api/solve/production', build:(pl,opts)=>productionPayload(pl,(opts&&opts.production)||productionOptsFromConfig()),  // LP-B
    summary:(r)=>`${r.status||'?'} · ${(r.gantt||[]).length} runs · ${r.periods||0} periods` },
  { key:'linecap', label:'Capital signal — ₹ line-capacity dual',
    endpoint:'/api/solve/linecap', build:(pl,opts,prev)=>_loopLinecapPayload(prev.aggregate),
    summary:(r)=>`${(r.lines||[]).filter(l=>l.binding).length}/${(r.lines||[]).length} lines binding` },
  { key:'montecarlo', label:'Risk — Monte Carlo on the committed schedule',
    endpoint:'/api/solve/montecarlo', build:(pl,opts,prev)=>montecarloPayload(pl,{ ...(opts&&opts.montecarlo||{}), prodResult:prev.production }),
    summary:(r)=>`policy ${r.policy_simulated} · CVaR95 ₹${((r.cvar95||0)/1e5).toFixed(2)}L · fill ${r.avg_fill}%` },
];
async function runFullLoop(cfg){
  cfg = cfg || {};
  const planning = cfg.planning || (appStore.get().planning);
  const opts = cfg.opts || {};
  const prev = {};                 // chained results: prev[stepKey] = result
  const log = [];
  for(const step of LOOP_STEPS){
    const entry = { key:step.key, label:step.label, ok:false, ms:0, summary:'', error:null };
    log.push(entry);
    if(cfg.onStep) cfg.onStep([...log]);
    const t0 = (typeof performance!=='undefined'?performance.now():Date.now());
    try{
      const payload = step.build(planning, opts, prev);
      if(!payload){ throw new Error('payload builder unavailable'); }
      const r = await apiPost(step.endpoint, payload);
      prev[step.key] = r;
      if(step.after) step.after(r);               // LP-A — side effect (forecast writes committed demand)
      cacheSolve(step.key, r);                    // downstream tabs read this
      markSolved(step.key);                       // clear staleness on the owning tab
      entry.ok = true; entry.summary = step.summary(r);
    }catch(e){ entry.error = e.message || String(e); }
    entry.ms = Math.round((typeof performance!=='undefined'?performance.now():Date.now()) - t0);
    if(cfg.onStep) cfg.onStep([...log]);
  }
  return log;
}

// ════════════════════════════════════════════════════════════════════════
// 4½. SCENARIO ENGINE (W10/W11 · Platform L4 — branch · run · compare · merge)
//   Kinaxis-style concurrent what-if on ONE model. A scenario is a SNAPSHOT of
//   the editable input slices (committed demand, config, planning, sourcing,
//   network, demand-shaping, costs, holidays) plus the SOLVED KPIs captured when
//   it was last run. Running a scenario is TRANSPARENT to the live working set:
//   we save live (inputs + the solve cache), apply the scenario's inputs, run the
//   full loop, capture KPIs, then RESTORE live — so branches never disturb each
//   other or the base. applyScenario()/mergeScenario() are the deliberate
//   "switch the working set to this branch" actions (they DO overwrite live).
//   Every op is logged to the immutable event trail (§4b) — the audit/version
//   history. Evidence: W10 (scenario branching/compare), W11 (concurrent what-if).
// ════════════════════════════════════════════════════════════════════════
const _SCN_INPUT_KEYS = ['demand','config','planning','sourcing','network','demandInputs','productCosts','holidays'];
function _snapshotSlices(keys){
  const s = appStore.get(); const out = {};
  for(const k of keys) out[k] = JSON.parse(JSON.stringify(s[k] !== undefined ? s[k] : (k==='holidays'?[]:{})));
  return out;
}
function _restoreSlices(snap){ if(snap) appStore.replace(JSON.parse(JSON.stringify(snap))); }
// ── prodArch (B-5) ───────────────────────────────────────────────────────────
// The editable lines / stages / changeover matrix live in the global production
// master window.M (mutated via bumpMaster()), NOT an appStore slice — so the
// slice snapshot/restore above is blind to them and a *capacity* what-if silently
// no-ops and can't be byte-restored. These two mirror that master in/out so
// prodArch becomes a first-class scenario lever like any other. (Each line's
// stages[] ride along inside the deep clone of M.lines.)
function _snapshotProdArch(){
  const M = window.M || {};
  return { lines:      JSON.parse(JSON.stringify(M.lines || [])),
           changeover: JSON.parse(JSON.stringify(M.changeover || [])) };
}
function _restoreProdArch(pa){
  if(!pa) return;
  const M = window.M || (window.M = {});
  if(pa.lines)      M.lines      = JSON.parse(JSON.stringify(pa.lines));
  if(pa.changeover) M.changeover = JSON.parse(JSON.stringify(pa.changeover));
  bumpMaster();   // notify useMasterRev consumers; does NOT mark solves stale
}
// _applyEnvelope(env): restore a full scenario envelope — the appStore input
// slices (+ solve cache on a live restore) via _restoreSlices, PLUS the prodArch
// master via window.M. prodArch is peeled off so it routes to the master and never
// pollutes appStore as a phantom slice. Used by run/apply in place of a bare
// _restoreSlices so EVERY lever (incl. capacity) applies and byte-restores.
function _applyEnvelope(env){
  if(!env) return;
  // B-16 — DO NOT object-rest-destructure here (no `const {prodArch, ...slices} = env`).
  // Babel-standalone hoists a top-level `const _excluded` helper per file for `{a,...r}`,
  // and lib.jsx (Box/Btn) is the SOLE sanctioned emitter by convention; a second one
  // collides in the shared global scope ("Identifier '_excluded' already declared"), which
  // aborts store.jsx execution and BLANKS THE WHOLE APP. (The B-5 fix introduced exactly this
  // regression; it survived because no static/HTTP smoke boots the app — HARNESS-1b's first
  // real-browser run caught it.) Strip prodArch with Object.assign+delete, like capitalPayload.
  const prodArch = env.prodArch;
  const slices = Object.assign({}, env); delete slices.prodArch;
  _restoreSlices(slices);
  if(prodArch) _restoreProdArch(prodArch);
}
// the full transparent-run envelope: inputs + the solve freshness/cache + the
// prodArch master, so a scenario run leaves the live tabs exactly as it found them.
function _snapshotForRun(){
  return { ..._snapshotSlices([..._SCN_INPUT_KEYS, 'solves', 'solveResults']),
           prodArch: _snapshotProdArch() };
}

// _captureKpis(): read the cross-stage solve cache into a flat, comparable KPI row.
// Pure reads of getSolveResult — the REAL solved numbers, never fabricated. Null
// for any solve not present (honest "not run in this scenario").
function _captureKpis(){
  const ag = getSolveResult('aggregate'), pr = getSolveResult('production'),
        lc = getSolveResult('linecap'),  mc = getSolveResult('montecarlo'),
        pc = getSolveResult('procurement');
  const prodUnits = pr && pr.gantt ? pr.gantt.reduce((a,e)=>a+(Number(e.quantity)||0),0) : null;
  const lcLines = lc && lc.lines ? lc.lines : null;
  return {
    planCost:    ag ? (ag.total_cost ?? null) : null,
    planStrategy:ag ? (ag.strategy || null) : null,
    prodStatus:  pr ? (pr.status || null) : null,
    prodUnits,
    prodRuns:    pr && pr.campaign ? (pr.campaign.runs ?? null) : (pr && pr.gantt ? pr.gantt.length : null),
    avgRunUnits: pr && pr.campaign ? (pr.campaign.avg_run_units ?? null) : null,
    procParts:   pc && pc.materials ? pc.materials.length : null,
    procCost:    pc ? (pc.total_cost ?? pc.total ?? null) : null,   // B-14: procurement.py returns `total_cost`, NOT `total` — the B-6 groundwork read the wrong key so procCost was ALWAYS null (HARNESS-2 cost/FX sub-flows + the What-If bot cost delta both silently got null). `?? pc.total` kept as a defensive fallback.
    bindingLines: lcLines ? lcLines.filter(x=>x.binding).length : null,
    lineShadowMax: lcLines ? Math.max(0, ...lcLines.map(x=>Number(x.shadow_price)||0)) : null,
    mcMeanCost:  mc ? (mc.avg_cost ?? null) : null,
    var95:       mc ? (mc.var95 ?? null) : null,
    cvar95:      mc ? (mc.cvar95 ?? null) : null,
    avgFill:     mc ? (mc.avg_fill ?? null) : null,
    minFill:     mc ? (mc.min_fill ?? null) : null,
    policy:      mc ? (mc.policy_simulated || null) : null,
  };
}
// a hook-free scenario-store accessor (initialised lazily).
function getScenarios(){ const sc = appStore.get().scenarios; return sc || { list:{}, order:[], active:'base' }; }
function _putScenarios(sc){ appStore.set({ scenarios: sc }); }
function _newScnId(){ return 'scn_' + Date.now().toString(36) + Math.random().toString(36).slice(2,5); }

// captureScenario(name, note): snapshot the CURRENT live inputs (+ whatever KPIs
// are cached right now) as a named scenario. This is how you "save the base" or
// pin an edited working set as a branch point.
function captureScenario(name, note, quiet){
  const sc = getScenarios();
  const id = _newScnId();
  const scn = { id, name: name || ('Scenario ' + ((sc.order||[]).length + 1)), note: note||'',
    parent: sc.active && sc.active!=='base' ? sc.active : null, createdAt: new Date().toISOString(),
    inputs: { ..._snapshotSlices(_SCN_INPUT_KEYS), prodArch: _snapshotProdArch() },   // B-5 — capacity lever
    kpis: _captureKpis(), ranAt: null };
  _putScenarios({ ...sc, list:{ ...sc.list, [id]: scn }, order:[...(sc.order||[]), id] });
  // quiet=true suppresses the audit event — used by the self-test harness so its
  // throwaway scenarios never inflate the ValueLedger's "scenarios explored" ROI count.
  if(!quiet) logEvent('scenario_create', id, { name: scn.name });
  return id;
}
// branchScenario(fromId, name): copy a scenario's inputs into a new sibling branch.
function branchScenario(fromId, name, note){
  const sc = getScenarios(); const from = (sc.list||{})[fromId]; if(!from) return null;
  const id = _newScnId();
  const scn = { id, name: name || (from.name + ' ✦'), note: note||'', parent: fromId,
    createdAt: new Date().toISOString(), inputs: JSON.parse(JSON.stringify(from.inputs)),
    kpis: null, ranAt: null };
  _putScenarios({ ...sc, list:{ ...sc.list, [id]: scn }, order:[...(sc.order||[]), id] });
  logEvent('scenario_branch', id, { from: fromId });
  return id;
}
// updateScenarioInputs(id, transform): mutate a scenario's input snapshot in place
// via transform(inputs)→inputs (used by the what-if bot to perturb a clone). Clears
// stale KPIs so the row reads "re-run to score".
function updateScenarioInputs(id, transform){
  const sc = getScenarios(); const scn = (sc.list||{})[id]; if(!scn) return;
  const inputs = transform(JSON.parse(JSON.stringify(scn.inputs))) || scn.inputs;
  _putScenarios({ ...sc, list:{ ...sc.list, [id]: { ...scn, inputs, kpis:null, ranAt:null } } });
}
function deleteScenario(id, quiet){
  const sc = getScenarios(); if(!(sc.list||{})[id]) return;
  const list = { ...sc.list }; delete list[id];
  _putScenarios({ ...sc, list, order:(sc.order||[]).filter(x=>x!==id),
    active: sc.active===id ? 'base' : sc.active });
  if(!quiet) logEvent('scenario_delete', id, {});
}
// runScenario(id, opts): the concurrent what-if. Save live → apply this scenario's
// inputs → runFullLoop → capture the solved KPIs onto the scenario → RESTORE live.
// Returns {log, kpis}. The live working set and its solve cache are byte-restored,
// so you can score many branches without ever leaving (or disturbing) the base.
async function runScenario(id, opts){
  opts = opts || {};
  const sc = getScenarios(); const scn = (sc.list||{})[id];
  if(!scn) throw new Error('scenario not found: ' + id);
  const restore = _snapshotForRun();
  try{
    _applyEnvelope(scn.inputs);   // B-5 — applies appStore slices AND the prodArch master
    const log = await runFullLoop({ planning: appStore.get().planning, opts: opts.loopOpts, onStep: opts.onStep });
    const kpis = _captureKpis();
    const sc2 = getScenarios();
    if((sc2.list||{})[id]) _putScenarios({ ...sc2, list:{ ...sc2.list,
      [id]: { ...sc2.list[id], kpis, ranAt:new Date().toISOString(), loopLog:log } } });
    if(!opts.quiet) logEvent('scenario_run', id, { ok: log.filter(s=>s.ok).length, of: log.length });
    return { log, kpis };
  } finally {
    _applyEnvelope(restore);   // live + its solve cache + prodArch master are exactly as before — true isolation
  }
}
// applyScenario(id): DELIBERATELY switch the live working set to this branch's
// inputs (the editable surface every tab reads), mark it active, and flag all
// solves stale so the tabs re-solve against it. This is the non-transparent path.
function applyScenario(id){
  const sc = getScenarios(); const scn = (sc.list||{})[id]; if(!scn) return;
  _applyEnvelope(scn.inputs);   // B-5 — apply prodArch too, so a capacity branch actually switches the master
  _putScenarios({ ...getScenarios(), active:id });
  ['procurement','aggregate','production','linecap','montecarlo','meionet','cvar','profitmix','transport','capital']
    .forEach(k=>markStale(k));
  logEvent('scenario_apply', id, {});
}
// mergeScenario(id): adopt a scenario as the working set of record (apply + an
// explicit merge marker in the audit trail). The Kinaxis "promote this branch".
function mergeScenario(id){ applyScenario(id); logEvent('scenario_merge', id, { note:'promoted to working set' }); }
function useScenarios(){
  const { state } = useStore(s=>s.scenarios || { list:{}, order:[], active:'base' });
  return state;
}

// ── EVA-driven scenario branch (Finance L4 — the ops↔finance wedge) ──────────
// scenarioPruneSkus(skus): clone the live base into a branch that PRUNES the named
// value-destroyer SKUs (zero their committed demand) so the full loop re-solves the
// portfolio WITHOUT them — quantifying whether dropping ROIC<hurdle SKUs actually
// lifts company cost / fill / EVA, or whether their shared-line/shared-part
// contribution was load-bearing. Beyond IBP: a finance flag drives an ops re-plan.
function scenarioPruneSkus(skus, name, note){
  skus = skus || [];
  const id = captureScenario(name || ('Prune ' + skus.length + ' destroyer' + (skus.length===1?'':'s')),
                             note || 'EVA-driven — drop ROIC<hurdle SKUs and re-solve the portfolio');
  updateScenarioInputs(id, (inp)=>{
    const dem = { ...(inp.demand || {}) };
    skus.forEach(s=>{ if(dem[s]) dem[s] = dem[s].map(()=>0); });
    inp.demand = dem; return inp;
  });
  logEvent('scenario_eva_prune', id, { skus });
  return id;
}

// ── Event-sourced replay + version diff/merge (W11 · Platform L4 depth) ──────
// _envelopeOf(idOrBase): the input snapshot for a scenario id, or the LIVE working
// set when 'base'/null. The unit both diff and merge operate on.
function _envelopeOf(idOrBase){
  if(idOrBase === 'base' || idOrBase == null) return _snapshotSlices(_SCN_INPUT_KEYS);
  const scn = (getScenarios().list || {})[idOrBase];
  return scn ? scn.inputs : null;
}
// scenarioDiff(a, b): structural diff between two input envelopes over the fields a
// planner reasons about — committed-demand totals per SKU, config scalars, sourcing
// overrides — so two versions can be COMPARED before a merge. Each row {slice, field,
// a, b}. Pure read; never mutates.
function scenarioDiff(a, b){
  const ea = _envelopeOf(a), eb = _envelopeOf(b);
  if(!ea || !eb) return [];
  const out = [];
  const sum = (arr)=> (arr||[]).reduce((x,y)=>x+(Number(y)||0),0);
  const skus = new Set([...Object.keys(ea.demand||{}), ...Object.keys(eb.demand||{})]);
  skus.forEach(s=>{ const ta=Math.round(sum(ea.demand[s])), tb=Math.round(sum(eb.demand[s]));
    if(ta!==tb) out.push({ slice:'demand', field:s, a:ta, b:tb }); });
  const cfgKeys = new Set([...Object.keys(ea.config||{}), ...Object.keys(eb.config||{})]);
  cfgKeys.forEach(k=>{ const va=(ea.config||{})[k], vb=(eb.config||{})[k];
    if(va && typeof va==='object') return;
    if(va!==vb) out.push({ slice:'config', field:k, a:va, b:vb }); });
  const srcKeys = new Set([...Object.keys(ea.sourcing||{}), ...Object.keys(eb.sourcing||{})]);
  srcKeys.forEach(k=>{ const va=JSON.stringify((ea.sourcing||{})[k]||{}), vb=JSON.stringify((eb.sourcing||{})[k]||{});
    if(va!==vb) out.push({ slice:'sourcing', field:k, a:'override', b:'override' }); });
  return out;
}
// mergeScenarioFields(targetId, sourceId, picks): a real cherry-pick VERSION MERGE —
// copy the chosen {slice,field} values FROM source INTO target's input snapshot
// (vs applyScenario's whole-branch overwrite). Clears the target's KPIs so it reads
// "re-run to score". Logged to the immutable trail.
function mergeScenarioFields(targetId, sourceId, picks){
  const sc = getScenarios(); const tgt = (sc.list||{})[targetId]; const src = _envelopeOf(sourceId);
  if(!tgt || !src) return;
  const inputs = JSON.parse(JSON.stringify(tgt.inputs));
  (picks||[]).forEach(({ slice, field })=>{
    if(!inputs[slice]) inputs[slice] = {};
    inputs[slice][field] = JSON.parse(JSON.stringify((src[slice]||{})[field]));
  });
  _putScenarios({ ...sc, list:{ ...sc.list, [targetId]:{ ...tgt, inputs, kpis:null, ranAt:null } } });
  logEvent('scenario_merge_fields', targetId, { from: sourceId, picks });
}
// replayLog(): the event trail as a replayable version history — a pure read of the
// immutable events[], the auditable "what changed, when, by which op". The UI steps
// through it to reconstruct how the working set reached its current state.
function replayLog(){ return (appStore.get().events || []).map(e=>({ ...e })); }

// ── MSME tier — single derived fact, reused by Setup + Sourcing + Finance ──
// MSMED Act 2020 (₹Cr): Micro inv≤1 & TO≤5; Small ≤10 & ≤50; Medium ≤50 & ≤250; else not an MSME.
function msmeTier(investmentCr, annualTurnoverCr){
  const inv=Number(investmentCr)||0, to=Number(annualTurnoverCr)||0;
  const tier = (inv<=1 && to<=5) ? 'MICRO'
             : (inv<=10 && to<=50) ? 'SMALL'
             : (inv<=50 && to<=250) ? 'MEDIUM'
             : 'NOT MSME';
  return { tier, isMsme: tier!=='NOT MSME',
    band: { MICRO:'investment ≤ ₹1Cr · turnover ≤ ₹5Cr', SMALL:'investment ≤ ₹10Cr · turnover ≤ ₹50Cr',
            MEDIUM:'investment ≤ ₹50Cr · turnover ≤ ₹250Cr', 'NOT MSME':'investment > ₹50Cr or turnover > ₹250Cr' }[tier] };
}

// G-I2 — ABC-differentiated cycle-service target for a finished SKU. A class-A item
// earns a tighter fill (higher z) than a long-tail C-item, instead of one global α.
// Falls back to the global serviceLevel when the SKU/class isn't found ⇒ safe default.
function serviceLevelForSku(sku){
  const cfg = appStore.get().config || {};
  const base = Number(cfg.serviceLevel) || 0.95;
  const prod = (window.M && (window.M.products||[]).find(p=>p.sku===sku)) || null;
  const abc = prod && prod.abc;
  const map = cfg.abcService || {};
  const v = abc!=null ? map[abc] : null;
  return (v!=null && v!=='') ? Number(v) : base;
}

// ════════════════════════════════════════════════════════════════════════
// 4. RECOMPUTE DAG + EVENT LOG (W0 · Platform foundations — EXECUTION_PLAN P1,P2)
//    The orchestration spine. When an upstream INPUT changes, every solver that
//    consumes it is flagged STALE — and ONLY downstream solvers, not the whole
//    app — so the UI can say "re-solve to trust these numbers." The event log is
//    the immutable record of every plan-changing action. Both live in appStore
//    so they persist (localStorage) and any standalone stage can read them.
//    Evidence: CRITIQUE_R2 Part D (no recompute cascade), Part H (no event log).
// ════════════════════════════════════════════════════════════════════════

// ── 4a. Dependency graph — solveKey → the INPUT sources it consumes (P1) ────
// Read each row as: "<solver> must re-run when any of these change." Single
// source of truth for staleness. Sources are the editable masters: demand
// (committed forecast), network (nodes/lanes/suppliers/contracts/onHand),
// productCosts, config (tax/FX/service level), planning (grain/horizon/calendar),
// bom (shared parts). A solveKey may also depend on ANOTHER solve (montecarlo
// chains off the committed procurement plan) — staleness then cascades.
// ── Ph2 · config dependency tokens ───────────────────────────────────────────
// The single coarse 'config' token re-flagged EVERY config-dependent solve on
// ANY config edit (e.g. changing the profit-mix warehouse cap falsely staled
// procurement). The split below carves out the two field groups whose reader
// set is provably a SINGLE solver family, so their edits cascade precisely:
//   cfg.prod   → production / aggregate / linecap  (the scheduler knobs — also
//                FIXES a prior gap: these solves never listed 'config', so prod-
//                opt edits silently failed to stale them).
//   cfg.profit → profitmix                          (pmBudget / pmWarehouse).
// Everything else stays on the broad 'config' token ON PURPOSE: taxRate, finEquity,
// finDebt etc. fan into WACC → carryRate() → the whole inventory family, so a
// finer token there would SILENTLY under-stale. Over-staling within 'config' is
// safe; under-staling is the bug we refuse. CONFIG_TOKEN maps each edited field
// to its token; configTokens() unions them for setConfig.
const CONFIG_TOKEN = {
  prodLaborRate:'cfg.prod', prodShutdownPct:'cfg.prod', prodTimePhased:'cfg.prod',
  prodHoldingCost:'cfg.prod', prodCampaignMinRun:'cfg.prod', prodRouting:'cfg.prod',
  prodLaborHeadcountCap:'cfg.prod', prodLaborOtCapHrs:'cfg.prod',   // G-P4
  planEndCoverEnabled:'cfg.prod', planEndCoverPeriods:'cfg.prod',   // G-P2 (aggregate dep)
  skuLaborFrac:'cfg.prod',
  pmBudget:'cfg.profit', pmWarehouse:'cfg.profit',
};
function configTokens(patch){
  const toks = new Set();
  for(const k of Object.keys(patch||{})) toks.add(CONFIG_TOKEN[k] || 'config');
  return toks.size ? [...toks] : ['config'];
}
const SOLVE_DEPS = {
  procurement: ['demand','network','productCosts','planning','bom','config','sourcing'],
  policy:      ['demand','network','productCosts','planning','bom','config','sourcing'],  // (s,S)/(R,Q) autopilot
  rolling:     ['demand','network','productCosts','planning','bom','config','sourcing'],  // rolling re-plan / nervousness
  meio:        ['demand','productCosts','planning','bom','config','sourcing'],            // multi-echelon SS placement (RM→WIP→FG)
  meionet:     ['demand','productCosts','planning','bom','config','sourcing'],            // W8 — multi-product risk pooling on shared parts
  cvar:        ['demand','productCosts','planning','bom','config','sourcing'],            // costly-item newsvendor (h vs p) + CVaR robust stock
  production:  ['demand','planning','productCosts','prodArch','cfg.prod'],   // prodArch = editable lines/stages/changeover; cfg.prod = scheduler knobs
  aggregate:   ['demand','planning','productCosts','prodArch','cfg.prod'],   // S&OP (worker-time weighting reads cfg.prod skuLaborFrac)
  linecap:     ['demand','planning','productCosts','prodArch','cfg.prod'],   // PL-A — line-capacity shadow price (₹/unit)
  profitmix:   ['demand','productCosts','config','cfg.profit'],              // cfg.profit = pmBudget / pmWarehouse caps
  transport:   ['demand','network'],
  capital:     ['demand','productCosts','config'],
  montecarlo:  ['demand','procurement','production','sourcing'],   // risk runs on the committed plan (R-1)
};

// markStale(key): flag every solve that depends — directly or transitively — on
// `key`. Used both when a SOURCE changes (key='demand') and when a SOLVE re-runs
// (key='procurement' → its consumers montecarlo/cvar go stale). The "already
// stale" guard terminates the walk and prevents cycles.
function markStale(key){
  const cur = { ...(appStore.get().solves || {}) };
  const ts = new Date().toISOString();
  let touched = false;
  // Batch 4 — remember the ROOT source that triggered staleness (the thing the user
  // actually changed, e.g. 'demand'/'prodArch'/'config') so the Exception Cockpit can
  // say "stale because you edited X" instead of a generic "inputs changed". The root
  // is the original markStale argument, carried unchanged through the cascade.
  const root = key;
  const visit = (k)=>{
    for(const [solve, deps] of Object.entries(SOLVE_DEPS)){
      if(deps.includes(k) && !(cur[solve] && cur[solve].stale)){
        cur[solve] = { ...(cur[solve]||{}), stale:true, staleSrc: root, staleAt: ts };
        touched = true;
        visit(solve);   // cascade to this solve's own consumers
      }
    }
  };
  visit(key);
  if(touched) appStore.set({ solves: cur });
}

// markSolved(solveKey, result?): a solver just produced a fresh result — clear its
// stale flag, stamp ranAt, and invalidate anything computed from its (now
// superseded) previous output. If the fresh `result` is passed it is CACHED
// (solveResults[key]) so downstream stages / runFullLoop can read this solve's
// real output without re-running it. Call right after useSolve.run() resolves.
function markSolved(solveKey, result){
  const cur = { ...(appStore.get().solves || {}) };
  const ts = new Date().toISOString();
  cur[solveKey] = { stale:false, ranAt:ts };
  const patch = { solves: cur };
  if(result !== undefined){
    const rc = { ...(appStore.get().solveResults || {}) };
    rc[solveKey] = { result, ranAt:ts };
    patch.solveResults = rc;
  }
  appStore.set(patch);
  markStale(solveKey);   // downstream consumers must now re-run
}
// getSolveResult(key): non-reactive read of the last cached result for a solve
// (null if never run / not cached). cacheSolve(key,result): write without
// touching freshness (used by the orchestrator between chained steps).
function getSolveResult(key){ const e = (appStore.get().solveResults||{})[key]; return e ? e.result : null; }
function cacheSolve(key, result){
  const rc = { ...(appStore.get().solveResults || {}) };
  rc[key] = { result, ranAt:new Date().toISOString() };
  appStore.set({ solveResults: rc });
  return result;
}
function useSolveResult(key){
  const { state } = useStore(s=>s.solveResults||{});
  const e = state[key] || {};
  return { result: e.result || null, ranAt: e.ranAt ? new Date(e.ranAt) : null };
}

// useStale(solveKey): subscribe to one solve's freshness for the StaleMark UI.
function useStale(solveKey){
  const { state } = useStore(s=>s.solves||{});
  const e = state[solveKey] || {};
  return { stale: !!e.stale, ranAt: e.ranAt ? new Date(e.ranAt) : null, neverRun: !e.ranAt };
}

// ── 4b. Event log — immutable audit trail (P2) ─────────────────────────────
// Append-only. type = 'override'|'cancel'|'replan'|'actuals'|'commit'|... ;
// target = what it acted on (a SKU, a PO, 'demand'); detail = optional
// before/after payload. Returns the stored event. Never mutated or deleted —
// the auditable record of WHAT changed and WHEN, replayable by a version history.
function logEvent(type, target, detail){
  const cur = appStore.get().events || [];
  const ev = { id: cur.length ? cur[cur.length-1].id + 1 : 1,
    type, target: target||null, detail: detail||null, ts: new Date().toISOString() };
  appStore.set({ events: [...cur, ev] });
  return ev;
}
function getEvents(filter){
  const evs = appStore.get().events || [];
  return typeof filter==='function' ? evs.filter(filter) : evs;
}
function useEvents(){
  const { state } = useStore(s=>s.events||[]);
  return { events: state, log: logEvent };
}

// ── (R14) Editable master data — direct M.* edits, reactive + stale cascade ────
// Every payload builder reads window.M LIVE, so editing the master in place is the
// ONE change that reaches all solvers at once (no per-builder threading). React
// can't see a plain-object mutation, so we bump a counter slice (_masterRev) to
// re-render subscribers, and flag the owning source slice stale so the recompute
// DAG prompts a re-run. Backs the editable Products catalog (yield/shelf/salvage)
// and the per-part BOM scrap. NOTE the discipline (see the audit): yield is a real
// lever for EVERY SKU; salvage/shelf only bite when shelf_life < horizon (expiry
// actually occurs), so the UI exposes those as governed advanced inputs, not a
// field scattered on every row.
function bumpMaster(){ appStore.set({ _masterRev: (appStore.get()._masterRev||0)+1 }); }
function useMasterRev(){ const { state } = useStore(s=>s._masterRev||0); return state; }
function editProductAttr(sku, patch){
  const M = window.M || {}; const p = (M.products||[]).find(x=>x.sku===sku); if(!p) return;
  Object.assign(p, patch); bumpMaster(); try{ markStale('productCosts'); }catch(e){}
  logEvent('override', sku, { fields:Object.keys(patch), to:patch });
}
function editPartAttr(part, patch){
  const M = window.M || {}; const b = (M.bom||[]).find(x=>x.part===part); if(!b) return;
  Object.assign(b, patch); bumpMaster(); try{ markStale('bom'); }catch(e){}
  logEvent('override', part, { fields:Object.keys(patch), to:patch });
}
function addProduct(seed){
  const M = window.M || {};
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const base = fin[0] || {};
  const n = fin.length + 1;
  const sku = (seed&&seed.sku) || `TPA-NEW${n}`;
  if((M.products||[]).some(p=>p.sku===sku)) return null;          // no dup skus
  // copy a finished template for safe solver defaults, zero demand (won't be built
  // until the user gives it demand), then overlay the seed.
  const np = { ...base, sku, name:(seed&&seed.name)||`New Product ${n}`, demand:0, ...seed, cat:'Finished' };
  M.products.push(np);
  if(Array.isArray(M.items)) M.items.push({ id:sku, code:sku, name:np.name, kind:'FG', uom:'unit', family:'General' });
  bumpMaster(); try{ markStale('productCosts'); }catch(e){}
  logEvent('commit', sku, { added:true });
  return np;
}

// ── Production architecture editing (Batch 3) ───────────────────────────────
// Lines → stages → machines is master data and was read-only (a Fact-5 bug). We
// mutate window.M.lines / M.changeover IN PLACE (the same discipline as
// editProductAttr) + bump _masterRev to re-render + flag the production-family
// solves stale via the new 'prodArch' source. productionPayload already reads
// M.lines/M.changeover directly, so no payload rewiring is needed.
//   • Line capacity & bottleneck are DERIVED, never typed: line.cap = its slowest
//     stage's cap; bottleneck = that stage. So editing one stage re-derives the
//     line — the "a line is only as fast as its slowest stage" rule stays true.
//   • A stage carries machines (m), workers (w), cycle (ct), OEE and capacity (cap).
function _recalcLine(l){
  const sts = (l && l.stages) || [];
  if(!sts.length){ if(l){ l.cap = 0; l.bottleneck = '—'; } return; }
  let min = Infinity, bn = sts[0];
  sts.forEach(s=>{ const c = Number(s.cap)||0; if(c < min){ min = c; bn = s; } });
  l.cap = (min===Infinity ? 0 : min);
  l.bottleneck = bn.name;
  sts.forEach(s=>{ s.bottleneck = (s===bn); });
}
function _prodChanged(target, patch){
  bumpMaster(); try{ markStale('prodArch'); }catch(e){}
  logEvent('override', target, patch);
}
function editLine(lineId, patch){
  const M = window.M || {}; const l = (M.lines||[]).find(x=>x.id===lineId); if(!l) return;
  Object.assign(l, patch); _prodChanged(lineId, { fields:Object.keys(patch), to:patch });
}
function editStage(lineId, stageId, patch){
  const M = window.M || {}; const l = (M.lines||[]).find(x=>x.id===lineId); if(!l) return;
  const s = (l.stages||[]).find(x=>x.id===stageId); if(!s) return;
  Object.assign(s, patch); _recalcLine(l);
  _prodChanged(lineId+'/'+stageId, { fields:Object.keys(patch), to:patch });
}
function addStage(lineId){
  const M = window.M || {}; const l = (M.lines||[]).find(x=>x.id===lineId); if(!l) return;
  const n = (l.stages||[]).length + 1;
  const st = { id:`ST-${lineId.replace('LINE-','L')}-${Date.now()%10000}`, name:`Stage ${n}`,
    m:1, w:1, ct:2, oee:0.85, cap:1200 };
  (l.stages = l.stages||[]).push(st); _recalcLine(l);
  bumpMaster(); try{ markStale('prodArch'); }catch(e){}
  logEvent('commit', lineId, { addedStage:st.id });
  return st;
}
function delStage(lineId, stageId){
  const M = window.M || {}; const l = (M.lines||[]).find(x=>x.id===lineId); if(!l) return;
  l.stages = (l.stages||[]).filter(s=>s.id!==stageId); _recalcLine(l);
  bumpMaster(); try{ markStale('prodArch'); }catch(e){}
  logEvent('cancel', lineId, { removedStage:stageId });
}
function addLine(){
  const M = window.M || {}; const lines = (M.lines = M.lines||[]);
  let n = lines.length + 1, id = `LINE-${String(n).padStart(2,'0')}`;
  while(lines.some(l=>l.id===id)){ n++; id = `LINE-${String(n).padStart(2,'0')}`; }
  const ln = { id, name:`New Line ${n}`, oee:0.82, shifts:1, cap:1200, bottleneck:'—', stages:[
    { id:`ST-${id}-1`, name:'Stage 1', m:1, w:1, ct:2, oee:0.85, cap:1200 } ] };
  _recalcLine(ln); lines.push(ln);
  bumpMaster(); try{ markStale('prodArch'); }catch(e){}
  logEvent('commit', id, { addedLine:true });
  return ln;
}
function delLine(lineId){
  const M = window.M || {}; M.lines = (M.lines||[]).filter(l=>l.id!==lineId);
  bumpMaster(); try{ markStale('prodArch'); }catch(e){}
  logEvent('cancel', lineId, { removedLine:true });
}
function setChangeover(ri, ci, val){
  const M = window.M || {};
  if(!M.changeover || !M.changeover[ri] || ri===ci) return;     // diagonal stays '—'
  const num = Number(val);
  if(val==='' || val==null || isNaN(num)) return;
  M.changeover[ri][ci] = Math.max(0, num);
  bumpMaster(); try{ markStale('prodArch'); }catch(e){}
  logEvent('override', `changeover[${ri}][${ci}]`, { to:num });
}

// ── (R14) Model JSON round-trip — real backing for the "Import / Export" headers
// (was inert). Exports the editable master fields + the persisted store slices;
// import matches master rows by sku/part and replaces the store slices.
function exportModelJson(){
  const M = window.M || {}; const s = appStore.get();
  return JSON.stringify({
    _kind:'es-model', _version:'2.0', exportedAt:new Date().toISOString(),
    products:(M.products||[]).map(p=>({ sku:p.sku, name:p.name, cat:p.cat, demand:p.demand,
      price:p.price, cost:p.cost, yield:p.yield, shelf:p.shelf, salvage:p.salvage, moq:p.moq })),
    bom:(M.bom||[]).map(b=>({ part:b.part, name:b.name, qty:b.qty, cost:b.cost, lt:b.lt, moq:b.moq, scrap:b.scrap })),
    state:{ config:s.config, planning:s.planning, productCosts:s.productCosts,
      sourcing:s.sourcing, demandInputs:s.demandInputs, bomOverrides:s.bomOverrides },
  }, null, 2);
}
function downloadText(filename, text, mime){
  try{ const blob = new Blob([text], { type:mime||'application/json' });
    const url = URL.createObjectURL(blob); const a = document.createElement('a');
    a.href = url; a.download = filename; document.body.appendChild(a); a.click();
    a.remove(); setTimeout(()=>URL.revokeObjectURL(url), 1000);
  }catch(e){}
}
function importModelJson(text){
  let m; try{ m = JSON.parse(text); }catch(e){ return { ok:false, error:'Not valid JSON' }; }
  if(!m || m._kind!=='es-model') return { ok:false, error:'Not an es-model export (missing _kind)' };
  const M = window.M || {}; let nP=0, nB=0;
  (m.products||[]).forEach(row=>{ const p=(M.products||[]).find(x=>x.sku===row.sku); if(p){ Object.assign(p, row); nP++; } });
  (m.bom||[]).forEach(row=>{ const b=(M.bom||[]).find(x=>x.part===row.part); if(b){ Object.assign(b, row); nB++; } });
  if(m.state) appStore.set(m.state);
  bumpMaster(); try{ markStale('productCosts'); markStale('bom'); }catch(e){}
  logEvent('replan', 'model-import', { products:nP, parts:nB });
  return { ok:true, products:nP, parts:nB };
}
// reportPdf(extra): builds a forgiving payload from the live master + cached solves
// and downloads the real PDF from /api/report/pdf (generate_report, reportlab).
async function reportPdf(extra){
  const M = window.M || {}; const s = appStore.get();
  const sr = s.solveResults || {};
  const products = (M.products||[]).filter(p=>p.cat==='Finished').map(p=>({
    name:p.name, sku:p.sku, sell_price:p.price, variable_cost:p.cost,
    shelf_life:Math.round((Number(p.shelf)||365)/7), yield_pct:p.yield||0.95,
    capacity:p.demand, bom:(M.bom||[]).map(b=>({ name:b.name, qty_per:b.qty, cost:b.cost, lead_time:b.lt, moq:b.moq })) }));
  const payload = { config:s.config||{}, products,
    solver_results:(sr.profit&&sr.profit.result)||(sr.procurement&&sr.procurement.result)||{},
    mc_results:(sr.montecarlo&&sr.montecarlo.result)||{}, ...(extra||{}) };
  const res = await fetch('/api/report/pdf', { method:'POST',
    headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  if(!res.ok) throw new Error('report failed ('+res.status+')');
  const blob = await res.blob(); const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = 'supply_chain_report.pdf';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
  logEvent('commit', 'report-pdf', { products:products.length });
}

Object.assign(window, {
  apiPost, apiGet, useSolve,
  bumpMaster, useMasterRev, editProductAttr, editPartAttr, addProduct,
  editLine, editStage, addStage, delStage, addLine, delLine, setChangeover,
  exportModelJson, importModelJson, downloadText, reportPdf,
  appStore, useStore, useConfig, usePlanning, useCalendar, useProductCosts,
  getNetwork, useNetwork, msmeTier, networkOpeningInv, planOpeningInv, serviceLevelForSku,
  getItemDemand, setItemDemand, getFinishedDemand, bomParts, bomForSku, editPartQty, transportPayload,
  productionPayload, finishedWeeklyDemand, aggEndCoverParams,
  getDemandInputs, useDemandInputs, useHolidays,
  getHistoryImport, setHistoryImport, useHistoryImport, historyFor, parseHistoryCsv, bucketHistory,
  getYieldConfirmations, measuredYield, skuYield, logYieldConfirmation, clearYieldConfirmations, useYieldConfirmations,
  sourcingDefault, getSourcing, useSourcing, effLandedCost, fxFactor, freightSteps, skuWeightKg, skuVolM3,
  landedRate, landedBuildup, landedDetailSeed,
  STORAGE_CLASSES, STORAGE_CLASS_LABEL, storageClassFor, nodeClassCap, nodeStorageUtil,
  costWaterfallLive, tcoPerSku,
  hsDuty, originConcentration, COUNTRY_NAME,
  signals, commodityFactor, portDelayPeriods,
  SOLVE_DEPS, markStale, markSolved, useStale, logEvent, getEvents, useEvents,
  cacheSolve, getSolveResult, useSolveResult,
  montecarloPayload, productionPlanBySku, runFullLoop, LOOP_STEPS, productionOptsFromConfig,
  getScenarios, useScenarios, captureScenario, branchScenario, updateScenarioInputs,
  deleteScenario, runScenario, applyScenario, mergeScenario, _captureKpis,
  scenarioPruneSkus, scenarioDiff, mergeScenarioFields, replayLog,
});
