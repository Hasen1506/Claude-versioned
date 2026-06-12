#!/usr/bin/env bash
# V1-2 (PRODUCT_BLUEPRINT_V3 Part 8) — THE gate. One command, four layers, in order
# of increasing depth (observed ≫ sampled ≫ reasoned):
#
#   1. pytest solver contracts   — python-side field contracts + hand-verified goldens
#   2. OBS-3 provenance lint     — every solved/derived chip traces to a real solve
#   3. HARNESS-1 model_check     — parse, shadows, _excluded, panel==harness, endpoints
#   4. HARNESS-1b golden path    — BOOTS the real app (Playwright) + 6 identities
#
# Layer 4 needs the Flask server; if :5000 is down we start it the sanctioned way
# (nohup + pidfile — NEVER pkill -f) and leave it running for the session.
#
# Usage:  bash app_v2/tools/gate.sh [--skip-boot]   (--skip-boot = layers 1–3 only)
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # app_v2/tools
APPV2="$(dirname "$HERE")"                              # app_v2
ROOT="$(dirname "$APPV2")"                              # repo root
SKIP_BOOT="${1:-}"

pass=0; fail=0
step() {  # step <name> <cmd...>
  local name="$1"; shift
  echo "──── $name"
  if "$@"; then echo "✅ $name"; pass=$((pass+1)); else echo "❌ $name"; fail=$((fail+1)); fi
  echo
}

step "1/4 pytest solver contracts" \
  python3 -m pytest "$ROOT/tests" -q -p no:cacheprovider --no-header -W ignore

step "2/4 lints (OBS-3 provenance + V2-5 units + V2-12 payload literals)" \
  bash -c "node '$HERE/provenance_lint.js' && node '$HERE/units_lint.js' && node '$HERE/payload_literal_lint.js'"

step "3/4 HARNESS-1 model_check" \
  node "$HERE/model_check.js"

if [ "$SKIP_BOOT" = "--skip-boot" ]; then
  echo "(4/4 HARNESS-1b skipped by --skip-boot)"
else
  if ! curl -s -m 3 -o /dev/null "http://localhost:5000/"; then
    echo "server down — starting (setsid --fork + pidfile, fully detached)"
    # setsid --fork: the server must be NOBODY'S child — the old `setsid … &`
    # left it a child of THIS shell, which then sat in do_wait forever after
    # the last step (observed 2026-06-10: gate wedged 9 min with all 4 layers
    # done), and `echo $!` captured the WRONG pid. --fork reparents the server
    # to init; the inner `echo $$ && exec` writes the REAL server pid (exec
    # keeps it). </dev/null + log redirect: never inherit the gate's stdio.
    ( cd "$ROOT" && setsid --fork bash -c 'echo $$ > /tmp/es_server.pid && exec python3 app.py' </dev/null > /tmp/es_server.log 2>&1 )
    for i in $(seq 1 20); do
      sleep 1
      curl -s -m 2 -o /dev/null "http://localhost:5000/" && break
    done
  fi
  step "4/4 HARNESS-1b golden path (boots the app)" \
    node "$HERE/golden_path.js"
fi

echo "════ GATE: $pass passed · $fail failed"
[ "$fail" -eq 0 ]
