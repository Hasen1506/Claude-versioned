"""What is still missing before the company can be planned, in the order a planner sets it up.

The readiness gate answers "is anything wrong?". This answers "what haven't I done yet?", which the gate
cannot: an empty company has nothing wrong with it and nothing to plan. Each item is one plain sentence
naming products and places by name, with the screen that fixes it.

Steps: places → products → demand → how each product is supplied → how it is made → stock → unfinished
records. A step is ``done`` when nothing in it needs doing, ``todo`` when planning cannot give a useful answer
until it is done, ``check`` when the plan runs but will likely be wrong, and ``info`` for an assumption worth
knowing.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..model import Dataset, LocationType, ProductType
from ..model.common import PRODUCTION_LOCATION_TYPES, STOCKING_LOCATION_TYPES
from ..network import build_graph, supply_options
from .lenient import SINGULAR, SetAside

Status = Literal["done", "todo", "check", "info"]


class SetupAction(BaseModel):
    label: str
    route: list[str]     # the web client's route segments, e.g. ["data", "demand"] or ["setup", "product", product, location]


class SetupItem(BaseModel):
    step: str            # places | products | demand | supply | making | stock | unfinished
    status: Status
    text: str
    action: SetupAction | None = None


STEPS: dict[str, str] = {
    "places": "Places", "products": "Products", "demand": "Demand", "supply": "How each product is supplied",
    "making": "How products are made", "stock": "Stock on hand", "unfinished": "Unfinished records",
}


def checklist(ds: Dataset, aside: list[SetAside] | None = None) -> list[SetupItem]:
    out: list[SetupItem] = []
    add = lambda step, status, text, label=None, route=None: out.append(  # noqa: E731
        SetupItem(step=step, status=status, text=text,
                  action=SetupAction(label=label, route=route) if label and route else None))
    lname = {lo.id: lo.name or lo.id for lo in ds.locations}
    pname = {p.id: p.name or p.id for p in ds.products}

    # --- places
    stocking = [lo for lo in ds.locations if lo.type in STOCKING_LOCATION_TYPES]
    if not stocking:
        add("places", "todo", "Add the places where you make or keep stock: plants, warehouses, distribution centres or "
            "stores. Suppliers and customers come next.", "Add places", ["setup", "network"])
    else:
        counts: dict[str, int] = {}
        for lo in ds.locations:
            counts[lo.type.value] = counts.get(lo.type.value, 0) + 1
        add("places", "done", f"{len(ds.locations)} place{'s' if len(ds.locations) != 1 else ''}: "
            + ", ".join(f"{n} {_TYPE_WORD[t][n != 1]}" for t, n in counts.items()) + ".", "Open the network", ["setup", "network"])

    # --- products
    fgs = [p for p in ds.products if p.type is ProductType.FG]
    if not ds.products:
        add("products", "todo", "Add the products you sell, and the parts and materials they are made from.",
            "Add products", ["setup", "products"])
    elif not fgs:
        add("products", "todo", "No product is marked as a finished good, so nothing is sold. Set the type of what you sell "
            "to “finished good”.", "Open products", ["setup", "products"])
    else:
        add("products", "done", f"{len(ds.products)} product{'s' if len(ds.products) != 1 else ''}, "
            f"{len(fgs)} of them sold.", "Open products", ["setup", "products"])

    # --- demand
    demanded = {d.product for d in ds.demand if d.qty > 0} | {h.product for h in ds.history} | {n.product for n in ds.npi}
    no_demand = [p for p in fgs if p.id not in demanded]
    if fgs and len(no_demand) == len(fgs):
        add("demand", "todo", "Nothing to plan yet: no product has any demand. Enter the quantities you expect to sell "
            "(a demand plan), or upload sales history to forecast from.", "Add demand", ["demand"])
    else:
        for p in no_demand:
            add("demand", "check", f"{pname[p.id]} has no demand and no sales history, so the plan makes none of it.",
                "Add demand", ["demand"])
        if fgs and not no_demand:
            n_rows = sum(1 for d in ds.demand if d.qty > 0)
            add("demand", "done", f"Every sold product has demand ({n_rows} demand row{'s' if n_rows != 1 else ''}"
                + (f", {len(ds.history)} rows of sales history" if ds.history else "") + ").", "Open demand", ["demand"])

    # --- supply: every place that needs a product must be able to get it
    g = build_graph(ds)
    needed: dict[tuple[str, str], str] = {}  # node → why it is needed
    for n in g.nodes:
        needed.setdefault(n, "")
    for ps in ds.production_sources:
        if ps.location not in lname:
            continue
        for c in ps.components:
            if c.product in pname and not needed.get((ps.location, c.product)):
                needed[(ps.location, c.product)] = f"a component of {pname.get(ps.product, ps.product)}"
    onhand = {(lp.location, lp.product): lp.on_hand for lp in ds.location_products}
    missing = 0
    for (loc, prod), why in needed.items():
        if ds.location_type(loc) in (LocationType.SUPPLIER, LocationType.CUSTOMER, None):
            continue
        opts = g.options.get((loc, prod))
        if opts is None:
            opts = supply_options(ds, (loc, prod))
        if opts:
            continue
        missing += 1
        stock = onhand.get((loc, prod), 0.0)
        add("supply", "todo", f"{pname.get(prod, prod)} at {lname.get(loc, loc)}{f' ({why})' if why else ''} has no way to be "
            f"supplied: it is not made there, bought for there, or shipped there"
            + (f", so only the {stock:g} on hand can be used." if stock else "."),
            "Set up how it is supplied", ["setup", "product", prod, loc])
    for p in fgs:
        if p.id in demanded and not any(ps.product == p.id for ps in ds.production_sources) \
                and not any(pu.product == p.id for pu in ds.purchasing_sources):
            missing += 1
            add("supply", "todo", f"{pname[p.id]} is neither made nor bought anywhere.", "Set up how it is supplied",
                ["setup", "product", p.id])
    if not missing and needed:
        add("supply", "done", "Every product can reach every place that needs it.", "Open the network", ["setup", "network"])

    # --- making
    for ps in ds.production_sources:
        if ps.location not in lname or ps.product not in pname:
            continue
        what = f"{pname[ps.product]} at {lname[ps.location]}"
        if not ps.components and pname:
            add("making", "info", f"{what} is made from nothing: it has no bill of material, so no parts are planned for it.",
                "Open how it is made", ["setup", "product", ps.product, ps.location])
        if not ps.operations:
            add("making", "check" if ps.fixed_lead_time_workdays is None else "info",
                f"{what} has no routing: no machine time is planned for it"
                + (", and it takes no time to make." if ps.fixed_lead_time_workdays is None else
                   f", and it takes {ps.fixed_lead_time_workdays:g} working days."),
                "Add a routing", ["setup", "product", ps.product, ps.location])
    plants = [lo for lo in ds.locations if lo.type in PRODUCTION_LOCATION_TYPES]
    if ds.production_sources and not ds.resources and plants:
        add("making", "check", "No machines, lines or crews are defined, so capacity is not checked.",
            "Add a resource", ["data", "resources"])
    if ds.production_sources and not any(i.status in ("check", "todo") for i in out if i.step == "making"):
        add("making", "done", f"{len(ds.production_sources)} way{'s' if len(ds.production_sources) != 1 else ''} of making "
            f"products, on {len(ds.resources)} resource{'s' if len(ds.resources) != 1 else ''}.",
            "Open production sources", ["data", "production_sources"])

    # --- stock
    if ds.locations and not any(lp.on_hand > 0 for lp in ds.location_products) and not ds.movements:
        add("stock", "info", "No stock on hand is entered anywhere, so the plan assumes every place starts empty.",
            "Enter stock on hand", ["data", "location_products"])

    # --- unfinished records
    for a in aside or []:
        add("unfinished", "check", f"{SINGULAR[a.collection]} {a.label} is left out until it is finished: {a.reason}.",
            "Finish it", ["data", a.collection, a.object_id.replace("/", "|")])
    return out


def ready(items: list[SetupItem]) -> bool:
    """True when nothing blocks a useful plan (a `todo` means the plan would be empty or wrong)."""
    return not any(i.status == "todo" for i in items)


_TYPE_WORD = {
    "plant": ("plant", "plants"), "dc": ("distribution centre", "distribution centres"),
    "warehouse": ("warehouse", "warehouses"), "store": ("store", "stores"), "supplier": ("supplier", "suppliers"),
    "customer": ("customer", "customers"),
}
