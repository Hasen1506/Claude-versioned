"""HTTP API. Deliberately thin: parse the dataset (pydantic), call the engine, return typed results.

The server is stateless in P0/P1: the client owns the dataset document and posts it with each
request. Plan versions and persistence arrive in P7/P8 (see docs/BLUEPRINT.md §10).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from .. import __version__
from ..actuals import ActualsView, FirmReport, RollReport, actuals_view, firm_orders, roll_forward
from ..demand import ForecastResult, ReleaseResult, release, run_forecast
from ..finance import FinanceResult, run_finance
from ..tower import TowerResult, WorkItem, get_tracker, run_tower
from ..demand import foundation
from ..demand.models import SPECS
from ..demand.result import FoundationStatus
from ..inventory import InventoryResult, PlacementApplied, apply_placement, run_inventory
from ..model import Dataset, DemandRecord, ForecastModelId
from ..model.common import Out
from ..network import build_graph, location_edges, location_layers
from ..plan import PlanResult, run_mrp
from ..plan.level import LevelPreview, level_preview
from ..purchasing import PurchasingError, act as purchasing_act, create_purchase_orders, purchasing_view
from ..purchasing.result import ActionReport, CreateReport, PurchasingView
from ..promise import PromiseResult, check_order, commit, run_bop, run_promise
from ..scenarios import BY_ID as SCENARIOS, EngineClient, ScenarioInfo, ScenarioReport
from ..schedule import (
    HEURISTICS, PROFILES, ApplyReport, Heuristic, Profile, ScheduleComparison, ScheduleResult, apply_schedule,
    compare_schedules, run_schedule,
)
from ..sop import SopRelease, SopResult, release_sop, run_sop
from ..validate import RULES, Issue, validate
from ..validate.lenient import SINGULAR, DatasetRejected, SetAside, lenient, plain_errors
from ..validate.setup import SetupItem, checklist
from ..versions import Comparison, VersionDoc, VersionError, VersionMeta, compare, get_store

ROOT = Path(__file__).resolve().parents[3]          # scp/
EXAMPLES = ROOT / "examples"
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="SCP — Supply Chain Planning", version=__version__,
              description="Typed network master data, readiness gate, demand planning, network MRP/DRP.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "https://hasen1506.github.io"],
                   allow_methods=["*"], allow_headers=["*"])


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
    p = EXAMPLES / f"{name}.json"
    if not p.is_file() or p.parent != EXAMPLES:
        raise HTTPException(404, f"no example '{name}'")
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


@app.post("/api/validate", response_model=ValidationResult)
def post_validate(raw: RawDataset) -> ValidationResult:
    """The readiness gate on everything that can be planned; unfinished records are set aside and listed,
    each also as a SET_ASIDE warning, instead of making the whole dataset unreadable."""
    ds, aside = lenient(raw)
    issues = [Issue(code="SET_ASIDE", severity="warning", object_type=a.object_type, object_id=a.object_id,
                    message=f"{SINGULAR[a.collection]} {a.label} is left out of planning until it is fixed: {a.reason}",
                    hint="Fix it or delete it; it comes back into the plan as soon as it is complete", field=a.field)
              for a in aside]
    issues += validate(ds)
    return ValidationResult(issues=issues, blocking=any(i.severity == "error" for i in issues), set_aside=aside,
                            setup=checklist(ds, aside))


@app.post("/api/network", response_model=NetworkView)
def post_network(raw: RawDataset) -> NetworkView:
    ds, _ = lenient(raw)
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


class ModelInfo(Out):
    id: ForecastModelId
    label: str
    family: str
    description: str


class ForecastModels(Out):
    models: list[ModelInfo]
    foundation: FoundationStatus


class ReleaseRequest(Out):
    dataset: Dataset
    keys: list[str] | None = None


class ReleaseResponse(Out):
    dataset: Dataset
    release: ReleaseResult


@app.get("/api/forecast/models", response_model=ForecastModels)
def forecast_models() -> ForecastModels:
    _, st = foundation.get()
    return ForecastModels(
        models=[ModelInfo(id=s.id, label=s.label, family=s.family, description=s.description) for s in SPECS.values()],
        foundation=FoundationStatus(**st.__dict__))


@app.post("/api/forecast", response_model=ForecastResult)
def post_forecast(ds: Dataset) -> ForecastResult:
    return run_forecast(ds)


@app.post("/api/forecast/release", response_model=ReleaseResponse)
def post_release(req: ReleaseRequest) -> ReleaseResponse:
    result = run_forecast(req.dataset)
    if not result.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before releasing a forecast")
    new, info = release(req.dataset, result, req.keys)
    return ReleaseResponse(dataset=new, release=info)


@app.post("/api/inventory", response_model=InventoryResult)
def post_inventory(ds: Dataset) -> InventoryResult:
    return run_inventory(ds)


class PlacementRequest(Out):
    dataset: Dataset
    keys: list[str] | None = None     # "location|product"; None: every stage whose recommendation differs


class PlacementResponse(Out):
    dataset: Dataset
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
    return PlacementResponse(dataset=new, applied=info)


@app.post("/api/sop", response_model=SopResult)
def post_sop(ds: Dataset) -> SopResult:
    return run_sop(ds)


class SopReleaseResponse(Out):
    dataset: Dataset
    release: SopRelease


@app.post("/api/sop/release", response_model=SopReleaseResponse)
def post_sop_release(ds: Dataset) -> SopReleaseResponse:
    result = run_sop(ds)
    if not result.ok:
        raise HTTPException(409, "the S&OP plan did not solve; fix the readiness issues first")
    new, info = release_sop(ds, result)
    return SopReleaseResponse(dataset=new, release=info)


class ScheduleRequest(Out):
    dataset: Dataset
    sequence: dict[str, list[str]] | None = None   # resource → operation keys, each run where it is listed;
                                                   # None = the start rule, local search and optimiser per settings
    hold: dict[str, float] | None = None           # order → not-before clock hour (the result's holds)


@app.post("/api/schedule", response_model=ScheduleResult)
def post_schedule(req: ScheduleRequest) -> ScheduleResult:
    return run_schedule(req.dataset, req.sequence, hold=req.hold)


class ScheduleCatalogue(Out):
    heuristics: list[Heuristic]
    profiles: list[Profile]


@app.get("/api/schedule/catalogue", response_model=ScheduleCatalogue)
def get_schedule_catalogue() -> ScheduleCatalogue:
    """The scheduling heuristics and the profiles that bundle a start rule, the search and the objective weights."""
    return ScheduleCatalogue(heuristics=HEURISTICS, profiles=PROFILES)


@app.post("/api/schedule/compare", response_model=ScheduleComparison)
def post_schedule_compare(ds: Dataset) -> ScheduleComparison:
    """Every start rule, the local search and the optimiser on the same window, scored with the current weights."""
    return compare_schedules(ds)


class ScheduleApplyRequest(ScheduleRequest):
    ids: list[str] | None = None       # scheduled orders to date; None = every order on the schedule


class ScheduleApplyResponse(Out):
    dataset: Dataset
    report: ApplyReport


@app.post("/api/schedule/apply", response_model=ScheduleApplyResponse)
def post_schedule_apply(req: ScheduleApplyRequest) -> ScheduleApplyResponse:
    """Fix the schedule's dates on its orders: planned ones become production orders, released ones are re-dated."""
    new, rep = apply_schedule(req.dataset, req.sequence, req.ids, req.hold)
    if not rep.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before using the schedule's dates")
    return ScheduleApplyResponse(dataset=new, report=rep)


