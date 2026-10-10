"""Watching the running server (ENTERPRISE_PLAN 1.2).

* **Request id**: every answer carries ``X-Request-ID`` (the caller's own, when it sends a sensible one, so a proxy's
  id runs through), and every log line written while the request is answered names it.
* **Logs**: one line per API call (method, route, status, milliseconds, request id), never the body, the query or who
  asked. ``SCP_LOG_FORMAT=json`` writes every line as one JSON object (for a log service); otherwise plain text.
* **Metrics**: ``GET /api/metrics`` in the Prometheus text format: calls by route and status, time taken by route
  (a histogram), calls under way, plans and other calculations run, the process's start. The counts are this
  process's (with several server processes, the scraper adds them up per instance). With ``SCP_METRICS_TOKEN`` set,
  the page needs ``Authorization: Bearer <token>``.
* **Errors**: with ``SCP_SENTRY_DSN`` set and the ``sentry-sdk`` package installed, unexpected errors are reported
  there too (with the request id; never the request body).
"""
from __future__ import annotations

import contextvars
import hmac
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections import defaultdict

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
log = logging.getLogger("scp.request")
STARTED = time.time()
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
_SANE_ID = re.compile(r"[A-Za-z0-9._:-]{1,64}")


def commit() -> str:
    """The build's commit: ``SCP_COMMIT`` (set by the image build), or the one the host says it deployed."""
    for k in ("SCP_COMMIT", "RENDER_GIT_COMMIT", "SOURCE_COMMIT", "GIT_COMMIT"):
        v = os.environ.get(k, "").strip()
        if v:
            return v[:40]
    return ""


