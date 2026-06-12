#!/usr/bin/env node
/*
 * HARNESS-1b · Golden-path cross-solver IDENTITY harness  (Observability spec, Part 6)
 * ----------------------------------------------------------------------------------
 * The end-to-end check HARNESS-1 (model_check.js) explicitly deferred:
 *
 *   "the live 6-way cross-solver IDENTITY assertions … need WIRED data, so they are
 *    delivered by OBS-2 in the running app … A pure-CI golden-path that replays them
 *    needs payload fixtures captured from the app — that is HARNESS-1b."
 *
 * WHY a browser, not a node payload-rebuild (the honesty point — see the
 * verification-depth-honesty memory). The cross-solver identities only mean
 * something if the payloads are EXACTLY what the UI sends. The UI's payload
 * builders (productionPayload / profitmixPayload / linecapPayload / _loopAggregate…
 * / montecarloPayload / meioNetworkPayload) read window.M + the live appStore and a
 * web of helpers. Rebuilding them in node would be a *reconstruction* that can drift
 * from the real thing — "a fake check dressed as a real one." So HARNESS-1b loads
 * the REAL app in headless Chromium and calls the REAL builders + the REAL
 * runFullLoop against the LIVE solvers. Nothing is paraphrased: this is the
 * genuinely OBSERVED end-to-end run, not a reasoned/sampled stand-in.
 *
 * WHAT it asserts (the identities OBS-2's ConsistencyPanel only DISPLAYS passively;
 * here they are hard PASS/FAIL with an exit code). The honest pass-conditions matter
 * — a naive version gets two of them WRONG:
 *   · I-5  demand ⇄ production reconcile   — Σ committed demand vs Σ production build, ratio∈[0.7,1.4]
 *   · B-13 aggregate sources COMMITTED dem — _loopAggregatePayload.forecast == getItemDemand (NOT the seed master)
 *   · I-3  carry rate anchored to hurdle   — carryRate == finBlendedHurdle().wacc + holding spread (FIN-8)
 *   · #5   MC ran on the COMMITTED plan    — montecarlo ranAt ≥ production ranAt AND policy_simulated=='plan' (B-7)
 *   · I-2  bottleneck is priced            — profit-mix yields a binding dual (pmMax>0). NEW GOLDEN
 *                                            (V2-1 2026-06-10, baseline-moving): capacity is the REAL
 *                                            M.lines pool (hrs × OEE, horizon-scaled) — at TPAC volumes
 *                                            the lines are HONESTLY slack, so the priced scarcity is the
 *                                            DEMAND ceilings ("Max prod:" duals, ₹930/u = top unit margin).
 *                                            The pre-V2-1 binding "Shared Capacity" was an artefact of the
 *                                            circular demandHours×0.82 capacity. Cross-check: profit-mix
 *                                            line utilization must AGREE with linecap's slack/bind verdict.
 *                                            NOT lcMax>0 — requiring it would falsely fail (SF-7 lesson).
 *   · I-6  MEIO pooling dividend           — pooled SS value < Σ decentralised, capital_freed>0 (√N law)
 *
 * Like HARNESS-1, server/browser-dependent: WARN + exit 0 when the server is down or
 * the Chromium binary is missing (CI stays green server-less). Exit 1 only on a
 * VIOLATED identity once the chain has actually run.
 *
 * Usage:  node app_v2/tools/golden_path.js [--base http://localhost:5000] [--runs 300] [--headed]
 */
'use strict';
const args = process.argv.slice(2);
const argv = (flag, def) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : def; };
const BASE = argv('--base', 'http://localhost:5000');
const N_RUNS = parseInt(argv('--runs', '300'), 10) || 300;     // montecarlo n_runs (CI speed; identities don't need 500)
const HEADED = args.includes('--headed');
const HARD_TIMEOUT_MS = 240000;                                 // whole-run guard so a hung solve can't hang CI

const results = [];   // {step, status:'PASS'|'FAIL'|'WARN', detail}
const add = (step, status, detail) => results.push({ step, status, detail });
const inr = n => '₹' + (Math.abs(+n) >= 1e5 ? (n / 1e5).toFixed(2) + 'L' : Math.round(+n).toLocaleString('en-IN'));

