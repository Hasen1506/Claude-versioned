"""Run an engine (whichever ``scp`` package is first on PYTHONPATH) over companies read from stdin and write what it
planned to stdout, as JSON. Used by tests/test_differential.py to compare two versions of the engine in separate
processes; not a test itself.

stdin:  {"companies": [<dataset dict>, ...]}
stdout: [{"plan": <MRP result>, "issues": [<readiness issues>], "forecast": <forecast result or null>}, ...]"""
from __future__ import annotations

import json
import os
import sys


def main() -> None:
    os.environ.setdefault("SCP_SCHEDULER", "0")
    import scp
    from scp.demand import run_forecast
    from scp.model import Dataset
    from scp.plan import run_mrp
    from scp.validate import validate

    jobs = json.load(sys.stdin)["companies"]
    out = []
    for d in jobs:
        ds = Dataset.model_validate(d)
        plan = run_mrp(ds).model_dump(mode="json")
        issues = sorted(json.dumps(i.model_dump(mode="json"), sort_keys=True) for i in validate(ds))
        fc = run_forecast(ds).model_dump(mode="json") if ds.history else None
        out.append({"plan": plan, "issues": issues, "forecast": fc})
    json.dump({"engine": os.path.dirname(scp.__file__), "results": out}, sys.stdout, sort_keys=True)


if __name__ == "__main__":
    main()
