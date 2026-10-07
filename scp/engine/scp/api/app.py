"""HTTP API. Deliberately thin: parse the dataset (pydantic), call the engine, return typed results.

Planning calls are stateless: the client owns the working dataset and posts it with each request. What is kept, a
company on the server, its plan versions and its worklist, belongs to a company (``X-Company``) and is only for its
members (see :mod:`scp.api.companies`); without a company, versions and the worklist are the browser's own.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from .. import __version__
from ..actuals import ActualsView, FirmReport, PostingError, RollReport, actuals_view, firm_orders, post, roll_forward
from ..actuals.post import production_usage
from ..demand import ForecastResult, ReleaseResult, release, run_forecast
from ..finance import FinanceResult, run_finance
from ..tower import TowerResult, WorkItem, get_tracker, run_tower
from ..demand import foundation
from ..demand.models import SPECS
from ..demand.result import FoundationStatus
from ..inventory import InventoryResult, PlacementApplied, apply_placement, run_inventory
from ..model import Dataset, DemandRecord, ForecastModelId, StockType
from ..model.common import Out
from ..network import build_graph, location_edges, location_layers
from ..plan import PlanResult, run_mrp
from ..plan.mrp import with_kept_plan
from ..plan.trace import PlanTrace, index as trace_index, trace
from ..plan.level import LevelPreview, level_preview
from ..purchasing import PurchasingError, act as purchasing_act, create_one_off_po, create_purchase_orders, purchasing_view
from ..purchasing.result import ActionReport, CreateReport, PurchasingView
from ..sales import SalesError, act as sales_act, sales_view
from ..sales.result import SalesReport, SalesView
from ..promise import PromiseResult, check_lines, check_order, commit, run_bop, run_promise
from ..promise.orders import (
    OrderError, SalesOrderReport, accept as accept_order, cancel as cancel_order, change as change_order,
)
from ..scenarios import BY_ID as SCENARIOS, EngineClient, ScenarioInfo, ScenarioReport
from ..schedule import (
    HEURISTICS, PROFILES, ApplyReport, Heuristic, Profile, ScheduleComparison, ScheduleResult, apply_schedule,
    compare_schedules, run_schedule,
)
from ..sop import SopRelease, SopResult, release_sop, run_sop
from ..validate import RULES, Issue, validate
from ..validate.lenient import SINGULAR, DatasetRejected, SetAside, lenient, lenient_checked, plain_errors
from ..validate.setup import SetupItem, checklist
from ..versions import Comparison, VersionDoc, VersionError, VersionMeta, compare, get_store
from ..companies import CompanyError
from .connect import router as connect_router
from .companies import (
    Scope, StoredEditScope, StoredScope, company_error, edit_scope, gate, is_company, require_signin,
    router as companies_router, signup_policy, who_asks,
)
from .working import PlanData, answer, is_ref, read as read_ref, respond, send

ROOT = Path(__file__).resolve().parents[3]          # scp/
EXAMPLES = ROOT / "examples"
WEB_DIST = ROOT / "web" / "dist"



@asynccontextmanager
async def lifespan(_app: FastAPI):
    """With SCP_BACKUP_DIR set, the database is copied there every night (scp.backup); scheduled imports and worklist
    reminders run on their own clock (scp.connect.scheduler)."""
    from ..backup import start_nightly
    from ..versions.store import get_store

    from ..connect.scheduler import start as start_clock

    signup_policy()
    require_signin()
    store = get_store()
    start_nightly(store.db, store.lock)
    start_clock()       # scheduled imports and worklist reminders (Phase Q)
    yield


def _docs_on() -> bool:
    """The interactive API pages (/docs, /redoc, /openapi.json): on unless SCP_DOCS is off, and off by default on a
    server that requires sign-in (CV-L03)."""
    v = os.environ.get("SCP_DOCS", "").strip().lower()
    if v:
        return v not in ("0", "false", "no", "off")
    return os.environ.get("SCP_REQUIRE_SIGNIN", "").strip().lower() not in ("1", "true", "yes", "on")


_DOCS = _docs_on()
app = FastAPI(title="SCP — Supply Chain Planning", version=__version__, lifespan=lifespan,
              description="Typed network master data, readiness gate, demand planning, network MRP/DRP.",
              docs_url="/docs" if _DOCS else None, redoc_url="/redoc" if _DOCS else None,
              openapi_url="/openapi.json" if _DOCS else None)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://hasen1506.github.io"],
                   allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Rows"])


app.middleware("http")(gate)

app.add_exception_handler(CompanyError, company_error)  # type: ignore[arg-type]
app.include_router(companies_router)
app.include_router(connect_router)


@app.exception_handler(RequestValidationError)
def _request_invalid(_request, exc: RequestValidationError) -> JSONResponse:
    """422 with each field's problem in plain words (``loc`` still points at the field for the forms)."""
    return JSONResponse(status_code=422, content={"detail": plain_errors(list(exc.errors()))})


