"""Differential test: this engine against the engine before PR #22 (commit 435873f) on random companies.

The two engines run in separate processes on the same randomly generated companies (networks, policies, lot sizes,
demand and sales history). Their plans, readiness checks and forecasts must be identical — except for the changes we
made on purpose, listed in ``INTENTIONAL`` below. That exception is checked exactly, not waved through: the old engine
is run a second time with only those documented changes applied to it, and *that* must equal this engine byte for
byte. So an unintended change anywhere in planning fails here, and so does an intentional one nobody documented.

The baseline source comes from git (``git archive``); CI checks out the full history for it. Outside a git checkout
(a source tarball) the test is skipped locally, never on CI."""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from .strategies import network

BASELINE = os.environ.get("SCP_DIFF_BASE", "435873f")       # main before PR #22
N = int(os.environ.get("SCP_DIFF_COMPANIES", "60"))
ENGINE = Path(__file__).resolve().parents[1]                  # scp/engine
RUNNER = Path(__file__).with_name("differential_runner.py")

# Every behaviour change since the baseline that the plan is allowed to show, with what it is and where it was made.
# (name, path inside scp/engine, how): "file" takes this engine's whole file; (old, new) replaces one passage.
INTENTIONAL: list[tuple[str, str, object]] = [
    ("CV-M02 (PR #22): a max-lot split keeps every lot within the maximum and on the rounding value",
     "scp/plan/lotsize.py", "file"),
    ("TS-01 (this PR): replenish-to-max rounds down in whole rounding steps when it splits by the maximum",
     "scp/plan/mrp.py",
     ("                    lots = apply_modifiers(down, mins=[], roundings=[], maxes=maxes)",
      "                    lots = apply_modifiers(down, mins=[], roundings=[step], maxes=maxes)")),    ('S4-B1 (s4 backtest B): a fixed lot size repeats the fixed lot, one order per lot (S/4 FX)',
     "scp/plan/mrp.py",
     ('        if st.lp.strategy is Strategy.MTO:\n            lots = apply_modifiers(qty, mins=[], roundings=batch + whole, maxes=maxes)\n        else:',
      '        if st.lp.strategy is Strategy.MTO:\n            lots = apply_modifiers(qty, mins=[], roundings=batch + whole, maxes=maxes)\n        elif ls.policy is LotSizePolicy.FIXED and ls.fixed_qty:\n            # fixed lot size (S/4 FX): the fixed lot is repeated until the shortage is covered, one order per lot (a\n            # shortage of 120 in lots of 50 is three orders of 50, not one of 150: each lot is a batch, a setup and\n            # an order cost). The minimums and rounding apply to the lot itself\n            one = apply_modifiers(ls.fixed_qty, mins=mins, roundings=rounds, maxes=maxes)\n            n = max(1, math.ceil(qty / sum(one) - 1e-9))\n            lots = one * n\n        else:')),
    ("S4-B2 (s4 backtest B): safety time counts working days on the location's calendar",
     "scp/plan/mrp.py",
     ('            need = max(self.start, d - timedelta(days=lp.safety_time_days)) if lp.safety_time_days else d',
      "            # safety time (S/4 §8.1): the receipt is planned this many WORKING days early on the location's calendar,\n            # so a Monday requirement with two days of safety time is due on Thursday, never on a closed Saturday\n            need = (max(self.start, location_calendar(self.ds, node[0]).add_workdays(d, -lp.safety_time_days))\n                    if lp.safety_time_days else d)")),
    ('S4-B3 (s4 backtest B): reschedule-out / receipt-not-needed exceptions (S/4 15 and 20), part 1',
     "scp/plan/mrp.py",
     ('EPS = 1e-9\n_PREFIX',
      'EPS = 1e-9\nRESCHEDULE_OUT_TOLERANCE_DAYS = 3   # a firm receipt up to this many days early is left alone (S/4 rescheduling tolerance)\n_PREFIX')),
    ('S4-B3 (s4 backtest B): reschedule-out / receipt-not-needed exceptions (S/4 15 and 20), part 2',
     "scp/plan/mrp.py",
     ('                threshold = max(threshold, lp.reorder_point)\n',
      '                threshold = max(threshold, lp.reorder_point)\n            thresholds[d] = threshold\n')),
    ('S4-B3 (s4 backtest B): reschedule-out / receipt-not-needed exceptions (S/4 15 and 20), part 3',
     "scp/plan/mrp.py",
     ('        fresh = _Fresh(onhand) if shelf else None\n        for d in dates:',
      '        fresh = _Fresh(onhand) if shelf else None\n        thresholds: dict[date, float] = {}\n        for d in dates:')),
    ('S4-B3 (s4 backtest B): reschedule-out / receipt-not-needed exceptions (S/4 15 and 20), part 4',
     "scp/plan/mrp.py",
     ('                    fresh.add(max(d, o.available_date) + timedelta(days=shelf), o.qty, o.id)\n        self._peg(node, st)\n',
      '                    fresh.add(max(d, o.available_date) + timedelta(days=shelf), o.qty, o.id)\n        if disc is None:\n            self._reschedule_out(node, st, thresholds)\n        self._peg(node, st)\n\n    def _reschedule_out(self, node: Node, st: _NodeState, thresholds: dict[date, float]) -> None:\n        """The rescheduling check the other way (S/4 exceptions 15 and 20): a firm receipt the plan does not need on its\n        date. Receipts are taken in date order; each is needed on the first checked date where the stock without it\n        (and without the firm receipts after it) would fall below the safety stock, target or reorder point. Needed\n        nowhere in the horizon: RECEIPT_NOT_NEEDED (cancel it, or pull it in instead of a new order); needed more than\n        RESCHEDULE_OUT_TOLERANCE_DAYS later: RESCHEDULE_OUT to that date. Advice only: the receipt keeps its date."""\n        firm = sorted((s for s in st.supplies if s.kind == "receipt"), key=lambda s: (s.date, s.id))\n        if not firm or not thresholds:\n            return\n        others = [s for s in st.supplies if s.kind != "receipt"]\n        out_req: dict[date, float] = defaultdict(float)\n        for r in st.reqs:\n            out_req[r.date] += r.qty\n        checks = sorted(thresholds)\n        for k, rc in enumerate(firm):\n            inflow: dict[date, float] = defaultdict(float)\n            for s in [*others, *firm[:k]]:\n                inflow[s.date] += s.qty\n            avail = 0.0\n            needed: date | None = None\n            for d in sorted(set(checks) | set(inflow) | set(out_req)):\n                avail += inflow.get(d, 0.0) - out_req.get(d, 0.0)\n                if d in thresholds and avail < thresholds[d] - EPS:\n                    needed = d\n                    break\n            if needed is None:\n                self._exc("RECEIPT_NOT_NEEDED", "warning",\n                          f"{rc.id}: {rc.qty:,.1f} arrive {rc.date.isoformat()} but nothing needs them before the "\n                          f"horizon ends: cancel or push it out (or pull it in in place of a new order)",\n                          node=node, order=rc.id, when=rc.date, qty=rc.qty)\n            elif (needed - rc.date).days > RESCHEDULE_OUT_TOLERANCE_DAYS:\n                self._exc("RESCHEDULE_OUT", "warning",\n                          f"{rc.id}: arrives {rc.date.isoformat()} but is first needed {needed.isoformat()}; push it "\n                          f"out by {(needed - rc.date).days} d", node=node, order=rc.id, when=needed, qty=rc.qty)\n')),
]