function report(exitImmediately) {
  const w = Math.max(...results.map(r => r.step.length));
  for (const r of results) {
    const tag = { PASS: '✓ PASS', FAIL: '✗ FAIL', WARN: '⚠ WARN' }[r.status];
    console.log(`  ${tag}  ${r.step.padEnd(w)}  ${r.detail}`);
  }
  const fails = results.filter(r => r.status === 'FAIL').length;
  const warns = results.filter(r => r.status === 'WARN').length;
  const pass = results.filter(r => r.status === 'PASS').length;
  console.log('\n' + '─'.repeat(78));
  console.log(`${pass} pass · ${fails} fail · ${warns} warn`);
  // Don't claim the identities "hold" when none actually ran (server/browser absent) —
  // a green-ish summary over 0 assertions is the exact false-green this gate exists to prevent.
  const identityChecks = results.filter(r => /·/.test(r.step)).length;   // the I-x / #5 / B-13 rows
  if (fails) console.log('✗ a cross-solver identity is VIOLATED — the engines disagree (see ✗ rows)');
  else if (identityChecks === 0) console.log('— no identities asserted (server down or Chromium missing) — nothing verified this run');
  else console.log('✓ cross-solver identities hold on the golden path' + (warns ? ' (some checks skipped)' : ''));
  if (exitImmediately !== false) process.exit(fails ? 1 : 0);
}

// ── the in-page driver: runs in the REAL app's global scope ──────────────────
// Everything here is the app's own code (window.* = the Object.assign export in
// store.jsx + the global function declarations in console/plan/sourcing/finance).
// No logic is re-implemented; we only ORCHESTRATE the real builders + solves and
// read back the real results.
async function drive(nRuns) {
  const out = { err: null, loopLog: null, pmRan: false, mnRan: false };
  try {
    const S = window.appStore;
    const planning = S.get().planning;
    const config = S.get().config || {};

    // 1 — the real end-to-end loop: forecast → procurement → aggregate → production
    //     → linecap → montecarlo, each step's REAL builder, each result cached so the
    //     next reads the previous (the forecast step also COMMITS demand via setItemDemand).
    out.loopLog = await window.runFullLoop({ opts: { montecarlo: { nRuns } } });

    // 2 — the two identities the loop doesn't cover, via their REAL builders.
    const sl = Number(config.serviceLevel) || 0.95;
    try {
      const pm = await window.apiPost('/api/solve/profitmix', window.profitmixPayload());
      window.cacheSolve('profitmix', pm); out.pmRan = true;
    } catch (e) { out.pmErr = String(e && e.message || e); }
    try {
      const mn = await window.apiPost('/api/solve/meio-network', window.meioNetworkPayload(sl, 0, 0, { pairwise: true }));
      window.cacheSolve('meionet', mn); out.mnRan = true;
    } catch (e) { out.mnErr = String(e && e.message || e); }

    // 3 — read back the REAL cached results + freshness, exactly like ConsistencyPanel does.
    const g = window.getSolveResult, solves = S.get().solves || {};
    const ag = g('aggregate'), pr = g('production'), lc = g('linecap'),
          mc = g('montecarlo'), pm = g('profitmix'), mn = g('meionet');
    const fin = (window.M.products || []).filter(p => p.cat === 'Finished');
    const demand = S.get().demand || {};

    // I-5 — committed demand vs production build (mirror of ConsistencyPanel exactly).
    const demTot = fin.reduce((a, p) => { const s = demand[p.sku]; return a + (s && s.length ? s.reduce((x, y) => x + (+y || 0), 0) : 0); }, 0);
    const prodUnits = pr && pr.gantt ? pr.gantt.reduce((a, e) => a + (+e.quantity || 0), 0) : null;
    out.demTot = demTot; out.prodUnits = prodUnits;
    out.ratio = (demTot > 0 && prodUnits != null) ? prodUnits / demTot : null;

    // I-3 — carry rate ⇄ blended hurdle (pure arithmetic; the real finance helpers).
    out.hurdle = (typeof window.finBlendedHurdle === 'function') ? window.finBlendedHurdle(config).wacc : null;
    out.carry  = (typeof window.carryRate === 'function') ? window.carryRate(config) * 100 : null;
    out.spread = (typeof window.carryRateParts === 'function') ? window.carryRateParts(config).spread : null;

    // #5 — MC replays the committed schedule (timing + the policy it actually simulated).
    out.prodAt = solves.production && solves.production.ranAt || null;
    out.mcAt   = solves.montecarlo && solves.montecarlo.ranAt || null;
    out.mcPolicy = mc ? (mc.policy_simulated || null) : null;

    // I-2 — bottleneck priced: linecap dual (finite, may be 0=slack) + profit-mix binding dual.
    out.lcMax = lc && lc.lines ? Math.max(0, ...lc.lines.map(x => +x.shadow_price || 0)) : null;
    out.lcLinesN = lc && lc.lines ? lc.lines.length : null;
    out.lcBindingN = lc && lc.lines ? lc.lines.filter(x => x.binding).length : null;
    const pmB = pm && pm.shadow_prices ? pm.shadow_prices.filter(x => x.binding) : null;
    out.pmMax = pmB ? Math.max(0, ...pmB.map(x => +x.shadow_price || 0)) : null;
    out.pmBindingN = pmB ? pmB.length : null;
    out.pmBindingNames = pmB ? pmB.map(x => x.constraint).slice(0, 4) : null;
    // V2-1 — line-pool internal consistency: which "Line hrs:" duals bind, and each
    // line's solved utilization (a binding line dual MUST coincide with ~100% util).
    out.pmLineBind = pm && pm.shadow_prices
      ? pm.shadow_prices.filter(x => x.binding && /^Line hrs:/i.test(x.constraint))
          .map(x => String(x.constraint).replace(/^Line hrs:\s*/i, '').trim())
      : null;
    out.pmUtil = pm && pm.line_allocation
      ? pm.line_allocation.map(l => ({ name: l.line_name, u: +l.utilization_pct || 0 }))
      : null;

    // I-6 — pooling dividend.
    if (mn) { out.pooled = mn.total_ss_value_pooled; out.decentralised = mn.total_ss_value_decentralised; out.freed = mn.total_capital_freed; }

    // B-13 — the aggregate plan must source COMMITTED demand (getItemDemand), not the
    // seed master. Re-derive the REAL aggregate payload and compare each SKU's forecast
    // to getItemDemand over the SAME period count. A regression to the seed branch shows
    // up as a mismatch (seed reslice ≠ committed series).
    const ap = window._loopAggregatePayload(planning);
    const periods = ap.params.periods;
    const mism = [];
    (ap.products || []).forEach(p => {
      const committed = window.getItemDemand(p.name, periods).reduce((a, b) => a + (+b || 0), 0);
      const inPlan = (p.forecast || []).reduce((a, b) => a + (+b || 0), 0);
      if (Math.abs(committed - inPlan) > 1) mism.push({ sku: p.name, committed: Math.round(committed), inPlan: Math.round(inPlan) });
    });
    out.b13 = { periods, mismatches: mism, n: (ap.products || []).length };
  } catch (e) {
    out.err = String(e && e.stack || e);
  }
  return out;
}