@app.exception_handler(DatasetRejected)
def _dataset_rejected(_request, exc: DatasetRejected) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": exc.errors})


@app.exception_handler(VersionError)
def _version_error(_request, exc: VersionError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc)})


class Health(Out):
    status: str
    version: str


class ExampleInfo(Out):
    name: str
    title: str
    locations: int
    products: int


class RuleInfo(Out):
    code: str
    severity: str
    description: str


# A dataset as the client holds it, possibly with unfinished records (see validate.lenient).
RawDataset = Annotated[dict[str, Any], Body()]


class ValidationResult(Out):
    issues: list[Issue]
    blocking: bool
    set_aside: list[SetAside] = []
    setup: list[SetupItem] = []   # what is still missing, in the order a planner sets a company up


class NetLocation(Out):
    id: str
    name: str
    type: str
    region: str
    lat: float | None
    lon: float | None
    layer: int
    products: list[str]
    resources: list[str]
    production_sources: list[str]


class NetEdge(Out):
    origin: str
    destination: str
    kind: str
    ids: list[str]
    products: list[str] | None
    modes: list[str]
    transit_days: float | None


class NetOption(Out):
    kind: str
    source_id: str
    upstream: list[tuple[str, str]]


class NetNode(Out):
    location: str
    product: str
    llc: int | None
    options: list[NetOption]


class NetworkView(Out):
    locations: list[NetLocation]
    edges: list[NetEdge]
    nodes: list[NetNode]
    cycles: list[list[tuple[str, str]]]


@app.get("/api/health", response_model=Health)
def health() -> Health:
    return Health(status="ok", version=__version__)


@app.get("/api/examples", response_model=list[ExampleInfo])
def examples() -> list[ExampleInfo]:
    out = []
    for p in sorted(EXAMPLES.glob("*.json")):
        d = json.loads(p.read_text())
        out.append(ExampleInfo(name=p.stem, title=d["settings"].get("company_name", p.stem),
                               locations=len(d.get("locations", [])), products=len(d.get("products", []))))
    return out


@app.get("/api/examples/{name}", response_model=Dataset)
def example(name: str) -> Dataset:
    # looked up among the examples there are, never opened by a name the caller made up: a name too long for the
    # file system (or naming another folder) is simply not an example, not a server error
    p = next((x for x in EXAMPLES.glob("*.json") if x.stem == name), None)
    if p is None:
        raise HTTPException(404, f"no example '{name[:80]}'")
    return Dataset.model_validate_json(p.read_text())


@app.get("/api/rules", response_model=list[RuleInfo])
def rules() -> list[RuleInfo]:
    out = [RuleInfo(code=k, severity=v[0], description=v[1]) for k, v in RULES.items()]
    # raised while reading the dataset (validate.lenient), before the readiness gate runs
    return out + [RuleInfo(code="SET_ASIDE", severity="warning",
                           description="An unfinished record is left out of planning until it is fixed")]


@app.get("/api/schema")
def schema() -> dict:
    """JSON schema of the dataset, including ``x-unit`` / ``x-ref`` field metadata for forms."""
    return Dataset.model_json_schema()


def validation_view(raw: RawDataset) -> ValidationResult:
    """The readiness gate on everything that can be planned; unfinished records are set aside and listed,
    each also as a SET_ASIDE warning, instead of making the whole dataset unreadable."""
    if is_ref(raw):
        r = read_ref(raw)
        ds, aside, checked = r.ds, r.aside, r.checked
    else:
        ds, aside, checked = lenient_checked(raw)
    issues = [Issue(code="SET_ASIDE", severity="warning", object_type=a.object_type, object_id=a.object_id,
                    message=f"{SINGULAR[a.collection]} {a.label} is left out of planning until it is fixed: {a.reason}",
                    hint="Fix it or delete it; it comes back into the plan as soon as it is complete", field=a.field)
              for a in aside]
    issues += validate(ds) if checked is None else checked
    return ValidationResult(issues=issues, blocking=any(i.severity == "error" for i in issues), set_aside=aside,
                            setup=checklist(ds, aside))