def _engine_passage(path: str, start: str, stop: str) -> str:
    """This engine's text of ``path`` from the line starting ``start`` up to (not including) ``stop``."""
    text = (ENGINE / path).read_text()
    i = text.index(start)
    return text[i:text.index(stop, i)]


# S/4 guide backtest part A: a readiness warning when consumption windows cannot bridge spot forecasts
_GAP = "scp/validate/__init__.py"
INTENTIONAL += [
    ("S4-A (guide §5.4): CONSUMPTION_GAP joins the readiness rules", _GAP,
     ('    "MTO_WITH_FORECAST": ("warning", "Forecast on an MTO product is ignored"),\n',
      _engine_passage(_GAP, '    "MTO_WITH_FORECAST"', '    "FORECAST_TWICE"'))),
    ("S4-A (guide §5.4): the check that raises it", _GAP,
     ("def _demand(ds: Dataset, c: _Collector) -> None:\n",
      _engine_passage(_GAP, "def _consumption_gaps(", "def _demand(") + "def _demand(ds: Dataset, c: _Collector) -> None:\n")),
    ("S4-A (guide §5.4): run with the other demand checks", _GAP,
     ("    for loc, prod in sorted(mto_fc):\n",
      "    _consumption_gaps(ds, c, end)\n    for loc, prod in sorted(mto_fc):\n")),
]


