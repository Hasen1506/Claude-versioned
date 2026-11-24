"""Read one complete booked ISO 20022 camt.053 statement, including CGI pagination."""
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from xml.etree import ElementTree as XML

from .model.carrier_bank import CAMT_MAX_BYTES, CAMT_MAX_PAGES, BankStatementHeader, CamtOriginal, CamtSourceEvidence, SupplierDebitSource
from .model.currency import MATERIAL_CURRENCIES, material_units

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"
XML_NS = {"": NS}
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
    if len(encoded) > CAMT_MAX_BYTES:
        raise ValueError("the original bank XML can contain at most 256000 bytes")
    return encoded, sha256(encoded).hexdigest()


def file_set_evidence(files: list[str]) -> list[tuple[bytes, str]]:
    if not 1 <= len(files) <= CAMT_MAX_PAGES:
        raise ValueError(f"choose between one and {CAMT_MAX_PAGES} originals for one statement")
    originals = []
    total = 0
    for xml in files:
        data, digest = file_evidence(xml)
        total += len(data)
        if total > CAMT_MAX_BYTES:
            raise ValueError("the original bank XML set can contain at most 256000 bytes")
        originals.append((data, digest))
    return originals


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


def _minor(amount: str, currency: str) -> int:
    if not MONEY.fullmatch(amount):
        raise ValueError("camt.053 amounts must be unsigned decimal values")
    digits = material_units(currency).digits
    minor = Decimal(amount).scaleb(digits)
    if minor != int(minor):
        precision = "two decimals" if digits == 2 else f"{digits} decimal places"
        raise ValueError(f"camt.053 amounts must be exact to the company currency's {precision}")
    return int(minor)


def _signed(node: XML.Element, currency: str, *, optional_currency: bool = False) -> int:
    amount = _one(node, "Amt")
    assert amount is not None
    if amount.get("Ccy") != currency and not (optional_currency and amount.get("Ccy") is None):
        raise ValueError("camt.053 booked currency must match the registered account")
    minor = _minor(_text(node, "Amt"), currency)
    direction = _text(node, "CdtDbtInd")
    if direction not in ("CRDT", "DBIT"):
        raise ValueError("camt.053 requires a credit or debit indicator")
    return minor if direction == "CRDT" else -minor


def bank_account_hash(*, iban: str = "", bic: str = "", local: str = "") -> str:
    if iban:
        if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban):
            raise ValueError("the bank account has an invalid IBAN")
        numeric = "".join(char if char.isdigit() else str(ord(char) - 55) for char in iban[4:] + iban[:4])
        if int(numeric) % 97 != 1:
            raise ValueError("the bank account has an invalid IBAN checksum")
        identity = f"iso20022:iban:{iban}"
    else:
        if not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?", bic):
            raise ValueError("local account identifiers require a valid servicing bank BIC")
        identity = f"iso20022:other:{bic}:{local}"
    return sha256(identity.encode()).hexdigest()


def _account_hash(account: XML.Element) -> str:
    identifier = _one(account, "Id")
    assert identifier is not None
    iban = _text(identifier, "IBAN", required=False).upper()
    if len(identifier) != 1:
        raise ValueError("camt.053 requires one bank account identifier")
    if iban:
        return bank_account_hash(iban=iban)
    return bank_account_hash(local=_text(identifier, "Othr/Id"), bic=_text(account, "Svcr/FinInstnId/BICFI").upper())


def _pagination(node: XML.Element, path: str) -> tuple[int, bool] | None:
    page = _one(node, path, required=False)
    if page is None:
        return None
    number = _text(page, "PgNb")
    last = _text(page, "LastPgInd")
    if (not re.fullmatch(r"[0-9]{1,5}", number) or not 1 <= int(number) <= CAMT_MAX_PAGES
            or last not in ("true", "false", "1", "0")):
        raise ValueError("camt.053 has invalid page numbering or a last-page indicator")
    return int(number), last in ("true", "1")


