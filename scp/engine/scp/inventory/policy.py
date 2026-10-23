"""Inventory policy, one table (Enterprise 8.2; docs/CONFORMANCE.md §1).

Every product kept at a place, read the way the textbooks set a policy (Silver, Pyke & Thomas ch. 4–7): its class by
annual usage value (ABC) and by the variability its safety stock is sized with (XYZ); the review (continuous or every
R days); the rule — reorder point with a fixed quantity (s, Q), reorder point up to a maximum (s, S), time-phased MRP
or a DDMRP buffer; the service target and where it comes from, beside the one its ABC-XYZ cell suggests; the safety
stock the policy holds, the reorder point set and the one the numbers suggest (s = d̄·(L + R) + SS); and the service
achieved: the share of its customer orders shipped from the place that were delivered in full by the requested date.

The numbers are the planner's own: the demand rate, its variance, the lead time and its spread, the lot and the
safety stock come from the functions supply planning and inventory optimisation use (scp.plan.rates), so this page
can never show a safety stock the plan does not hold.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date

from pydantic import Field

from ..demand.pipeline import service_level as cell_service_level
from ..model import LocationType, LotSizePolicy, MrpType, SafetyStockMethod
from ..model.common import Out
from ..model.dataset import Dataset
from ..model.master import review_days as first_review
from ..network import build_graph
from ..plan import costing
from ..plan.leadtime import lead_time_std_days, nominal_lead_time_days
from ..plan.safety import SSInputs, sigma_lt, statistical_ss
from ..plan.rates import bucket_days, horizon_flows, node_role, policy_safety_stock, typical_lot
from ..time import Buckets
from ..tower.kpis import Kpis
from ..validate import Issue, has_errors, validate

EPS = 1e-9
LUMPY = 0.5   # CV of demand over the lead time above which a normal spread is a poor fit (Silver, Pyke & Thomas §6.10)

RULES = {
    "sQ": "Reorder point, fixed quantity (s, Q)",
    "sS": "Reorder point, order up to (s, S)",
    "RsQ": "Periodic review, reorder point, fixed quantity (R, s, Q)",
    "RsS": "Periodic review, order up to (R, s, S)",
    "mrp": "Time-phased (MRP)",
    "ddmrp": "DDMRP buffer",
    "none": "Not replenished",
}
CV_FROM = {"policy": "set on the product", "pooled": "from the demand it feeds", "default": "company default",
           "none": "no demand"}


class PolicyRow(Out):
    location: str
    product: str
    abc: str                              # by annual usage value at the place
    xyz: str | None                       # by weekly CV; None: no demand
    cv: float | None                      # weekly coefficient of variation the safety stock is sized with
    cv_from: str
    usage_value: float                    # a year's demand at its unit value
    rule: str                             # RULES key
    rule_label: str
    lot: str                              # lot-sizing rule code (L4L, FIXED, EOQ, …)
    order_qty: float | None               # Q: what one order typically is
    order_up_to: float | None             # S: the maximum stock a min-max lot fills to
    review_days: float                    # R; 0: continuous
    next_review: date | None = None       # on a review calendar: the first review day from the plan start
    method: str                           # safety-stock method
    distribution: str = "normal"          # how a target reads demand over L + R: normal | gamma | poisson
    exposure_cv: float | None = None      # CV of demand over L + R, the spread the safety stock covers
    target: float | None                  # service target (None: the method sets no target)
    target_kind: str                      # "cycle" (chance of no stock-out in a cycle) | "fill" (share of demand met) | ""
    target_from: str                      # "product" | "company" | ""
    suggested: float | None               # the ABC-XYZ cell's service level
    mean_daily: float
    lead_time_days: float
    lead_time_std_days: float
    safety_stock: float
    safety_stock_value: float
    reorder_point: float | None
    suggested_reorder_point: float | None
    on_hand: float
    cover_days: float | None
    orders: int                           # closed customer orders shipped from here in the KPI window
    served: int                           # of them, delivered in full by the requested date
    achieved: float | None
    notes: list[str] = Field(default_factory=list)


class PolicyCell(Out):
    cell: str                             # "AX" … "CZ", or "A–" when no demand was measured
    rows: int
    safety_stock_value: float
    suggested: float | None
    targets: list[float]                  # the distinct targets its rows have
    orders: int
    served: int
    achieved: float | None


class PolicyView(Out):
    ok: bool
    currency: str
    window_days: int
    issues: list[Issue] = Field(default_factory=list)
    rows: list[PolicyRow] = Field(default_factory=list)
    cells: list[PolicyCell] = Field(default_factory=list)
    safety_stock_value: float = 0.0
    below_suggestion: int = 0             # rows whose cycle service target is below their cell's suggestion
    reorder_off: int = 0                  # reorder-point rows whose s is more than 10 % from the suggestion
    short_of_target: int = 0              # rows whose achieved service is below the target


def _rule(lp) -> str:
    if lp.mrp_type is MrpType.NONE:
        return "none"
    if lp.mrp_type is MrpType.DDMRP:
        return "ddmrp"
    if lp.mrp_type is MrpType.REORDER_POINT:
        rule = "sS" if lp.lot_sizing.policy is LotSizePolicy.MIN_MAX else "sQ"
        return "R" + rule if lp.reorder_point is not None and lp.safety_stock.review_period_days >= 0.5 else rule
    return "mrp"


def _xyz(cv: float | None, x: float, y: float) -> str | None:
    if cv is None:
        return None
    return "X" if cv < x else "Y" if cv < y else "Z"


def policy_view(ds: Dataset) -> PolicyView:
    s = ds.settings
    view = PolicyView(ok=False, currency=s.currency, window_days=ds.tower.kpi_window_days)
    view.issues = validate(ds)
    if has_errors(view.issues):
        return view
    g = build_graph(ds)
    val = costing.roll_up(ds, g)
    flow = horizon_flows(ds, g)
    per_bucket = bucket_days(ds, len(Buckets(s)))
    fs = ds.forecasting

    # customer orders shipped from each place, as the OTIF figures count them
    k = Kpis(ds)
    served: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for c in k.closed:
        if c.kind != "sales" or not c.counterparty:
            continue
        x = served[(c.counterparty, c.product)]
        x[0] += 1
        if k._in_full(c) and c.last_delivery is not None and c.last_delivery <= c.due_date:
            x[1] += 1

    kept = [lp for lp in ds.location_products
            if ds.location_type(lp.location) is not LocationType.CUSTOMER and node_role(ds, (lp.location, lp.product)) == "stocking"]
    usage = {(lp.location, lp.product): flow.mean.get((lp.location, lp.product), 0.0) * 365.0
             * val.unit_value.get((lp.location, lp.product), 0.0) for lp in kept}
    total = sum(usage.values())
    abc: dict[tuple[str, str], str] = {}
    cum = 0.0
    for key, v in sorted(usage.items(), key=lambda kv: (-kv[1], kv[0])):
        before = cum / total if total > EPS else 1.0
        cum += v
        abc[key] = "A" if before < fs.abc_a else "B" if before < fs.abc_b else "C"

    for lp in kept:
        n = (lp.location, lp.product)
        opts = g.options.get(n) or []
        lt = (nominal_lead_time_days(ds, opts[0]) or 0.0) if opts else 0.0
        lt_sd = lead_time_std_days(ds, opts[0]) if opts else 0.0
        mean, var = flow.mean.get(n, 0.0), flow.var.get(n, 0.0)
        uv = val.unit_value.get(n, 0.0)
        cv = math.sqrt(var * 7.0) / (mean * 7.0) if mean > EPS else None
        xyz = _xyz(cv, fs.xyz_x, fs.xyz_y)
        pol = policy_safety_stock(ds, g, n, mean_daily=mean, lead_time=lt, lead_time_std=lt_sd, unit_value=uv,
                                  days_per_bucket=per_bucket)
        m = lp.safety_stock.method
        statistical = m in (SafetyStockMethod.SERVICE_LEVEL, SafetyStockMethod.FILL_RATE)
        target = (lp.safety_stock.service_level or s.default_service_level) if statistical else None
        rule = _rule(lp)
        review = lp.safety_stock.review_period_days
        q = typical_lot(ds, g, n, mean, uv, per_bucket) if mean > EPS else None
        notes: list[str] = []
        suggested_s = None
        if rule in ("sQ", "sS", "RsQ", "RsS") and mean > EPS:
            suggested_s = mean * (lt + review) + pol.qty
            if lp.reorder_point is not None and abs(lp.reorder_point - suggested_s) > 0.1 * suggested_s:
                notes.append("the reorder point is more than 10 % from what the demand, lead time and safety stock "
                             "suggest")
        if rule == "mrp" and review >= 0.5:
            notes.append("the review period widens the safety stock, but time-phased MRP orders whenever it is short: "
                         "put it on a reorder point to order on review days only")
        if m is SafetyStockMethod.NONE and rule != "none" and mean > EPS:
            notes.append("no safety stock: every late delivery or demand above the forecast is a shortage")
        cv_e = None
        if statistical and mean > EPS:
            mu = mean * max(0.0, lt + review)
            cv_e = sigma_lt(lp.safety_stock, SSInputs(mean, lt, lt_sd, 0.0, 0.0)) / mu if mu > EPS else None
            dist = lp.safety_stock.distribution
            if dist == "normal" and cv_e is not None and cv_e > LUMPY:
                alt = statistical_ss(lp.safety_stock.model_copy(update={"distribution": "gamma"}),
                                     SSInputs(mean, lt, lt_sd, target or 0.0, q or 0.0)).qty
                notes.append(f"its demand over the lead time varies widely (CV {cv_e:.2f}), which a normal spread fits "
                             f"poorly: spread as a gamma, the target needs {alt:,.0f} instead of {pol.qty:,.0f}")
        if flow.cv_source.get(n) == "default" and statistical:
            notes.append("its demand variability is the company default, not measured")
        o, ok = served.get(n, [0, 0])
        achieved = ok / o if o else None
        suggested = cell_service_level(fs, abc[n], xyz) if xyz else None
        view.rows.append(PolicyRow(
            location=lp.location, product=lp.product, abc=abc[n], xyz=xyz, cv=cv,
            cv_from=CV_FROM.get(flow.cv_source.get(n, "none"), ""), usage_value=usage[n], rule=rule,
            rule_label=RULES[rule], lot=lp.lot_sizing.policy.value if lp.lot_sizing.policy else s.default_lot_policy.value,
            order_qty=q, order_up_to=lp.max_stock if lp.lot_sizing.policy is LotSizePolicy.MIN_MAX else None,
            review_days=review, method=m.value, distribution=lp.safety_stock.distribution, exposure_cv=cv_e,
            next_review=(first_review(lp.safety_stock.review_from, review, s.planning_start)[0]
                         if rule[0] == "R" else None), target=target,
            target_kind="fill" if m is SafetyStockMethod.FILL_RATE else "cycle" if statistical else "",
            target_from=("product" if lp.safety_stock.service_level else "company") if statistical else "",
            suggested=suggested, mean_daily=mean, lead_time_days=lt, lead_time_std_days=lt_sd,
            safety_stock=pol.qty, safety_stock_value=pol.qty * uv, reorder_point=lp.reorder_point,
            suggested_reorder_point=suggested_s, on_hand=lp.on_hand,
            cover_days=lp.on_hand / mean if mean > EPS else None, orders=o, served=ok, achieved=achieved, notes=notes))

    cells: dict[str, list[PolicyRow]] = defaultdict(list)
    for r in view.rows:
        cells[r.abc + (r.xyz or "–")].append(r)
    for cell, rows in sorted(cells.items()):
        o = sum(r.orders for r in rows)
        ok = sum(r.served for r in rows)
        view.cells.append(PolicyCell(
            cell=cell, rows=len(rows), safety_stock_value=sum(r.safety_stock_value for r in rows),
            suggested=rows[0].suggested, targets=sorted({r.target for r in rows if r.target is not None}),
            orders=o, served=ok, achieved=ok / o if o else None))
    view.rows.sort(key=lambda r: (r.abc, r.xyz or "~", -r.usage_value, r.location, r.product))
    view.safety_stock_value = sum(r.safety_stock_value for r in view.rows)
    view.below_suggestion = sum(1 for r in view.rows if r.target_kind == "cycle" and r.suggested is not None
                                and r.target is not None and r.target < r.suggested - EPS)
    view.reorder_off = sum(1 for r in view.rows if r.reorder_point is not None and r.suggested_reorder_point
                           and abs(r.reorder_point - r.suggested_reorder_point) > 0.1 * r.suggested_reorder_point)
    view.short_of_target = sum(1 for r in view.rows if r.achieved is not None and r.target is not None
                               and r.achieved < r.target - EPS)
    view.ok = True
    return view


class PolicyError(ValueError):
    pass


def _few(names: list[str], n: int = 5) -> str:
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def _suggested_s(r: PolicyRow) -> float | None:
    """s = d̄·(L + R) + SS for the row's demand, lead time, review and safety stock (None: no demand)."""
    return r.mean_daily * (r.lead_time_days + r.review_days) + r.safety_stock if r.mean_daily > EPS else None