def network_view(raw: RawDataset) -> NetworkView:
    ds = read_ref(raw).ds if is_ref(raw) else lenient(raw)[0]
    g = build_graph(ds)
    layers = location_layers(ds)
    prods: dict[str, set[str]] = {}
    for (loc, prod) in g.nodes:
        prods.setdefault(loc, set()).add(prod)
    locs = [NetLocation(id=lo.id, name=lo.name or lo.id, type=lo.type.value, region=lo.region, lat=lo.lat,
                        lon=lo.lon, layer=layers.get(lo.id, 0), products=sorted(prods.get(lo.id, ())),
                        resources=[r.id for r in ds.resources if r.location == lo.id],
                        production_sources=[p.id for p in ds.production_sources if p.location == lo.id])
            for lo in ds.locations]
    for pu in ds.purchasing_sources:  # suppliers list what they sell
        for lo in locs:
            if lo.id == pu.supplier and pu.product not in lo.products:
                lo.products.append(pu.product)
    edges = []
    for e in location_edges(ds):
        modes: list[str] = []
        transit = None
        if e.kind == "lane":
            for lid in e.ids:
                ln = ds.lane_by_id[lid]
                modes += [m.mode.value for m in ln.modes]
                t = ln.planning_mode.transit_days
                transit = t if transit is None else min(transit, t)
        edges.append(NetEdge(origin=e.origin, destination=e.destination, kind=e.kind, ids=e.ids,
                             products=e.products, modes=sorted(set(modes)), transit_days=transit))
    nodes = [NetNode(location=n[0], product=n[1], llc=g.llc.get(n),
                     options=[NetOption(kind=o.kind, source_id=o.source_id, upstream=list(o.upstream))
                              for o in g.options.get(n, [])]) for n in g.nodes]
    return NetworkView(locations=locs, edges=edges, nodes=nodes, cycles=g.cycles)


@app.post("/api/validate", response_model=ValidationResult)
def post_validate(raw: RawDataset) -> Response:
    if is_ref(raw):
        return respond("validate", read_ref(raw).ds, lambda: validation_view(raw))
    return send(validation_view(raw))


@app.post("/api/network", response_model=NetworkView)
def post_network(raw: RawDataset) -> Response:
    if is_ref(raw):
        return respond("network", read_ref(raw).ds, lambda: network_view(raw))
    return send(network_view(raw))


class ModelInfo(Out):
    id: ForecastModelId
    label: str
    family: str
    description: str


class ForecastModels(Out):
    models: list[ModelInfo]
    foundation: FoundationStatus


class ReleaseRequest(Out):
    dataset: PlanData
    keys: list[str] | None = None


class ReleaseResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    release: ReleaseResult


@app.get("/api/forecast/models", response_model=ForecastModels)
def forecast_models() -> ForecastModels:
    _, st = foundation.get()
    return ForecastModels(
        models=[ModelInfo(id=s.id, label=s.label, family=s.family, description=s.description) for s in SPECS.values()],
        foundation=FoundationStatus(**st.__dict__))


@app.post("/api/forecast", response_model=ForecastResult)
def post_forecast(ds: PlanData) -> Response:
    return respond("forecast", ds, lambda: run_forecast(ds))


@app.post("/api/forecast/release", response_model=ReleaseResponse)
def post_release(req: ReleaseRequest) -> ReleaseResponse:
    result = run_forecast(req.dataset)
    if not result.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before releasing a forecast")
    new, info = release(req.dataset, result, req.keys)
    return ReleaseResponse(**answer(req.dataset, new), release=info)


@app.post("/api/inventory", response_model=InventoryResult)
def post_inventory(ds: PlanData) -> Response:
    return respond("inventory", ds, lambda: run_inventory(ds))


class PlacementRequest(Out):
    dataset: PlanData
    keys: list[str] | None = None     # "location|product"; None: every stage whose recommendation differs


class PlacementResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    applied: PlacementApplied


@app.post("/api/inventory/apply", response_model=PlacementResponse)
def post_inventory_apply(req: PlacementRequest) -> PlacementResponse:
    result = run_inventory(req.dataset)
    if not result.ok:
        raise HTTPException(409, "the placement did not solve; fix the readiness issues first")
    try:
        new, info = apply_placement(req.dataset, result, req.keys)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0])) from None
    return PlacementResponse(**answer(req.dataset, new), applied=info)


@app.post("/api/sop", response_model=SopResult)
def post_sop(ds: PlanData) -> Response:
    return respond("sop", ds, lambda: run_sop(ds))


class SopReleaseResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    release: SopRelease


@app.post("/api/sop/release", response_model=SopReleaseResponse)
def post_sop_release(ds: PlanData) -> SopReleaseResponse:
    result = run_sop(ds)
    if not result.ok:
        raise HTTPException(409, "the S&OP plan did not solve; fix the readiness issues first")
    new, info = release_sop(ds, result)
    return SopReleaseResponse(**answer(ds, new), release=info)


class ScheduleRequest(Out):
    dataset: PlanData
    sequence: dict[str, list[str]] | None = None   # resource → operation keys, each run where it is listed;
                                                   # None = the start rule, local search and optimiser per settings
    hold: dict[str, float] | None = None           # order → not-before clock hour (the result's holds)


@app.post("/api/schedule", response_model=ScheduleResult)
def post_schedule(req: ScheduleRequest) -> Response:
    return respond("schedule", req.dataset, lambda: run_schedule(req.dataset, req.sequence, hold=req.hold), req.sequence,
                   req.hold)


class ScheduleCatalogue(Out):
    heuristics: list[Heuristic]
    profiles: list[Profile]


@app.get("/api/schedule/catalogue", response_model=ScheduleCatalogue)
def get_schedule_catalogue() -> ScheduleCatalogue:
    """The scheduling heuristics and the profiles that bundle a start rule, the search and the objective weights."""
    return ScheduleCatalogue(heuristics=HEURISTICS, profiles=PROFILES)


