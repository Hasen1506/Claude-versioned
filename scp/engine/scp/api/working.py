"""The company kept on the server as the data of a planning call (Phase S, N77).

A browser working on a company kept on the server need not send the whole company with every planning call (71 MB
for 5,000 products at 20 places): it names the save its working copy was made from and sends what it changed since,

    {"$ref": {"revision": 41, "patch": {...}}}          # the company is the request's X-Company

in place of the dataset, whole or in a request's ``dataset`` field. The server reads that save, applies the changes,
sets aside unfinished records (:func:`scp.validate.lenient.lenient_checked`, as the browser's own planning view does)
and keeps the result for the next calls on the same data, so *Plan everything* reads the company once, not eleven
times. A call that changes the company (releasing a forecast, firming orders, …) then answers with what it changed
(``patch``) instead of the whole company, for the browser to apply to its working copy.

Only a member of the company may name it; a patch that does not fit the save named is refused (409, ``patch:
"unfit"``) and the browser sends the company whole instead.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import threading
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Annotated, Any
from collections.abc import Callable

from fastapi.responses import Response
from pydantic import BaseModel, BeforeValidator, TypeAdapter, ValidationError

from ..companies import CompanyError, get_companies
from ..companies.patch import PatchError, apply_patch, make_patch
from ..model import Dataset
from ..plan import mrp
from ..validate import validate
from ..validate.lenient import COLLECTION_TYPES, SetAside, lenient_checked

REF = "$ref"
KEEP = 2      # companies kept read (a large one takes about 1.5 GB): the latest save, and it with unsaved changes

#: who asks and in which company: set for each request by the API's gate
asker: ContextVar[tuple[str | None, str]] = ContextVar("asker", default=(None, ""))
#: the asker takes a compressed answer (``Accept-Encoding: gzip``): set by the gate
takes_gzip: ContextVar[bool] = ContextVar("takes_gzip", default=False)
PACK_FROM = 32 * 1024     # answers this big go compressed: a plan's JSON shrinks about twenty times
#: the asker reads lists of records sent as rows (``X-Pack: rows``, see :func:`pack_rows`): set by the gate
takes_rows: ContextVar[bool] = ContextVar("takes_rows", default=False)
ROWS_FROM = 256 * 1024    # answers this big go as rows to an asker who reads them
ROWS_MIN = 8              # lists this long, at least


@dataclass
class Read:
    """A company as read for planning: the dataset, the records set aside, and the readiness checks run on it."""
    key: tuple[str, int, str]
    ds: Dataset
    aside: list[SetAside]
    checked: list[Any] | None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """Stands for the data's content: the save and the changes on it (see :func:`scp.plan.mrp.run_mrp`)."""
        return f"ref:{self.key[0]}@{self.key[1]}#{self.key[2]}"


_kept: OrderedDict[tuple[str, int, str], Read] = OrderedDict()
_lock = threading.Lock()
_reading: dict[tuple[str, int, str], threading.Lock] = {}


def is_ref(v: Any) -> bool:
    return isinstance(v, dict) and REF in v