class _WithRequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request id, and the fields a line was given."""

    FIELDS = ("method", "route", "status", "ms")

    def format(self, record: logging.LogRecord) -> str:
        out = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
               "level": record.levelname.lower(), "logger": record.name, "message": record.getMessage()}
        rid = getattr(record, "request_id", "")
        if rid:
            out["request_id"] = rid
        for k in self.FIELDS:
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["error"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


JsonFormatter.converter = time.gmtime  # type: ignore[assignment]


def setup_logging() -> None:
    """Send the server's own lines (and uvicorn's errors) to standard output, as JSON with ``SCP_LOG_FORMAT=json``.
    uvicorn's own access line is switched off then: this module writes one with the request id."""
    as_json = os.environ.get("SCP_LOG_FORMAT", "").strip().lower() == "json"
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_WithRequestId())
    handler.setFormatter(JsonFormatter() if as_json else
                         logging.Formatter("%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    scp = logging.getLogger("scp")
    if not any(getattr(h, "_scp", False) for h in scp.handlers):
        handler._scp = True  # type: ignore[attr-defined]
        scp.addHandler(handler)
        scp.setLevel(os.environ.get("SCP_LOG_LEVEL", "INFO").upper())
        scp.propagate = False
    if as_json:
        logging.getLogger("uvicorn.access").disabled = True
        for name in ("uvicorn", "uvicorn.error"):
            for h in logging.getLogger(name).handlers:
                h.setFormatter(JsonFormatter())
    _sentry()


def _sentry() -> None:
    dsn = os.environ.get("SCP_SENTRY_DSN", "").strip()
    if not dsn:
        return
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:
        logging.getLogger("scp").warning("SCP_SENTRY_DSN is set but the sentry-sdk package is not installed")
        return
    sentry_sdk.init(dsn=dsn, release=commit() or None, send_default_pii=False,
                    environment=os.environ.get("SCP_ENV", "") or None, traces_sample_rate=0.0)


class Metrics:
    """This process's counts since it started (thread-safe)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.calls: dict[tuple[str, str, int], int] = defaultdict(int)
        self.hist: dict[str, list[int]] = defaultdict(lambda: [0] * (len(BUCKETS) + 1))
        self.seconds: dict[str, float] = defaultdict(float)
        self.under_way = 0

    def start(self) -> None:
        with self.lock:
            self.under_way += 1

    def done(self, method: str, route: str, status: int, seconds: float) -> None:
        with self.lock:
            self.under_way -= 1
            self.calls[(method, route, status)] += 1
            h = self.hist[route]
            for i, b in enumerate(BUCKETS):
                if seconds <= b:
                    h[i] += 1
                    break
            else:
                h[-1] += 1
            self.seconds[route] += seconds

    def text(self) -> str:
        def esc(v: str) -> str:
            return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        with self.lock:
            lines = ["# HELP scp_requests_total API calls answered, by route and status.",
                     "# TYPE scp_requests_total counter"]
            for (m, r, s), n in sorted(self.calls.items()):
                lines.append(f'scp_requests_total{{method="{m}",route="{esc(r)}",status="{s}"}} {n}')
            lines += ["# HELP scp_request_seconds Time taken to answer, by route.",
                      "# TYPE scp_request_seconds histogram"]
            for r, h in sorted(self.hist.items()):
                acc = 0
                for b, n in zip(BUCKETS, h, strict=False):
                    acc += n
                    lines.append(f'scp_request_seconds_bucket{{route="{esc(r)}",le="{b}"}} {acc}')
                acc += h[-1]
                lines.append(f'scp_request_seconds_bucket{{route="{esc(r)}",le="+Inf"}} {acc}')
                lines.append(f'scp_request_seconds_sum{{route="{esc(r)}"}} {self.seconds[r]:.6f}')
                lines.append(f'scp_request_seconds_count{{route="{esc(r)}"}} {acc}')
            lines += ["# HELP scp_requests_in_progress API calls being answered now.",
                      "# TYPE scp_requests_in_progress gauge", f"scp_requests_in_progress {self.under_way}",
                      "# HELP scp_process_start_time_seconds When this server process started (Unix time).",
                      "# TYPE scp_process_start_time_seconds gauge", f"scp_process_start_time_seconds {STARTED:.0f}"]
            info = f'version="{esc(_version())}",commit="{esc(commit())}"'
            lines += ["# HELP scp_build_info The running build.", "# TYPE scp_build_info gauge",
                      f"scp_build_info{{{info}}} 1"]
        return "\n".join(lines) + "\n"


def _version() -> str:
    from .. import __version__
    return __version__


metrics = Metrics()


def _route(request: Request) -> str:
    """The route's pattern (``/api/companies/{cid}``), never the address with its ids; ``other`` off the API."""
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    if path:
        return path
    return "unmatched" if request.url.path.startswith("/api/") else "other"


async def observe(request: Request, call_next) -> Response:
    """Outermost middleware: the request id, the time taken, one log line, the counts."""
    given = request.headers.get("x-request-id", "")
    rid = given if _SANE_ID.fullmatch(given) else uuid.uuid4().hex
    token = request_id.set(rid)
    t0 = time.perf_counter()
    metrics.start()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    except Exception:
        log.exception("unexpected error answering %s %s", request.method, _route(request))
        raise
    finally:
        took = time.perf_counter() - t0
        route = _route(request)
        metrics.done(request.method, route, status, took)
        if request.url.path.startswith("/api/") and route != "/api/health":
            log.log(logging.WARNING if status >= 500 else logging.INFO, "%s %s %s %.0f ms", request.method, route,
                    status, took * 1000, extra={"method": request.method, "route": route, "status": status,
                                                "ms": round(took * 1000, 1)})
        request_id.reset(token)


def metrics_page(request: Request) -> Response:
    want = os.environ.get("SCP_METRICS_TOKEN", "").strip()
    if want:
        got = request.headers.get("authorization", "")
        if not hmac.compare_digest(got.encode(), f"Bearer {want}".encode()):
            return PlainTextResponse("metrics need the token (SCP_METRICS_TOKEN)\n", status_code=401)
    return PlainTextResponse(metrics.text(), media_type="text/plain; version=0.0.4")