@app.post("/api/schedule/compare", response_model=ScheduleComparison)
def post_schedule_compare(ds: PlanData) -> Response:
    """Every start rule, the local search and the optimiser on the same window, scored with the current weights."""
    return respond("compare", ds, lambda: compare_schedules(ds))


class ScheduleApplyRequest(ScheduleRequest):
    ids: list[str] | None = None       # scheduled orders to date; None = every order on the schedule


class ScheduleApplyResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: ApplyReport


@app.post("/api/schedule/apply", response_model=ScheduleApplyResponse)
def post_schedule_apply(req: ScheduleApplyRequest) -> ScheduleApplyResponse:
    """Fix the schedule's dates on its orders: planned ones become production orders, released ones are re-dated."""
    new, rep = apply_schedule(req.dataset, req.sequence, req.ids, req.hold)
    if not rep.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before using the schedule's dates")
    return ScheduleApplyResponse(**answer(req.dataset, new), report=rep)


@app.post("/api/promise", response_model=PromiseResult)
def post_promise(ds: PlanData) -> Response:
    return respond("promise", ds, lambda: run_promise(ds))


@app.post("/api/promise/bop", response_model=PromiseResult)
def post_bop(ds: PlanData) -> Response:
    return respond("bop", ds, lambda: run_bop(ds))


class PromiseCheckRequest(Out):
    dataset: PlanData
    order: DemandRecord | None = None                                  # one line, or
    lines: list[DemandRecord] = Field(default_factory=list, max_length=500)   # the lines of one order, checked together


@app.post("/api/promise/check", response_model=PromiseResult)
def post_promise_check(req: PromiseCheckRequest) -> PromiseResult:
    if req.lines:
        return check_lines(req.dataset, req.lines)
    if req.order is None:
        raise HTTPException(422, "send the order to check, or its lines")
    return check_order(req.dataset, req.order)


class PromiseCommitRequest(Out):
    dataset: PlanData
    mode: Literal["entry", "bop"] = "entry"


class PromiseCommitResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    result: PromiseResult


@app.post("/api/promise/commit", response_model=PromiseCommitResponse)
def post_promise_commit(req: PromiseCommitRequest) -> PromiseCommitResponse:
    new, res = commit(req.dataset, req.mode)
    if not res.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before committing promises")
    return PromiseCommitResponse(**answer(req.dataset, new), result=res)


class SalesOrderChange(Out):
    qty: float | None = None                        # the whole ordered quantity, delivered included
    date: dt.date | None = None
    priority: int | None = None
    price: float | None = None                      # sent as null: the price list's price again
    complete_delivery: bool | None = None
    customer_ref: str | None = None


class SalesOrderRequest(Out):
    dataset: PlanData
    action: Literal["accept", "change", "cancel"]
    order: DemandRecord | None = None               # accept: the checked order (no number: the next one)
    id: str | None = None                           # change / cancel: the order
    changes: SalesOrderChange | None = None
    date: dt.date | None = None                     # cancel: the day (default: the planning start)
    reason: str = ""


class SalesOrderResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: SalesOrderReport


