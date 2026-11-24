"""Supplier payment reservations, independent approval, and ISO 20022 file generation."""
from datetime import date
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal
from xml.etree import ElementTree as XML

from pydantic import Field, StringConstraints, model_validator

from .camt_statements import bank_account_hash, file_evidence
from .carrier_accounts import BankAccounts
from .model import Dataset
from .model.carrier_bank import (CAMT_MAX_BYTES, MAX_BANK_MINOR, BankAccountId, SupplierInstructionLeg,
                                 SupplierInstructionRejection, SupplierPaymentInstruction)
from .model.common import Id, Model, Out
from .model.currency import MATERIAL_CURRENCIES, material_units, require_posting_currency

PAIN_NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.09"
STATUS_NS = "urn:iso:std:iso:20022:tech:xsd:pain.002.001.10"


class BankParty(Model):
    name: str = Field(min_length=1, max_length=140)
    bic: str = Field(pattern=r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
    iban: str = Field("", max_length=34)
    local_account: str = Field("", pattern=r"^[A-Za-z0-9/-]{0,34}$")

    @model_validator(mode="after")
    def valid_account(self):
        if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or char in ("\ufffe", "\uffff") for char in self.name):
            raise ValueError("party names must contain printable XML characters")
        if bool(self.iban) == bool(self.local_account):
            raise ValueError("provide exactly one IBAN or local account identifier")
        self.account_hash()
        return self

    def account_hash(self) -> str:
        return bank_account_hash(iban=self.iban, bic=self.bic, local=self.local_account)


class PaymentRouting(Model):
    debtor: BankParty
    creditor: BankParty

    def digest(self) -> str:
        return sha256(self.model_dump_json().encode()).hexdigest()


class ProposeSupplierPayment(Model):
    kind: Literal["propose_supplier_payment"]
    account: BankAccountId
    execute_on: date
    legs: list[SupplierInstructionLeg] = Field(min_length=1, max_length=100)
    routing: PaymentRouting


class ApproveSupplierPayment(Model):
    kind: Literal["approve_supplier_payment"]
    instruction: Id
    routing: PaymentRouting


class CancelSupplierPayment(Model):
    kind: Literal["cancel_supplier_payment"]
    instruction: Id


class RejectSupplierPayment(Model):
    kind: Literal["reject_supplier_payment"]
    instruction: Id
    xml: Annotated[str, StringConstraints(min_length=1, max_length=CAMT_MAX_BYTES, strip_whitespace=False)]

    def receipt_event(self) -> dict:
        data, digest = file_evidence(self.xml)
        return {"kind": self.kind, "instruction": self.instruction, "file_sha256": digest, "byte_count": len(data)}


InstructionChange = ProposeSupplierPayment | ApproveSupplierPayment | CancelSupplierPayment | RejectSupplierPayment
INSTRUCTION_CHANGES = (ProposeSupplierPayment, ApproveSupplierPayment, CancelSupplierPayment, RejectSupplierPayment)


class SupplierPaymentFile(Out):
    filename: str
    sha256: str
    xml: str


def instruction_for(ds: Dataset, identifier: str) -> SupplierPaymentInstruction:
    instruction = next((row for row in ds.supplier_payment_instructions if row.id == identifier), None)
    if instruction is None:
        raise ValueError("select a supplier payment instruction in this company")
    return instruction


def require_payment_grant(ds: Dataset, actor: str) -> None:
    if actor not in {email.strip().lower() for email in ds.finance.control_roles.get("payments", [])}:
        raise PermissionError("supplier bank posting and instructions require an explicit company payments grant")


def _routing(ds: Dataset, account_id: str, routing: PaymentRouting) -> None:
    account = BankAccounts(ds).by_id.get(account_id)
    if not account or not account.camt_source or account.camt_source.account_sha256 != routing.debtor.account_hash():
        raise ValueError("the debtor account must identify the registered account's native bank source")
    if routing.creditor.account_hash() == routing.debtor.account_hash():
        raise ValueError("the creditor must use a separate bank account")


def _replace(ds: Dataset, row: SupplierPaymentInstruction) -> Dataset:
    return ds.model_copy(update={"supplier_payment_instructions": [
        row if item.id == row.id else item for item in ds.supplier_payment_instructions]})


