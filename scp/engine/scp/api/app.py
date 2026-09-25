"""HTTP API. Deliberately thin: parse the dataset (pydantic), call the engine, return typed results.

The server is stateless in P0/P1: the client owns the dataset document and posts it with each
request. Plan versions and persistence arrive in P7/P8 (see docs/BLUEPRINT.md §10).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .. import __version__
from ..demand import ForecastResult, ReleaseResult, release, run_forecast
from ..demand import foundation
from ..demand.models import SPECS
from ..demand.result import FoundationStatus
from ..inventory import InventoryResult, run_inventory
from ..model import Dataset, DemandRecord, ForecastModelId
from ..model.common import Out
from ..network import build_graph, location_edges, location_layers
from ..plan import PlanResult, run_mrp
from ..promise import PromiseResult, check_order, commit, run_bop, run_promise
from ..schedule import ScheduleResult, run_schedule
from ..sop import SopRelease, SopResult, release_sop, run_sop
from ..validate import RULES, Issue, validate

ROOT = Path(__file__).resolve().parents[3]          # scp/
EXAMPLES = ROOT / "examples"
WEB_DIST = ROOT / "web" / "dist"

app = FastAPI(title="SCP — Supply Chain Planning", version=__version__,
              description="Typed network master data, readiness gate, demand planning, network MRP/DRP.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


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


class ValidationResult(Out):
    issues: list[Issue]
    blocking: bool


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
    return [RuleInfo(code=k, severity=v[0], description=v[1]) for k, v in RULES.items()]


@app.get("/api/schema")
def schema() -> dict:
    """JSON schema of the dataset, including ``x-unit`` / ``x-ref`` field metadata for forms."""
    return Dataset.model_json_schema()


@app.post("/api/validate", response_model=ValidationResult)
def post_validate(ds: Dataset) -> ValidationResult:
    issues = validate(ds)
    return ValidationResult(issues=issues, blocking=any(i.severity == "error" for i in issues))


@app.post("/api/network", response_model=NetworkView)
def post_network(ds: Dataset) -> NetworkView:
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
    sequence: dict[str, list[str]] | None = None   # resource → operation keys; None = EDD + local search


@app.post("/api/schedule", response_model=ScheduleResult)
def post_schedule(req: ScheduleRequest) -> ScheduleResult:
    return run_schedule(req.dataset, req.sequence)


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
