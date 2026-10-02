"""A planning dataset: one self-contained document with all master and transactional data.

It is what the user imports/exports, what the API accepts, and (later) what a plan version
snapshots. Lookup helpers build id indices lazily; they never mutate the data.
"""
from __future__ import annotations

import hashlib
import json
from functools import cached_property
from typing import Any, Literal

from pydantic import Field

from .actuals import AccuracyRecord, Batch, ClosedOrder, ExecutionSettings, GoodsMovement, InventoryDoc, RolledWeek
from .common import LocationType, Model
from .finance import FinanceSettings
from .tower import TowerSettings
from .demand import DemandEvent, ForecastOverride, ForecastSettings, NpiRule
from .inventory import InventorySettings
from .purchasing import PurchaseOrder, PurchasingSettings, Vendor
from .promise import Allocation, Confirmation, PromiseSettings
from .schedule import Changeover, ScheduleSettings
from .sop import SopSettings, StockTarget
from .master import (
    Calendar, CustomerPrice, Location, LocationProduct, LotSizing, MrpGroup, Product, ProductionSource, PurchasingSource,
    Resource, Settings, TransportLane,
)
from .transactional import DemandRecord, SalesHistory, ScheduledReceipt


class Dataset(Model):
    schema_version: Literal["1"] = "1"
    settings: Settings
    calendars: list[Calendar] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    products: list[Product] = Field(default_factory=list)
    customer_prices: list[CustomerPrice] = Field(default_factory=list)
    location_products: list[LocationProduct] = Field(default_factory=list)
    mrp_groups: list[MrpGroup] = Field(default_factory=list)
    resources: list[Resource] = Field(default_factory=list)
    production_sources: list[ProductionSource] = Field(default_factory=list)
    purchasing_sources: list[PurchasingSource] = Field(default_factory=list)
    lanes: list[TransportLane] = Field(default_factory=list)
    vendors: list[Vendor] = Field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = Field(default_factory=list)
    purchasing: PurchasingSettings = Field(default_factory=PurchasingSettings)
    demand: list[DemandRecord] = Field(default_factory=list)
    receipts: list[ScheduledReceipt] = Field(default_factory=list)
    history: list[SalesHistory] = Field(default_factory=list)
    forecasting: ForecastSettings = Field(default_factory=ForecastSettings)
    events: list[DemandEvent] = Field(default_factory=list)
    npi: list[NpiRule] = Field(default_factory=list)
    overrides: list[ForecastOverride] = Field(default_factory=list)
    inventory: InventorySettings = Field(default_factory=InventorySettings)
    sop: SopSettings = Field(default_factory=SopSettings)
    stock_targets: list[StockTarget] = Field(default_factory=list)
    changeovers: list[Changeover] = Field(default_factory=list)
    scheduling: ScheduleSettings = Field(default_factory=ScheduleSettings)
    allocations: list[Allocation] = Field(default_factory=list)
    confirmations: list[Confirmation] = Field(default_factory=list)
    promising: PromiseSettings = Field(default_factory=PromiseSettings)
    movements: list[GoodsMovement] = Field(default_factory=list)
    batches: list[Batch] = Field(default_factory=list)
    inventory_docs: list[InventoryDoc] = Field(default_factory=list)
    closed_orders: list[ClosedOrder] = Field(default_factory=list)
    accuracy: list[AccuracyRecord] = Field(default_factory=list)
    rolled_weeks: list[RolledWeek] = Field(default_factory=list)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    finance: FinanceSettings = Field(default_factory=FinanceSettings)
    tower: TowerSettings = Field(default_factory=TowerSettings)

    def forecast_inputs(self) -> str:
        """A fingerprint of what a forecast is made from besides sales history: demand events, new-product rules,
        consensus overrides and the forecast settings. A release records it; a change after that is not in the plan."""
        parts = {"events": [e.model_dump(mode="json") for e in self.events],
                 "npi": [n.model_dump(mode="json") for n in self.npi],
                 "overrides": [o.model_dump(mode="json") for o in self.overrides],
                 "settings": self.forecasting.model_dump(mode="json", exclude={"released_inputs"})}
        return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]

    def model_copy(self, *, update: dict | None = None, deep: bool = False) -> Dataset:
        """A copy without the lookup indices below: pydantic copies the instance dict, cached indices included, so
        a copy with new receipts or orders would otherwise look records up in the old ones."""
        c = super().model_copy(update=update, deep=deep)
        for name in _CACHED:
            c.__dict__.pop(name, None)
        return c

    # ---- indices (first occurrence wins; duplicates are reported by the readiness gate) ----
    @cached_property
    def location_by_id(self) -> dict[str, Location]:
        return _index(self.locations)

    @cached_property
    def product_by_id(self) -> dict[str, Product]:
        return _index(self.products)

    @cached_property
    def calendar_by_id(self) -> dict[str, Calendar]:
        return _index(self.calendars)

    @cached_property
    def resource_by_id(self) -> dict[str, Resource]:
        return _index(self.resources)

    @cached_property
    def production_source_by_id(self) -> dict[str, ProductionSource]:
        return _index(self.production_sources)

    @cached_property
    def purchasing_source_by_id(self) -> dict[str, PurchasingSource]:
        return _index(self.purchasing_sources)

    @cached_property
    def vendor_by_supplier(self) -> dict[str, Vendor]:
        out: dict[str, Vendor] = {}
        for v in self.vendors:
            out.setdefault(v.supplier, v)
        return out

    @cached_property
    def purchase_order_by_id(self) -> dict[str, PurchaseOrder]:
        return _index(self.purchase_orders)

    def vendor(self, supplier: str) -> Vendor:
        """The supplier's purchasing data, or the defaults when none is kept."""
        return self.vendor_by_supplier.get(supplier) or Vendor(supplier=supplier)

    def price_currency(self, pu: PurchasingSource) -> str | None:
        """The currency a source's price is in: its own, else the supplier's order currency (empty = the company's)."""
        cur = pu.currency or self.vendor(pu.supplier).currency
        return None if cur == self.settings.currency else cur

    def source_blocked(self, pu: PurchasingSource) -> bool:
        """A source planning and new orders may not use: blocked in the source list, or its supplier blocked."""
        return pu.blocked or self.vendor(pu.supplier).blocked

    @cached_property
    def lane_by_id(self) -> dict[str, TransportLane]:
        return _index(self.lanes)

    @cached_property
    def location_product_by_key(self) -> dict[tuple[str, str], LocationProduct]:
        out: dict[tuple[str, str], LocationProduct] = {}
        for lp in self.location_products:
            out.setdefault((lp.location, lp.product), lp)
        return out

    @cached_property
    def demand_nodes(self) -> set[tuple[str, str]]:
        """Every (location, product) with a demand record: forecast or customer order."""
        return {(d.location, d.product) for d in self.demand}

    def lot_sizing(self, lp: LocationProduct) -> LotSizing:
        """The lot-sizing rule planning uses at a node: its own, or the company default where it leaves it empty."""
        ls = lp.lot_sizing
        if ls.policy is not None:
            return ls
        s = self.settings
        return ls.model_copy(update={"policy": s.default_lot_policy, "periods": ls.periods or s.default_lot_periods})

    @cached_property
    def sources_at(self) -> dict[tuple[str, str], tuple[list[ProductionSource], list[PurchasingSource]]]:
        """Ways to make and ways to buy by (place, product), in list order."""
        out: dict[tuple[str, str], tuple[list[ProductionSource], list[PurchasingSource]]] = {}
        for ps in self.production_sources:
            out.setdefault((ps.location, ps.product), ([], []))[0].append(ps)
        for pu in self.purchasing_sources:
            out.setdefault((pu.location, pu.product), ([], []))[1].append(pu)
        return out

    @cached_property
    def lanes_into(self) -> dict[str, list[TransportLane]]:
        """Routes by the place they arrive at, in list order."""
        out: dict[str, list[TransportLane]] = {}
        for ln in self.lanes:
            out.setdefault(ln.destination, []).append(ln)
        return out

    @cached_property
    def memo(self) -> dict[str, Any]:
        """Results worked out from this dataset once and asked for by several steps (the supply network)."""
        return {}

    @cached_property
    def lp_memo(self) -> dict[tuple[str, tuple[str, str]], LocationProduct]:
        """planning_lp and demand_lp worked out once per node (they are asked for every demand row)."""
        return {}

    def planning_lp(self, node: tuple[str, str]) -> LocationProduct:
        """The node's planning policy as planning uses it: its record (or the defaults) with the company's lot size
        filled in."""
        hit = self.lp_memo.get(("p", node))
        if hit is not None:
            return hit
        lp = self.location_product_by_key.get(node) or LocationProduct(location=node[0], product=node[1])
        grp = next((g for g in self.mrp_groups if g.id == lp.mrp_group), None) if lp.mrp_group else None
        if grp is not None and (o := grp.overrides()):
            lp = lp.model_copy(update=o)
        if lp.lot_sizing.policy is None:
            lp = lp.model_copy(update={"lot_sizing": self.lot_sizing(lp)})
        self.lp_memo[("p", node)] = lp
        return lp

    def demand_lp(self, node: tuple[str, str]) -> LocationProduct:
        """The planning policy whose strategy decides how demand at a node is planned (forecast, orders, or orders
        consuming the forecast). A customer channel without a record of its own follows the nearest place upstream that
        has one: the strategy is set where the product is kept (make to order at the plant), not on every channel."""
        hit = self.lp_memo.get(("d", node))
        if hit is None:
            hit = self.lp_memo[("d", node)] = self._demand_lp(node)
        return hit

    def _demand_lp(self, node: tuple[str, str]) -> LocationProduct:
        lp = self.planning_lp(node)
        if node in self.location_product_by_key or self.location_type(node[0]) is not LocationType.CUSTOMER:
            return lp
        seen, level = {node[0]}, [node[0]]
        while level:
            nxt: list[str] = []
            for dest in level:
                for ln in self.lanes:
                    if ln.destination != dest or ln.origin in seen or (ln.products and node[1] not in ln.products):
                        continue
                    up = self.location_product_by_key.get((ln.origin, node[1]))
                    if up is not None:
                        return lp.model_copy(update={"strategy": up.strategy,
                                                     "consumption_backward_days": up.consumption_backward_days,
                                                     "consumption_forward_days": up.consumption_forward_days})
                    seen.add(ln.origin)
                    nxt.append(ln.origin)
            level = nxt
        return lp

    @cached_property
    def customer_price_by_key(self) -> dict[tuple[str, str], float]:
        out: dict[tuple[str, str], float] = {}
        for cp in self.customer_prices:
            out.setdefault((cp.customer, cp.product), cp.price)
        return out

    def selling_price(self, location: str, product: str, order_price: float | None = None) -> float | None:
        """What one unit sells for: the order's own price, else the customer's, else the product's (empty = no
        price: no revenue or margin is shown for it)."""
        if order_price is not None:
            return order_price
        cp = self.customer_price_by_key.get((location, product))
        if cp is not None:
            return cp
        p = self.product_by_id.get(product)
        return p.price if p else None

    def whole(self, product: str) -> bool:
        """Quantities of this product are planned in whole units."""
        p = self.product_by_id.get(product)
        return p.whole if p else False

    def location_type(self, loc_id: str) -> LocationType | None:
        loc = self.location_by_id.get(loc_id)
        return loc.type if loc else None


_CACHED = tuple(k for k, v in vars(Dataset).items() if isinstance(v, cached_property))


def _index(items: list) -> dict:
    out: dict = {}
    for it in items:
        out.setdefault(it.id, it)
    return out
