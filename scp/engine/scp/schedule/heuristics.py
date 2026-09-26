"""The heuristics catalogue (S/4 PP/DS heuristics, the ones a detailed scheduler reaches for) and the scheduling
profiles (≈ PP/DS strategy profiles) that bundle a start rule, the search and the objective weights.

A start rule builds the first sequence (and, backward, a not-before time per order); the local search and the
optimiser then improve on it under the objective weights. Every rule runs through the same decoder, so each result is
a feasible schedule on the shift calendar and can be compared like for like.
"""
from __future__ import annotations

from dataclasses import replace

from ..model.common import Out
from .core import Instance, Job, decode, edd


class Heuristic(Out):
    id: str
    name: str
    what: str            # what it does, in plain words
    good_for: str        # when a planner reaches for it
    sap: str             # the nearest S/4 PP/DS heuristic


class Profile(Out):
    id: str
    name: str
    what: str
    settings: dict       # the ScheduleSettings fields it sets


HEURISTICS: list[Heuristic] = [
    Heuristic(id="edd", name="Earliest due date first",
              what="Each machine takes its orders in due-date order.",
              good_for="A fair, explainable default; few orders late when capacity is tight but not overloaded.",
              sap="Schedule sequence by due date (SAP001)"),
    Heuristic(id="spt", name="Shortest job first",
              what="Orders with the least machine work go first.",
              good_for="Getting the most orders through quickly; short orders stop waiting behind long ones.",
              sap="Sequence by processing time"),
    Heuristic(id="slack", name="Least slack first",
              what="Orders with the least spare time between their work and their due date go first.",
              good_for="Protecting due dates when some orders have long routings or late parts.",
              sap="Critical ratio / sequence by slack"),
    Heuristic(id="campaign", name="Campaigns by setup group",
              what="A machine that comes free stays on its setup group while orders of that group are ready, "
                   "then moves to the most urgent ready order.",
              good_for="Few changeovers: long setups, cleaning between groups, colour or size changes.",
              sap="Setup-optimal sequence (SAP_PP_Q001 / campaign)"),
    Heuristic(id="backward", name="Backward from the due date (just in time)",
              what="Each order is held until its latest start (its own run time back from the due date, less a "
                   "buffer), then machines take orders in due-date order.",
              good_for="Keeping stock low: nothing is built long before it is needed.",
              sap="Backward scheduling (SAP_DS_02)"),
    Heuristic(id="improve", name="Local search",
              what="Tries pulling orders next to others of the same setup group and moving each order a few places "
                   "earlier or later; keeps every move that lowers the weighted objective.",
              good_for="Trading changeovers against lateness by the weights you set; runs in seconds.",
              sap="Sequence optimisation (heuristic)"),
    Heuristic(id="optimize", name="Optimiser (constraint solver)",
              what="A CP-SAT model chooses the machine (own or alternative) and the order of every step to lower the "
                   "weighted objective; the result is re-timed on the shift calendar and kept only if it beats the "
                   "local search.",
              good_for="Alternative machines, many orders competing, or when the other rules leave orders late.",
              sap="PP/DS optimiser"),
]

_BASE = {"tardiness_weight": 4.0, "setup_weight": 1.0, "earliness_weight": 0.0, "makespan_weight": 0.0,
         "start_rule": "edd", "improve": True, "optimizer": False}

PROFILES: list[Profile] = [
    Profile(id="balanced", name="Balanced",
            what="Due dates first, changeovers second: an hour late costs as much as four hours of changeover.",
            settings={**_BASE}),
    Profile(id="on_time", name="Protect due dates",
            what="Lateness costs far more than changeovers; starts with the orders that have the least slack.",
            settings={**_BASE, "tardiness_weight": 20.0, "start_rule": "slack"}),
    Profile(id="fewest_changeovers", name="Fewest changeovers",
            what="Long campaigns by setup group; an hour of changeover costs as much as four hours late.",
            settings={**_BASE, "tardiness_weight": 1.0, "setup_weight": 4.0, "start_rule": "campaign"}),
    Profile(id="just_in_time", name="Just in time",
            what="Orders start as late as they can and still finish on time, so stock is not built early; the "
                 "optimiser weighs an hour early at a quarter of an hour late.",
            settings={**_BASE, "earliness_weight": 1.0, "start_rule": "backward", "optimizer": True}),
    Profile(id="fastest", name="Finish everything soonest",
            what="Shortest total time to clear the window (makespan), then lateness.",
            settings={**_BASE, "tardiness_weight": 1.0, "makespan_weight": 4.0, "start_rule": "spt"}),
    Profile(id="best", name="Best possible (optimiser)",
            what="The balanced weights, with the constraint solver choosing machines and sequence.",
            settings={**_BASE, "optimizer": True}),
]