def _rejection(request: RejectSupplierPayment, day: date, actor: str) -> SupplierInstructionRejection:
    data, digest = file_evidence(request.xml)
    if b"\x00" in data or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("the bank status file cannot contain a document type or entity declaration")
    try:
        document = XML.fromstring(request.xml)
    except XML.ParseError:
        raise ValueError("the bank status XML is malformed") from None
    ns = {"": STATUS_NS}

    def one(node: XML.Element, path: str) -> XML.Element:
        matches = node.findall(path, ns)
        if len(matches) != 1:
            raise ValueError(f"final bank rejection requires exactly one {path}")
        return matches[0]

    if document.tag != f"{{{STATUS_NS}}}Document" or len(document) != 1:
        raise ValueError("use a native pain.002.001.10 payment status report")
    report = one(document, "CstmrPmtStsRpt")
    group = one(report, "OrgnlGrpInfAndSts")
    payment = one(report, "OrgnlPmtInfAndSts")
    transfer = one(payment, "TxInfAndSts")
    if (one(group, "OrgnlMsgId").text != request.instruction
            or one(group, "OrgnlMsgNmId").text != "pain.001.001.09"
            or one(payment, "OrgnlPmtInfId").text != request.instruction
            or one(transfer, "OrgnlEndToEndId").text != request.instruction
            or one(transfer, "TxSts").text != "RJCT"):
        raise ValueError("the bank status must reject the original message, payment and transfer identifiers")
    for node, tag in ((group, "GrpSts"), (payment, "PmtInfSts")):
        reported = node.findall(tag, ns)
        if reported and (len(reported) != 1 or reported[0].text != "RJCT"):
            raise ValueError("the rejection conflicts with the aggregate bank status")
    return SupplierInstructionRejection(date=day, by=actor, message=one(report, "GrpHdr/MsgId").text or "",
                                        reason=one(transfer, "StsRsnInf/Rsn/Cd").text or "", file_sha256=digest)