def _balances(statement: XML.Element, currency: str, start: date, end: date) -> dict[str, tuple[int, date]]:
    values = {}
    for balance in statement.findall("Bal", XML_NS):
        code = _text(balance, "Tp/CdOrPrtry/Cd", required=False)
        if code not in ("OPBD", "CLBD"):
            continue
        subtype = _one(balance, "Tp/SubTp", required=False)
        if subtype is not None and (len(subtype) != 1 or _text(subtype, "Cd", required=False) != "INTM"):
            raise ValueError("camt.053 booked balances require the INTM subtype for interim amounts")
        day = _day(balance, "Dt")
        key = f"{code}-INTM" if subtype is not None else code
        allowed = {"OPBD": start.toordinal() - day.toordinal() in (0, 1),
                   "CLBD": day == end}.get(key, start <= day <= end)
        if key in values or not allowed:
            raise ValueError("camt.053 requires one opening and one closing booked balance on the statement boundaries")
        values[key] = (_signed(balance, currency), day)
    return values


def _summary(statement: XML.Element, amounts: list[int], currency: str) -> None:
    def verify(node: XML.Element, selected: list[int], *, require_count: bool = False) -> None:
        count = _text(node, "NbOfNtries", required=require_count)
        total = _text(node, "Sum", required=False)
        if count and (not re.fullmatch(r"[0-9]{1,15}", count) or int(count) != len(selected)):
            raise ValueError("camt.053 reported entry count differs from the booked rows")
        if total and _minor(total, currency) != sum(abs(amount) for amount in selected):
            raise ValueError("camt.053 reported gross total differs from the booked rows")

    totals = _one(statement, "TxsSummry/TtlNtries")
    assert totals is not None
    verify(totals, amounts, require_count=True)
    net = _one(totals, "TtlNetNtry", required=False)
    if net is not None and _signed(net, currency, optional_currency=True) != sum(amounts):
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
    reversal: bool
    trace_ids: tuple[str, ...]
    included_fee_minor: int | None
    unresolved_charges: bool
    requires_allocation: bool
    supplier_debit: SupplierDebitSource | None


def _return_charges(node: XML.Element, currency: str) -> tuple[int | None, bool]:
    """Only entry-level, explicitly included bank debits affect the booked net."""
    charges = _one(node, "Chrgs", required=False)
    if node.findall("NtryDtls/TxDtls/Chrgs", XML_NS):
        return None, True
    if charges is None:
        return None, False
    records = charges.findall("Rcrd", XML_NS)
    if not records:
        return None, True
    included = total = 0
    for record in records:
        amount = _one(record, "Amt")
        assert amount is not None
        flag = _text(record, "ChrgInclInd", required=False)
        if amount.get("Ccy") != currency or flag not in ("true", "1", "false", "0"):
            return None, True
        minor = _minor(_text(record, "Amt"), currency)
        total += minor
        if flag in ("true", "1"):
            if _text(record, "CdtDbtInd", required=False) != "DBIT" or _one(record, "Tax", required=False) is not None:
                return None, True
            included += minor
    summary = _one(charges, "TtlChrgsAndTaxAmt", required=False)
    if summary is not None and (summary.get("Ccy") != currency or _minor(_text(charges, "TtlChrgsAndTaxAmt"), currency) != total):
        return None, True
    return included or None, False


