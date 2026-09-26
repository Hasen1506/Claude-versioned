"""Detailed-scheduling settings (blueprint §7, S/4 guide §8 PP-DS): the sequence-dependent
changeover matrix and the rules the finite scheduler uses to sequence released make orders."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .common import Model, Ref, Unit


class Changeover(Model):
    """Setup time when a resource switches from one setup group to another (≈ PP-DS setup matrix).

    ``resource`` empty = applies to every resource; a resource-specific entry wins."""

    resource: str | None = Ref("resource", default=None)
    from_group: str = Field(min_length=1, max_length=40)
    to_group: str = Field(min_length=1, max_length=40)
    hours: float = Unit("hours", le=500)

    @model_validator(mode="after")
    def _distinct(self) -> Changeover:
        if self.from_group == self.to_group:
            raise ValueError("a changeover goes between two different setup groups "
                             "(same-group setups use minor_setup_factor)")
        return self


class ScheduleSettings(Model):
    horizon_days: int = Unit("days", ge=1, le=365, default=42,
                             description="Schedule make orders whose planned start falls inside this window")
    day_start_hour: float = Unit("hours", le=23, default=6.0,
                                 description="Clock hour the first shift starts on a working day")
    minor_setup_factor: float = Unit(
        "fraction", le=1, default=0.2,
        description="Setup within the same setup group (another product) as a share of the full setup")
    tardiness_weight: float = Unit("ratio", le=1000, default=4.0,
                                   description="Objective weight per hour an order finishes late "
                                               "(4 = an hour late costs as much as four hours of changeover)")
    setup_weight: float = Unit("ratio", le=1000, default=1.0,
                               description="Objective weight per hour of changeover")
    earliness_weight: float = Unit("ratio", le=1000, default=0.0,
                                   description="Objective weight per hour an order finishes before it is due (stock "
                                               "built early); above 0, orders may be held back to start just in time")
    makespan_weight: float = Unit("ratio", le=1000, default=0.0,
                                  description="Objective weight per hour until the last order in the window finishes")
    profile: str = Field("balanced", max_length=40,
                         description="The scheduling profile these settings came from (a label; the settings rule)")
    start_rule: Literal["edd", "spt", "slack", "campaign", "backward"] = Field(
        "edd", description="How the first sequence is built: earliest due date, shortest job first, least slack, "
                           "campaigns by setup group, or backward from the due date (just in time)")
    optimizer: bool = Field(False, description="Search for a better machine choice and sequence with a constraint "
                                               "solver (CP-SAT), then time it on the shift calendar; never worse than "
                                               "the dispatching rule and local search")
    backward_buffer_days: float = Unit("days", le=30, default=1.0,
                                       description="Backward (just in time): start this many days before the latest "
                                                   "start, as a buffer against queues on shared machines")
    frozen_days: int = Unit("days", ge=0, le=60, default=0,
                            description="Frozen zone: orders already dated by the schedule that start within this "
                                        "many days keep their place and machine; only later orders are resequenced")
    wait_for_parts: bool = Field(True, description="A step starts only once the parts it uses are there: from stock, "
                                                   "a receipt, or the order that makes them (along the pegging)")
    improve: bool = Field(True, description="Improve the first sequence by campaign / swap local search")
    time_limit_seconds: float = Unit("seconds", gt=0, le=120, default=4.0,
                                     description="Search time budget: the local search gets this much, and the optimiser as much again")
