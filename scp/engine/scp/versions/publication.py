"""Release a reviewed receipt and backorder plan into authoritative company state."""
from __future__ import annotations

from datetime import date

from pydantic import Field, ValidationError

from ..companies.commands import CommandRequest, CommandResult, execute
from ..companies.store import Companies, CompanyDoc, User
from ..model import Dataset, ReceiptKind
from ..model.common import Model, Out
from ..model.transactional import ConfirmedDelivery
from ..promise import commit
from ..promise.result import OrderPromise
from ..purchasing import PurchasingError, confirm
from .store import VersionDoc, VersionError, canonical, sha


class PublicationRequest(Model):
    base_revision: int = Field(ge=1)
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ReceiptChange(Out):
    id: str
    before: date
    after: date
    before_quantity: float
    quantity: float
    previous_schedule: list[ConfirmedDelivery]
    schedule: list[ConfirmedDelivery]


class PublicationPreview(Out):
    base_revision: int
    plan_sha256: str
    receipts: list[ReceiptChange]
    orders: list[OrderPromise]
    exceptions: list[str]


_CONFIRMATION_FIELDS = {"confirmed_date", "confirmed_qty", "confirmations"}


def _prepare(live: CompanyDoc, scenario: VersionDoc, base: VersionDoc) -> tuple[Dataset, PublicationPreview]:
    if scenario.meta.status != "active" or base.meta.status != "active":
        raise VersionError("the scenario and its original base must be active; branch from the current company")
    try:
        current = Dataset.model_validate(live.dataset)
    except ValidationError as exc:
        raise VersionError(f"complete the live company's data before publishing: {exc}", 422) from None
    if canonical(current) != canonical(base.dataset):
        raise VersionError("the live data differs from this scenario's base; reopen the live company and prepare a new scenario")

    candidate = scenario.dataset
    allowed = {"receipts", "confirmations"}
    if candidate.model_dump(exclude=allowed) != current.model_dump(exclude=allowed):
        raise VersionError("this release supports purchase receipt acknowledgements and recalculated customer confirmations")
    if [r.id for r in current.receipts] != [r.id for r in candidate.receipts]:
        raise VersionError("a scenario release cannot add or remove open orders")

    changed = current
    changes = []
    for old, new in zip(current.receipts, candidate.receipts, strict=True):
        if old == new:
            continue
        if (old.kind is not ReceiptKind.PURCHASE or not old.po or new.confirmed_date is None
                or old.model_dump(exclude=_CONFIRMATION_FIELDS) != new.model_dump(exclude=_CONFIRMATION_FIELDS)):
            raise VersionError(f"{old.id}: only a purchase order acknowledgement can change in this release")
        try:
            changed, _ = confirm(changed, old.po, [{"id": old.id, "date": new.confirmed_date,
                                                   "qty": new.confirmed_qty, "parts": new.confirmations}])
        except (PurchasingError, ValueError) as exc:
            raise VersionError(str(exc)) from None
        confirmed = next(r for r in changed.receipts if r.id == old.id)
        if confirmed != new:
            raise VersionError(f"{old.id}: enter a complete supplier confirmation before publishing")
        changes.append(ReceiptChange(id=old.id, before=old.expected_date, after=new.expected_date,
                                     before_quantity=old.expected_qty, quantity=new.expected_qty,
                                     previous_schedule=old.confirmations, schedule=new.confirmations))

    released, result = commit(changed, "bop")
    if not result.ok:
        raise VersionError("the scenario does not pass planning validation", 422)
    if candidate.confirmations not in (current.confirmations, released.confirmations):
        raise VersionError("saved confirmations differ from the recalculated plan; review the supplier changes again")
    orders = [order for order in result.orders if order.change in ("lost", "gained", "changed")]
    exceptions = [f"{issue.object_id}: {issue.message}" for issue in result.issues if issue.code == "BOP_GROUP_STOPPED"]
    return released, PublicationPreview(base_revision=live.meta.revision, plan_sha256=sha(canonical(released)),
                                        receipts=changes, orders=orders, exceptions=exceptions)


def _review(c: Companies, user: User, cid: str, vid: str, reviewed: str | None) -> tuple[CompanyDoc, VersionDoc, VersionDoc]:
    if reviewed is None:
        raise VersionError("send the scenario's reviewed SHA-256 in If-Match", 428)
    with c.lock:
        c._need(user, cid, "owner")
        scenario, base = c.store.publication_source(vid, cid)
        if scenario.meta.sha256 != reviewed:
            raise VersionError("the scenario changed; open it and review it again", 412)
        return c.open(user, cid), scenario, base


def preview(c: Companies, user: User, cid: str, vid: str, reviewed: str | None) -> PublicationPreview:
    live, scenario, base = _review(c, user, cid, vid, reviewed)
    _, result = _prepare(live, scenario, base)
    return result


def publish(c: Companies, user: User, cid: str, vid: str, reviewed: str | None, req: PublicationRequest) -> CommandResult:
    store = c.store
    live, scenario, base = _review(c, user, cid, vid, reviewed)
    command = CommandRequest(id=f"scenario-publication:{vid}", base_revision=req.base_revision,
                             posting_date=scenario.dataset.settings.planning_start, kind="scenario_publication",
                             action="publish", parameters={"scenario": vid, "scenario_sha256": reviewed,
                                                           "plan_sha256": req.plan_sha256,
                                                           "reviewed_revision": req.base_revision})
    prepared = (_prepare(live, scenario, base)
                if scenario.meta.status == "active" and live.meta.revision == req.base_revision else None)

    def operation(_current: Dataset):
        if prepared is None:
            raise VersionError("the scenario or company changed; preview it again")
        released, result = prepared
        if result.plan_sha256 != req.plan_sha256:
            raise VersionError("the calculated plan changed; review the publication preview again", 412)
        version = store.promote(vid, scope=cid, expected_sha256=reviewed, released=released)
        return released, {"version": version.model_dump(mode="json"), "plan_sha256": result.plan_sha256,
                          "exceptions": result.exceptions}

    # Use the global lock because promotion and the company command both write in this transaction.
    with c.lock:
        c._need(user, cid, "owner")
        return execute(c, user, cid, command, operation)