@app.post("/api/orders/sales", response_model=SalesOrderResponse)
def post_sales_order(req: SalesOrderRequest) -> SalesOrderResponse:
    """Take a checked customer order, change one (it is promised again), or cancel what is still open."""
    try:
        if req.action == "accept":
            if req.order is None:
                raise OrderError("send the order to take")
            new, rep = accept_order(req.dataset, req.order)
        elif not req.id:
            raise OrderError("say which order")
        elif req.action == "change":
            ch = req.changes or SalesOrderChange()
            given = {k: getattr(ch, k) for k in ch.model_fields_set if getattr(ch, k) is not None or k == "price"}
            new, rep = change_order(req.dataset, req.id, given)
        else:
            new, rep = cancel_order(req.dataset, req.id, req.date, req.reason)
    except (OrderError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    return SalesOrderResponse(**answer(req.dataset, new), report=rep)


@app.post("/api/plan", response_model=PlanResult)
def post_plan(ds: PlanData, pegging: bool = True) -> Response:
    """The supply plan. ``pegging=false`` leaves out the requirements and the pegging (two thirds of a large plan):
    ``/api/plan/trace`` gives an order's or a product's part of them when it is looked at."""
    return respond("plan", ds, lambda: run_mrp(ds), exclude=None if pegging else {"requirements", "pegs"})


class TraceRequest(Out):
    dataset: PlanData
    order: str | None = None          # an order: what it serves, up to the customer, and what it depends on
    location: str | None = None       # or a product at a place: its requirements and what covers them
    product: str | None = None


@app.post("/api/plan/trace", response_model=PlanTrace)
def post_plan_trace(req: TraceRequest) -> Response:
    """Part of the plan's requirements and pegging: an order's chain, or one product's at one place."""
    plan = run_mrp(req.dataset)
    ix = with_kept_plan(req.dataset, plan, "trace", lambda: trace_index(plan))
    return send(trace(ix, req.order, req.location, req.product))


@app.post("/api/capacity/level", response_model=LevelPreview)
def post_level(ds: PlanData) -> Response:
    """What planning within machine capacity moves: earlier, onto alternative machines, or later."""
    return respond("level", ds, lambda: level_preview(ds))


@app.post("/api/finance", response_model=FinanceResult)
def post_finance(ds: PlanData) -> Response:
    """The plan in money: cost reconciliation, inventory value, cost to serve, capacity investment NPV."""
    return respond("finance", ds, lambda: run_finance(ds))


class ActualsRequest(Out):
    dataset: PlanData
    as_of: dt.date | None = None


@app.post("/api/actuals", response_model=ActualsView)
def post_actuals(req: ActualsRequest) -> Response:
    return respond("actuals", req.dataset, lambda: actuals_view(req.dataset, req.as_of), req.as_of)


class RollRequest(Out):
    dataset: PlanData
    as_of: dt.date


class RollResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: RollReport


@app.post("/api/actuals/roll", response_model=RollResponse)
def post_roll(req: RollRequest) -> RollResponse:
    new, rep = roll_forward(req.dataset, req.as_of)
    if not rep.ok:
        raise HTTPException(409, "; ".join(rep.warnings))
    return RollResponse(**answer(req.dataset, new), report=rep)


class FirmRequest(Out):
    dataset: PlanData
    ids: list[str] | None = None          # planned order ids; None = everything starting in the firm zone
    within_days: int | None = None        # overrides the dataset's firm zone
    starts: dict[str, dt.date] | None = None  # planned production runs moved by hand: firm, starting that day
    send: bool = False                    # send the purchase orders it makes at once (all but those to be released)


class FirmResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: FirmReport


@app.post("/api/orders/firm", response_model=FirmResponse)
def post_firm(req: FirmRequest) -> FirmResponse:
    new, rep = firm_orders(req.dataset, run_mrp(req.dataset), req.ids, req.within_days, req.starts, req.send)
    if not rep.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before firming orders")
    return FirmResponse(**answer(req.dataset, new), report=rep)


# --- procure-to-pay (Phase E) --------------------------------------------------------------------
@app.post("/api/purchasing", response_model=PurchasingView)
def post_purchasing(ds: PlanData) -> Response:
    """Requisitions from the supply plan, every purchase order with its lines' status, and the supplier scorecard."""
    return respond("purchasing", ds, lambda: purchasing_view(ds, run_mrp(ds)))


class RequisitionPick(Out):
    id: str
    source_id: str | None = None
    qty: float | None = None


class CreatePoRequest(Out):
    dataset: PlanData
    lines: list[RequisitionPick] | None = None      # None = every requisition due now, on its planned source
    order_date: dt.date | None = None


class CreatePoResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: CreateReport


@app.post("/api/purchasing/create", response_model=CreatePoResponse)
def post_create_pos(req: CreatePoRequest) -> CreatePoResponse:
    plan = run_mrp(req.dataset)
    lines = None if req.lines is None else [x.model_dump(exclude_none=True) for x in req.lines]
    new, rep = create_purchase_orders(req.dataset, plan, lines, req.order_date)
    if not rep.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before ordering")
    return CreatePoResponse(**answer(req.dataset, new), report=rep)


class OneOffPoRequest(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    dataset: PlanData
    source_id: str = Field(min_length=1)
    qty: float = Field(gt=0)
    due_date: dt.date | None = None       # None = as soon as the supplier can deliver
    order_date: dt.date | None = None


@app.post("/api/purchasing/one-off", response_model=CreatePoResponse)
def post_one_off_po(req: OneOffPoRequest) -> CreatePoResponse:
    """A purchase order no requisition asked for: one line on a purchasing source."""
    new, rep = create_one_off_po(req.dataset, req.source_id, req.qty, req.due_date, req.order_date)
    if not rep.ok:
        raise HTTPException(409, "; ".join(rep.skipped.values()) or "the order could not be made")
    return CreatePoResponse(**answer(req.dataset, new), report=rep)


class ConfirmPart(Out):
    date: dt.date
    qty: float


class PoLineInput(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str = ""                                    # the order line (an invoice line: the line invoiced)
    order: str | None = None                        # enter_invoice: the order line invoiced (same as id)
    qty: float | None = None
    date: dt.date | None = None
    price: float | None = None
    final: bool = False
    parts: list[ConfirmPart] | None = None          # confirm: several deliveries, each a date and quantity
    batch: str | None = None                        # receive: the batch (default: a new one for batch-managed products)
    expires_on: dt.date | None = None               # receive: its expiry (default: today + the shelf life)
    supplier_batch: str | None = None
    serials: list[str] | None = None                # receive: serial numbers, one per unit (default: numbered)


class PoActionRequest(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    dataset: PlanData
    action: Literal["approve", "send", "send_all", "confirm", "receive", "change", "cancel", "create_agreement",
                    "enter_invoice", "release_invoice", "pay_invoice", "cancel_invoice", "return_goods"]
    po: str = ""                                    # the order; for the invoice actions the invoice (enter: the order
                                                    # whose receipts it bills, when no lines are given)
    lines: list[PoLineInput] | None = None          # None = every open line, as ordered
    date: dt.date | None = None                     # sent on / received on / invoice date / paid on (default: today)
    reference: str = ""                             # the supplier's confirmation, invoice or payment number
    note: str = ""                                  # delivery note on a goods receipt; why goods go back
    by: str = ""                                    # who releases (signed in: the account, whatever this says)
    orders: list[str] | None = None                 # send_all: the orders (None: every approved one not sent)
    supplier: str | None = None                     # create_agreement, enter_invoice
    location: str | None = None                     # create_agreement
    product: str | None = None                      # create_agreement
    valid_to: dt.date | None = None                 # create_agreement
    qty: float | None = None                        # create_agreement: the target quantity
    tax: float | None = None                        # enter_invoice: as charged (default: the supplier's rate)
    kind: Literal["invoice", "credit_memo", "subsequent_debit", "subsequent_credit"] = "invoice"
    return_id: str | None = None                    # enter_invoice: the return a credit memo credits
    delivery_costs: float = Field(0.0, ge=0)        # enter_invoice: freight and other costs the order did not plan
    amount: float | None = None                     # pay_invoice (default: what is open, less the discount in time)
    stock_type: StockType | None = None             # return_goods: where the goods are (default: blocked)
    replace: bool = False                           # return_goods: the supplier replaces them (else credits them)


class PoActionResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: ActionReport


@app.post("/api/purchasing/act", response_model=PoActionResponse)
def post_po_action(req: PoActionRequest) -> PoActionResponse:
    lines = None if req.lines is None else [
        {**x.model_dump(exclude_none=True), **({"order": x.order or x.id})} for x in req.lines]
    try:
        new, rep = purchasing_act(req.dataset, req.action, req.po, lines=lines, on=req.date, reference=req.reference,
                                  note=req.note, by=who_asks() or req.by, orders=req.orders, supplier=req.supplier,
                                  location=req.location, product=req.product, valid_to=req.valid_to, qty=req.qty,
                                  tax=req.tax, kind=req.kind, return_id=req.return_id, amount=req.amount,
                                  stock_type=req.stock_type, replace=req.replace,
                                  delivery_costs=req.delivery_costs)
    except PurchasingError as e:
        raise HTTPException(409, str(e)) from e
    return PoActionResponse(**answer(req.dataset, new), report=rep)


@app.post("/api/sales", response_model=SalesView)
def post_sales(ds: PlanData, as_of: dt.date | None = None) -> Response:
    """Every sales order with its lines, quotations, deliveries, invoices and returns, what is due to deliver and to
    bill, and each customer's credit position."""
    return respond("sales", ds, lambda: sales_view(ds, as_of), as_of)


class SalesLineInput(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    order: str | None = None                        # deliveries, picking, proof: the order line
    product: str | None = None                      # orders and quotations: the product
    qty: float | None = None
    date: dt.date | None = None                     # orders and quotations: wanted on
    price: float | None = None                      # a net price agreed for this line (empty: the price list)
    priority: int | None = None
    complete_delivery: bool | None = None
    picked: float | None = None
    received: float | None = None
    batch: str | None = None
    ship_from: str | None = None


class SalesActionRequest(Out):
    model_config = ConfigDict(allow_inf_nan=False)
    dataset: PlanData
    action: Literal["create_order", "add_lines", "release_credit", "send_confirmation", "cancel_order",
                    "create_quotation", "win_quotation", "lose_quotation", "create_deliveries", "pick", "pack",
                    "issue", "proof", "cancel_delivery", "create_invoices", "pay", "cancel_invoice", "create_return",
                    "receive_return", "credit_return", "remind"]
    id: str | None = None                           # the order, quotation, delivery, invoice or return
    customer: str | None = None
    lines: list[SalesLineInput] | None = None
    date: dt.date | None = None                     # the day it happens (default: the planning start)
    customer_ref: str = ""
    payment_terms: str | None = None
    note: str = ""
    reason: str = ""
    by: str = ""                                    # released by, signed by
    valid_to: dt.date | None = None
    packages: int | None = None
    gross_kg: float | None = None
    amount: float | None = None
    reference: str = ""
    orders: list[str] | None = None                 # invoices: only these order lines or orders; remind: these invoices
    product: str | None = None                      # returns
    qty: float | None = None
    order: str | None = None
    location: str | None = None
    stock_type: StockType | None = None
    batch: str | None = None


class SalesActionResponse(Out):
    dataset: Dataset | None = None        # the changed company whole, or
    patch: dict[str, Any] | None = None   # what changed, when it came by reference (scp.api.working)
    report: SalesReport


@app.post("/api/sales/act", response_model=SalesActionResponse)
def post_sales_action(req: SalesActionRequest) -> SalesActionResponse:
    """One order-to-cash step: take an order, quote, deliver, invoice, record a payment, take a return back."""
    lines = None if req.lines is None else [x.model_dump(exclude_none=True) for x in req.lines]
    kw = req.model_dump(exclude={"dataset", "action", "id", "customer", "lines", "date"})
    try:
        new, rep = sales_act(req.dataset, req.action, id=req.id, customer=req.customer, lines=lines, on=req.date, **kw)
    except (SalesError, OrderError) as e:
        raise HTTPException(409, str(e)) from e
    return SalesActionResponse(**answer(req.dataset, new), report=rep)


class UsageInput(Out):
    product: str
    qty: float


class ProductionUsageInput(Out):
    location: str
    product: str
    qty: float


class ProductionUsageRequest(Out):
    dataset: PlanData
    order: str
    qty: float | None = Field(None, gt=0, allow_inf_nan=False)


@app.post("/api/actuals/production-usage", response_model=list[ProductionUsageInput])
def preview_production_usage(req: ProductionUsageRequest) -> list[ProductionUsageInput]:
    """Read the same default components that production confirmation will issue; no posting is made."""
    try:
        return [ProductionUsageInput(**row) for row in production_usage(req.dataset, req.order, req.qty)]
    except PostingError as e:
        raise HTTPException(409, str(e)) from e


class CountInput(Out):
    location: str
    product: str
    qty: float | None                               # None: not counted yet (a physical inventory line)
    batch: str | None = None                        # a physical inventory line: the batch and stock type counted
    stock_type: StockType | None = None


class NodeInput(Out):
    location: str
    product: str


class PostRequest(Out):
    dataset: PlanData
    action: Literal["ship", "receive", "deliver", "count", "move", "scrap", "scrap_expired", "reverse", "shorten",
                    "count_doc", "count_enter", "count_post", "count_cancel"]
    order: str | None = None                        # the firm order (ship / receive / shorten) or sales order (deliver)
    qty: float | None = None                        # default: everything still open (shorten: the new quantity)
    date: dt.date | None = None                     # posting date (default: the planning start; a count: the day before)
    final: bool = False                             # last delivery: closes the order even if short
    usage: list[UsageInput] | None = None           # production: parts actually used, instead of the backflush
    counts: list[CountInput] | None = None          # count / count_enter: stock counted per place and product
    ship_from: str | None = None                    # deliver: the place it ships from (default: where it was promised)
    note: str = ""
    batch: str | None = None                        # the batch received, shipped, delivered, moved or scrapped
    expires_on: dt.date | None = None               # receive: the batch's expiry (default: today + the shelf life)
    supplier_batch: str | None = None               # receive: the supplier's batch number
    serials: list[str] | None = None                # serial numbers, one per unit
    stock_type: StockType | None = None             # receive: the stock it goes to; move / scrap: the stock it leaves
    to_type: StockType | None = None                # move: the stock it goes to
    location: str | None = None                     # move / scrap: the place
    product: str | None = None                      # move / scrap: the product
    movement: str | None = None                     # reverse: a movement of the document to take back
    doc: str | None = None                          # count_enter / count_post / count_cancel: the inventory document
    nodes: list[NodeInput] | None = None            # count_doc: places and products to count
    block: bool = True                              # count_doc: refuse postings for them until the count is posted
    uncounted_zero: bool = False                    # count_post: lines not counted are posted as zero


@app.post("/api/actuals/post", response_model=PoActionResponse)
def post_posting(req: PostRequest) -> PoActionResponse:
    """Post what happened: ship a transfer, receive an order (with its parts issued), or count stock."""
    try:
        new, rep = post(req.dataset, req.action, order=req.order, qty=req.qty, on=req.date, final=req.final,
                        usage=None if req.usage is None else [u.model_dump() for u in req.usage],
                        counts=None if req.counts is None else [c.model_dump() for c in req.counts], note=req.note,
                        lot={"batch": req.batch, "expires_on": req.expires_on, "supplier_batch": req.supplier_batch or "",
                             "serials": req.serials, "stock_type": req.stock_type},
                        location=req.location, product=req.product, to_type=req.to_type, movement=req.movement,
                        doc=req.doc, nodes=None if req.nodes is None else [(n.location, n.product) for n in req.nodes],
                        block=req.block, uncounted_zero=req.uncounted_zero,
                        ship_from=req.ship_from)
    except PostingError as e:
        raise HTTPException(409, str(e)) from e
    return PoActionResponse(**answer(req.dataset, new), report=rep)


# --- versions & scenarios (P8) -------------------------------------------------------------------
class SaveBaseRequest(Out):
    dataset: Dataset
    name: str
    note: str = ""


class BranchRequest(Out):
    name: str
    note: str = ""


class PromoteRequest(Out):
    name: str | None = None
    note: str = ""


class CompareRequest(Out):
    a: Dataset
    b: Dataset
    label_a: str = "A"
    label_b: str = "B"


@app.get("/api/versions", response_model=list[VersionMeta])
def list_versions(sc: StoredScope) -> list[VersionMeta]:
    return get_store().list(sc)


@app.post("/api/versions", response_model=VersionMeta)
def save_base(req: SaveBaseRequest, sc: StoredEditScope) -> VersionMeta:
    return get_store().save_base(req.dataset, req.name, req.note, sc)


@app.get("/api/versions/{vid}", response_model=VersionDoc)
def get_version(vid: str, sc: StoredScope) -> VersionDoc:
    return get_store().get(vid, sc)


@app.put("/api/versions/{vid}", response_model=VersionMeta)
def update_version(vid: str, ds: Dataset, sc: StoredEditScope) -> VersionMeta:
    return get_store().update(vid, ds, sc)


@app.post("/api/versions/{vid}/branch", response_model=VersionMeta)
def branch_version(vid: str, req: BranchRequest, sc: StoredEditScope) -> VersionMeta:
    return get_store().branch(vid, req.name, req.note, sc)


@app.post("/api/tower", response_model=TowerResult)
def post_tower(ds: PlanData, sc: Scope, request: Request) -> Response:
    """KPIs, the exception worklist (recorded in the version store: first seen, owner, status) and data quality.
    Only a member who may change the company records the run in its worklist; a viewer sees it as it stands
    (CV-H05)."""
    record = True
    if not sc:                    # nowhere to keep it (CV-H06): shown as it would open, recorded nowhere
        sc, record = "anon:-", False
    elif is_company(sc):
        try:
            edit_scope(request)
        except CompanyError:
            record = False
    return send(run_tower(ds, scope=sc or None, record=record))


class WorkItemUpdate(Out):
    owner: str | None = None        # "" = back to the owner rules
    status: Literal["open", "acknowledged", "resolved"] | None = None
    note: str | None = None
    sla_days: dict[str, int] = {}


class WorkItemEntry(Out):
    at: str
    action: str
    detail: str


@app.post("/api/tower/items/{iid}", response_model=WorkItem)
def update_work_item(iid: str, body: WorkItemUpdate, sc: StoredEditScope) -> WorkItem:
    return get_tracker().update(iid, owner=body.owner, status=body.status, note=body.note, sla=body.sla_days,
                                scope=sc or None)


@app.get("/api/tower/items/{iid}/history", response_model=list[WorkItemEntry])
def work_item_history(iid: str, sc: StoredScope) -> list[WorkItemEntry]:
    return [WorkItemEntry(at=a, action=b, detail=c) for a, b, c in get_tracker().history(iid, sc or None)]


@app.post("/api/versions/{vid}/discard", response_model=VersionMeta)
def discard_version(vid: str, sc: StoredEditScope) -> VersionMeta:
    return get_store().discard(vid, sc)


@app.post("/api/versions/{vid}/promote", response_model=VersionMeta)
def promote_version(vid: str, req: PromoteRequest, sc: StoredEditScope) -> VersionMeta:
    return get_store().promote(vid, req.name, req.note, sc)


@app.get("/api/versions/{a}/compare/{b}", response_model=Comparison)
def compare_versions(a: str, b: str, sc: StoredScope) -> Comparison:
    st = get_store()
    return compare(st.dataset(a, sc), st.dataset(b, sc), a, b)


@app.post("/api/compare", response_model=Comparison)
def post_compare(req: CompareRequest) -> Comparison:
    """Compare any two datasets, e.g. the working copy against a stored version."""
    return compare(req.a, req.b, req.label_a, req.label_b)


# --- proof: end-to-end scenarios with hand-derived answers --------------------------------------------
def _scenario(sid: str):
    sc = SCENARIOS.get(sid)
    if sc is None:
        raise HTTPException(404, f"no scenario '{sid}'")
    return sc


@app.get("/api/scenarios", response_model=list[ScenarioInfo])
def list_scenarios() -> list[ScenarioInfo]:
    return [s.info() for s in SCENARIOS.values()]


@app.get("/api/scenarios/{sid}/dataset", response_model=Dataset)
def scenario_dataset(sid: str) -> Dataset:
    """The scenario's starting dataset: open it in the app to follow the workflow by hand."""
    return _scenario(sid).dataset()


@app.post("/api/scenarios/{sid}/run", response_model=ScenarioReport)
def run_scenario(sid: str) -> ScenarioReport:
    """Run every step and checkpoint against an isolated in-memory version store (never the user's)."""
    return _scenario(sid).execute(EngineClient())


# --- single-page app (built web client) --------------------------------------------------------
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "unknown API route")
        try:   # a name too long for the file system, or with a NUL in it, is no file of ours: the app's page
            f = (WEB_DIST / path).resolve()
            if path and f.is_file() and WEB_DIST in f.parents:
                return FileResponse(f)
        except (OSError, ValueError):
            pass
        return FileResponse(WEB_DIST / "index.html")
