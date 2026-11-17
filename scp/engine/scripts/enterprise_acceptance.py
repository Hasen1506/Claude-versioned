"""Reproducible synthetic contention and independently calculated planning checks.

Run from engine/: PYTHONPATH=. python scripts/enterprise_acceptance.py --output results.json
Uses a temporary SQLite database, never an existing company's data. Latencies
exclude HTTP/network and include reads, failed CAS attempts and retries. These
measurements are a baseline, not a customer SLA or a vendor comparison.
"""
from __future__ import annotations

import argparse
import itertools
import json
import multiprocessing as mp
import platform
import queue
import resource
import statistics
import subprocess
import tempfile
import time
from datetime import date
from pathlib import Path

from scp.companies.store import Companies, CompanyError
from scp.versions.store import Store


def worker(url, uid, cid, tag, rounds, start, output):
    try:
        c = Companies(Store(url))
        user = c._user(uid)
        start.wait(timeout=60)
        durations, saved, conflicts = [], [], 0
        for turn in range(rounds):
            began = time.perf_counter()
            while True:
                current = c.open(user, cid)
                current.dataset["settings"]["company_name"] = f"{tag}-{turn}"
                try:
                    result = c.save(user, cid, current.dataset, current.meta.revision)
                except CompanyError as exc:
                    if exc.status != 409:
                        raise
                    conflicts += 1
                    continue
                saved.append(result.meta.revision)
                durations.append(time.perf_counter() - began)
                break
        c.db.close()
        output.put({"company": cid, "revisions": saved, "conflicts": conflicts, "seconds": durations,
                    "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    except BaseException as exc:
        output.put({"error": repr(exc)})
        raise


def contention(products: int, locations: int, workers: int, rounds: int, shared: bool) -> dict:
    with tempfile.TemporaryDirectory(prefix="scp-acceptance-") as temporary:
        url = str(Path(temporary) / "benchmark.sqlite")
        c = Companies(Store(url))
        session = c.signup("benchmark@example.test", "Synthetic benchmark", "local-audit-winter-RIVER-3179")
        doc = {"settings": {"planning_start": "2026-01-05", "horizon_days": 28},
               "locations": [{"id": f"L{i}", "type": "plant"} for i in range(locations)],
               "products": [{"id": f"P{i}", "type": "FG", "price": i % 100 + 1} for i in range(products)],
               "location_products": [{"location": f"L{i}", "product": f"P{j}", "on_hand": 100}
                                     for i in range(locations) for j in range(products)]}
        ids = [c.create(session.user, doc).id for _ in range(1 if shared else workers)]
        c.db.close()
        ctx = mp.get_context("spawn")
        start, output = ctx.Barrier(workers + 1), ctx.Queue()
        children = [ctx.Process(target=worker, args=(url, session.user.id, ids[0 if shared else i],
                                                   i, rounds, start, output)) for i in range(workers)]
        for child in children:
            child.start()
        start.wait(timeout=60)
        began = time.perf_counter()
        rows = []
        try:
            for _ in children:
                rows.append(output.get(timeout=120))
        except queue.Empty:
            raise RuntimeError("benchmark worker exceeded 120 seconds") from None
        finally:
            for child in children:
                child.join(timeout=5)
                if child.is_alive():
                    child.terminate()
                    child.join()
        elapsed = time.perf_counter() - began
        if any(child.exitcode != 0 for child in children) or any("error" in row for row in rows):
            raise RuntimeError(rows)
        c = Companies(Store(url))
        for cid in ids:
            revisions = sorted(rev for row in rows if row["company"] == cid for rev in row["revisions"])
            assert revisions == list(range(2, len(revisions) + 2)), "missing or duplicated committed revision"
            stored = c.db.execute("SELECT revision FROM company_revisions WHERE company_id = ? ORDER BY revision",
                                  (cid,)).fetchall()
            assert [r[0] for r in stored] == [1, *revisions], "audit history disagrees with committed effects"
        c.db.close()
        durations = sorted(x for row in rows for x in row["seconds"])
        return {"mode": "same_company" if shared else "different_companies", "products": products,
                "locations": locations, "location_products": products * locations, "workers": workers,
                "writes": len(durations), "document_bytes": len(json.dumps(doc).encode()),
                "elapsed_seconds": elapsed, "writes_per_second": len(durations) / elapsed,
                "operation_seconds_p50": statistics.median(durations),
                "operation_seconds_p95": durations[max(0, int(len(durations) * .95) - 1)],
                "conflicts": sum(row["conflicts"] for row in rows),
                "worker_max_rss_kib": max(row["max_rss_kib"] for row in rows),
                "revision_and_audit_reconciliation": "passed"}


def forecast_oracle() -> dict:
    import numpy as np
    from scp.demand.competition import compete
    from scp.model import ForecastModelId as M, SelectionMetric
    values = [20 + 3 * (i % 4) + i // 4 for i in range(48)]
    outcome = compete(np.array(values, dtype=float), 4, 4, [M.NAIVE, M.SEASONAL_NAIVE], k=6, h=3,
                      metric=SelectionMetric.WAPE)
    scores = {}
    for score in outcome.scores:
        errors, actuals = [], []
        for origin, step, actual, prediction in score.backtest:
            # Independent indexing: no candidate or scoring implementation is used.
            expected = values[origin - 1] if score.model == M.NAIVE else values[origin - 4 + ((step - 1) % 4)]
            assert prediction == expected
            assert actual == values[origin + step - 1]
            errors.append(abs(expected - actual))
            actuals.append(actual)
        assert errors
        wape = sum(errors) / sum(actuals)
        assert abs(score.wape - wape) < 1e-12
        scores[score.model.value] = {"wape": wape, "holdout_predictions_checked": len(errors)}
    assert outcome.champion.value == min(scores, key=lambda key: scores[key]["wape"])
    return {"status": "passed", "scores": scores, "champion": outcome.champion.value,
            "limitation": "synthetic baselines; no independent customer accuracy or economic-value claim"}


def scheduling_oracle() -> dict:
    from scp.model import Calendar
    from scp.time import WorkCalendar
    from scp.schedule.clock import ResourceClock
    from scp.schedule.core import Instance, Job, OpSpec, Res, check, edd
    from scp.schedule.optimize import optimize
    processing, due = [2, 1, 4, 3, 2, 1], [3, 5, 8, 6, 11, 15]
    # One always-available machine, no setup or precedence: enumerate all 720 schedules.
    best = float("inf")
    for sequence in itertools.permutations(range(6)):
        elapsed, loss = 0, 0
        for i in sequence:
            elapsed += processing[i]
            loss += max(0, elapsed - due[i])
        best = min(best, loss)
    jobs = {}
    for i, duration in enumerate(processing):
        key = f"J{i}"
        operation = OpSpec(f"{key}:10", key, 10, "R", f"P{i}", "A", 1, 0, duration)
        jobs[key] = Job(key, f"P{i}", 0, due[i], [operation])
    clock = ResourceClock(WorkCalendar(Calendar(id="ALL", workdays=list(range(7)))), date(2026, 1, 5), 0, 24, 1)
    instance = Instance({"R": Res("R", 1, clock)}, jobs, lambda *args: 0, lambda op, end: end)
    began = time.perf_counter()
    _sequence, decoded, _hold, _pinned, info = optimize(instance, edd(instance), {}, 2)
    assert not check(instance, decoded)
    assert abs(decoded.objective - best) < 1e-7
    return {"status": "passed", "enumerated_schedules": 720, "independent_optimum": best,
            "actual_objective": decoded.objective, "seconds": time.perf_counter() - began,
            "solver_status": info.status, "limitation": "tiny exact oracle; no production-scale optimality claim"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--products", type=int, default=1000)
    parser.add_argument("--locations", type=int, default=5)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    if min(args.products, args.locations, args.workers, args.rounds) < 1:
        parser.error("workload dimensions must be positive")
    report = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True)),
              "python": platform.python_version(), "platform": platform.platform(), "database": "SQLite local file",
              "forecast": forecast_oracle(), "scheduling": scheduling_oracle(),
              "contention": [contention(args.products, args.locations, args.workers, args.rounds, shared)
                             for shared in (True, False)],
              "external_acceptance": "SAP/Kinaxis reference, customer workload, HA and production RPO/RTO not supplied"}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
