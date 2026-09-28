"""Part of a plan's pegging, asked for when it is looked at (Phase S, N77).

A large company's plan links a million requirements to their supply: sent whole, requirements and pegging are two
thirds of the plan's answer. The browser asks instead for what one screen shows: an order's chain (what it serves, up
to the customer, and what it depends on, down to the suppliers) or the requirements of one product at one place.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..model.common import Out
from .result import Peg, PlanResult, Requirement

DEPTH = 6        # levels followed each way (the pegging tree on the page shows as many)


class PlanTrace(Out):
    requirements: list[Requirement]
    pegs: list[Peg]


@dataclass
class TraceIndex:
    requirement: dict[str, Requirement] = field(default_factory=dict)
    by_supply: dict[str, list[Peg]] = field(default_factory=lambda: defaultdict(list))
    by_requirement: dict[str, list[Peg]] = field(default_factory=lambda: defaultdict(list))
    by_parent: dict[str, list[Requirement]] = field(default_factory=lambda: defaultdict(list))
    at: dict[tuple[str, str], list[Requirement]] = field(default_factory=lambda: defaultdict(list))


def index(plan: PlanResult) -> TraceIndex:
    ix = TraceIndex()
    for r in plan.requirements:
        ix.requirement[r.id] = r
        ix.at[(r.location, r.product)].append(r)
        if r.parent_order:
            ix.by_parent[r.parent_order].append(r)
    for p in plan.pegs:
        ix.by_supply[p.supply_id].append(p)
        ix.by_requirement[p.requirement_id].append(p)
    return ix


def trace(ix: TraceIndex, order: str | None = None, location: str | None = None,
          product: str | None = None) -> PlanTrace:
    """``order``'s chain both ways, ``DEPTH`` levels each; or the requirements of ``product`` at ``location`` and
    the pegs that cover them."""
    reqs: dict[str, Requirement] = {}
    pegs: dict[int, Peg] = {}

    def serves(supply: str, depth: int, seen: set[str]) -> None:
        for p in ix.by_supply.get(supply, ()):
            pegs[id(p)] = p
            r = ix.requirement.get(p.requirement_id)
            if r is None:
                continue
            reqs[r.id] = r
            if r.parent_order and depth < DEPTH and r.parent_order not in seen:
                serves(r.parent_order, depth + 1, seen | {r.parent_order})

    def needs(oid: str, depth: int, seen: set[str]) -> None:
        for r in ix.by_parent.get(oid, ()):
            reqs[r.id] = r
            for p in ix.by_requirement.get(r.id, ()):
                pegs[id(p)] = p
                if p.supply_kind == "order" and depth < DEPTH and p.supply_id not in seen:
                    needs(p.supply_id, depth + 1, seen | {p.supply_id})

    if order:
        serves(order, 0, {order})
        needs(order, 0, {order})
    elif location and product:
        for r in ix.at.get((location, product), ()):
            reqs[r.id] = r
            for p in ix.by_requirement.get(r.id, ()):
                pegs[id(p)] = p
    return PlanTrace(requirements=list(reqs.values()), pegs=list(pegs.values()))
