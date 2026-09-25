"""Demand Driven MRP buffer sizing (Ptak & Smith, *Demand Driven Material Requirements Planning*).

For a buffered (strategically decoupled) position:

    yellow      = ADU · DLT
    red base    = ADU · DLT · LTF          red safety = red base · VF          red = base + safety
    green       = max(ADU · order cycle, ADU · DLT · LTF, minimum order quantity)
    TOR = red   TOY = TOR + yellow         TOG = TOY + green

ADU is the average daily usage, DLT the *decoupled* lead time (the longest unbuffered cumulative
path back to the previous buffer or a supplier), LTF the lead-time factor (short DLT → larger
factor) and VF the variability factor. Replenishment is signalled by the net flow position

    NFP = on hand + open supply − qualified demand   (due today + spikes inside the DLT)

and an order of TOG − NFP is recommended whenever NFP ≤ TOY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..model import InventorySettings

Zone = Literal["red", "yellow", "green", "over"]
Band = Literal["short", "medium", "long", "low", "high"]


@dataclass
class Buffer:
    adu: float
    dlt: float
    ltf: float
    lt_band: Literal["short", "medium", "long"]
    vf: float
    var_band: Literal["low", "medium", "high"]
    red_base: float
    red_safety: float
    red: float
    yellow: float
    green: float
    tor: float
    toy: float
    tog: float


def lead_time_factor(dlt: float, s: InventorySettings) -> tuple[float, Literal["short", "medium", "long"]]:
    if dlt <= s.lt_short_days:
        return s.ltf_short, "short"
    if dlt <= s.lt_long_days:
        return s.ltf_medium, "medium"
    return s.ltf_long, "long"


def variability_factor(cv_weekly: float, s: InventorySettings) -> tuple[float, Literal["low", "medium", "high"]]:
    if cv_weekly <= s.cv_low:
        return s.vf_low, "low"
    if cv_weekly <= s.cv_high:
        return s.vf_medium, "medium"
    return s.vf_high, "high"


def size(adu: float, dlt: float, cv_weekly: float, moq: float, s: InventorySettings) -> Buffer:
    ltf, lb = lead_time_factor(dlt, s)
    vf, vb = variability_factor(cv_weekly, s)
    red_base = adu * dlt * ltf
    red_safety = red_base * vf
    red = red_base + red_safety
    yellow = adu * dlt
    green = max(adu * s.order_cycle_days, adu * dlt * ltf, moq)
    return Buffer(adu, dlt, ltf, lb, vf, vb, red_base, red_safety, red, yellow, green,
                  red, red + yellow, red + yellow + green)


def zone(nfp: float, b: Buffer) -> Zone:
    if nfp <= b.tor:
        return "red"
    if nfp <= b.toy:
        return "yellow"
    if nfp <= b.tog:
        return "green"
    return "over"


def order_qty(nfp: float, b: Buffer) -> float:
    return max(0.0, b.tog - nfp) if nfp <= b.toy else 0.0