# Forecast reduction by delivered orders (guide §5.1, §17.2, §20.1 #1): the forecast as entered is kept on the record by
# the roll, and every plan counts what delivered orders took of it (open orders' delivered part, the closed-order log)
# before open orders consume the rest, matched by the forecast as entered. Companies with seed % 4 == 2 carry such
# orders. The consumption module is taken whole; the two callers pass the dataset and the node.
INTENTIONAL += [
    ("Forecast reduction (guide §5.1/§17.2): consumption recomputed from delivered and open orders",
     "scp/plan/consumption.py", "file"),
    ("Forecast reduction: MRP passes the dataset and node to the consumption", "scp/plan/mrp.py",
     ("effective_demand(recs, lp.strategy, lp.consumption_backward_days, lp.consumption_forward_days)",
      "effective_demand(recs, lp.strategy, lp.consumption_backward_days, lp.consumption_forward_days,\n"
      "                                          ds=self.ds, node=node)")),
    ("Forecast reduction: the rate-based flow passes the dataset and node too", "scp/plan/rates.py",
     ("                     for r in effective_demand(rs, lp.strategy, lp.consumption_backward_days,\n"
      "                                               lp.consumption_forward_days)]",
      "                     for r in effective_demand(rs, lp.strategy, lp.consumption_backward_days,\n"
      "                                               lp.consumption_forward_days, ds=ds, node=node)]")),
]


def _git(*args: str, cwd: Path = ENGINE) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=120)


@pytest.fixture(scope="module")
def baseline(tmp_path_factory) -> Path:
    if _git("rev-parse", "--git-dir").returncode != 0:
        if os.environ.get("CI"):
            pytest.fail("the differential test needs the git history (actions/checkout with fetch-depth: 0)")
        pytest.skip("not a git checkout: no baseline engine to compare with")
    if _git("cat-file", "-e", f"{BASELINE}^{{commit}}").returncode != 0:
        pytest.fail(f"commit {BASELINE} is not in this clone: fetch the full history (git fetch --unshallow)")
    top = Path(_git("rev-parse", "--show-toplevel").stdout.decode().strip())
    rel = ENGINE.relative_to(top).as_posix()
    tar = _git("archive", "--format=tar", BASELINE, f"{rel}/scp", cwd=top)
    assert tar.returncode == 0, tar.stderr.decode()
    root = tmp_path_factory.mktemp("baseline")
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as t:
        t.extractall(root, filter="data")
    old = root / "old"
    shutil.move(str(root / rel), str(old))
    # the same old engine with only the documented changes applied
    fixed = root / "documented"
    shutil.copytree(old, fixed)
    for name, path, how in INTENTIONAL:
        target = fixed / path
        if how == "file":
            shutil.copy(ENGINE / path, target)
        else:
            a, b = how
            text = target.read_text()
            assert text.count(a) == 1, f"{name}: the passage it changes is not in the baseline once"
            target.write_text(text.replace(a, b))
    return root


def _random_lot(rng: random.Random) -> dict:
    policy = rng.choice(["L4L", "FIXED", "POQ", "EOQ", "MIN_MAX"])
    ls: dict = {"policy": policy, "min_qty": rng.choice([0, 0, 20, 30, 60])}
    if policy == "FIXED":
        ls["fixed_qty"] = rng.choice([10, 25, 40, 100])
    if policy == "POQ":
        ls["periods"] = rng.randint(1, 3)
    if policy == "EOQ":
        ls["ordering_cost"] = rng.choice([0, 100, 500])
    if rng.random() < 0.5:
        ls["rounding_qty"] = rng.choice([5, 10, 12, 25])
    if rng.random() < 0.5:
        ls["max_qty"] = max(ls["min_qty"], rng.choice([35, 50, 80, 150, 300]))
    return ls


