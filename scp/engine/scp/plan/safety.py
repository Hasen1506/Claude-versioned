"""Safety-stock policies (blueprint §5).

Notation: d̄ mean daily demand, σ_d std of daily demand, L replenishment lead time (days),
R review period (days), σ_L lead-time std (days).

* service_level (α, cycle service level):  SS = z(α) · √((L + R)·σ_d² + d̄²·σ_L²)
* fill_rate (β):  find k with σ_LT·G(k) = (1 − β)·Q, SS = max(0, k·σ_LT),
  G(k) = φ(k) − k·(1 − Φ(k)) the standard normal loss function, σ_LT the same root term.
* days_of_supply: SS(t) = requirements in [t, t + days) — the buffer breathes with demand.

``demand_cv`` is the coefficient of variation of WEEKLY demand (forecast error). Assuming
independent days, σ_d = cv · (7·d̄) / √7 = cv · d̄ · √7.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from ..model import SafetyStockMethod, SafetyStockPolicy

_N = NormalDist()


def loss(k: float) -> float:
    """Standard normal first-order loss function G(k) = E[(Z − k)⁺]."""
    return _N.pdf(k) - k * (1.0 - _N.cdf(k))


def k_for_fill_rate(target_loss: float) -> float:
    """Solve G(k) = target_loss by bisection (G is strictly decreasing)."""
    lo, hi = -6.0, 8.0
    if target_loss >= loss(lo):
        return lo
    if target_loss <= loss(hi):
        return hi
    for _ in range(100):
        mid = (lo + hi) / 2
        if loss(mid) > target_loss:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


@dataclass
class SSInputs:
    mean_daily: float
    lead_time_days: float
    lead_time_std_days: float
    service_level: float
    order_qty: float  # typical lot, for fill_rate


@dataclass
class SSResult:
    qty: float
    explanation: str


def sigma_lt(policy: SafetyStockPolicy, x: SSInputs) -> float:
    cv = policy.demand_cv or 0.0
    sd_daily = cv * x.mean_daily * math.sqrt(7.0)
    exposure = max(0.0, x.lead_time_days + policy.review_period_days)
    return math.sqrt(exposure * sd_daily ** 2 + (x.mean_daily * x.lead_time_std_days) ** 2)


def statistical_ss(policy: SafetyStockPolicy, x: SSInputs) -> SSResult:
    s = sigma_lt(policy, x)
    if policy.method is SafetyStockMethod.SERVICE_LEVEL:
        z = _N.inv_cdf(x.service_level)
        return SSResult(max(0.0, z * s),
                        f"α={x.service_level:.3f} → z={z:.3f}; σ_LT={s:.2f} (d̄={x.mean_daily:.2f}/d, "
                        f"L+R={x.lead_time_days + policy.review_period_days:.1f} d, σ_L={x.lead_time_std_days:.1f} d)")
    if policy.method is SafetyStockMethod.FILL_RATE:
        if s <= 0:
            return SSResult(0.0, "σ_LT = 0: no uncertainty, no safety stock")
        q = max(x.order_qty, 1e-9)
        k = k_for_fill_rate((1.0 - x.service_level) * q / s)
        return SSResult(max(0.0, k * s),
                        f"β={x.service_level:.3f}, Q≈{q:.1f} → k={k:.3f}; σ_LT={s:.2f}")
    raise ValueError(policy.method)
