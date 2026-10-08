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
      "                    lots = apply_modifiers(down, mins=[], roundings=[step], maxes=maxes)")),
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
