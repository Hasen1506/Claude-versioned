#!/usr/bin/env node
/*
 * OBS-3 · Provenance lint  (Observability spec, Part 6 · Tier-1)
 * --------------------------------------------------------------
 * Machine-checks the honesty contract that the per-tab review caught by hand.
 * Pattern P-A (DESIGN_REMEDIATION §3.1): a <Provenance kind="solved|derived">
 * chip MUST trace to a real solve (useSolve family / apiPost / .result) or to a
 * computed expression in the SAME component — never to a bare literal or M.* seed.
 *
 * The lint parses every app_v2/*.jsx, finds each Provenance chip, locates its
 * enclosing component, and asserts a backing exists. Two checks:
 *   UNBACKED  (HIGH)  — solved/derived chip whose component has NO solve and NO
 *                       computation at all  ⇒ almost certainly a seed-as-real lie.
 *   DISTANT   (REVIEW)— solved chip that IS backed somewhere in a large component
 *                       but not within ±window lines of the chip ⇒ eyeball it
 *                       (a seed card sitting inside an otherwise-solved tab).
 *
 * Exit code 1 if any UNBACKED (gates the simple-test loop); 0 otherwise.
 * Usage:  node app_v2/tools/provenance_lint.js [--strict] [file.jsx ...]
 *           --strict : also fail on DISTANT (not just UNBACKED)
 */
'use strict';
const fs = require('fs');
const path = require('path');
const parser = require('@babel/parser');

const DIR = path.resolve(__dirname, '..');
const WINDOW_UP = 24;   // lines above a chip to look for its backing
const WINDOW_DN = 6;    // lines below

