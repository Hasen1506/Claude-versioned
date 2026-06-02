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
function useSolve(endpoint, buildPayload){
  const [solving, setSolving] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState(null);
  const [ranAt,   setRanAt]   = useState(null);
  const run = async (override)=>{
    setSolving(true); setError(null);
    try{
      const payload = (override!==undefined) ? override : (buildPayload ? buildPayload() : {});
      const data = await apiPost(endpoint, payload);
      setResult(data); setRanAt(new Date());
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
    gstRegistered:true, city:'Chennai', plantState:'TN',
    // MSMED Act classification inputs — the tier is DERIVED from these (see msmeTier()).
    annualTurnoverCr:38.40,   // ₹ Cr
    investmentCr:9.40,        // ₹ Cr (plant & machinery)
    // FX table (₹ per 1 unit), as-of stamp; every $→₹ reads this.
    fxRates:{ USD:84.20, EUR:91.40, JPY:0.563 },
    fxAsOf:'30 May 2026 · 14:32 IST',
  },
  planning: {
    timeGrain:'week', horizonLength:52, startDate:'2026-06-01',
    workDaysPerWeek:6, indianHolidays:true,
    frozenWeeks:4, slushyWeeks:12,
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
  // transport / capital MILP payloads read via getItemDemand / getFinishedDemand —
  // so every downstream solver plans the SAME demand the forecast produced.
  // Empty until a forecast lands; reads fall back to M.products[].demand spread evenly.
  demand: {},
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
};

const appStore = {
  s: (()=>{ try{ const raw=localStorage.getItem('es_state'); return raw?JSON.parse(raw):null; }catch(e){ return null; } })(),
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
function useConfig(){   const { state, patch } = useStore(s=>s.config);   return { config:state,   setConfig:(p)=>{ patch({config:p}); markStale('config'); } }; }
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
const _NET_KEYS = ['nodes','lanes','suppliers','contracts','onHand'];
function getNetwork(){
  const slice = appStore.get().network || {};
  const M = window.M || {};
  const out = {};
  for(const k of _NET_KEYS) out[k] = slice[k] || M[k] || [];
  return out;
}
function useNetwork(){
  const { state, patch } = useStore(s=>s.network||{});
  const M = window.M || {};
  const network = {};
  for(const k of _NET_KEYS) network[k] = state[k] || M[k] || [];
  return { network, setNetwork:(p)=>{ patch({ network:{ ...state, ...p } }); markStale('network'); } };
}

// ── Demand series (KEYSTONE) — the shared per-SKU forecast the MILPs plan to ──
// getItemDemand(sku,T): the forecast series the Demand stage wrote, resampled to
// T periods; falls back to M.products[].demand spread evenly when no forecast yet.
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
    series = Array(T).fill(Math.round(annual / T));
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
  };
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
// effLandedCost(rawCost, src): quoted cost → landed cost the MILP plans against.
function effLandedCost(rawCost, src){
  const pct = Number(src && src.dutyFreightPct) || 0;
  return Math.round(Number(rawCost||0) * (1 + pct/100) * 100) / 100;
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
// bomParts(periodDays): map mock `M.bom` rows → the procurement solver's part
// schema (one shared illustrative BOM — documented limitation). Reused by Sourcing
// + Console. Lead time on `M.bom` is in DAYS; the solver counts in PERIODS, so we
// convert by the period length (30d monthly / 7d weekly) — otherwise a 14-day lead
// reads as 14 months and the part can never arrive within the horizon.
function bomParts(periodDays){
  const M = window.M || {};
  const pd = periodDays || 30;
  return (M.bom || []).map(b=>({
    name:b.name, cost:b.cost, qty_per:b.qty, lead_time:Math.max(1, Math.round(b.lt / pd)),
    moq:b.moq, hold_pct:b.hold, ordering_cost:120, scrap_factor:0.01, rm_shelf:b.shelf,
    // size order/storage caps off the MOQ so a single MOQ lot is always orderable
    // and storable (defaults of 9999 go infeasible against a 10 000-unit bolt MOQ).
    max_order:Math.max(b.moq * 5, 50000), rm_capacity:Math.max(b.moq * 3, 50000),
  }));
}

// transportPayload(): outbound lanes (from the network topology) each carry the
// finished-goods flow for one period. Tonnage = monthly FG units × an assumed
// unit weight (TPAC bearings ≈ 3 kg — the one documented assumption, since the
// mock lanes carry no weights); value = units × price. Shared by Console + Logistics.
const _UNIT_WEIGHT_KG = 3.0;   // assumption: avg finished-bearing shipping weight
function transportPayload(){
  const M = window.M || {};
  const net = getNetwork();
  const outbound = (net.lanes||[]).filter(l=>l.direction==='outbound');
  const fin = (M.products||[]).filter(p=>p.cat==='Finished');
  const totalMonthly = fin.reduce((s,p)=>s + getItemDemand(p.sku,12).reduce((a,b)=>a+b,0)/12, 0);
  const avgPrice = fin.length ? fin.reduce((s,p)=>s+p.price,0)/fin.length : 1850;
  // spread the monthly FG flow across the outbound lanes
  const perLane = outbound.length ? totalMonthly / outbound.length : totalMonthly;
  const shipments = (outbound.length?outbound:[{from:'PLANT',to:'DC',mode:'FTL'}]).map(l=>({
    name:`${l.from}→${l.to}`, origin:l.from, destination:l.to,
    weight_kg:Math.max(30, Math.round(perLane * _UNIT_WEIGHT_KG)),
    volume_cbm:Math.max(0.1, +(perLane * 0.004).toFixed(1)),
    value:Math.round(perLane * avgPrice), deadline_days:7,
  }));
  return { shipments, params:{} };
}

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
const SOLVE_DEPS = {
  procurement: ['demand','network','productCosts','planning','bom','config','sourcing'],
  policy:      ['demand','network','productCosts','planning','bom','config','sourcing'],  // (s,S)/(R,Q) autopilot
  rolling:     ['demand','network','productCosts','planning','bom','config','sourcing'],  // rolling re-plan / nervousness
  production:  ['demand','planning','productCosts'],
  aggregate:   ['demand','planning','productCosts'],   // S&OP
  profitmix:   ['demand','productCosts','config'],
  transport:   ['demand','network'],
  capital:     ['demand','productCosts','config'],
  montecarlo:  ['demand','procurement'],   // risk runs on the committed supply plan
  cvar:        ['demand','procurement'],
};

// markStale(key): flag every solve that depends — directly or transitively — on
// `key`. Used both when a SOURCE changes (key='demand') and when a SOLVE re-runs
// (key='procurement' → its consumers montecarlo/cvar go stale). The "already
// stale" guard terminates the walk and prevents cycles.
function markStale(key){
  const cur = { ...(appStore.get().solves || {}) };
  let touched = false;
  const visit = (k)=>{
    for(const [solve, deps] of Object.entries(SOLVE_DEPS)){
      if(deps.includes(k) && !(cur[solve] && cur[solve].stale)){
        cur[solve] = { ...(cur[solve]||{}), stale:true };
        touched = true;
        visit(solve);   // cascade to this solve's own consumers
      }
    }
  };
  visit(key);
  if(touched) appStore.set({ solves: cur });
}

// markSolved(solveKey): a solver just produced a fresh result — clear its stale
// flag, stamp ranAt, and invalidate anything computed from its (now superseded)
// previous output. Call from a stage right after useSolve.run() resolves.
function markSolved(solveKey){
  const cur = { ...(appStore.get().solves || {}) };
  cur[solveKey] = { stale:false, ranAt:new Date().toISOString() };
  appStore.set({ solves: cur });
  markStale(solveKey);   // downstream consumers must now re-run
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

Object.assign(window, {
  apiPost, apiGet, useSolve,
  appStore, useStore, useConfig, usePlanning, useCalendar, useProductCosts,
  getNetwork, useNetwork, msmeTier,
  getItemDemand, setItemDemand, getFinishedDemand, bomParts, transportPayload,
  getDemandInputs, useDemandInputs, useHolidays,
  sourcingDefault, getSourcing, useSourcing, effLandedCost, freightSteps,
  SOLVE_DEPS, markStale, markSolved, useStale, logEvent, getEvents, useEvents,
});
