#!/usr/bin/env node
/*
 * V2-5 · Units lint  (PRODUCT_BLUEPRINT_V3 Q11)
 * ---------------------------------------------
 * The unit suffixes in this codebase LIE: `yield_pct` is a FRACTION (0.95),
 * `max_ot_pct` is a FRACTION (0.25), while `hold_pct`/`tax_rate` are true
 * PERCENTS (python divides by 100) and `carry_rate` is a fraction again.
 * Scattered conversion comments rot; the institutional fix is ONE ledger —
 * app_v2/UNITS.md — and this lint, which makes the ledger self-enforcing:
 *
 *   every unit-suffixed key that app_v2/*.jsx SENDS across the JS→Python
 *   boundary (an object-literal key, i.e. `foo_pct:`) MUST have a backticked
 *   `foo_pct` row in UNITS.md, or the lint FAILS.
 *
 * Scope (stated honestly): payload keys written in jsx. Member-access READS
 * (`r.equity_weight_pct` — result fields) and python-internal fields don't
 * cross the app's send boundary and are not required, though UNITS.md may
 * document them anyway. A new unit-suffixed payload key without a ledger row
 * is exactly the mistake class this exists to catch (B-14/B-15 were field-
 * CONTRACT drift; this is field-UNIT drift).
 *
 * Exit 1 on any unledgered key. Usage: node app_v2/tools/units_lint.js [--list]
 */
'use strict';
const fs = require('fs');
const path = require('path');

const DIR = path.resolve(__dirname, '..');
const LEDGER = path.join(DIR, 'UNITS.md');

const SUFFIX = '(?:min|mins|hrs|hours|pct|percent|days|weeks|months|rate|kg)';
// Object-literal key forms: bare `foo_pct:` (not preceded by . / ?. / word /
// quote — excludes member-access ternaries like `hr.equity_weight_pct : 62`)
// and quoted `'foo_pct':`.
const BARE_RE = new RegExp(`(^|[^.\\w'"\`])([a-z][a-z0-9_]*_${SUFFIX})\\s*:`, 'g');
const QUOTED_RE = new RegExp(`['"]([a-z][a-z0-9_]*_${SUFFIX})['"]\\s*:`, 'g');
// ES6 shorthand keys ALSO cross the boundary: `{ eligible_skus, cycle_time_by_sku_min }`
const SHORT_RE = new RegExp(`[{,]\\s*([a-z][a-z0-9_]*_${SUFFIX})\\s*(?=[,}])`, 'g');

function stripComments(src) {
  // good enough for a lint: kill // and /* */ so commented-out payloads don't count
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/[^\n]*/g, '$1');
}

const found = new Map();   // key -> first "file:line"
for (const f of fs.readdirSync(DIR).filter(x => x.endsWith('.jsx'))) {
  const src = stripComments(fs.readFileSync(path.join(DIR, f), 'utf8'));
  const lines = src.split('\n');
  lines.forEach((ln, i) => {
    for (const re of [BARE_RE, QUOTED_RE, SHORT_RE]) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(ln))) {
        const key = m[m.length - 1];
        if (!found.has(key)) found.set(key, `${f}:${i + 1}`);
      }
    }
  });
}

if (process.argv.includes('--list')) {
  [...found.keys()].sort().forEach(k => console.log(`${k}  (${found.get(k)})`));
  process.exit(0);
}

if (!fs.existsSync(LEDGER)) {
  console.error(`units_lint FAIL: ${LEDGER} missing — the ledger IS the contract`);
  process.exit(1);
}
const ledger = fs.readFileSync(LEDGER, 'utf8');
const missing = [...found.keys()].sort().filter(k => !ledger.includes('`' + k + '`'));

if (missing.length) {
  console.error(`units_lint FAIL — ${missing.length} unit-suffixed payload key(s) cross the JS→Python boundary with NO row in app_v2/UNITS.md:`);
  missing.forEach(k => console.error(`  ${k}  first seen ${found.get(k)}`));
  console.error('Add a ledger row (name · unit · fraction-or-percent · converted-where) for each.');
  process.exit(1);
}
console.log(`units_lint PASS — ${found.size} boundary keys, all ledgered in UNITS.md`);
