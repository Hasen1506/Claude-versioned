"""Optional foundation-model forecaster: Google's TimesFM.

TimesFM is a pretrained decoder-only transformer that forecasts a series zero-shot, without fitting
per-series parameters. Here it is *one more candidate* in the forecast competition: it is backtested
on the same rolling origins and scored with the same metric, and it only becomes a series' champion
where it measurably beats the statistical models on that series. Nothing downstream depends on it.

Enabling it (engine host only; the browser never downloads a model):

    pip install -e ".[timesfm]"            # installs timesfm[torch]
    export SCP_TIMESFM=1                    # opt in
    export SCP_TIMESFM_CHECKPOINT=google/timesfm-2.5-200m-pytorch   # default; or a local directory

Licensing matters for a planning system that runs a business. TimesFM 2.5 weights are Apache-2.0.
TimesFM 3.0 weights are released under a non-commercial licence, so a 3.0 checkpoint is refused
unless ``SCP_TIMESFM_ALLOW_NONCOMMERCIAL=1`` is set deliberately (evaluation only).
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

DEFAULT_CHECKPOINT = "google/timesfm-2.5-200m-pytorch"
MAX_CONTEXT = 1024
MAX_HORIZON = 256


class Provider(Protocol):
    name: str
    license: str

    def forecast(self, contexts: list[np.ndarray], horizon: int) -> list[np.ndarray]:
        """Point forecasts (median), one array of ``horizon`` values per context."""


@dataclass
class Status:
    enabled: bool
    available: bool
    model: str
    license: str
    detail: str


class _TimesFM25:
    """Adapter over ``timesfm.TimesFM_2p5_200M_torch``."""

    license = "Apache-2.0"

    def __init__(self, checkpoint: str):
        import timesfm  # noqa: PLC0415 — optional dependency
        import torch  # noqa: PLC0415

        torch.set_float32_matmul_precision("high")
        self.name = f"TimesFM 2.5 ({checkpoint})"
        self._model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(checkpoint)
        self._model.compile(timesfm.ForecastConfig(
            max_context=MAX_CONTEXT, max_horizon=MAX_HORIZON, normalize_inputs=True,
            use_continuous_quantile_head=True, force_flip_invariance=True, infer_is_positive=True,
            fix_quantile_crossing=True,
        ))

    def forecast(self, contexts: list[np.ndarray], horizon: int) -> list[np.ndarray]:
        if horizon > MAX_HORIZON:
            raise ValueError(f"TimesFM horizon is limited to {MAX_HORIZON} periods")
        # the library pads the list it is given in place, so hand it a copy
        points, _ = self._model.forecast(horizon=horizon, inputs=[np.asarray(c, dtype=np.float32) for c in contexts])
        return [np.maximum(np.asarray(p, dtype=float), 0.0) for p in points]


_lock = threading.Lock()
_provider: Provider | None = None
_status: Status | None = None


def _noncommercial(checkpoint: str) -> bool:
    c = checkpoint.lower()
    return "timesfm-3" in c or "timesfm3" in c


def _load() -> tuple[Provider | None, Status]:
    checkpoint = os.environ.get("SCP_TIMESFM_CHECKPOINT", DEFAULT_CHECKPOINT)
    if os.environ.get("SCP_TIMESFM", "") not in ("1", "true", "yes"):
        return None, Status(False, False, checkpoint, "", "Off. Set SCP_TIMESFM=1 on the engine host to enable.")
    if _noncommercial(checkpoint) and os.environ.get("SCP_TIMESFM_ALLOW_NONCOMMERCIAL") != "1":
        return None, Status(True, False, checkpoint, "non-commercial",
                            "TimesFM 3.0 weights are licensed for non-commercial use only. Use a 2.5 checkpoint, "
                            "or set SCP_TIMESFM_ALLOW_NONCOMMERCIAL=1 for evaluation.")
    try:
        if _noncommercial(checkpoint):
            raise RuntimeError("the TimesFM 3.0 adapter is not implemented; use a 2.5 checkpoint")
        p = _TimesFM25(checkpoint)
    except ImportError:
        return None, Status(True, False, checkpoint, "", 'Not installed. Run pip install -e ".[timesfm]".')
    except Exception as e:  # noqa: BLE001 — download/compile failures are reported, never fatal
        return None, Status(True, False, checkpoint, "", f"Could not load: {e}")
    return p, Status(True, True, p.name, p.license, "Loaded")


def get() -> tuple[Provider | None, Status]:
    """The provider if one is enabled and loads, plus a status for the UI. Loaded once per process."""
    global _provider, _status
    with _lock:
        if _status is None:
            _provider, _status = _load()
        return _provider, _status


def set_provider(p: Provider | None) -> None:
    """Install a provider directly (tests, or an embedding application). ``None`` resets to env config."""
    global _provider, _status
    with _lock:
        if p is None:
            _provider, _status = None, None
        else:
            _provider = p
            _status = Status(True, True, p.name, p.license, "Loaded")
