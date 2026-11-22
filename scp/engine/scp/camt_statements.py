"""Read the booked, single-statement profile of ISO 20022 camt.053.001.08."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from xml.etree import ElementTree as XML

from .model.carrier_bank import BankStatementHeader, CamtSourceEvidence

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
XML_NS = {"": NS}
MAX_BYTES = 256_000
MONEY = re.compile(r"[0-9]{1,18}(?:\.[0-9]{1,5})?")
ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
ISO_CLOCK = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?")
ENCODING = re.compile(r"""^\ufeff?<\?xml\s+[^?]*?\bencoding\s*=\s*(['"])([^'"]+)\1""")
EMPTY_REFERENCE = {"NOTPROVIDED", "NONREF"}


def file_evidence(xml: str) -> tuple[bytes, str]:
    try:
        encoded = xml.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("the original bank XML must use UTF-8") from error
    if len(encoded) > MAX_BYTES:
        raise ValueError("the original bank XML can contain at most 256000 bytes")
    return encoded, sha256(encoded).hexdigest()


def _one(node: XML.Element, path: str, *, required: bool = True) -> XML.Element | None:
    current = node
    for part in path.split("/"):
        found = current.findall(part, XML_NS)
        if len(found) > 1 or (not found and required):
            raise ValueError(f"camt.053 requires one {path}")
        if not found:
            return None
        current = found[0]
    return current


def _text(node: XML.Element, path: str, *, required: bool = True, limit: int = 35) -> str:
    field = _one(node, path, required=required)
    if field is None:
        return ""
    value = (field.text or "").strip()
    if len(field) or not value or len(value) > limit:
        raise ValueError(f"camt.053 has an invalid {path}")
    return value


def _clock(value: str) -> datetime:
    if not ISO_CLOCK.fullmatch(value):
        raise ValueError("camt.053 requires an ISO date and time in the statement's local calendar")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _day(node: XML.Element, path: str) -> date:
    box = _one(node, path)
    assert box is not None
    day, clock = (_text(box, tag, required=False) for tag in ("Dt", "DtTm"))
    if len(box) != 1 or bool(day) == bool(clock) or (day and not ISO_DAY.fullmatch(day)):
        raise ValueError(f"camt.053 requires one booking date or date and time in {path}")
    return date.fromisoformat(day) if day else _clock(clock).date()


def _minor(amount: str) -> int:
    if not MONEY.fullmatch(amount):
        raise ValueError("camt.053 amounts must be unsigned decimal values")
    minor = Decimal(amount) * 100
    if minor != int(minor):
        raise ValueError("camt.053 amounts must be exact to the company currency's two decimals")
    return int(minor)


def _signed(node: XML.Element, currency: str | None) -> int:
    amount = _one(node, "Amt")
    assert amount is not None
    if currency is not None and amount.get("Ccy") != currency:
        raise ValueError("camt.053 booked currency must match the registered account")
    minor = _minor(_text(node, "Amt"))
    direction = _text(node, "CdtDbtInd")
    if direction not in ("CRDT", "DBIT"):
        raise ValueError("camt.053 requires a credit or debit indicator")
    return minor if direction == "CRDT" else -minor


def _account_hash(account: XML.Element) -> str:
    identifier = _one(account, "Id")
    assert identifier is not None
    iban = _text(identifier, "IBAN", required=False).upper()
    if len(identifier) != 1:
        raise ValueError("camt.053 requires one bank account identifier")
    if iban:
        if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban):
            raise ValueError("camt.053 contains an invalid IBAN")
        numeric = "".join(char if char.isdigit() else str(ord(char) - 55) for char in iban[4:] + iban[:4])
        if int(numeric) % 97 != 1:
            raise ValueError("camt.053 contains an invalid IBAN checksum")
        identity = f"iso20022:iban:{iban}"
    else:
        local = _text(identifier, "Othr/Id")
        bic = _text(account, "Svcr/FinInstnId/BICFI").upper()
        if not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?", bic):
            raise ValueError("camt.053 local account identifiers require a valid servicing bank BIC")
        identity = f"iso20022:other:{bic}:{local}"
    return sha256(identity.encode()).hexdigest()


def _single_page(node: XML.Element, path: str) -> None:
    page = _one(node, path, required=False)
    if page is not None and (_text(page, "PgNb").lstrip("0") != "1" or _text(page, "LastPgInd") not in ("true", "1")):
        raise ValueError("camt.053 requires a complete single-page statement")


def _balances(statement: XML.Element, currency: str, start: date, end: date) -> tuple[int, int]:
    values = {}
    for balance in statement.findall("Bal", XML_NS):
        code = _text(balance, "Tp/CdOrPrtry/Cd", required=False)
        if code not in ("OPBD", "CLBD"):
            continue
        day = _day(balance, "Dt")
        allowed = day == end if code == "CLBD" else start.toordinal() - day.toordinal() in (0, 1)
        if code in values or not allowed:
            raise ValueError("camt.053 requires one opening and one closing booked balance on the statement boundaries")
        values[code] = _signed(balance, currency)
    if set(values) != {"OPBD", "CLBD"}:
        raise ValueError("camt.053 requires both opening (OPBD) and closing (CLBD) booked balances")
    return values["OPBD"], values["CLBD"]


