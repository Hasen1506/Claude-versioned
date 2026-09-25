"""End-to-end scenarios with hand-derived answers (see :mod:`.harness`)."""
from __future__ import annotations

from .harness import (
    Check, Client, ClientError, EngineClient, Scenario, ScenarioInfo, ScenarioReport, StepReport,
)
from .s1_coffee import SCENARIO as S1
from .s2_kettles import SCENARIO as S2
from .s3_bikes import SCENARIO as S3
from .s4_grocer import SCENARIO as S4
from .s5_paints import SCENARIO as S5
from .s6_tents import SCENARIO as S6
from .s7_bakery import SCENARIO as S7
from .s8_golive import SCENARIO as S8

SCENARIOS: list[Scenario] = [S1, S2, S3, S4, S5, S6, S7, S8]
BY_ID: dict[str, Scenario] = {s.id: s for s in SCENARIOS}

__all__ = ["BY_ID", "Check", "Client", "ClientError", "EngineClient", "SCENARIOS", "Scenario", "ScenarioInfo", "ScenarioReport",
           "StepReport"]
