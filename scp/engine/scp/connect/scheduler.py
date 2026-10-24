"""The server's clock for connections (Phase Q): every half minute it runs the scheduled imports whose time has come
and sends the worklist reminders that are due. With several server processes on one database, one of them runs it
(the first to ask; the next takes over when it stops, see scp.dblock), so an import never runs twice.
``SCP_SCHEDULER=0`` switches it off in a process."""
from __future__ import annotations

import datetime as dt
import logging
import os
import threading
import time

from ..companies import get_companies

log = logging.getLogger("scp.connect")
EVERY = 30.0


def tick(now: dt.datetime | None = None) -> None:
    """One round: imports due, then reminders due."""
    from .imports import run_due
    from .outbox import remind_due

    c = get_companies()
    now = now or dt.datetime.now(dt.UTC)
    try:
        run_due(c, now)
    except Exception:  # noqa: BLE001 - one bad round must not stop the clock
        log.exception("scheduled imports failed")
    try:
        remind_due(c, now)
    except Exception:  # noqa: BLE001
        log.exception("worklist reminders failed")


def start() -> threading.Thread | None:
    if os.environ.get("SCP_SCHEDULER", "1").strip().lower() in ("0", "off", "no", "false"):
        return None

    def run() -> None:
        from ..versions.store import get_store
        while True:
            time.sleep(EVERY)
            try:
                leads = get_store().lock.lead("clock")
            except Exception:  # noqa: BLE001 - a database that cannot be reached now is tried again next round
                log.exception("could not reach the database for the clock")
                continue
            if leads:
                tick()

    t = threading.Thread(target=run, name="scp-connections", daemon=True)
    t.start()
    return t