def record_instruction(ds: Dataset, request: InstructionChange, day: date, actor: str, identifier: str) -> tuple[Dataset, str]:
    from .purchasing.payables import invoice_entity, pay_invoice, still_blocked

    require_payment_grant(ds, actor)
    if isinstance(request, ProposeSupplierPayment):
        account = BankAccounts(ds).by_id.get(request.account)
        _routing(ds, request.account, request.routing)
        if request.execute_on < day or request.execute_on < account.camt_source.starts_on:
            raise ValueError("request a payment date on or after proposal and account enrollment")
        if ds.finance.closed_through and request.execute_on <= ds.finance.closed_through:
            raise ValueError("request a payment date in an open accounting period")
        digits = material_units(account.currency)
        if account.currency not in MATERIAL_CURRENCIES:
            require_posting_currency(account.currency)
        invoices = {invoice.id: invoice for invoice in ds.supplier_invoices}
        legs = sorted(request.legs, key=lambda leg: leg.invoice)
        if len({leg.invoice for leg in legs}) != len(legs) or sum(leg.amount_minor for leg in legs) > MAX_BANK_MINOR:
            raise ValueError("select each invoice once and keep the payment within the supported bank amount")
        suppliers = set()
        for leg in legs:
            invoice = invoices.get(leg.invoice)
            if invoice is None or invoice.credit or (invoice.currency or ds.settings.currency) != account.currency:
                raise ValueError("propose a transfer for ordinary invoices in the account currency")
            company = invoice.entity if invoice.entity is not None else invoice_entity(ds, invoice.lines)
            if company != account.company:
                raise ValueError("the invoice belongs to a different paying entity")
            suppliers.add(invoice.supplier)
            pay_invoice(ds, invoice.id, digits.major(leg.amount_minor), request.execute_on, identifier,
                        bank_account=account.id if digits.digits != 2 else None, dated_review=True)
        if len(suppliers) != 1:
            raise ValueError("one payment instruction must name one supplier")
        row = SupplierPaymentInstruction(id=identifier, account=account.id, currency=account.currency,
            supplier=next(iter(suppliers)), execute_on=request.execute_on, proposed_on=day, proposed_by=actor,
            routing_sha256=request.routing.digest(), legs=legs)
        return ds.model_copy(update={"supplier_payment_instructions": [*ds.supplier_payment_instructions, row]}), (
            f"Proposed {row.id}. A second person must verify and approve the instruction.")
    current = instruction_for(ds, request.instruction)
    if isinstance(request, RejectSupplierPayment):
        if not current.reserved or not current.approved_on or day < current.approved_on:
            raise ValueError("select an approved instruction awaiting a bank outcome")
        if actor == current.proposed_by:
            raise PermissionError("a different person must review the bank rejection")
        rejected = _rejection(request, day, actor)
        if any(row.account == current.account and row.rejection and row.rejection.message == rejected.message
               for row in ds.supplier_payment_instructions):
            raise ValueError("the bank rejection message is already retained")
        return _replace(ds, current.model_copy(update={"rejection": rejected})), (
            f"Recorded final bank rejection for {current.id}. Its invoices are available again.")
    if not current.reserved or current.approved_on:
        raise ValueError("only pending proposals can be approved or cancelled")
    if day < current.proposed_on:
        raise ValueError("the decision cannot precede the proposal")
    if isinstance(request, ApproveSupplierPayment):
        if actor == current.proposed_by:
            raise PermissionError("a different person must independently approve the instruction")
        if day > current.execute_on or (ds.finance.closed_through and current.execute_on <= ds.finance.closed_through):
            raise ValueError("the requested execution date has passed or closed")
        _routing(ds, current.account, request.routing)
        if request.routing.digest() != current.routing_sha256:
            raise ValueError("the independently reviewed routing differs from the proposal")
        invoiced = {invoice.id: invoice for invoice in ds.supplier_invoices}
        if any(still_blocked(ds, invoiced[leg.invoice], current.execute_on) for leg in current.legs):
            raise ValueError("a proposed invoice is blocked on its requested payment date")
        if ds.finance.separate_payments and any(actor in (invoiced[leg.invoice].entered_by.lower(),
                                                         invoiced[leg.invoice].released_by.lower()) for leg in current.legs):
            raise PermissionError("payment approval requires a different person from the invoice entrant and releaser")
        return _replace(ds, current.model_copy(update={"approved_on": day, "approved_by": actor})), f"Approved {current.id}."
    return _replace(ds, current.model_copy(update={"cancelled_on": day, "cancelled_by": actor})), f"Cancelled {current.id}."


def payment_file(ds: Dataset, identifier: str, routing: PaymentRouting, actor: str) -> SupplierPaymentFile:
    require_payment_grant(ds, actor)
    instruction = instruction_for(ds, identifier)
    if not instruction.approved_on or not instruction.reserved:
        raise ValueError("only approved unsettled instructions can produce a payment file")
    if instruction.approved_by != actor:
        raise PermissionError("the independent approver must export the payment file")
    _routing(ds, instruction.account, routing)
    if routing.digest() != instruction.routing_sha256:
        raise ValueError("routing differs from the approved instruction")

    def element(parent: XML.Element, tag: str, value: str, **attributes: str):
        XML.SubElement(parent, tag, attributes).text = value

    def party(parent: XML.Element, tag: str, details: BankParty) -> None:
        element(XML.SubElement(parent, tag), "Nm", details.name)

    def account(parent: XML.Element, tag: str, details: BankParty) -> None:
        identity = XML.SubElement(XML.SubElement(parent, tag), "Id")
        if details.iban:
            element(identity, "IBAN", details.iban)
        else:
            element(XML.SubElement(identity, "Othr"), "Id", details.local_account)

    def agent(parent: XML.Element, tag: str, details: BankParty) -> None:
        element(XML.SubElement(XML.SubElement(parent, tag), "FinInstnId"), "BICFI", details.bic)

    amount = format(Decimal(instruction.amount_minor).scaleb(-material_units(instruction.currency).digits), "f")
    document = XML.Element("Document", xmlns=PAIN_NS)
    message = XML.SubElement(document, "CstmrCdtTrfInitn")
    group = XML.SubElement(message, "GrpHdr")
    element(group, "MsgId", instruction.id)
    element(group, "CreDtTm", f"{instruction.approved_on.isoformat()}T00:00:00Z")
    element(group, "NbOfTxs", "1")
    element(group, "CtrlSum", amount)
    party(group, "InitgPty", routing.debtor)
    info = XML.SubElement(message, "PmtInf")
    element(info, "PmtInfId", instruction.id)
    element(info, "PmtMtd", "TRF")
    element(info, "NbOfTxs", "1")
    element(info, "CtrlSum", amount)
    element(XML.SubElement(info, "ReqdExctnDt"), "Dt", instruction.execute_on.isoformat())
    party(info, "Dbtr", routing.debtor)
    account(info, "DbtrAcct", routing.debtor)
    agent(info, "DbtrAgt", routing.debtor)
    transfer = XML.SubElement(info, "CdtTrfTxInf")
    element(XML.SubElement(transfer, "PmtId"), "EndToEndId", instruction.id)
    element(XML.SubElement(transfer, "Amt"), "InstdAmt", amount, Ccy=instruction.currency)
    agent(transfer, "CdtrAgt", routing.creditor)
    party(transfer, "Cdtr", routing.creditor)
    account(transfer, "CdtrAcct", routing.creditor)
    element(XML.SubElement(transfer, "RmtInf"), "Ustrd", instruction.id)
    payload = XML.tostring(document, encoding="utf-8", xml_declaration=True)
    return SupplierPaymentFile(filename=f"{instruction.id}.xml", sha256=sha256(payload).hexdigest(), xml=payload.decode())