@app.post("/api/promise", response_model=PromiseResult)
def post_promise(ds: Dataset) -> PromiseResult:
    return run_promise(ds)


@app.post("/api/promise/bop", response_model=PromiseResult)
def post_bop(ds: Dataset) -> PromiseResult:
    return run_bop(ds)


class PromiseCheckRequest(Out):
    dataset: Dataset
    order: DemandRecord


@app.post("/api/promise/check", response_model=PromiseResult)
def post_promise_check(req: PromiseCheckRequest) -> PromiseResult:
    return check_order(req.dataset, req.order)


class PromiseCommitRequest(Out):
    dataset: Dataset
    mode: Literal["entry", "bop"] = "entry"


class PromiseCommitResponse(Out):
    dataset: Dataset
    result: PromiseResult


@app.post("/api/promise/commit", response_model=PromiseCommitResponse)
def post_promise_commit(req: PromiseCommitRequest) -> PromiseCommitResponse:
    new, res = commit(req.dataset, req.mode)
    if not res.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before committing promises")
    return PromiseCommitResponse(dataset=new, result=res)


@app.post("/api/plan", response_model=PlanResult)
def post_plan(ds: Dataset) -> PlanResult:
    return run_mrp(ds)


@app.post("/api/capacity/level", response_model=LevelPreview)
def post_level(ds: Dataset) -> LevelPreview:
    """What planning within machine capacity moves: earlier, onto alternative machines, or later."""
    return level_preview(ds)


@app.post("/api/finance", response_model=FinanceResult)
def post_finance(ds: Dataset) -> FinanceResult:
    """The plan in money: cost reconciliation, inventory value, cost to serve, capacity investment NPV."""
    return run_finance(ds)


class ActualsRequest(Out):
    dataset: Dataset
    as_of: dt.date | None = None


@app.post("/api/actuals", response_model=ActualsView)
def post_actuals(req: ActualsRequest) -> ActualsView:
    return actuals_view(req.dataset, req.as_of)


class RollRequest(Out):
    dataset: Dataset
    as_of: dt.date


class RollResponse(Out):
    dataset: Dataset
    report: RollReport


@app.post("/api/actuals/roll", response_model=RollResponse)
def post_roll(req: RollRequest) -> RollResponse:
    new, rep = roll_forward(req.dataset, req.as_of)
    if not rep.ok:
        raise HTTPException(409, "; ".join(rep.warnings))
    return RollResponse(dataset=new, report=rep)


class FirmRequest(Out):
    dataset: Dataset
    ids: list[str] | None = None          # planned order ids; None = everything starting in the firm zone
    within_days: int | None = None        # overrides the dataset's firm zone


