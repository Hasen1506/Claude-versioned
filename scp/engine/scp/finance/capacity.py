"""Capacity investment appraisal: what the S&OP plan saves with more hours, and whether that pays back.

Two estimates of the saving, which agree while the added hours stay inside each bucket's valid range:
the dual estimate Σ shadow price × added hours (free: it comes with the base solve), and the exact saving
from re-solving the S&OP LP with the option's hours added (``SopSettings.capacity_add_hours_per_week``).
The NPV uses the cash effect of the re-solve — Δ(revenue − purchase − production − transport − holding −
overtime) — annualised over the S&OP horizon; penalties for late or lost demand are planning weights, not cash.
"""
from __future__ import annotations

from ..model import CapacityOption, Dataset
from ..sop import SopResult, run_sop
from .result import BucketValue, CapacityAppraisal

CASH = ("purchase", "production", "transport", "holding", "overtime")


def objective(r: SopResult) -> float:
    """The LP objective the duals refer to (minimised)."""
    assert r.economics is not None
    return -r.economics.profit if r.mode.value == "profit" else r.economics.total_cost


def cash(r: SopResult) -> float:
    e = r.economics
    assert e is not None
    return e.revenue - sum(getattr(e, c) for c in CASH)


def npv(flows: list[float], rate: float) -> float:
    return sum(f / (1.0 + rate) ** y for y, f in enumerate(flows))


def irr(flows: list[float]) -> float | None:
    """The rate at which the NPV is zero (bisection on [−99 %, 1000 %]); None when the flows never change sign."""
    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(flows, lo), npv(flows, hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(flows, mid)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def with_hours(ds: Dataset, resource: str, hours: float) -> Dataset:
    d = ds.model_dump(mode="json")
    add = d["sop"].setdefault("capacity_add_hours_per_week", {})
    add[resource] = add.get(resource, 0.0) + hours
    return Dataset.model_validate(d)


def appraise(ds: Dataset, base: SopResult, opt: CapacityOption) -> CapacityAppraisal:
    rate = ds.finance.discount_rate if ds.finance.discount_rate is not None else ds.settings.wacc
    horizon = sum(b.days for b in base.buckets)
    line = next((r for r in base.resources if r.resource == opt.resource), None)
    buckets: list[BucketValue] = []
    dual = 0.0
    within = True
    for b in base.buckets:
        added = opt.added_hours_per_week * b.days / 7.0
        sp = line.shadow_price[b.index] if line else 0.0
        cap = line.capacity[b.index] if line else 0.0
        up = line.valid_up[b.index] if line else None
        # a non-binding row's shadow price (zero) holds for any increase
        head = None if up is None or abs(sp) <= 1e-9 else max(0.0, up - cap)
        est = sp * (added if head is None else min(added, head))
        if head is not None and added > head + 1e-9 and abs(sp) > 1e-9:
            within = False
        dual += est
        buckets.append(BucketValue(bucket=b.index, label=b.label, capacity=cap, added=added, shadow_price=sp,
                                   valid_headroom=head, estimate=est))
    after = run_sop(with_hours(ds, opt.resource, opt.added_hours_per_week))
    if not after.ok or after.economics is None:
        saving = delta = 0.0
        fill_after = base.kpis.fill_rate if base.kpis else 0.0
    else:
        saving = objective(base) - objective(after)
        delta = cash(after) - cash(base)
        fill_after = after.kpis.fill_rate if after.kpis else 0.0
    annual = delta * 365.0 / horizon if horizon else 0.0
    net = annual - opt.fixed_cost_per_year
    flows = [-opt.capex] + [net] * opt.life_years
    payback = opt.capex / net if net > 0 else None
    return CapacityAppraisal(
        id=opt.id, name=opt.name or opt.id, resource=opt.resource, added_hours_per_week=opt.added_hours_per_week,
        capex=opt.capex, fixed_cost_per_year=opt.fixed_cost_per_year, life_years=opt.life_years, discount_rate=rate,
        horizon_days=horizon, dual_estimate=dual, within_range=within, objective_saving=saving, cash_delta=delta,
        fill_rate_before=base.kpis.fill_rate if base.kpis else 0.0, fill_rate_after=fill_after,
        annual_cash=annual, annual_net=net, npv=npv(flows, rate), irr=irr(flows) if opt.capex > 0 else None,
        payback_years=payback if payback is None or payback <= opt.life_years * 10 else None,
        cash_flows=flows, buckets=buckets)
