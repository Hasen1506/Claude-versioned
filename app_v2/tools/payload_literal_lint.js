#!/usr/bin/env node
/*
 * V2-12 · payload-literal lint — every BARE NUMERIC LITERAL sent to a solver must
 * be REGISTERED (PAYLOAD_LITERALS.md) or governed out of existence.
 * ---------------------------------------------------------------------------
 * THE CLASS OF BUG: a number typed straight into a payload builder silently
 * becomes solver truth with no Setup field, no provenance chip, no registry row
 * — the V2 program kept finding these one at a time (ordering_cost:120,
 * setup_cost:50, hrs-per-shift 8, hire/fire/wage seeds, rehire_notice_hrs:80…).
 * This lint freezes the surviving set in a visible ledger and FAILS the gate on
 * any NEW one, so the next hardcode is a conscious, reviewed decision.
 *
 * MECHANIC (same self-enforcing pattern as units_lint.js / UNITS.md):
 *   · solver payload keys are snake_case — UI props are camelCase — so a
 *     `snake_case_key: <bare number>` in jsx is a payload literal by construction.
 *   · governed values are EXPRESSIONS (`Number(opts.x)||0`, `cfg.y ?? 50`,
 *     `_eff(config.z, 4)`) and don't match a bare-literal regex, so governing a
 *     literal makes its ledger row stale-able and the lint self-cleans via --prune.
 *   · each surviving pair must appear backticked as `key: value` in
 *     PAYLOAD_LITERALS.md — changing the VALUE also fails (re-register on drift).
 *
 * HONEST SCOPE: catches bare numerics on snake_case keys written in app_v2 jsx.
 * It cannot see literals buried inside expressions (`Number(80)`), camelCase
 * staging objects, or python-side defaults — those stay the per-solver contract
 * tables' job (blueprint Part 6).
 *
 * Usage: node payload_literal_lint.js [--list]
 */
'use strict';
const fs = require('fs');
const path = require('path');
const DIR = path.resolve(__dirname, '..');
const LEDGER = path.join(DIR, 'PAYLOAD_LITERALS.md');
const LIST = process.argv.includes('--list');

const stripComments = (src) => src
  .replace(/\/\*[\s\S]*?\*\//g, m => m.replace(/[^\n]/g, ' '))
  .replace(/(^|[^:])\/\/[^\n]*/g, (m, p) => p + m.slice(p.length).replace(/[^\n]/g, ' '));

// bare/quoted snake_case key : bare numeric literal (expressions don't match)
const KEY = `[a-z][a-z0-9]*(?:_[a-z0-9]+)+`;
const NUM = `-?\\d+(?:\\.\\d+)?`;
const BARE_RE = new RegExp(`(^|[^.\\w'"\`])(${KEY})\\s*:\\s*(${NUM})(?=\\s*[,}\\]])`, 'g');
const QUOTED_RE = new RegExp(`['"](${KEY})['"]\\s*:\\s*(${NUM})(?=\\s*[,}\\]])`, 'g');

const found = new Map();   // "key: value" → first file:line
for (const f of fs.readdirSync(DIR).filter(x => x.endsWith('.jsx'))) {
  const src = stripComments(fs.readFileSync(path.join(DIR, f), 'utf8'));
  for (const [re, ki, vi] of [[BARE_RE, 2, 3], [QUOTED_RE, 1, 2]]) {
    re.lastIndex = 0;
    let m;
    while ((m = re.exec(src))) {
      const pair = `${m[ki]}: ${m[vi]}`;
      if (!found.has(pair)) found.set(pair, `${f}:${src.slice(0, m.index).split('\n').length}`);
    }
  }
}

if (LIST) {
  for (const [pair, at] of [...found].sort()) console.log(`${pair.padEnd(36)} ${at}`);
  console.log(`\n${found.size} payload literals`);
  process.exit(0);
}

let ledger = '';
try { ledger = fs.readFileSync(LEDGER, 'utf8'); }
catch (e) { console.error(`payload_literal_lint FAIL — ledger missing: ${LEDGER}`); process.exit(1); }
const registered = new Set([...ledger.matchAll(/`([a-z][a-z0-9_]+:\s*-?\d+(?:\.\d+)?)`/g)]
  .map(m => m[1].replace(/\s+/g, ' ')));

const missing = [...found].filter(([pair]) => !registered.has(pair));
const stale = [...registered].filter(pair => !found.has(pair));
if (missing.length) {
  console.error(`payload_literal_lint FAIL — ${missing.length} UNREGISTERED payload literal(s):`);
  for (const [pair, at] of missing) console.error(`  ${pair}  (${at})`);
  console.error(`govern it (expression beats literal) or register it in ${path.basename(LEDGER)} with a reason.`);
  process.exit(1);
}
if (stale.length) {
  console.log(`note: ${stale.length} ledger row(s) no longer in code (governed away?) — prune when convenient: ${stale.join(' · ')}`);
}
console.log(`payload_literal_lint PASS — ${found.size} payload literals, all registered in PAYLOAD_LITERALS.md`);