class FirmResponse(Out):
    dataset: Dataset
    report: FirmReport


@app.post("/api/orders/firm", response_model=FirmResponse)
def post_firm(req: FirmRequest) -> FirmResponse:
    new, rep = firm_orders(req.dataset, run_mrp(req.dataset), req.ids, req.within_days)
    if not rep.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before firming orders")
    return FirmResponse(dataset=new, report=rep)


# --- procure-to-pay (Phase E) --------------------------------------------------------------------
@app.post("/api/purchasing", response_model=PurchasingView)
def post_purchasing(ds: Dataset) -> PurchasingView:
    """Requisitions from the supply plan, every purchase order with its lines' status, and the supplier scorecard."""
    return purchasing_view(ds, run_mrp(ds))


class RequisitionPick(Out):
    id: str
    source_id: str | None = None
    qty: float | None = None


class CreatePoRequest(Out):
    dataset: Dataset
    lines: list[RequisitionPick] | None = None      # None = every requisition due now, on its planned source
    order_date: dt.date | None = None


class CreatePoResponse(Out):
    dataset: Dataset
    report: CreateReport


@app.post("/api/purchasing/create", response_model=CreatePoResponse)
def post_create_pos(req: CreatePoRequest) -> CreatePoResponse:
    plan = run_mrp(req.dataset)
    lines = None if req.lines is None else [x.model_dump(exclude_none=True) for x in req.lines]
    new, rep = create_purchase_orders(req.dataset, plan, lines, req.order_date)
    if not rep.ok:
        raise HTTPException(409, "the readiness gate has errors; fix them before ordering")
    return CreatePoResponse(dataset=new, report=rep)


class PoLineInput(Out):
    id: str
    qty: float | None = None
    date: dt.date | None = None
    price: float | None = None
    final: bool = False


class PoActionRequest(Out):
    dataset: Dataset
    action: Literal["approve", "send", "confirm", "receive", "change", "cancel"]
    po: str
    lines: list[PoLineInput] | None = None          # None = every open line, as ordered
    date: dt.date | None = None                     # sent on / received on (default: the planning start)
    reference: str = ""                             # the supplier's confirmation number
    note: str = ""                                  # delivery note on a goods receipt


class PoActionResponse(Out):
    dataset: Dataset
    report: ActionReport


@app.post("/api/purchasing/act", response_model=PoActionResponse)
def post_po_action(req: PoActionRequest) -> PoActionResponse:
    lines = None if req.lines is None else [x.model_dump(exclude_none=True) for x in req.lines]
    try:
        new, rep = purchasing_act(req.dataset, req.action, req.po, lines=lines, on=req.date, reference=req.reference,
                                  note=req.note)
    except PurchasingError as e:
        raise HTTPException(409, str(e)) from e
    return PoActionResponse(dataset=new, report=rep)


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
def list_versions() -> list[VersionMeta]:
    return get_store().list()


@app.post("/api/versions", response_model=VersionMeta)
def save_base(req: SaveBaseRequest) -> VersionMeta:
    return get_store().save_base(req.dataset, req.name, req.note)


@app.get("/api/versions/{vid}", response_model=VersionDoc)
def get_version(vid: str) -> VersionDoc:
    return get_store().get(vid)


@app.put("/api/versions/{vid}", response_model=VersionMeta)
def update_version(vid: str, ds: Dataset) -> VersionMeta:
    return get_store().update(vid, ds)


@app.post("/api/versions/{vid}/branch", response_model=VersionMeta)
def branch_version(vid: str, req: BranchRequest) -> VersionMeta:
    return get_store().branch(vid, req.name, req.note)


@app.post("/api/tower", response_model=TowerResult)
def post_tower(ds: Dataset) -> TowerResult:
    """KPIs, the exception worklist (recorded in the version store: first seen, owner, status) and data quality."""
    return run_tower(ds)


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
def update_work_item(iid: str, body: WorkItemUpdate) -> WorkItem:
    return get_tracker().update(iid, owner=body.owner, status=body.status, note=body.note, sla=body.sla_days)


@app.get("/api/tower/items/{iid}/history", response_model=list[WorkItemEntry])
def work_item_history(iid: str) -> list[WorkItemEntry]:
    return [WorkItemEntry(at=a, action=b, detail=c) for a, b, c in get_tracker().history(iid)]


@app.post("/api/versions/{vid}/discard", response_model=VersionMeta)
def discard_version(vid: str) -> VersionMeta:
    return get_store().discard(vid)


@app.post("/api/versions/{vid}/promote", response_model=VersionMeta)
def promote_version(vid: str, req: PromoteRequest) -> VersionMeta:
    return get_store().promote(vid, req.name, req.note)


@app.get("/api/versions/{a}/compare/{b}", response_model=Comparison)
def compare_versions(a: str, b: str) -> Comparison:
    st = get_store()
    return compare(st.dataset(a), st.dataset(b), a, b)


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
        f = (WEB_DIST / path).resolve()
        if path and f.is_file() and WEB_DIST in f.parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