(async () => {
  console.log('HARNESS-1b · golden-path cross-solver identity harness  —  ' + new Date().toISOString().slice(0, 19).replace('T', ' '));
  console.log('replays the REAL app loop in headless Chromium, then asserts the OBS-2 identities end-to-end\n');

  // server up? (WARN + exit 0 when down, like HARNESS-1)
  try {
    const r = await fetch(BASE + '/api/meta/solvers', { method: 'GET' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
  } catch (e) {
    add('server reachable', 'WARN', `not up at ${BASE} (${e.code || e.message}) — start it (nohup python3 app.py …) to run the golden path`);
    return report();
  }
  add('server reachable', 'PASS', BASE);

  let playwright;
  try { playwright = require('playwright'); }
  catch (e) { add('playwright present', 'WARN', 'playwright not installed — npm i -D playwright'); return report(); }

  let browser;
  try { browser = await playwright.chromium.launch({ headless: !HEADED }); }
  catch (e) {
    add('chromium launch', 'WARN', 'no Chromium binary — run: npx playwright install chromium  (' + (e.message || e).split('\n')[0] + ')');
    return report();
  }

  const pageErrors = [];
  let drv;
  try {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    page.on('pageerror', e => pageErrors.push(String(e.message || e)));
    page.on('console', m => { if (m.type() === 'error') pageErrors.push('[console] ' + m.text()); });

    await page.goto(BASE + '/', { waitUntil: 'load', timeout: 30000 });
    // wait for babel-standalone to transpile + run all 18 jsx (the app boots async).
    await page.waitForFunction(() =>
      typeof window.runFullLoop === 'function' &&
      typeof window.profitmixPayload === 'function' &&
      typeof window.meioNetworkPayload === 'function' &&
      typeof window._loopAggregatePayload === 'function' &&
      window.M && Array.isArray(window.M.products) &&
      window.appStore && window.appStore.get().config,
      { timeout: 30000, polling: 200 });
    add('app booted (18 jsx transpiled)', 'PASS', 'window.runFullLoop + builders + M + appStore ready');

    // the whole golden-path run, guarded so a hung solve can't hang forever.
    drv = await Promise.race([
      page.evaluate(drive, N_RUNS),
      new Promise((_, rej) => setTimeout(() => rej(new Error('golden-path run exceeded ' + (HARD_TIMEOUT_MS / 1000) + 's')), HARD_TIMEOUT_MS)),
    ]);
  } catch (e) {
    add('golden-path run', 'WARN', (e.message || String(e)) + (pageErrors.length ? '  · page: ' + pageErrors.slice(-2).join(' | ') : ''));
    await browser.close().catch(() => {});
    return report();
  }
  await browser.close().catch(() => {});

  if (drv.err) { add('golden-path run', 'WARN', 'in-page error: ' + drv.err.split('\n')[0] + (pageErrors.length ? '  · ' + pageErrors.slice(-1)[0] : '')); return report(); }

  // ── loop chain ran? (each of the 6 steps) ──────────────────────────────────
  const log = drv.loopLog || [];
  const badSteps = log.filter(s => !s.ok);
  if (!log.length) add('golden-path chain', 'WARN', 'runFullLoop returned no log');
  else if (badSteps.length) add('golden-path chain', 'FAIL', badSteps.map(s => `${s.key}: ${s.error || 'failed'}`).join(' · '));
  else add('golden-path chain', 'PASS', `${log.length} steps solved (${log.map(s => s.key).join('→')})`);
  if (!drv.pmRan) add('profit-mix solve (I-2 input)', 'WARN', 'did not run' + (drv.pmErr ? ': ' + drv.pmErr : ''));
  if (!drv.mnRan) add('MEIO-network solve (I-6 input)', 'WARN', 'did not run' + (drv.mnErr ? ': ' + drv.mnErr : ''));

  // ── I-5 — demand ⇄ production reconcile ─────────────────────────────────────
  if (drv.ratio == null) add('I-5 · demand ⇄ production reconcile', 'WARN', 'demand or production missing — chain incomplete');
  else if (drv.ratio >= 0.7 && drv.ratio <= 1.4)
    add('I-5 · demand ⇄ production reconcile', 'PASS', `committed ${Math.round(drv.demTot).toLocaleString('en-IN')}u vs build ${Math.round(drv.prodUnits).toLocaleString('en-IN')}u (ratio ${drv.ratio.toFixed(2)}, within inventory swing)`);
  else
    add('I-5 · demand ⇄ production reconcile', 'FAIL', `ratio ${drv.ratio.toFixed(2)} outside [0.70,1.40] — committed ${Math.round(drv.demTot)}u vs build ${Math.round(drv.prodUnits)}u (check labor-weighted vs physical basis, P-C)`);

  // ── B-13 — aggregate sources committed demand, not the seed master ──────────
  if (!drv.b13) add('B-13 · aggregate uses COMMITTED demand', 'WARN', 'aggregate payload not derivable');
  else if (drv.b13.mismatches.length === 0)
    add('B-13 · aggregate uses COMMITTED demand', 'PASS', `all ${drv.b13.n} SKUs: aggregate forecast == getItemDemand over ${drv.b13.periods} periods (not the seed reslice)`);
  else
    add('B-13 · aggregate uses COMMITTED demand', 'FAIL', `${drv.b13.mismatches.length} SKU(s) plan to the SEED, not committed: ` + drv.b13.mismatches.map(m => `${m.sku} plan=${m.inPlan} vs committed=${m.committed}`).join(', '));

  // ── I-3 — carry rate anchored to the blended hurdle (FIN-8) ─────────────────
  if (drv.carry == null || drv.hurdle == null) add('I-3 · carry rate anchored to hurdle', 'WARN', 'finance helpers unavailable');
  else {
    const expect = drv.hurdle + (drv.spread || 0);
    const anchored = Math.abs(drv.carry - expect) < 0.6 && drv.carry > drv.hurdle;
    add('I-3 · carry rate anchored to hurdle', anchored ? 'PASS' : 'FAIL',
      `carry ${drv.carry.toFixed(2)}% = hurdle ${drv.hurdle.toFixed(2)}% + spread ${(drv.spread || 0).toFixed(1)}%` + (anchored ? ' (= by construction)' : `  ✗ expected ≈${expect.toFixed(2)}%`));
  }

  // ── #5 — Monte-Carlo replays the COMMITTED plan ─────────────────────────────
  if (!drv.prodAt || !drv.mcAt) add('#5 · MC ran on the committed plan', 'WARN', 'production or montecarlo missing');
  else {
    const ordered = drv.mcAt >= drv.prodAt, plan = drv.mcPolicy === 'plan';
    add('#5 · MC ran on the committed plan', (ordered && plan) ? 'PASS' : 'FAIL',
      `MC ${ordered ? 'after' : 'BEFORE ✗'} the schedule · policy_simulated='${drv.mcPolicy}'` + (plan ? ' (replayed the committed gantt)' : " ✗ expected 'plan' — committed-plan replay did NOT engage (B-7 class)"));
  }

  // ── I-2 — bottleneck is priced (V2-1 golden: real line pool; demand may be the
  // honest scarcity). FAILs if nothing is priced, or if a line dual disagrees with
  // its own solved utilization (binding ⇔ ~100% — the internal-consistency lie test).
  if (drv.pmMax == null) add('I-2 · bottleneck is priced (dual)', 'WARN', 'profit-mix dual unavailable');
  else if (drv.pmMax > 0) {
    const lb = new Set(drv.pmLineBind || []);
    const utilBad = (drv.pmUtil || []).filter(l => lb.has(l.name) ? l.u < 99.5 : l.u > 100.5);
    const utilMax = drv.pmUtil && drv.pmUtil.length ? Math.max(...drv.pmUtil.map(l => l.u)) : null;
    const lcNote = drv.lcMax == null ? 'linecap not run'
      : drv.lcMax > 0 ? `linecap dual ${inr(drv.lcMax)}/u (${drv.lcBindingN}/${drv.lcLinesN} lines bind) — both price capacity`
      : `linecap slack (0/${drv.lcLinesN} lines bind, π=0 — honestly not the constraint at this volume)`;
    const utilNote = utilMax == null ? '' : ` · pm line util max ${utilMax.toFixed(0)}% ${lb.size ? `(${lb.size} line dual binds)` : '(lines slack — demand is the priced scarcity)'}`;
    if (utilBad.length)
      add('I-2 · bottleneck is priced (dual)', 'FAIL', `line dual ⇄ utilization disagree: ${utilBad.map(l => `${l.name} util ${l.u}% vs dual ${lb.has(l.name) ? 'BINDING' : 'slack'}`).join('; ')}`);
    else
      add('I-2 · bottleneck is priced (dual)', 'PASS', `profit-mix dual ${inr(drv.pmMax)}/u binds [${(drv.pmBindingNames || []).join(', ')}]${utilNote} · ${lcNote}`);
  } else
    add('I-2 · bottleneck is priced (dual)', 'FAIL', `profit-mix reports NO binding dual (pmMax=0) — the glass-box bottleneck claim is empty; with the V2-1 real line pool, EITHER a "Line hrs:" dual OR a "Max prod:" demand dual must price the scarcity`);

  // ── I-6 — MEIO pooling dividend (√N law) ────────────────────────────────────
  if (drv.pooled == null) add('I-6 · MEIO pooling dividend (√N)', 'WARN', 'meio-network not run');
  else if (drv.pooled < drv.decentralised && drv.freed > 0)
    add('I-6 · MEIO pooling dividend (√N)', 'PASS', `pooled ${inr(drv.pooled)} < decentralised ${inr(drv.decentralised)} · capital freed ${inr(drv.freed)}`);
  else
    add('I-6 · MEIO pooling dividend (√N)', 'FAIL', `pooled ${inr(drv.pooled)} NOT < decentralised ${inr(drv.decentralised)} (freed ${inr(drv.freed)}) — pooling shows no dividend`);

  if (pageErrors.length) add('page console', 'WARN', `${pageErrors.length} page error(s); last: ` + pageErrors.slice(-1)[0].slice(0, 120));
  report();
})().catch(e => { console.error('harness crashed:', e); process.exit(2); });
