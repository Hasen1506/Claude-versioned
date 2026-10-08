"""Example cases (roadmap H): fictional teaching datasets with a story and ready-made what-if scenarios.

A case is one of the bundled examples (``scp/examples/<name>.json``) plus what a class needs to use it: a short brief
and the scenarios that go with it, which the what-if page offers in one click. Everything in a case is invented; it is
labelled as an example case wherever it is shown and is never real company data.
"""
from __future__ import annotations

from .model.common import Out
from .whatif import AddShiftChip, LaneDelayChip, LeadTimeChip, ScenarioIn

CASE_LABEL = "Example case (fictional, not real company data)"


class CaseInfo(Out):
    example: str                      # the example dataset's name
    company_name: str                 # the dataset's settings.company_name: how the web client recognises it
    title: str
    label: str = CASE_LABEL
    brief: str
    questions: list[str] = []
    scenarios: list[ScenarioIn]       # the what-if presets; the first is the baseline


_MONSOON = [LaneDelayChip(days=6, location="PORT-MAA"), LeadTimeChip(days=10, supplier="SUP-SEAL-IMPORT")]

CASES: dict[str, CaseInfo] = {c.example: c for c in [
    CaseInfo(
        example="chennai_port_pumps",
        company_name="Example case: Coromandel Pumps, Chennai (fictional)",
        title="DMSC case: a Chennai pump maker and the north-east monsoon",
        brief=("Coromandel Pumps (invented for this case) assembles farm pumps and export pumps at Sriperumbudur. "
               "Farm pumps go to Tamil Nadu dealers by truck; export pumps leave through the Chennai port yard for "
               "Jebel Ali and Singapore, and the mechanical seals in every pump arrive from overseas through the "
               "same port. In the north-east monsoon (October to December) heavy rain and swell slow the port: "
               "here, six more days through the port yard and ten more on imported seals."),
        questions=["How many points of on-time service does the monsoon cost, and which customers lose them?",
                   "Does a third shift on the assembly line buy that service back? Why, or why not?",
                   "What would you change before October: more seals in stock, an earlier export cut-off, a second "
                   "seal supplier? Try it in the data and compare again."],
        scenarios=[ScenarioIn(label="Baseline"),
                   ScenarioIn(label="Monsoon at the port", chips=_MONSOON),
                   ScenarioIn(label="Monsoon + third shift", chips=[*_MONSOON, AddShiftChip(resource="ASM-LINE")])],
    ),
]}