// What "backed by a real solve" looks like in source. `.ranAt` is the timestamp
// every cached solve result carries (proc.ranAt, npv.ranAt, seq.ranAt) — a strong
// "this chip's value is a solve output" signal even when the useSolve call is far away.
const SOLVE_RE = /useSolve\b|useSolveResult\b|getSolveResult\b|cacheSolve\b|markSolved\b|apiPost\b|apiGet\b|\.result\b|\branAt\b|solveKey|\/api\//;
// Field names that exist ONLY on a real solver-result object — so a component that
// reads them is consuming a solve passed in as a prop (DemHorizon({prod,res}) etc.),
// which our static scan otherwise can't follow across the component boundary.
const RESULT_FIELD_RE = /accuracy_by_horizon|reconciliation|\bensemble\b|shadow_prices|reduced_costs|crossover|tracking_signal|out_of_control|projected_inventory|blended_ke|fill_rate|\bcvar\b|\.objective\b|poPlan|seasonal_prebuild|\bwinner\b/;
// What "computed from other fields" looks like (legitimises a `derived` chip).
const COMPUTE_RE = /_effNum|Math\.|\.map\(|\.reduce\(|\.filter\(|\.toFixed\(|[-+*/%]=|[A-Za-z0-9_)\]]\s*[-+*/]\s*[A-Za-z0-9_(]/;
// The honest result-gate pattern: a solved chip that is the consequent of a live-result
// test, with a seed/preview/undefined/solve-button fallback ⇒ it only shows when real.
const GATE_RE = /kind=["']seed["']|SeedFence|PreviewTag|:\s*undefined|:\s*<Btn|\.run\(/;

function parse(src) {
  for (const sourceType of ['script', 'module']) {
    try { return parser.parse(src, { sourceType, plugins: ['jsx'], errorRecovery: true }); }
    catch (_) { /* try next */ }
  }
  return null;
}

const FN_TYPES = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression']);

// Recursive own-property walker. Tracks a stack of enclosing functions (with a
// best-effort name) and a name hint passed down through declarators/properties.
function collectChips(ast, src) {
  const chips = [];
  function fnName(node, hint) {
    if (node.id && node.id.name) return node.id.name;
    return hint || '(anonymous)';
  }
  function walk(node, fnStack, hint) {
    if (!node || typeof node.type !== 'string') return;
    let stack = fnStack;
    if (FN_TYPES.has(node.type)) {
      stack = fnStack.concat([{ name: fnName(node, hint), start: node.start, end: node.end,
                                line: node.loc && node.loc.start.line }]);
    }
    if (node.type === 'JSXOpeningElement') {
      const nm = node.name && node.name.type === 'JSXIdentifier' ? node.name.name : null;
      if (nm === 'Provenance') {
        const kindAttr = (node.attributes || []).find(a =>
          a.type === 'JSXAttribute' && a.name && a.name.name === 'kind');
        let kind = null, dynamic = false;
        if (kindAttr && kindAttr.value) {
          if (kindAttr.value.type === 'StringLiteral') kind = kindAttr.value.value;
          else dynamic = true;
        } else if (!kindAttr) {
          kind = 'solved'; // default per the component signature
        }
        const owner = stack[stack.length - 1] || null;
        chips.push({ kind, dynamic, line: node.loc.start.line, owner });
      }
    }
    // descend
    for (const key of Object.keys(node)) {
      if (key === 'loc' || key === 'start' || key === 'end' || key === 'range' || key === 'leadingComments' || key === 'trailingComments') continue;
      const val = node[key];
      // pass a name hint when descending into declarators / assignments / props
      let childHint = undefined;
      if (node.type === 'VariableDeclarator' && node.id && node.id.name) childHint = node.id.name;
      if (node.type === 'AssignmentExpression' && node.left && node.left.name) childHint = node.left.name;
      if (node.type === 'ObjectProperty' && node.key && node.key.name) childHint = node.key.name;
      if (Array.isArray(val)) val.forEach(c => walk(c, stack, childHint));
      else if (val && typeof val.type === 'string') walk(val, stack, childHint);
    }
  }
  walk(ast.program, [], undefined);
  return chips;
}

function lintFile(file, lines) {
  const src = lines.join('\n');
  const ast = parse(src);
  const findings = [];
  if (!ast) { findings.push({ sev: 'PARSE', line: 0, kind: '-', owner: '-', msg: 'could not parse' }); return findings; }
  const chips = collectChips(ast, src);
  for (const ch of chips) {
    if (ch.dynamic) continue;                          // kind={expr} — can't resolve statically
    if (ch.kind !== 'solved' && ch.kind !== 'derived') continue; // seed/input/external are honest-by-name
    // auditable escape hatch: `prov-ok: <reason>` on the chip line or the line above
    const annoNear = lines.slice(Math.max(0, ch.line - 2), ch.line).join('\n');
    if (/prov-ok\b/.test(annoNear)) continue;
    const owner = ch.owner;
    const fnSrc = owner ? src.slice(owner.start, owner.end) : src;
    const hasSolve = SOLVE_RE.test(fnSrc);
    const hasResultField = RESULT_FIELD_RE.test(fnSrc);
    const hasCompute = COMPUTE_RE.test(fnSrc);
    const backed = ch.kind === 'solved' ? (hasSolve || hasResultField) : (hasSolve || hasResultField || hasCompute);
    // proximity window around the chip
    const lo = Math.max(0, ch.line - 1 - WINDOW_UP), hi = Math.min(lines.length, ch.line + WINDOW_DN);
    const near = lines.slice(lo, hi).join('\n');
    const gated = GATE_RE.test(near);                  // honest result-gate XOR seed fallback
    const proximate = gated || (ch.kind === 'solved'
      ? (SOLVE_RE.test(near) || RESULT_FIELD_RE.test(near))
      : (SOLVE_RE.test(near) || RESULT_FIELD_RE.test(near) || COMPUTE_RE.test(near)));
    const ownerName = owner ? owner.name : '(file scope)';
    if (!backed) {
      findings.push({ sev: 'UNBACKED', line: ch.line, kind: ch.kind, owner: ownerName,
        msg: ch.kind === 'solved'
          ? 'solved chip but component has no useSolve/apiPost/.result anywhere'
          : 'derived chip but component has no computation or solve anywhere' });
    } else if (ch.kind === 'solved' && !proximate) {
      findings.push({ sev: 'DISTANT', line: ch.line, kind: ch.kind, owner: ownerName,
        msg: `solved chip is backed in ${ownerName} but no solve within ±${WINDOW_UP} lines — verify it isn't a seed card inside a solved tab` });
    }
  }
  return findings;
}

function main() {
  const args = process.argv.slice(2);
  const strict = args.includes('--strict');
  const explicit = args.filter(a => !a.startsWith('--'));
  const files = (explicit.length ? explicit : fs.readdirSync(DIR).filter(f => f.endsWith('.jsx')))
    .map(f => path.isAbsolute(f) ? f : path.join(DIR, f));

  let unbacked = 0, distant = 0, parseErr = 0, totalChips = 0, filesWith = 0;
  console.log('OBS-3 · provenance lint  —  ' + new Date().toISOString().slice(0, 19).replace('T', ' '));
  console.log('contract: a solved/derived chip must trace to a solve or a computation in its component\n');
  for (const file of files) {
    const lines = fs.readFileSync(file, 'utf8').split('\n');
    const findings = lintFile(file, lines);
    if (!findings.length) continue;
    filesWith++;
    console.log('▌ ' + path.relative(process.cwd(), file));
    for (const f of findings.sort((a, b) => a.line - b.line)) {
      const tag = { UNBACKED: '✗ UNBACKED', DISTANT: '⚠ DISTANT ', PARSE: '✗ PARSE   ' }[f.sev] || f.sev;
      console.log(`  ${tag}  L${String(f.line).padEnd(5)} ${('[' + f.kind + ']').padEnd(10)} ${f.owner.padEnd(24)} ${f.msg}`);
      if (f.sev === 'UNBACKED') unbacked++;
      else if (f.sev === 'DISTANT') distant++;
      else if (f.sev === 'PARSE') parseErr++;
    }
    console.log('');
  }
  console.log('─'.repeat(72));
  console.log(`scanned ${files.length} files · ${unbacked} UNBACKED · ${distant} DISTANT · ${parseErr} parse-err`);
  if (!unbacked && !distant && !parseErr) console.log('✓ clean — every solved/derived chip traces to a solve or a computation.');
  const fail = parseErr > 0 || unbacked > 0 || (strict && distant > 0);
  process.exit(fail ? 1 : 0);
}

main();
