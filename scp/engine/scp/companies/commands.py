"""Atomic, idempotent business commands over authoritative live company state.

The callback is trusted server code, never supplied by a client. A command carries
parameters, not a replacement company. Its effect, revision/audit and receipt
commit together; a replay returns the original result plus current company state.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field, ValidationError

from ..model import Dataset
from ..model.common import Model, Out
from ..transactions import atomic
from .store import CAN_EDIT, Companies, CompanyDoc, CompanyError, User, _canonical, _iso, _now
from .patch import keys_of

_MISSING = object()


def _changes(raw: Any, baseline: Any, changed: Any, name: str = "") -> Any:
    """Apply only the operation's delta, preserving unrelated raw/default shape.

    Parsing a minimal saved document fills schema defaults. Those defaults are
    not master-data edits and must not require unrelated departmental grants.
    """
    if baseline == changed:
        return raw
    if isinstance(baseline, dict) and isinstance(changed, dict):
        original = raw if isinstance(raw, dict) else {}
        result = dict(original)
        for key in baseline.keys() | changed.keys():
            if key not in changed:
                result.pop(key, None)
                continue
            value = _changes(original.get(key, _MISSING), baseline.get(key, _MISSING), changed[key], key)
            if value is not _MISSING:
                result[key] = value
        return result
    if isinstance(baseline, list) and isinstance(changed, list):
        original = raw if isinstance(raw, list) else []
        fields = keys_of(name)
        def identity(row):
            return tuple(row.get(key) for key in fields) if isinstance(row, dict) else None
        keys = [identity(row) for row in baseline]
        keyed = bool(keys) and all(key is not None and any(v is not None for v in key) for key in keys)
        lookup = {key: i for i, key in enumerate(keys)} if keyed else {}
        keyed = keyed and len(lookup) == len(keys)
        result = []
        for position, row in enumerate(changed):
            index = lookup.get(identity(row)) if keyed else position
            if index is None or index >= len(baseline):
                result.append(row)
            else:
                value = _changes(original[index] if index < len(original) else _MISSING, baseline[index], row)
                result.append(row if value is _MISSING else value)
        return result
    return changed


class CommandRequest(Model):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")
    base_revision: int = Field(ge=1)
    posting_date: date = Field(description="Explicit business date; never inferred from a planning scenario's start")
    kind: Literal["purchasing", "sales", "stock", "transport", "intercompany", "outside", "production_cost", "carrier_bank"]
    action: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict, max_length=40)


class CommandResult(Out):
    id: str
    revision: int                 # the revision at which the original command completed
    duplicate: bool
    engine_commit: str            # original implementation identity, even after an application upgrade
    result: dict[str, Any]
    company: CompanyDoc           # current authoritative state; never an old snapshot on replay


class CommandRecord(Out):
    id: str
    kind: str
    action: str
    posting_date: date
    revision: int
    at: str
    by: str
    engine_commit: str
    request_hash: str
    parameters: dict[str, Any]
    result: dict[str, Any]


def record(c: Companies, user: User, cid: str, identifier: str) -> CommandRecord:
    with c.lock.scoped("company", cid):
        c._need(user, cid)
        row = c.db.execute("SELECT * FROM company_commands WHERE company_id = ? AND command_id = ?",
                           (cid, identifier)).fetchone()
        if row is None:
            raise CompanyError("there is no completed command with that identifier", 404)
        return CommandRecord(id=row["command_id"], kind=row["kind"], action=row["action"], posting_date=row["posting_date"],
                             revision=row["revision"], at=row["at"], by=c._name(row["user_id"]),
                             engine_commit=row["engine_commit"], request_hash=row["request_hash"],
                             parameters=json.loads(row["parameters"]), result=json.loads(row["result"]))


def _record(c: Companies, cid: str, user: User, req: CommandRequest, digest: str, revision: int,
            result: dict[str, Any], parameters: dict[str, Any]) -> None:
    c.db.execute("INSERT INTO company_commands (company_id, command_id, user_id, kind, action, request_hash, posting_date, "
                 "revision, at, engine_commit, parameters, result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (cid, req.id, user.id, req.kind, req.action, digest, req.posting_date.isoformat(), revision, _iso(_now()),
                 os.environ.get("SCP_COMMIT", ""), _canonical(parameters), _canonical(result)))


def execute(c: Companies, user: User, cid: str, req: CommandRequest,
            operation: Callable[[Dataset], tuple[Dataset, dict[str, Any]]], *,
            receipt_parameters: dict[str, Any] | None = None) -> CommandResult:
    payload = {"kind": req.kind, "action": req.action, "posting_date": req.posting_date.isoformat(), "parameters": req.parameters}
    digest = hashlib.sha256(_canonical(payload).encode()).hexdigest()
    with c.lock.scoped("company", cid):
        c._need(user, cid, *CAN_EDIT)
        previous = c.db.execute("SELECT * FROM company_commands WHERE company_id = ? AND command_id = ?",
                                (cid, req.id)).fetchone()
        if previous is not None:
            if previous["request_hash"] != digest:
                raise CompanyError("this command identifier was already used with different parameters", 409)
            return CommandResult(id=req.id, revision=previous["revision"], duplicate=True,
                                 engine_commit=previous["engine_commit"], result=json.loads(previous["result"]),
                                 company=c.open(user, cid))
        with atomic(c.db):
            current = c.open(user, cid)
            if current.meta.revision != req.base_revision:
                raise CompanyError("the company changed; review its current state before issuing a new command", 409,
                                   {"revision": current.meta.revision})
            try:
                ds = Dataset.model_validate(current.dataset)
            except ValidationError as exc:
                raise CompanyError(f"complete the company's invalid data before posting: {exc}", 422) from None
            baseline = ds.model_dump(mode="json")
            changed, result = operation(ds)
            document = _changes(current.dataset, baseline, changed.model_dump(mode="json"))
            saved = c.save(user, cid, document, req.base_revision, action="posted",
                           allow_production_posting=req.kind == "production_cost",
                           count_projection=req.kind == "stock" and req.action == "count_post",
                           allow_carrier_bank=req.kind == "carrier_bank",
                           freight_action=req.action if req.kind == "transport" else "")
            if saved.held is not None:
                raise CompanyError("this command needs a master-data change that has not been approved; approve it "
                                   "before posting the transaction", 409)
            _record(c, cid, user, req, digest, saved.meta.revision, result,
                    req.parameters if receipt_parameters is None else receipt_parameters)
            return CommandResult(id=req.id, revision=saved.meta.revision, duplicate=False,
                                 engine_commit=os.environ.get("SCP_COMMIT", ""), result=result, company=c.open(user, cid))
