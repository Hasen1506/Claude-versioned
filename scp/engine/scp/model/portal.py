"""What suppliers tell us without a planner typing it (Enterprise 7.2): the dispatch advice a supplier sends when goods
leave them (≈ S/4 inbound delivery from an advanced shipping notification, a UBL DespatchAdvice, an EDI DESADV)."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import Field

from .common import Model, Ref, Unit


class NoticeLine(Model):
    order: str = Field(min_length=1, max_length=64, description="The purchase order line it ships")
    product: str = Ref("product")
    qty: float = Unit("qty", gt=0)
    batch: str | None = Field(None, max_length=40, description="The supplier's batch, for products kept in batches")
    expires_on: dt.date | None = None


class ShippingNotice(Model):
    """Goods on their way from a supplier: they arrive on ``arrives_on`` and are received against the notice."""

    id: str = Field(min_length=1, max_length=20)
    supplier: str = Ref("location")
    reference: str = Field("", max_length=64, description="Their dispatch note or lorry receipt number")
    shipped_on: dt.date
    arrives_on: dt.date
    lines: list[NoticeLine] = Field(min_length=1, max_length=200)
    source: Literal["portal", "message", "entered"] = "entered"
    received_on: dt.date | None = None
    cancelled: bool = False
    note: str = Field("", max_length=400)