def _entry(node: XML.Element, currency: str) -> CamtEntry:
    indicator = _text(node, "RvslInd", required=False)
    if _text(node, "Sts/Cd") != "BOOK" or indicator not in ("", "false", "0", "true", "1"):
        raise ValueError("camt.053 requires booked entries and a valid reversal indicator")
    identifier = _text(node, "AcctSvcrRef", required=False) or _text(node, "NtryRef")
    if identifier.upper() in EMPTY_REFERENCE:
        raise ValueError("camt.053 requires a stable bank entry identifier")
    batches = {_text(detail, "Btch/PmtInfId", required=False) for detail in node.findall("NtryDtls", XML_NS)}
    details = node.findall("NtryDtls/TxDtls", XML_NS)
    transactions = {_text(tx, "Refs/EndToEndId", required=False) for tx in details}
    trace_ids = {_text(tx, "Refs/UETR", required=False, limit=36).lower() for tx in details}
    trace_ids = {trace for trace in trace_ids if re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", trace)}
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
    reversal = indicator in ("true", "1")
    fee, unresolved = _return_charges(node, currency) if reversal else (None, False)
    requires_allocation = False
    if currency in MATERIAL_CURRENCIES:
        declared = [_text(part, "Btch/NbOfTxs", required=False) for part in node.findall("NtryDtls", XML_NS)]
        requires_allocation = (len(details) > 1 or any(count and count.lstrip("0") != "1" for count in declared)
                               or bool(node.findall("Chrgs", XML_NS) or node.findall("NtryDtls/TxDtls/Chrgs", XML_NS)))
    supplier_debit = None
    if not reversal and amount < 0:
        debit_fee, ambiguous = _return_charges(node, currency)
        supplier_debit = SupplierDebitSource(included_fee_minor=debit_fee, unresolved_charges=ambiguous)
    return CamtEntry(identifier, reference, _day(node, "BookgDt"), amount, reversal, tuple(sorted(trace_ids)), fee, unresolved,
                     requires_allocation, supplier_debit)


@dataclass(frozen=True)
class CamtStatement:
    account_hash: str
    header: BankStatementHeader
    entries: list[CamtEntry]
    file_sha256: str
    source: CamtSourceEvidence


def _read_document(xml: str, data: bytes) -> XML.Element:
    encoding = ENCODING.match(xml)
    if encoding and encoding[2].upper() != "UTF-8":
        raise ValueError("the original bank XML must declare UTF-8 when it specifies an encoding")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("bank XML cannot contain a document type or entity declaration")
    try:
        document = XML.fromstring(data)
    except XML.ParseError as error:
        raise ValueError("the original bank XML is malformed") from error
    if document.tag != f"{{{NS}}}Document" or len(document) != 1:
        raise ValueError("use the camt.053.001.08 BankToCustomerStatement XML format")
    message = _one(document, "BkToCstmrStmt")
    assert message is not None
    return message


@dataclass(frozen=True)
class _Page:
    node: XML.Element
    account_hash: str
    statement: str
    sequence: str
    first: datetime
    last: datetime
    pagination: tuple[int, bool]
    balances: dict[str, tuple[int, date]]
    entries: list[CamtEntry]

    def identity(self) -> tuple[str, ...]:
        return self.account_hash, self.statement, self.sequence, self.first.isoformat(), self.last.isoformat()


def _read_page(statement: XML.Element, currency: str, message_page: tuple[int, bool] | None) -> _Page:
    pagination = _pagination(statement, "StmtPgntn") or message_page or (1, True)
    if message_page not in (None, (1, True), pagination):
        raise ValueError("camt.053 message and statement pagination disagree")
    bank = _one(statement, "Acct")
    assert bank is not None
    if _text(bank, "Ccy", required=False) not in ("", currency):
        raise ValueError("camt.053 account currency must match the registered account")
    first = _clock(_text(statement, "FrToDt/FrDtTm"))
    last = _clock(_text(statement, "FrToDt/ToDtTm"))
    if (first.tzinfo is None) != (last.tzinfo is None) or last < first or last.date() < first.date():
        raise ValueError("camt.053 statement dates must be in chronological order")
    balances = _balances(statement, currency, first.date(), last.date())
    rows = statement.findall("Ntry", XML_NS)
    if len(rows) > 500:
        raise ValueError("one statement import can contain at most 500 booked entries")
    entries = [_entry(node, currency) for node in rows]
    if any(not first.date() <= entry.date <= last.date() for entry in entries):
        raise ValueError("camt.053 booked entries must fall within the statement dates")
    sequence = _text(statement, "ElctrncSeqNb", required=False)
    return _Page(statement, _account_hash(bank), _text(statement, "Id"), sequence, first, last, pagination, balances, entries)


def _page_balances(pages: list[_Page]) -> tuple[int, int]:
    previous = None
    for index, page in enumerate(pages):
        start = "OPBD" if index == 0 else "OPBD-INTM"
        end = "CLBD" if index == len(pages) - 1 else "CLBD-INTM"
        if set(page.balances) != {start, end}:
            raise ValueError(f"camt.053 page {index + 1} requires both opening ({start}) and closing ({end}) booked balances")
        opening, closing = page.balances[start], page.balances[end]
        if previous is not None and previous != opening:
            raise ValueError("camt.053 interim booked balances do not carry forward between pages")
        if opening[0] + sum(entry.amount_minor for entry in page.entries) != closing[0]:
            raise ValueError("camt.053 opening balance plus signed activity must equal closing balance on every page")
        previous = closing
    return pages[0].balances["OPBD"][0], pages[-1].balances["CLBD"][0]


def read_statement_files(files: list[str], account: str, currency: str) -> CamtStatement:
    sources = file_set_evidence(files)
    originals = []
    pages = []
    for xml, (data, digest) in zip(files, sources, strict=True):
        message = _read_document(xml, data)
        message_page = _pagination(message, "GrpHdr/MsgPgntn")
        statements = message.findall("Stmt", XML_NS)
        if not statements or (len(files) > 1 and len(statements) != 1):
            raise ValueError("camt.053 requires one Stmt in each split original or every page in one original")
        if len(statements) + len(pages) > CAMT_MAX_PAGES:
            raise ValueError(f"one statement can contain at most {CAMT_MAX_PAGES} pages")
        if len(statements) > 1 and message_page not in (None, (1, True)):
            raise ValueError("one original containing all statement pages must be a complete message")
        group = [_read_page(statement, currency, message_page) for statement in statements]
        pages.extend(group)
        originals.append(CamtOriginal(message_id=_text(message, "GrpHdr/MsgId"), file_sha256=digest, byte_count=len(data),
                                      pages=sorted(page.pagination[0] for page in group)))
    pages.sort(key=lambda page: page.pagination[0])
    if len(pages) == 1 and pages[0].pagination != (1, True):
        raise ValueError("camt.053 requires a complete single-page statement or all pages of one split statement")
    if [page.pagination for page in pages] != [(i, i == len(pages)) for i in range(1, len(pages) + 1)]:
        raise ValueError("camt.053 requires every consecutive page once and one final-page indicator on the last page")
    first = pages[0]
    if len(pages) > 1 and (not re.fullmatch(r"[0-9]{1,18}", first.sequence)
                           or any(page.identity() != first.identity() for page in pages[1:])):
        raise ValueError("camt.053 pages must share the bank account, statement ID, electronic sequence and statement window")
    if any(_one(page.node, "TxsSummry", required=False) is not None for page in pages[1:]):
        raise ValueError("camt.053 whole-statement totals belong on the first page")
    entries = [entry for page in pages for entry in page.entries]
    if len(entries) > 500:
        raise ValueError("one statement import can contain at most 500 booked entries")
    if len({entry.identifier.casefold() for entry in entries}) != len(entries):
        raise ValueError("camt.053 repeats a bank entry identifier")
    _summary(first.node, [entry.amount_minor for entry in entries], currency)
    opening, closing = _page_balances(pages)
    header = BankStatementHeader(account=account, number=first.statement, starts_on=first.first.date(), ends_on=first.last.date(),
                                 opening_minor=opening, closing_minor=closing, line_count=len(entries))
    originals.sort(key=lambda original: original.pages[0])
    source = CamtSourceEvidence(message_id=originals[0].message_id, byte_count=sum(file.byte_count for file in originals),
                                originals=originals if len(pages) > 1 else [])
    digest = source.manifest_sha256() if len(originals) > 1 else originals[0].file_sha256
    return CamtStatement(first.account_hash, header, entries, digest, source)


def read_statement(xml: str, account: str, currency: str) -> CamtStatement:
    return read_statement_files([xml], account, currency)