def protect_instructions(old: Dataset, new: Dataset, action: str, actor: str) -> None:
    prior, retained = old.supplier_payment_instructions, new.supplier_payment_instructions
    if prior != retained:
        if action not in ("propose_supplier_payment", "approve_supplier_payment", "cancel_supplier_payment", "reject_supplier_payment",
                          "clear_supplier_statement"):
            raise ValueError("supplier instructions require an authoritative payment command")
        email = actor.strip().lower()
        require_payment_grant(old, email)
        if action == "propose_supplier_payment":
            if len(retained) != len(prior) + 1 or prior != retained[:-1] or retained[-1].proposed_by != email:
                raise ValueError("a proposal appends one instruction from the signed-in actor")
            proposed = retained[-1]
            if not proposed.reserved or proposed.approved_on or proposed.approved_by or proposed.cancelled_by:
                raise ValueError("a new instruction starts as an unsigned proposal")
        else:
            changes = [(a, b) for a, b in zip(prior, retained, strict=False) if a != b]
            if len(prior) != len(retained) or len(changes) != 1:
                raise ValueError("an instruction decision updates exactly one retained instruction")
            a, b = changes[0]
            if not a.reserved:
                raise ValueError("an instruction's final state is retained")
            fields = {"approve_supplier_payment": {"approved_on", "approved_by"},
                      "cancel_supplier_payment": {"cancelled_on", "cancelled_by"},
                      "reject_supplier_payment": {"rejection"},
                      "clear_supplier_statement": {"statement_line"}}[action]
            if a.model_dump(exclude=fields) != b.model_dump(exclude=fields):
                raise ValueError("the original payment instruction and decision history are retained")
            if action == "approve_supplier_payment" and (a.approved_on or not b.approved_on or b.approved_by != email or a.proposed_by == email):
                raise ValueError("approval requires the signed-in independent reviewer")
            if action == "cancel_supplier_payment" and (a.approved_on or not b.cancelled_on or b.cancelled_by != email):
                raise ValueError("only an unapproved instruction can be cancelled")
            if action == "reject_supplier_payment" and (not a.approved_on or not b.rejection or b.rejection.by != email
                                                         or a.proposed_by == email or b.rejection.date < a.approved_on):
                raise ValueError("a rejected instruction requires independent review of the final bank status")
            if action == "clear_supplier_statement" and (not a.approved_on or not b.statement_line):
                raise ValueError("only an approved instruction can be settled")
    lines = {line.id: line for line in new.carrier_bank_lines if line.supplier_clearing and line.supplier_clearing.instruction}
    settled = {row.statement_line: row for row in retained if row.statement_line}
    if lines.keys() != settled.keys() or any(lines[key].supplier_clearing.instruction != row.id for key, row in settled.items()):
        raise ValueError("a settled instruction and its bank clearing must retain each other's reference")
