"""A PDF of a document the application makes (N140): the purchase order, delivery schedule, order confirmation,
invoice, credit note, statement of account and payment reminder that *Print* shows as a page.

Those pages are built by the web client from a small, known set of tags (``header``, ``h1``, ``h2``, ``div``, ``b``,
``p``, ``br``, ``table`` with ``thead``/``tbody``/``tfoot``, ``footer``), so the server lays them out itself, without a
browser: a header and a ``grid`` side by side in columns, paragraphs wrapped to the page, tables with their columns
sized to what they hold (``num`` cells to the right), a new page when one is full. Text is set in Helvetica, the
PDF's own font, in the Windows Latin-1 characters it has; a rupee sign becomes "INR " and other characters it has not
become "?". The page itself stays attached beside it as the exact copy.
"""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from html.parser import HTMLParser

PAGE_W, PAGE_H, MARGIN = 595.0, 842.0, 48.0
WIDTH = PAGE_W - 2 * MARGIN
GRAY, INK, RULE = (0.36, 0.39, 0.44), (0.1, 0.12, 0.14), (0.85, 0.87, 0.89)

# glyph widths of Helvetica and Helvetica-Bold for the characters 32-126 (from their font metrics), in 1/1000 em
_REG = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, *[556] * 10, 278, 278, 584,
        584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722,
        667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556,
        222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, *[556] * 10, 333, 333, 584,
         584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722,
         667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611,
         278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]
_SWAP = {"₹": "INR ", " ": " ", " ": " ", "−": "-", "→": "->", "≥": ">=", "≤": "<=", "✓": "v"}


def _clean(text: str) -> str:
    for a, b in _SWAP.items():
        text = text.replace(a, b)
    return text.encode("cp1252", "replace").decode("cp1252")


