#!/usr/bin/env node
/*
 * HARNESS-1 · Model-integrity harness  (Observability spec, Part 6 · Tier-2)
 * -------------------------------------------------------------------------
 * ONE script that replaces the 18 bespoke per-tab smokes with a single truth.
 * It asserts the machine is structurally sound and honest:
 *   1. every app_v2/*.jsx parses (the per-tab parse smoke, ×18 in one pass)
 *   2. the OBS-3 provenance lint is clean (no seed-as-real chip)
 *   3. all 16 curated solver endpoints are actually registered on the live
 *      server (introspected from /api/meta/solvers — catches a solver that
 *      drifts out of the route map)
 *   4. the server serves the app shell (served-bytes > 0)
 *
 * NOT in scope here (honest): the live 6-way cross-solver IDENTITY assertions
 * (Forecast demand = Aggregate input = … ; profit-mix dual = linecap dual …)
 * need WIRED data, so they are delivered by OBS-2 in the running app
 * (Reference ▸ Model Map ▸ Cross-solver consistency). A pure-CI golden-path
 * that replays them needs payload fixtures captured from the app — that is the
 * remaining Tier-2 follow-up (HARNESS-1b).
 *
 * Exit 1 on any HARD failure (parse / lint). Server checks WARN (not fail) when
 * the server is down, so this still runs in a server-less CI step.
 * Usage:  node app_v2/tools/model_check.js [--base http://localhost:5000]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const parser = require('@babel/parser');

const DIR = path.resolve(__dirname, '..');
const TOOLS = __dirname;
const args = process.argv.slice(2);
const baseIx = args.indexOf('--base');
const BASE = baseIx >= 0 ? args[baseIx + 1] : 'http://localhost:5000';

// The 16 curated solver endpoints (must stay in lock-step with M.solvers / _OBS_API).
const CURATED_ENDPOINTS = [
  '/api/forecast', '/api/solve/aggregate', '/api/calc/disaggregate',
  '/api/solve/profitmix', '/api/solve/procurement', '/api/solve/production', '/api/solve/sequence',
  '/api/solve/lotsizing', '/api/solve/transport', '/api/solve/meio', '/api/solve/meio-network',
  '/api/solve/montecarlo', '/api/solve/cvar', '/api/solve/capital', '/api/solve/capital-capacity',
];
// note: Reconcile is exposed as the S&OP pipeline at /api/solve/sop (run_sop_pipeline),
// NOT /api/solve/reconcile — HARNESS-1 caught that drift on first run (2026-06-05).
CURATED_ENDPOINTS.push('/api/solve/sop');

const results = [];   // {step, status:'PASS'|'FAIL'|'WARN', detail}
const add = (step, status, detail) => results.push({ step, status, detail });

// ── 1. parse every jsx ──────────────────────────────────────────────────────
function parseAll() {
  const files = fs.readdirSync(DIR).filter(f => f.endsWith('.jsx'));
  const bad = [];
  for (const f of files) {
    const src = fs.readFileSync(path.join(DIR, f), 'utf8');
    let ok = false;
    for (const sourceType of ['script', 'module']) {
      try { parser.parse(src, { sourceType, plugins: ['jsx'] }); ok = true; break; } catch (_) {}
    }
    if (!ok) bad.push(f);
  }
  if (bad.length) add(`parse ${files.length} jsx`, 'FAIL', 'broken: ' + bad.join(', '));
  else add(`parse ${files.length} jsx`, 'PASS', 'all parse clean');
}

// ── 2. provenance lint (OBS-3) ──────────────────────────────────────────────
function provLint() {
  try {
    cp.execFileSync('node', [path.join(TOOLS, 'provenance_lint.js')], { stdio: 'pipe' });
    add('provenance lint (OBS-3)', 'PASS', 'no seed-as-real chip');
  } catch (e) {
    const out = (e.stdout ? e.stdout.toString() : '') + (e.stderr ? e.stderr.toString() : '');
    const m = out.match(/(\d+) UNBACKED/);
    add('provenance lint (OBS-3)', 'FAIL', (m ? m[0] : 'lint failed') + ' — run: node app_v2/tools/provenance_lint.js');
  }
}

// ── 2b. shared-global shadow check ──────────────────────────────────────────
// All 18 jsx load as classic scripts into ONE global scope (no bundler/modules).
// So a top-level `function NAME`/`const NAME` declared in TWO files is NOT two
// locals — the later-loaded file silently shadows the earlier for EVERY consumer.
// Invisible to the parser and to served-bytes, and it caused a real bug: console.jsx's
// no-arg productionPayload/montecarloPayload shadowed store.jsx's governed versions
// (2026-06-06), neutering the Production tab + Risk committed-plan replay. Hard fail.
function dupGlobals() {
  const files = fs.readdirSync(DIR).filter(f => f.endsWith('.jsx'));
  const seen = {};   // name -> [files]
  const DECL = /^(?:function|const|let|var)\s+([A-Za-z0-9_$]+)/;
  for (const f of files) {
    const names = new Set();
    for (const ln of fs.readFileSync(path.join(DIR, f), 'utf8').split('\n')) {
      const m = ln.match(DECL);
      if (m) names.add(m[1]);
    }
    for (const n of names) (seen[n] = seen[n] || []).push(f);
  }
  const dups = Object.entries(seen).filter(([, fls]) => fls.length > 1);
  if (dups.length) add('no shared-global shadows', 'FAIL',
    dups.map(([n, fls]) => `${n} in ${fls.join(' & ')}`).join('; ') + ' — later file silently shadows earlier');
  else add('no shared-global shadows', 'PASS', `${Object.keys(seen).length} top-level names unique across ${files.length} files`);
}

// ── 2c. object-rest _excluded collision (B-16) ──────────────────────────────
// Babel-standalone hoists a top-level `const _excluded` helper per FILE for any
// object-REST destructuring (`const {a, ...rest} = o`  /  `({a, ...rest}) => …`).
// All 18 jsx share ONE global scope, so a SECOND file emitting `_excluded` throws
// "Identifier '_excluded' already declared" when babel appends it — which ABORTS
// that whole file and BLANKS the app. This is the exact class of bug the source-
// level shadow check above CANNOT see (the helper is injected at transpile time,
// not written in the source). B-16: the B-5 fix added a 2nd emitter in store.jsx
// and it survived every parse/curl/served-bytes smoke because none BOOT the app —
// only HARNESS-1b's real-browser run caught it. Convention: lib.jsx (Box/Btn) is
// the SOLE sanctioned emitter. Enforce ≤1 file. (AST-based so object-SPREAD in a
// literal — `{...x}`, a different helper — is correctly NOT flagged.)
function objRestCollision() {
  const files = fs.readdirSync(DIR).filter(f => f.endsWith('.jsx'));
  const hasObjRest = (root) => {
    let found = false;
    const visit = (n) => {
      if (found || !n || typeof n !== 'object') return;
      if (n.type === 'ObjectPattern' && Array.isArray(n.properties) && n.properties.some(p => p && p.type === 'RestElement')) { found = true; return; }
      for (const k in n) {
        if (k === 'loc' || k === 'start' || k === 'end' || k === 'range' || k === 'leadingComments' || k === 'trailingComments' || k === 'innerComments') continue;
        const v = n[k];
        if (Array.isArray(v)) { for (const e of v) visit(e); } else if (v && typeof v === 'object' && typeof v.type === 'string') visit(v);
      }
    };
    visit(root);
    return found;
  };
  const emitters = [];
  for (const f of files) {
    const src = fs.readFileSync(path.join(DIR, f), 'utf8');
    let ast = null;
    for (const sourceType of ['script', 'module']) {
      try { ast = parser.parse(src, { sourceType, plugins: ['jsx'] }); break; } catch (_) {}
    }
    if (ast && hasObjRest(ast)) emitters.push(f);
  }
  if (emitters.length > 1) add('one object-rest _excluded emitter', 'FAIL',
    `${emitters.length} files emit Babel _excluded (${emitters.join(', ')}) — a 2nd collides in the shared global scope & BLANKS the app (B-16); keep object-rest destructuring in lib.jsx only (use Object.assign+delete elsewhere)`);
  else add('one object-rest _excluded emitter', 'PASS',
    emitters.length ? `only ${emitters[0]} emits _excluded (sanctioned)` : 'no object-rest destructuring anywhere');
}

// ── 2d. panel == harness identity parity (G-RF1) ────────────────────────────
// The Reference ▸ ConsistencyPanel DISPLAYS the cross-solver identities; HARNESS-1b
// (golden_path.js) ASSERTS them with an exit code. If the two drift — an identity the
// harness checks but the panel never surfaces (or vice-versa) — the operator's "do the
// engines agree?" view silently under-reports. Enforce: the set of identity IDs the
// panel renders == the set the harness asserts. Both are extracted from the REAL source
// (the panel's checks[].id and the harness's `add('<ID> · …')` rows — the same ` · `
// rule report() uses to count identityChecks), so neither can be a stale declaration.
function identityParity() {
  const MID = '·';
  let gp, ref;
  try { gp = fs.readFileSync(path.join(TOOLS, 'golden_path.js'), 'utf8'); }
  catch (e) { add('panel == harness identities (G-RF1)', 'WARN', 'golden_path.js unreadable'); return; }
  try { ref = fs.readFileSync(path.join(DIR, 'reference.jsx'), 'utf8'); }
  catch (e) { add('panel == harness identities (G-RF1)', 'WARN', 'reference.jsx unreadable'); return; }

  // harness: every add('<ID> · …') first-arg — the rows report() counts as identities.
  const harness = new Set();
  const reH = new RegExp("add\\('([^']+?) " + MID, 'g');
  let m; while ((m = reH.exec(gp))) harness.add(m[1]);

  // panel: the checks[].id values inside the ConsistencyPanel function body only.
  const start = ref.indexOf('function ConsistencyPanel');
  const after = start >= 0 ? ref.indexOf('\nfunction ', start + 1) : -1;
  const body = start >= 0 ? ref.slice(start, after >= 0 ? after : ref.length) : '';
  const panel = new Set();
  const reP = /\bid:'([^']+)'/g;
  while ((m = reP.exec(body))) panel.add(m[1]);

  const onlyH = [...harness].filter(x => !panel.has(x)).sort();
  const onlyP = [...panel].filter(x => !harness.has(x)).sort();
  if (!harness.size) add('panel == harness identities (G-RF1)', 'WARN', 'no identity rows found in golden_path.js');
  else if (onlyH.length || onlyP.length) add('panel == harness identities (G-RF1)', 'FAIL',
    (onlyH.length ? `harness asserts but panel omits: ${onlyH.join(', ')}` : '') +
    (onlyH.length && onlyP.length ? ' · ' : '') +
    (onlyP.length ? `panel shows but harness never asserts: ${onlyP.join(', ')}` : '') +
    ' — keep ConsistencyPanel checks[] in lock-step with golden_path identities');
  else add('panel == harness identities (G-RF1)', 'PASS',
    `${harness.size} identities surfaced in both: ${[...harness].sort().join(', ')}`);
}

// ── 3 & 4. server-dependent checks ──────────────────────────────────────────
async function httpGet(url) {
  // node 18+ has global fetch
  const r = await fetch(url, { method: 'GET' });
  const text = await r.text();
  return { status: r.status, text };
}
async function serverChecks() {
  let meta;
  try { meta = await httpGet(BASE + '/api/meta/solvers'); }
  catch (e) { add('server', 'WARN', `not reachable at ${BASE} (${e.code || e.message}) — start it to run endpoint + shell checks`); return; }

  // served bytes
  try {
    const shell = await httpGet(BASE + '/');
    if (shell.status === 200 && shell.text.length > 0) add('serves app shell', 'PASS', `${shell.text.length} bytes @ ${BASE}/`);
    else add('serves app shell', 'FAIL', `HTTP ${shell.status}, ${shell.text.length} bytes`);
  } catch (e) { add('serves app shell', 'WARN', e.message); }

  // endpoint registration
  let endpoints = [];
  try { const j = JSON.parse(meta.text); endpoints = (j.endpoints || []).map(e => e.path); }
  catch (e) { add('16 solver endpoints registered', 'WARN', 'could not parse /api/meta/solvers'); return; }
  const missing = CURATED_ENDPOINTS.filter(p => !endpoints.includes(p));
  if (missing.length) add('16 solver endpoints registered', 'FAIL', 'missing from route map: ' + missing.join(', '));
  else add('16 solver endpoints registered', 'PASS', `all 16 present (of ${endpoints.length} routes)`);
}

(async () => {
  console.log('HARNESS-1 · model-integrity harness  —  ' + new Date().toISOString().slice(0, 19).replace('T', ' '));
  console.log('one truth replacing the 18 bespoke per-tab smokes\n');
  parseAll();
  provLint();
  dupGlobals();
  objRestCollision();
  identityParity();
  await serverChecks();

  const w = Math.max(...results.map(r => r.step.length));
  for (const r of results) {
    const tag = { PASS: '✓ PASS', FAIL: '✗ FAIL', WARN: '⚠ WARN' }[r.status];
    console.log(`  ${tag}  ${r.step.padEnd(w)}  ${r.detail}`);
  }
  const fails = results.filter(r => r.status === 'FAIL').length;
  const warns = results.filter(r => r.status === 'WARN').length;
  console.log('\n' + '─'.repeat(72));
  console.log(`${results.filter(r => r.status === 'PASS').length} pass · ${fails} fail · ${warns} warn`);
  if (!fails) console.log('✓ model integrity holds' + (warns ? ' (server checks skipped — start the server to include them)' : ''));
  process.exit(fails ? 1 : 0);
})();