def _work(j: Job) -> float:
    return sum(o.setup + o.run for o in j.ops)


def alone(inst: Instance, j: Job) -> tuple[float, float]:
    """(first start, completion) of the order on an empty shop: its own flow time, parts and calendars included."""
    one = replace(inst, jobs={j.id: j}, frozen={})
    d = decode(one, edd(one))
    first = min((b.setup_start for b in d.blocks), default=j.release)
    return first, d.completion.get(j.id, j.release)


def _dispatch(inst: Instance, prio: dict[str, tuple], stay: bool = False) -> dict[str, list[str]]:
    """Non-delay dispatching per machine: when a machine comes free it takes, of the steps that could start by
    then (by their own flow on an empty shop), the one first by priority; if none could, the one that can start
    soonest. A priority rule then never idles a machine for an order still waiting for parts or an earlier step.
    With ``stay`` a machine keeps to the setup group it is on while steps of that group could start."""
    est: dict[str, float] = {}
    dur: dict[str, float] = {}
    for j in inst.jobs.values():
        one = replace(inst, jobs={j.id: j}, frozen={})
        d = decode(one, edd(one))
        for b in d.blocks:
            est[b.key] = min(est.get(b.key, b.setup_start), b.setup_start)
            dur[b.key] = max(dur.get(b.key, 0.0), b.end - est[b.key])
    out: dict[str, list[str]] = {r: [] for r in inst.resources}
    for r in inst.resources:
        todo = [o for j in inst.jobs.values() for o in j.ops if o.resource == r]
        t = 0.0
        group: str | None = None
        while todo:
            can = [o for o in todo if est.get(o.key, 0.0) <= t + 1e-9]
            if stay and group is not None and any(o.group == group for o in can):
                can = [o for o in can if o.group == group]
            o = (min(can, key=lambda o: (*prio[o.order], o.seq)) if can
                 else min(todo, key=lambda o: (est.get(o.key, 0.0), *prio[o.order], o.seq)))
            todo.remove(o)
            group = o.group
            out[r].append(o.key)
            t = max(t, est.get(o.key, 0.0)) + dur.get(o.key, 0.0)
    return out


def start(inst: Instance, rule: str, buffer_days: float = 1.0) -> tuple[dict[str, list[str]], dict[str, float]]:
    """The first sequence (and not-before times) a start rule builds."""
    jobs = inst.jobs
    if rule == "spt":
        return _dispatch(inst, {j.id: (_work(j), j.due, j.id) for j in jobs.values()}), {}
    if rule == "slack":
        slack = {}
        for j in jobs.values():
            first, done = alone(inst, j)
            slack[j.id] = j.due - max(j.release, first) - (done - first)
        return _dispatch(inst, {j.id: (slack[j.id], j.due, j.id) for j in jobs.values()}), {}
    if rule == "campaign":
        return _dispatch(inst, {j.id: (j.due, j.release, j.id) for j in jobs.values()}, stay=True), {}
    if rule == "backward":
        hold = {}
        for j in jobs.values():
            first, done = alone(inst, j)
            latest = j.due - (done - first) - buffer_days * 24.0
            if latest > j.release:
                hold[j.id] = latest
        return edd(inst), hold
    return edd(inst), {}


__all__ = ["HEURISTICS", "PROFILES", "Heuristic", "Profile", "alone", "start"]
