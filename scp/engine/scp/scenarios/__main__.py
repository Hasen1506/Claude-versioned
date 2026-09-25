"""Run the end-to-end scenarios and print their checkpoints.

    python -m scp.scenarios                       # all scenarios, straight through the engine
    python -m scp.scenarios s2-kettles -v         # one scenario, every checkpoint with its derivation
    python -m scp.scenarios --url http://localhost:8000   # through a running server's HTTP API

Exit status 1 if any checkpoint fails.
"""
from __future__ import annotations

import argparse
import sys

from . import BY_ID, SCENARIOS, EngineClient
from .harness import Client, ScenarioReport


def _print(r: ScenarioReport, verbose: bool) -> None:
    mark = "PASS" if r.ok else "FAIL"
    print(f"{mark}  {r.id:<12} {r.title}  —  {r.passed} passed, {r.failed} failed ({r.seconds:.2f}s, {r.client})")
    for st in r.steps:
        bad = [c for c in st.checks if not c.passed]
        if not (verbose or bad or st.error):
            continue
        print(f"      {st.n}. {st.title}   [{st.stage} · {st.call}]")
        if st.error:
            print("         ERROR " + st.error.splitlines()[0])
        for c in st.checks:
            if c.passed and not verbose:
                continue
            print(f"         {'✓' if c.passed else '✗'} {c.label}")
            if not c.passed or verbose:
                print(f"             expected {c.expected}")
                print(f"             actual   {c.actual}")
            if verbose and c.why:
                print(f"             why      {c.why}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scp.scenarios", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="scenario ids (default: all)")
    ap.add_argument("--url", help="run through the HTTP API of a running server")
    ap.add_argument("-v", "--verbose", action="store_true", help="show every checkpoint and its derivation")
    a = ap.parse_args(argv)
    unknown = [i for i in a.ids if i not in BY_ID]
    if unknown:
        ap.error(f"unknown scenario(s) {', '.join(unknown)}; choose from {', '.join(BY_ID)}")
    def client() -> Client:          # a fresh client per scenario: its own version store in the engine
        if not a.url:
            return EngineClient()
        import httpx

        from .http import HttpClient
        return HttpClient(httpx.Client(base_url=a.url, timeout=120))

    reports = [BY_ID[i].execute(client()) for i in (a.ids or [s.id for s in SCENARIOS])]
    for r in reports:
        _print(r, a.verbose)
    total = sum(r.passed + r.failed for r in reports)
    failed = sum(r.failed for r in reports)
    print(f"\n{len(reports)} scenario(s), {total} checkpoints, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