def _sha(patch: Any) -> str:
    if not patch:
        return ""
    return hashlib.sha256(json.dumps(patch, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]


def read(v: dict[str, Any]) -> Read:
    """The company a reference names, read (or kept from an earlier call on the same data)."""
    ref = v[REF]
    if not isinstance(ref, dict) or not isinstance(ref.get("revision"), int):
        raise CompanyError("a reference to the company names the revision its changes are based on", 422)
    token, cid = asker.get()
    if not cid:
        raise CompanyError("a reference to the company needs the company open (X-Company)", 422)
    companies = get_companies()
    user = companies.whoami(token)
    companies.role(user, cid)                    # a member of the company, whatever the role
    patch = ref.get("patch") or None
    key = (cid, int(ref["revision"]), _sha(patch))
    with _lock:
        hit = _kept.get(key)
        if hit is not None:
            _kept.move_to_end(key)
            return hit
        gate = _reading.setdefault(key, threading.Lock())
    with gate:                                   # two calls on the same new data read it once
        with _lock:
            hit = _kept.get(key)
            if hit is not None:
                return hit
        with _lock:
            base = _kept.get((cid, key[1], "")) if patch else None
        out = _on_base(base, key, patch) if base is not None else None
        if out is None:
            doc = json.loads(companies.text_at(user, cid, key[1]))
            if patch:
                try:
                    doc = apply_patch(doc, patch)
                except PatchError as e:
                    raise CompanyError(f"the changes sent do not fit revision {key[1]}: {e}; send the whole company",
                                       409, {"patch": "unfit"}) from None
            ds, aside, checked = lenient_checked(doc)
            del doc
            out = Read(key, ds, aside, checked)
        with _lock:
            _kept[key] = out
            while len(_kept) > KEEP:
                _kept.popitem(last=False)
            _reading.pop(key, None)
        return out


def _on_base(base: Read, key: tuple[str, int, str], patch: dict[str, Any]) -> Read | None:
    """The saved company ``base`` with ``patch`` applied, reading only the lists the patch changes and sharing every
    other one with it: a planner's unsaved edit costs its own lists, not a second copy of the whole company (about
    1.5 GB for 5,000 products at 20 places). None when anything is out of the ordinary (a record that would be set
    aside, a list removed): the company is then read whole."""
    if base.aside or patch.get("drop"):
        return None
    names = set(patch.get("set") or {}) | set(patch.get("lists") or {})
    fields = Dataset.model_fields
    if not names or not names <= set(fields):
        return None
    try:
        parts = base.ds.model_dump(mode="json", by_alias=True, include=names)
        parts = apply_patch(parts, {**patch, "sizes": {k: v for k, v in (patch.get("sizes") or {}).items() if k in names}})
        update = {n: TypeAdapter(fields[n].annotation).validate_python(parts[n]) for n in names}
    except (PatchError, ValidationError):
        return None
    ds = base.ds.model_copy(update=update)
    checked = validate(ds)
    # a changed record with a reference to nothing yet would be set aside: the whole reading does that
    kinds = {COLLECTION_TYPES[n] for n in names if n in COLLECTION_TYPES}
    if any(i.code == "REF_UNKNOWN" and i.object_type in kinds for i in checked):
        return None
    return Read(key, ds, [], checked)


def kept_read(ds: Dataset) -> Read | None:
    """The read company ``ds`` is, when it came by reference."""
    with _lock:
        for r in _kept.values():
            if r.ds is ds:
                return r
    return None


def forget() -> None:
    with _lock:
        _kept.clear()


def _dataset_or_ref(v: Any) -> Any:
    return read(v).ds if is_ref(v) else v


def _fingerprint(ds: Dataset) -> str | None:
    r = kept_read(ds)
    return r.fingerprint if r is not None else None


mrp.known_fingerprint = _fingerprint

#: A dataset in a request: the company whole, or a reference to the one kept on the server.
PlanData = Annotated[Dataset, BeforeValidator(_dataset_or_ref)]


def answer(before: Dataset, after: Dataset) -> dict[str, Any]:
    """The changed company for the answer: whole, or, when ``before`` came by reference, what changed (``patch``)."""
    if kept_read(before) is None:
        return {"dataset": after}
    changed = [f for f in Dataset.model_fields if getattr(before, f) is not getattr(after, f)
               and getattr(before, f) != getattr(after, f)]
    if not changed:
        return {"dataset": None, "patch": {"v": 1, "sizes": {}}}
    a = before.model_dump(mode="json", by_alias=True, include=set(changed))
    b = after.model_dump(mode="json", by_alias=True, include=set(changed))
    return {"dataset": None, "patch": make_patch(a, b)}


@dataclass(frozen=True)
class Body:
    """An answer ready to send: its bytes, whether they are compressed, and whether its lists go as rows."""
    data: bytes
    gz: bool
    rows: bool


def pack_rows(x: Any) -> Any:
    """``x`` with each list of records that share their fields sent as ``{"$cols": [...], "$rows": [[...], ...]}``:
    a plan's orders and a forecast's weeks repeat the same field names hundreds of thousands of times, and without
    them the answer is two to three times shorter for the browser to read (``web/src/api/client.ts`` unpacks it)."""
    if isinstance(x, list):
        if len(x) >= ROWS_MIN and type(x[0]) is dict:
            cols = list(x[0])
            if all(type(i) is dict and len(i) == len(cols) and i.keys() == x[0].keys() for i in x):
                return {"$cols": cols, "$rows": [[pack_rows(i[c]) for c in cols] for i in x]}
        return [pack_rows(i) for i in x]
    if isinstance(x, dict):
        return {k: pack_rows(v) for k, v in x.items()}
    return x


def _send(b: Body) -> Response:
    headers = {"X-Rows": "1"} if b.rows else {}
    if not b.gz:
        return Response(b.data, media_type="application/json", headers=headers)
    if takes_gzip.get():
        return Response(b.data, media_type="application/json",
                        headers={**headers, "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(gzip.decompress(b.data), media_type="application/json", headers=headers)


def _body(out: BaseModel, exclude: set[str] | None = None) -> Body:
    raw = out.model_dump_json(by_alias=True, exclude=exclude).encode()
    rows = takes_rows.get() and len(raw) >= ROWS_FROM
    if rows:
        raw = json.dumps(pack_rows(json.loads(raw)), separators=(",", ":"), ensure_ascii=False).encode()
    return Body(gzip.compress(raw, 1), True, rows) if len(raw) >= PACK_FROM else Body(raw, False, rows)


def send_raw(raw: bytes) -> Response:
    """JSON already written, compressed when large."""
    return _send(Body(gzip.compress(raw, 1), True, False) if len(raw) >= PACK_FROM else Body(raw, False, False))


def send(out: BaseModel) -> Response:
    """An answer written straight to JSON, compressed when large (see :func:`respond`)."""
    return _send(_body(out))


_making: dict[tuple, threading.Lock] = {}


def respond(name: str, ds: Dataset, make: Callable[[], BaseModel], *params: Any, exclude: set[str] | None = None) -> Response:
    """The answer to a call that only reads the company: written straight to JSON (three times faster than the
    generic path) and compressed when large; and, when the company came by reference, kept beside it, so the same
    call on the same data is answered at once (*Plan everything* again, a page opened again, another member)."""
    r = kept_read(ds)
    if r is None:
        return _send(_body(make(), exclude))
    key = (name, json.dumps(params, sort_keys=True, default=str), tuple(sorted(exclude or ())), takes_rows.get())
    with _lock:
        hit = r.extras.get(key)
        gate = None if hit is not None else _making.setdefault((r.key, key), threading.Lock())
    if hit is not None:
        return _send(hit)
    with gate:                                   # the same call twice at once works it out once
        with _lock:
            hit = r.extras.get(key)
        if hit is None:
            hit = _body(make(), exclude)
            with _lock:
                r.extras[key] = hit
                _making.pop((r.key, key), None)
    return _send(hit)