def width(text: str, size: float, bold: bool = False) -> float:
    table = _BOLD if bold else _REG
    return sum(table[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in text) * size / 1000


# ------------------------------------------------------------------------------------------------ reading the page
@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    kids: list[Node | str] = field(default_factory=list)

    @property
    def cls(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def find(self, pred) -> Node | None:
        for k in self.kids:
            if isinstance(k, Node):
                if pred(k):
                    return k
                if (hit := k.find(pred)) is not None:
                    return hit
        return None

    def elements(self) -> list[Node]:
        return [k for k in self.kids if isinstance(k, Node)]


class _Reader(HTMLParser):
    VOID = {"br", "meta", "link", "img", "hr", "input"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "title", "head"):
            self.skip += 1
            return
        n = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].kids.append(n)
        if tag not in self.VOID:
            self.stack.append(n)

    def handle_endtag(self, tag):
        if tag in ("style", "script", "title", "head"):
            self.skip = max(0, self.skip - 1)
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self.skip and data:
            self.stack[-1].kids.append(data)


# ------------------------------------------------------------------------------------------------ text in lines
@dataclass
class Para:
    runs: list[tuple[str, bool]]
    size: float = 9.5
    color: tuple = INK
    space: float = 0.0           # room above


BLOCKS = {"div", "p", "h1", "h2", "header", "footer", "section", "li", "ul", "tr", "table"}


def _paras(node: Node, size: float = 9.5, bold: bool = False, color: tuple = INK) -> list[Para]:
    out: list[Para] = []
    cur: list[tuple[str, bool]] = []

    def flush(sz=size, col=color, space=0.0):
        nonlocal cur
        text = "".join(t for t, _ in cur).strip()
        if text:
            out.append(Para(_trim(cur), sz, col, space))
        cur = []

    def walk(n: Node | str, b: bool, sz: float, col: tuple):
        if isinstance(n, str):
            cur.append((re.sub(r"\s+", " ", n), b))
            return
        if n.tag == "br":
            flush(sz, col)
            return
        cls = n.cls
        nb, nsz, ncol = b, sz, col
        if n.tag in ("b", "strong", "th") or n.tag in ("h1", "h2"):
            nb = True
        if n.tag == "h1":
            nsz = 17
        elif n.tag == "h2":
            nsz, ncol = 7.5, GRAY
        elif n.tag == "footer" or cls & {"muted", "id", "faint"}:
            ncol = GRAY
            nsz = min(sz, 8.5)
        if "flag" in cls:
            ncol = (0.71, 0.28, 0.03)
        block = n.tag in BLOCKS
        if block:
            flush(sz, col)
        for k in n.kids:
            walk(k, nb, nsz, ncol)
        if block:
            flush(nsz, ncol, 6.0 if n.tag in ("p", "footer") else 0.0)

    for k in node.kids:
        walk(k, bold, size, color)
    flush()
    return out


def _trim(runs: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    out: list[tuple[str, bool]] = []
    for t, b in runs:
        if out and out[-1][1] == b:
            out[-1] = (out[-1][0] + t, b)
        else:
            out.append((t, b))
    if out:
        out[0] = (out[0][0].lstrip(), out[0][1])
        out[-1] = (out[-1][0].rstrip(), out[-1][1])
    return [(re.sub(r" {2,}", " ", t), b) for t, b in out if t]


def _wrap(p: Para, w: float) -> list[list[tuple[str, bool]]]:
    """A paragraph's runs broken into lines no wider than ``w``."""
    words: list[tuple[str, bool]] = []
    for t, b in p.runs:
        for i, piece in enumerate(re.split(r"(\s+)", t)):
            if not piece:
                continue
            words.append((" " if i % 2 else piece, b))
    lines: list[list[tuple[str, bool]]] = [[]]
    used = 0.0
    for t, b in words:
        wd = width(_clean(t), p.size, b)
        if t == " ":
            if lines[-1]:
                lines[-1].append((t, b))
                used += wd
            continue
        if used + wd > w and lines[-1]:
            while lines[-1] and lines[-1][-1][0] == " ":
                lines[-1].pop()
            lines.append([])
            used = 0.0
        lines[-1].append((t, b))
        used += wd
    return [ln for ln in lines if ln] or [[]]


# ------------------------------------------------------------------------------------------------ laying out
class _Doc:
    def __init__(self) -> None:
        self.pages: list[list[str]] = [[]]
        self.y = PAGE_H - MARGIN

    @property
    def ops(self) -> list[str]:
        return self.pages[-1]

    def need(self, h: float) -> None:
        if self.y - h < MARGIN:
            self.pages.append([])
            self.y = PAGE_H - MARGIN

    def text(self, x: float, y: float, runs: list[tuple[str, bool]], size: float, color: tuple) -> None:
        self.ops.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
        for t, b in _trim(runs):
            s = _clean(t)
            esc = s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            self.ops.append(f"BT /{'F2' if b else 'F1'} {size:.1f} Tf {x:.2f} {y:.2f} Td ({esc}) Tj ET")
            x += width(s, size, b)

    def rule(self, x0: float, x1: float, y: float, w: float = 0.6, color: tuple = RULE) -> None:
        self.ops.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} RG {w:.2f} w {x0:.2f} {y:.2f} m {x1:.2f} {y:.2f} l S")


def _line_w(ln: list[tuple[str, bool]], size: float) -> float:
    return sum(width(_clean(t), size, b) for t, b in ln)


def _flow(doc: _Doc, paras: list[Para], x: float, w: float, align: str = "left", dry: bool = False,
          top: float | None = None) -> float:
    """Set paragraphs in a column from ``top`` (default: where the page is); the height used."""
    y = doc.y if top is None else top
    start = y
    for p in paras:
        y -= p.space
        lead = p.size * 1.35
        for ln in _wrap(p, w):
            y -= lead
            if not dry:
                lw = _line_w(ln, p.size)
                doc.text(x + (w - lw if align == "right" else 0), y + lead * 0.25, ln, p.size, p.color)
    return start - y


def _columns(doc: _Doc, cols: list[Node]) -> None:
    if not cols:
        return
    gap = 18.0
    w = (WIDTH - gap * (len(cols) - 1)) / len(cols)
    sets = [(_paras(c), "right" if "right" in c.attrs.get("style", "") else "left") for c in cols]
    h = max(_flow(doc, ps, 0, w, a, dry=True) for ps, a in sets)
    doc.need(h)
    for i, (ps, a) in enumerate(sets):
        _flow(doc, ps, MARGIN + i * (w + gap), w, a, top=doc.y)
    doc.y -= h + 10


def _cells(tr: Node) -> list[tuple[list[Para], bool, bool, int]]:
    out = []
    for c in tr.elements():
        if c.tag in ("td", "th"):
            out.append((_paras(c, 8.5 if c.tag == "th" else 9.0, c.tag == "th", GRAY if c.tag == "th" else INK),
                        "num" in c.cls, c.tag == "th", int(c.attrs.get("colspan") or 1)))
    return out


def _table(doc: _Doc, t: Node) -> None:
    rows: list[tuple[list, str]] = []
    for part in t.elements():
        trs = part.elements() if part.tag in ("thead", "tbody", "tfoot") else [part]
        for tr in trs:
            if tr.tag == "tr":
                rows.append((_cells(tr), "head" if part.tag == "thead" else
                             "total" if "total" in tr.cls else "foot" if part.tag == "tfoot" else "body"))
    n = max((sum(c[3] for c in r) for r, _ in rows), default=0)
    if not n:
        return
    natural, least = [0.0] * n, [0.0] * n
    for r, _ in rows:
        i = 0
        for ps, _num, _th, span in r:
            if span == 1 and i < n:
                for p in ps:
                    full = sum(width(_clean(t), p.size, b) for t, b in p.runs)
                    word = max((width(_clean(wd), p.size, b) for t, b in p.runs for wd in t.split()), default=0)
                    natural[i] = max(natural[i], min(full, 260))
                    least[i] = max(least[i], word)
            i += span
    pad = 5.0
    natural = [max(a, b) + 2 * pad for a, b in zip(natural, least, strict=True)]
    least = [x + 2 * pad for x in least]
    total = sum(natural)
    if total <= WIDTH:
        widths = [x * WIDTH / total for x in natural] if total else [WIDTH / n] * n
    else:
        spare = WIDTH - sum(least)
        extra = [a - b for a, b in zip(natural, least, strict=True)]
        widths = [lo + (e * spare / sum(extra) if sum(extra) and spare > 0 else 0) for lo, e in zip(least, extra, strict=True)]
    doc.y -= 4
    for r, kind in rows:
        spans = []
        i = 0
        for ps, num, _th, span in r:
            spans.append((ps, num, sum(widths[i:i + span]), sum(widths[:i])))
            i += span
        h = max((_flow(doc, ps, 0, w - 2 * pad, dry=True) for ps, _, w, _ in spans), default=0) + 2 * pad
        doc.need(h)
        top = doc.y
        for ps, num, w, x in spans:
            _flow(doc, ps, MARGIN + x + pad, w - 2 * pad, "right" if num else "left", top=top - pad)
        doc.y -= h
        if kind == "total":
            doc.rule(MARGIN, MARGIN + WIDTH, top, 1.2, INK)
        if kind in ("head", "body"):
            doc.rule(MARGIN, MARGIN + WIDTH, doc.y)
    doc.y -= 10


def _render(doc: _Doc, node: Node) -> None:
    for k in node.kids:
        if isinstance(k, str):
            if k.strip():
                _flow(doc, [Para([(k.strip(), False)])], MARGIN, WIDTH)
            continue
        if k.tag == "header" or "grid" in k.cls:
            _columns(doc, k.elements())
            if k.tag == "header":
                doc.rule(MARGIN, MARGIN + WIDTH, doc.y + 4, 1.4, INK)
                doc.y -= 6
        elif k.tag == "table":
            _table(doc, k)
        elif k.tag in ("html", "body") or "page" in k.cls:
            _render(doc, k)
        else:
            ps = _paras(Node("div", kids=[k]))
            h = _flow(doc, ps, MARGIN, WIDTH, dry=True)
            doc.need(min(h, PAGE_H - 2 * MARGIN))
            doc.y -= _flow(doc, ps, MARGIN, WIDTH)


def html_to_pdf(html: str, title: str = "") -> bytes:
    """The document page as a PDF: A4, Helvetica, as laid out above."""
    r = _Reader()
    r.feed(html)
    doc = _Doc()
    _render(doc, r.root)
    return _write(doc.pages, title)


# ------------------------------------------------------------------------------------------------ the file
def _write(pages: list[list[str]], title: str) -> bytes:
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)

    add(b"")                                    # 1 catalog, filled in last
    add(b"")                                    # 2 pages
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    kids = []
    total = len(pages)
    for i, ops in enumerate(pages, 1):
        foot = [] if total == 1 else [f"0.36 0.39 0.44 rg BT /F1 7.5 Tf {PAGE_W - MARGIN - 40:.2f} {MARGIN / 2:.2f} Td "
                                      f"(Page {i} of {total}) Tj ET"]
        stream = zlib.compress("\n".join([*ops, *foot]).encode("cp1252", "replace"))
        content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.0f} {PAGE_H:.0f}] /Resources << /Font "
                        f"<< /F1 {f1} 0 R /F2 {f2} 0 R >> >> /Contents {content} 0 R >>".encode()))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    safe = _clean(title).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    info = add(f"<< /Title ({safe}) /Producer (SCP) >>".encode("cp1252", "replace"))
    objs[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, info, xref)
    return bytes(out)
