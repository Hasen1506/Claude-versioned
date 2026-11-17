"""Finance overlay settings (blueprint P9): capacity investment options to appraise against the S&OP plan."""
from __future__ import annotations

import datetime as dt
from typing import Literal
from pydantic import Field

from .common import Id, Model, Ref, Unit


class CapacityOption(Model):
    """A capacity investment (a new machine, an added shift, a line upgrade) that adds regular hours to one
    resource. Its value is what the S&OP plan saves with the hours; its NPV nets that against the spend."""

    id: Id
    name: str = ""
    resource: str = Ref("resource")
    added_hours_per_week: float = Unit("hours", gt=0, description="Extra regular hours per week the option adds")
    capex: float = Unit("money", default=0.0, description="One-off investment at year 0")
    fixed_cost_per_year: float = Unit("money", default=0.0, description="Running cost per year (crew, lease, upkeep)")
    life_years: int = Field(5, ge=1, le=50, description="Years of benefit counted in the NPV")


class FinanceSettings(Model):
    closed_through: dt.date | None = Field(None, description="Posted financial transactions on or before this date are closed")
    control_roles: dict[Literal["master_data", "planning", "purchasing", "sales", "manufacturing", "warehouse",
                                "transport", "billing", "payments", "invoice_release", "credit_release", "period_close"],
                        list[str]] = Field(default_factory=dict, max_length=12,
                                           description="Named e-mail grants. Empty: legacy member roles. When configured, "
                                                       "every operation requires its grant, including for owners and keys")
    separate_payments: bool = Field(False, description="A payer must differ from the invoice's recorded entrant and releaser")
    capacity_options: list[CapacityOption] = Field(default_factory=list)
    discount_rate: float | None = Unit("fraction", le=1, default=None,
                                       description="Per year for NPV; empty = the company WACC")
    ledgers: dict[str, str] = Field(default_factory=dict, max_length=60,
                                    description="Accounting (Enterprise 7.4): the ledger name in Tally for an account "
                                                "of the journal, by its code (STOCK, GRIR, SALES, …); empty = ours")
    tally_company: str = Field("", max_length=120, description="The company's name in Tally, for the export; empty = "
                                                               "its name here")
