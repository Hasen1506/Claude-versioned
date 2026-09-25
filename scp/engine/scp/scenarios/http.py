"""Run the scenarios through the HTTP API, exactly as the web client calls it.

``HttpClient`` takes any session with ``get / post / put`` methods and ``.json()`` responses: FastAPI's
``TestClient`` in the test suite, or an ``httpx.Client(base_url=…)`` against a running server
(``python -m scp.scenarios --url http://localhost:8000``). Every dataset crosses the wire as JSON and is
parsed back into the typed models, so the checkpoints also prove that nothing is lost between calls.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from ..actuals import ActualsView, FirmReport, RollReport
from ..demand import ForecastResult, ReleaseResult
from ..finance import FinanceResult
from ..inventory import InventoryResult
from ..model import Dataset, DemandRecord
from ..plan import PlanResult
from ..promise import PromiseResult
from ..schedule import ScheduleResult
from ..sop import SopRelease, SopResult
from ..tower import TowerResult
from ..validate import Issue
from ..versions import Comparison, VersionDoc, VersionMeta
from .harness import ClientError

M = TypeVar("M", bound=BaseModel)


class Session(Protocol):
    def get(self, url: str, **kw: Any) -> Any: ...
    def post(self, url: str, **kw: Any) -> Any: ...
    def put(self, url: str, **kw: Any) -> Any: ...


def _ds(ds: Dataset) -> dict:
    return ds.model_dump(mode="json")


class HttpClient:
    name = "http"

    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- transport ------------------------------------------------------------------------------
    def _json(self, r: Any) -> Any:
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            raise ClientError(r.status_code, detail if isinstance(detail, str) else str(detail))
        return r.json()

    def _post(self, path: str, body: Any, model: type[M]) -> M:
        return model.model_validate(self._json(self.s.post(path, json=body)))

    def _pair(self, path: str, body: Any, key: str, model: type[M]) -> tuple[Dataset, M]:
        out = self._json(self.s.post(path, json=body))
        return Dataset.model_validate(out["dataset"]), model.model_validate(out[key])

    # ---- the stages -----------------------------------------------------------------------------
    def validate(self, ds: Dataset) -> list[Issue]:
        out = self._json(self.s.post("/api/validate", json=_ds(ds)))
        return [Issue.model_validate(i) for i in out["issues"]]

    def network(self, ds: Dataset) -> Any:
        from ..api.app import NetworkView    # the view model lives in the API layer
        return self._post("/api/network", _ds(ds), NetworkView)

    def forecast(self, ds: Dataset) -> ForecastResult:
        return self._post("/api/forecast", _ds(ds), ForecastResult)

    def release_forecast(self, ds: Dataset, keys: list[str] | None = None) -> tuple[Dataset, ReleaseResult]:
        return self._pair("/api/forecast/release", {"dataset": _ds(ds), "keys": keys}, "release", ReleaseResult)

    def inventory(self, ds: Dataset) -> InventoryResult:
        return self._post("/api/inventory", _ds(ds), InventoryResult)

    def sop(self, ds: Dataset) -> SopResult:
        return self._post("/api/sop", _ds(ds), SopResult)

    def release_sop(self, ds: Dataset) -> tuple[Dataset, SopRelease]:
        return self._pair("/api/sop/release", _ds(ds), "release", SopRelease)

    def plan(self, ds: Dataset) -> PlanResult:
        return self._post("/api/plan", _ds(ds), PlanResult)

    def schedule(self, ds: Dataset, sequence: dict[str, list[str]] | None = None) -> ScheduleResult:
        return self._post("/api/schedule", {"dataset": _ds(ds), "sequence": sequence}, ScheduleResult)

    def promise(self, ds: Dataset) -> PromiseResult:
        return self._post("/api/promise", _ds(ds), PromiseResult)

    def bop(self, ds: Dataset) -> PromiseResult:
        return self._post("/api/promise/bop", _ds(ds), PromiseResult)

    def check(self, ds: Dataset, order: DemandRecord) -> PromiseResult:
        return self._post("/api/promise/check", {"dataset": _ds(ds), "order": order.model_dump(mode="json")},
                          PromiseResult)

    def commit(self, ds: Dataset, mode: str = "entry") -> tuple[Dataset, PromiseResult]:
        return self._pair("/api/promise/commit", {"dataset": _ds(ds), "mode": mode}, "result", PromiseResult)

    def firm(self, ds: Dataset, ids: list[str] | None = None, within_days: int | None = None) -> tuple[Dataset, FirmReport]:
        return self._pair("/api/orders/firm", {"dataset": _ds(ds), "ids": ids, "within_days": within_days}, "report",
                          FirmReport)

    def actuals(self, ds: Dataset, as_of: dt.date | None = None) -> ActualsView:
        return self._post("/api/actuals", {"dataset": _ds(ds), "as_of": as_of.isoformat() if as_of else None},
                          ActualsView)

    def roll(self, ds: Dataset, as_of: dt.date) -> tuple[Dataset, RollReport]:
        return self._pair("/api/actuals/roll", {"dataset": _ds(ds), "as_of": as_of.isoformat()}, "report", RollReport)

    def finance(self, ds: Dataset) -> FinanceResult:
        return self._post("/api/finance", _ds(ds), FinanceResult)

    def tower(self, ds: Dataset) -> TowerResult:
        return self._post("/api/tower", _ds(ds), TowerResult)

    # ---- versions ---------------------------------------------------------------------------------
    def save_base(self, ds: Dataset, name: str, note: str = "") -> VersionMeta:
        return self._post("/api/versions", {"dataset": _ds(ds), "name": name, "note": note}, VersionMeta)

    def branch(self, vid: str, name: str, note: str = "") -> VersionMeta:
        return self._post(f"/api/versions/{vid}/branch", {"name": name, "note": note}, VersionMeta)

    def update_version(self, vid: str, ds: Dataset) -> VersionMeta:
        return VersionMeta.model_validate(self._json(self.s.put(f"/api/versions/{vid}", json=_ds(ds))))

    def get_version(self, vid: str) -> VersionDoc:
        return VersionDoc.model_validate(self._json(self.s.get(f"/api/versions/{vid}")))

    def discard(self, vid: str) -> VersionMeta:
        return self._post(f"/api/versions/{vid}/discard", None, VersionMeta)

    def promote(self, vid: str, name: str | None = None) -> VersionMeta:
        return self._post(f"/api/versions/{vid}/promote", {"name": name}, VersionMeta)

    def compare_versions(self, a: str, b: str) -> Comparison:
        return Comparison.model_validate(self._json(self.s.get(f"/api/versions/{a}/compare/{b}")))


__all__ = ["HttpClient"]