def apply_policy(ds: Dataset, keys: list[tuple[str, str]], *, method: str | None = None,
                 service_level: float | str | None = None, days: float | None = None, qty: float | None = None,
                 review_period_days: float | None = None, review_from: date | None = None,
                 rule: str | None = None, distribution: str | None = None,
                 reorder_point: str | None = None) -> tuple[Dataset, str]:
    """Give the products at places ``keys`` one policy (CONFORMANCE I4): a safety-stock method, a service target (a
    number, or "suggested": each its own ABC-XYZ cell's), a review period and a day reviews fall on, the rule
    ("mrp": time-phased; "reorder_point": ordered when the stock reaches s, which is then set to the suggestion), and
    the suggested reorder point. Only what is given changes; the rest of each product's policy stays. The reorder point
    is suggested from the policy as it is after the other changes: a new target or review period moves it."""
    if not keys:
        raise PolicyError("choose the products to change")
    by = {(lp.location, lp.product): i for i, lp in enumerate(ds.location_products)}
    missing = [f"{lc} {pr}" for lc, pr in keys if (lc, pr) not in by]
    if missing:
        raise PolicyError(f"there is no {missing[0]} kept at a place")
    if service_level is not None and service_level != "suggested" and not 0.5 <= float(service_level) < 1:
        raise PolicyError("a service target is from 50 % to below 100 %")
    if distribution not in (None, "normal", "gamma", "poisson"):
        raise PolicyError("demand is spread as normal, gamma or Poisson")
    if rule not in (None, "mrp", "reorder_point"):
        raise PolicyError("the rule is time-phased MRP or a reorder point")
    meth = SafetyStockMethod(method) if method else None
    if meth is SafetyStockMethod.FIXED and qty is None:
        raise PolicyError("a fixed safety stock needs its quantity")
    if meth is SafetyStockMethod.DAYS_OF_SUPPLY and not days:
        raise PolicyError("safety stock in days of cover needs the number of days")
    statistical = meth in (SafetyStockMethod.SERVICE_LEVEL, SafetyStockMethod.FILL_RATE)
    view = policy_view(ds) if service_level == "suggested" or statistical else None
    if view is not None and not view.ok:
        raise PolicyError("the data has problems that stop planning; put them right first")
    rows = {(r.location, r.product): r for r in view.rows} if view else {}
    lps = list(ds.location_products)
    said: dict[str, int] = defaultdict(int)
    skipped: dict[str, list[str]] = defaultdict(list)   # why → the products left as they were
    chosen = list(dict.fromkeys(keys))
    was = {key: lps[by[key]] for key in chosen}
    took: list[str] = []                                 # demand variability taken from the demand they feed
    for key in chosen:
        lp = lps[by[key]]
        ss = lp.safety_stock.model_dump()
        upd: dict = {}
        name = f"{lp.product} at {lp.location}"
        no_cv = False
        if statistical and ss.get("demand_cv") is None:
            # a target needs the demand's variability: the one measured from the demand it feeds, else it is left
            r = rows.get(key)
            if r is not None and r.cv is not None and r.cv_from == CV_FROM["pooled"]:
                ss["demand_cv"] = round(r.cv, 3)
                took.append(name)
            else:
                no_cv = True
                skipped["no demand variability to size a service target with"].append(name)
        if meth is not None and not no_cv:
            ss["method"] = meth.value
            if meth is SafetyStockMethod.FIXED:
                ss["qty"] = qty
            if meth is SafetyStockMethod.DAYS_OF_SUPPLY:
                ss["days"] = days
            said["method"] += 1
        by_target = SafetyStockMethod(ss["method"]) in (SafetyStockMethod.SERVICE_LEVEL, SafetyStockMethod.FILL_RATE)
        if no_cv:
            pass
        elif service_level is not None and not by_target:
            skipped["safety stock not set by a service target"].append(name)
        elif service_level == "suggested":
            r = rows.get(key)
            if r is None or r.suggested is None:
                skipped["no demand to class them by"].append(f"{lp.product} at {lp.location}")
            else:
                ss["service_level"] = r.suggested
                said["target"] += 1
        elif service_level is not None:
            ss["service_level"] = float(service_level)
            said["target"] += 1
        if distribution is not None and not no_cv:
            if SafetyStockMethod(ss["method"]) in (SafetyStockMethod.SERVICE_LEVEL, SafetyStockMethod.FILL_RATE):
                ss["distribution"] = distribution
                said["distribution"] += 1
            elif service_level is None:
                skipped["safety stock not set by a service target"].append(name)
        if review_period_days is not None:
            ss["review_period_days"] = review_period_days
            said["review"] += 1
        if review_from is not None:
            ss["review_from"] = review_from
            said["review"] += review_period_days is None
        if rule == "mrp" and lp.mrp_type is not MrpType.DETERMINISTIC:
            upd["mrp_type"] = MrpType.DETERMINISTIC.value
            said["rule"] += 1
        upd["safety_stock"] = ss
        lps[by[key]] = type(lp).model_validate({**lp.model_dump(), **upd})
    out = ds.model_copy(update={"location_products": lps})
    # the reorder point, from the policy as it now is; a product put on a reorder point gets one with the rule
    put_on = [k for k in chosen if (rule == "reorder_point" and was[k].mrp_type is not MrpType.REORDER_POINT)
              or (reorder_point == "suggested" and lps[by[k]].mrp_type is MrpType.REORDER_POINT)]
    if put_on:
        after = policy_view(out)
        if not after.ok:
            raise PolicyError("the data has problems that stop planning; put them right first")
        now = {(r.location, r.product): r for r in after.rows}
        for key in put_on:
            lp = lps[by[key]]
            sug = _suggested_s(now[key]) if key in now else None
            if sug is None:   # no reorder point to order at: the rule stays
                skipped["no demand to set a reorder point from"].append(f"{lp.product} at {lp.location}")
                continue
            if lp.mrp_type is not MrpType.REORDER_POINT:
                said["rule"] += 1
            lps[by[key]] = lp.model_copy(update={"reorder_point": round(sug, 2), "mrp_type": MrpType.REORDER_POINT})
            said["reorder"] += 1
    if reorder_point == "suggested":
        skipped["not planned by reorder point"] += [f"{lps[by[k]].product} at {lps[by[k]].location}" for k in chosen
                                                    if lps[by[k]].mrp_type is not MrpType.REORDER_POINT]
    if not any(said.values()):
        raise PolicyError("nothing to change: " + "; ".join(f"{_few(v)} ({w})" for w, v in skipped.items() if v)
                          if any(skipped.values()) else "say what to change")
    parts = [f"{v} {w}{'' if v == 1 else 's'}" for w, v in (
        ("safety-stock method", said["method"]), ("service target", said["target"]), ("review period", said["review"]),
        ("demand spread", said["distribution"]), ("rule", said["rule"]), ("reorder point", said["reorder"])) if v]
    n = len(chosen)
    msg = f"Set {', '.join(parts)} on {n} product{'' if n == 1 else 's'} at {'a place' if n == 1 else 'places'}."
    if took:
        msg += f" The demand variability is the one measured from the demand they feed for {_few(took)}."
    for why, names in skipped.items():
        if names:
            msg += f" Left as they were, {why}: {_few(names)}."
    return ds.model_copy(update={"location_products": lps}), msg


__all__ = ["PolicyCell", "PolicyError", "PolicyRow", "PolicyView", "apply_policy", "policy_view"]
