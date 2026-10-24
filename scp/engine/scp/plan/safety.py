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


def safety_factor(fill_rate: bool, target: float, sigma: float, order_qty: float) -> float:
    """The multiple of σ a target needs: z(α) for a cycle-service level; for a fill rate β the k with
    σ·G(k) = (1 − β)·Q, which depends on σ, so on how many days of demand the buffer covers."""
    if not fill_rate:
        return _N.inv_cdf(target)
    if sigma <= 0:
        return 0.0
    return k_for_fill_rate((1.0 - target) * max(order_qty, 1e-9) / sigma)


def buffer(fill_rate: bool, target: float, sigma: float, order_qty: float) -> float:
    """Safety stock for demand over the exposure with standard deviation ``sigma``."""
    return max(0.0, safety_factor(fill_rate, target, sigma, order_qty) * sigma)


def _gamma_ss(fill_rate: bool, target: float, mu: float, sigma: float, order_qty: float) -> float:
    """The reorder level s over the mean for demand over the exposure spread as a gamma with mean μ and standard
    deviation σ (Silver, Pyke & Thomas §6.10, for lumpy demand): shape k = μ²/σ², scale θ = σ²/μ. A cycle service
    level α puts s at the α-quantile; a fill rate β at the s whose expected shortage per cycle,
    μ·(1 − F(s; k + 1)) − s·(1 − F(s; k)), is (1 − β)·Q."""
    from scipy.stats import gamma
    k, theta = (mu / sigma) ** 2, sigma ** 2 / mu
    if not fill_rate:
        return float(gamma.ppf(target, k, scale=theta)) - mu

    def short(r: float) -> float:
        return mu * float(gamma.sf(r, k + 1, scale=theta)) - r * float(gamma.sf(r, k, scale=theta))
    want = (1.0 - target) * max(order_qty, 1e-9)
    lo, hi = 0.0, mu + 50 * sigma
    if short(lo) <= want:
        return -mu
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if short(mid) > want else (lo, mid)
    return hi - mu


def _poisson_ss(fill_rate: bool, target: float, mu: float, order_qty: float) -> float:
    """The same for a slow mover sold a few at a time: demand over the exposure is Poisson with mean μ (its variance
    is μ, whatever the CV says). s is the smallest whole number with P(X ≤ s) ≥ α, or with expected shortage per
    cycle Σ_{x > s} (x − s)·p(x) ≤ (1 − β)·Q."""
    from scipy.stats import poisson
    if not fill_rate:
        return float(poisson.ppf(target, mu)) - mu
    want = (1.0 - target) * max(order_qty, 1e-9)
    r, below, cdf_mass = 0, 0.0, 0.0     # Σ_{x ≤ r} (r − x)·p(x), Σ_{x ≤ r} p(x)
    while True:
        cdf_mass += float(poisson.pmf(r, mu))
        if mu - r + below <= want + 1e-12 or r > mu + 50 * math.sqrt(mu) + 50:
            return r - mu
        r += 1
        below += cdf_mass


def statistical_ss(policy: SafetyStockPolicy, x: SSInputs) -> SSResult:
    s = sigma_lt(policy, x)
    mu = x.mean_daily * max(0.0, x.lead_time_days + policy.review_period_days)
    fill = policy.method is SafetyStockMethod.FILL_RATE
    if policy.distribution != "normal" and mu > 0 and policy.method in (SafetyStockMethod.SERVICE_LEVEL,
                                                                          SafetyStockMethod.FILL_RATE):
        what = f"{'β' if fill else 'α'}={x.service_level:.3f}"
        if policy.distribution == "poisson":
            ss = max(0.0, _poisson_ss(fill, x.service_level, mu, x.order_qty))
            return SSResult(ss, f"{what}; demand over L+R Poisson with mean {mu:.2f} → s={mu + ss:.0f}")
        if s > 0:
            ss = max(0.0, _gamma_ss(fill, x.service_level, mu, s, x.order_qty))
            return SSResult(ss, f"{what}; demand over L+R gamma with mean {mu:.2f}, σ {s:.2f} (CV {s / mu:.2f}) "
                                f"→ s={mu + ss:.2f}")
        return SSResult(0.0, "σ_LT = 0: no uncertainty, no safety stock")
    if policy.method is SafetyStockMethod.SERVICE_LEVEL:
        z = safety_factor(False, x.service_level, s, x.order_qty)
        return SSResult(max(0.0, z * s),
                        f"α={x.service_level:.3f} → z={z:.3f}; σ_LT={s:.2f} (d̄={x.mean_daily:.2f}/d, "
                        f"L+R={x.lead_time_days + policy.review_period_days:.1f} d, σ_L={x.lead_time_std_days:.1f} d)")
    if policy.method is SafetyStockMethod.FILL_RATE:
        if s <= 0:
            return SSResult(0.0, "σ_LT = 0: no uncertainty, no safety stock")
        q = max(x.order_qty, 1e-9)
        k = safety_factor(True, x.service_level, s, q)
        return SSResult(max(0.0, k * s),
                        f"β={x.service_level:.3f}, Q≈{q:.1f} → k={k:.3f}; σ_LT={s:.2f}")
    raise ValueError(policy.method)