def companies(n: int) -> list[dict]:
    out = []
    for seed in range(n):
        rng = random.Random(10_000 + seed)
        probe = network(seed)
        lots = {p["id"]: _random_lot(rng) for p in probe["products"]} if seed % 2 else None
        d = network(seed, lots, max_stock=seed % 3 == 0)
        if seed % 4 == 0:            # sales history for a forecast: weekly, a year back
            fg = next(p["id"] for p in d["products"] if p["type"] == "FG")
            cus = next(x["id"] for x in d["locations"] if x["type"] == "customer")
            start = network(seed)["settings"]["planning_start"]
            from datetime import date, timedelta
            first = date.fromisoformat(start) - timedelta(weeks=52)
            d["history"] = [{"location": cus, "product": fg, "date": (first + timedelta(weeks=i)).isoformat(),
                             "qty": float(max(0, round(rng.gauss(60, 15))))} for i in range(52)]
        if seed % 4 == 2:            # orders already partly or wholly delivered (forecast reduction, see INTENTIONAL)
            from datetime import date, timedelta
            k = 0
            for row in d["demand"]:
                if row["kind"] == "sales_order":
                    row["id"] = f"SO{k}"
                    k += 1
                    if rng.random() < 0.5:     # partly delivered: ``qty`` is what is still open
                        row["ordered_qty"] = float(row["qty"] + rng.randint(1, 40))
            fcs = [row for row in d["demand"] if row["kind"] == "forecast"]
            closed = []
            for j, row in enumerate(rng.sample(fcs, k=min(len(fcs), 3))):
                due = date.fromisoformat(row["date"]) + timedelta(days=rng.randint(-2, 3))
                q = float(rng.randint(5, 80))
                closed.append({"kind": "sales", "id": f"CS{j}", "location": row["location"], "product": row["product"],
                               "ordered_qty": q, "delivered_qty": q, "due_date": due.isoformat(),
                               "closed_on": due.isoformat()})
            d["closed_orders"] = closed
        out.append(d)
    return out


def _run(pythonpath: Path, jobs: list[dict]) -> dict:
    env = {**os.environ, "PYTHONPATH": str(pythonpath), "SCP_SCHEDULER": "0", "PYTHONHASHSEED": "0"}
    p = subprocess.run([sys.executable, str(RUNNER)], input=json.dumps({"companies": jobs}).encode(),
                       capture_output=True, env=env, cwd=pythonpath, timeout=600)
    assert p.returncode == 0, p.stderr.decode()[-3000:]
    res = json.loads(p.stdout)
    assert Path(res["engine"]).resolve() == (pythonpath / "scp").resolve(), res["engine"]
    return res


def _first_difference(a, b, at="") -> str:
    if type(a) is not type(b):
        return f"{at}: {a!r} vs {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return _first_difference(a.get(k), b.get(k), f"{at}.{k}")
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{at}: {len(a)} items vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            if x != y:
                return _first_difference(x, y, f"{at}[{i}]")
    return f"{at}: {str(a)[:200]} vs {str(b)[:200]}"


def test_plans_match_the_engine_before_pr22_except_for_documented_changes(baseline):
    jobs = companies(N)
    old = _run(baseline / "old", jobs)["results"]
    documented = _run(baseline / "documented", jobs)["results"]
    new = _run(ENGINE, jobs)["results"]
    changed = [i for i in range(N) if old[i] != new[i]]
    unexplained = [i for i in range(N) if documented[i] != new[i]]
    msg = "\n".join(f"company {i}: {_first_difference(documented[i], new[i])}" for i in unexplained[:5])
    assert not unexplained, f"{len(unexplained)} of {N} plans changed in a way no documented change explains:\n{msg}"
    # the documented changes are exercised by the generated companies (the test would prove nothing otherwise)
    assert changed, "no generated company exercises the documented changes: widen the generator"
    print(f"{N} companies; {len(changed)} plans differ from {BASELINE}, every difference explained by "
          f"{', '.join(n.split(':')[0] for n, _, _ in INTENTIONAL)}")