def _summary(statement: XML.Element, amounts: list[int]) -> None:
    def verify(node: XML.Element, selected: list[int], *, require_count: bool = False) -> None:
        count = _text(node, "NbOfNtries", required=require_count)
        total = _text(node, "Sum", required=False)
        if count and (not re.fullmatch(r"[0-9]{1,15}", count) or int(count) != len(selected)):
            raise ValueError("camt.053 reported entry count differs from the booked rows")
        if total and _minor(total) != sum(abs(amount) for amount in selected):
            raise ValueError("camt.053 reported gross total differs from the booked rows")

    totals = _one(statement, "TxsSummry/TtlNtries")
    assert totals is not None
    verify(totals, amounts, require_count=True)
    net = _one(totals, "TtlNetNtry", required=False)
    if net is not None and _signed(net, None) != sum(amounts):
        raise ValueError("camt.053 reported net total differs from the booked rows")
    for tag, selected in (("TtlCdtNtries", [a for a in amounts if a > 0]), ("TtlDbtNtries", [a for a in amounts if a < 0])):
        summary = _one(statement, f"TxsSummry/{tag}", required=False)
        if summary is not None:
            verify(summary, selected)


@dataclass(frozen=True)
class CamtEntry:
    identifier: str
    reference: str
    date: date
    amount_minor: int


def _entry(node: XML.Element, currency: str) -> CamtEntry:
    if _text(node, "Sts/Cd") != "BOOK" or _text(node, "RvslInd", required=False) not in ("", "false", "0"):
        raise ValueError("camt.053 requires booked entries without a reversal indicator")
    identifier = _text(node, "AcctSvcrRef", required=False) or _text(node, "NtryRef")
    if identifier.upper() in EMPTY_REFERENCE:
        raise ValueError("camt.053 requires a stable bank entry identifier")
    batches = {_text(detail, "Btch/PmtInfId", required=False) for detail in node.findall("NtryDtls", XML_NS)}
    transactions = {_text(tx, "Refs/EndToEndId", required=False)
                    for tx in node.findall("NtryDtls/TxDtls", XML_NS)}
    reference = identifier
    for offered in (batches, transactions):
        if len(offered) == 1:
            candidate = next(iter(offered))
            if candidate and candidate.upper() not in EMPTY_REFERENCE:
                reference = candidate
                break
    amount = _signed(node, currency)
    if not amount:
        raise ValueError("camt.053 booked entries require a nonzero amount")
    return CamtEntry(identifier, reference, _day(node, "BookgDt"), amount)


@dataclass(frozen=True)
class CamtStatement:
    account_hash: str
    header: BankStatementHeader
    entries: list[CamtEntry]
    file_sha256: str
    source: CamtSourceEvidence


def read_statement(xml: str, account: str, currency: str) -> CamtStatement:
    data, digest = file_evidence(xml)
    encoding = ENCODING.match(xml)
    if encoding and encoding[2].upper() != "UTF-8":
        raise ValueError("the original bank XML must declare UTF-8 when it specifies an encoding")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("bank XML cannot contain a document type or entity declaration")
    try:
        document = XML.fromstring(data)
    except XML.ParseError as error:
        raise ValueError("the original bank XML is malformed") from error
    if document.tag != f"{{{NS}}}Document":
        raise ValueError("use the camt.053.001.08 BankToCustomerStatement XML format")
    message = _one(document, "BkToCstmrStmt")
    assert message is not None
    _single_page(message, "GrpHdr/MsgPgntn")
    statement = _one(message, "Stmt")
    assert statement is not None
    _single_page(statement, "StmtPgntn")
    bank = _one(statement, "Acct")
    assert bank is not None
    if _text(bank, "Ccy", required=False) not in ("", currency):
        raise ValueError("camt.053 account currency must match the registered account")
    first = _clock(_text(statement, "FrToDt/FrDtTm"))
    last = _clock(_text(statement, "FrToDt/ToDtTm"))
    if (first.tzinfo is None) != (last.tzinfo is None) or last < first or last.date() < first.date():
        raise ValueError("camt.053 statement dates must be in chronological order")
    opening, closing = _balances(statement, currency, first.date(), last.date())
    rows = statement.findall("Ntry", XML_NS)
    if len(rows) > 500:
        raise ValueError("one statement import can contain at most 500 booked entries")
    entries = [_entry(node, currency) for node in rows]
    if len({entry.identifier.casefold() for entry in entries}) != len(entries):
        raise ValueError("camt.053 repeats a bank entry identifier")
    if any(not first.date() <= entry.date <= last.date() for entry in entries):
        raise ValueError("camt.053 booked entries must fall within the statement dates")
    _summary(statement, [entry.amount_minor for entry in entries])
    if opening + sum(entry.amount_minor for entry in entries) != closing:
        raise ValueError("camt.053 opening balance plus signed activity must equal closing balance")
    header = BankStatementHeader(account=account, number=_text(statement, "Id"), starts_on=first.date(), ends_on=last.date(),
                                 opening_minor=opening, closing_minor=closing, line_count=len(entries))
    provenance = CamtSourceEvidence(message_id=_text(message, "GrpHdr/MsgId"), byte_count=len(data))
    return CamtStatement(_account_hash(bank), header, entries, digest, provenance)
