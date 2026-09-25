"""Finance overlay (blueprint P9): the plan in money — reconciled costs, inventory value, cost to serve and
capacity investment appraisal."""
from __future__ import annotations

from ..model import Dataset
from ..plan import PlanResult, run_mrp
from ..sop import run_sop
from .capacity import appraise
from .ledger import cost_to_serve, inventory_value
from .result import FinanceResult

NOTES = [
    "Plan costs are the MRP plan's: purchase, production, setup, ordering, transport, handling and holding.",
    "Cost to serve follows the pegging upstream: an order's full cost includes its inputs; demand carries the "
    "pegged share. Opening stock and firm receipts consumed are shown at unit value (stock, firm), not as plan spend.",
    "Unabsorbed cost is what no demand is pegged to (lot-size excess, stock at the horizon end, inputs to firm "
    "orders); served + unabsorbed = plan, category by category.",
    "Capacity options are valued on the S&OP plan: the dual estimate from shadow prices, checked by a re-solve; "
    "the NPV uses the re-solve's cash effect annualised over the S&OP horizon.",
]


def run_finance(ds: Dataset, plan: PlanResult | None = None) -> FinanceResult:
    plan = plan or run_mrp(ds)
    out = FinanceResult(ok=plan.ok, currency=ds.settings.currency, issues=plan.issues, notes=list(NOTES))
    if not plan.ok:
        return out
    out.inventory = inventory_value(ds, plan)
    out.serve, out.reconciliation = cost_to_serve(ds, plan)
    if ds.finance.capacity_options:
        base = run_sop(ds)
        out.sop_mode = base.mode.value
        if base.ok and base.economics is not None:
            out.capacity = [appraise(ds, base, o) for o in ds.finance.capacity_options]
        else:
            out.notes.append("The S&OP plan did not solve, so capacity options could not be appraised.")
    return out


__all__ = ["FinanceResult", "run_finance"]
