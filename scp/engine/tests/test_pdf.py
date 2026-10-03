"""N140: a document page laid out as a PDF on the server, without a browser."""
from __future__ import annotations

import re
import zlib

from scp.connect.pdf import html_to_pdf, width

PAGE = """<!doctype html><html><head><title>x</title><style>body { color: red }</style></head><body><div class="page">
<header><div><h1>Purchase order PO-00007</h1></div><div style="text-align:right"><b>Mehta Paints</b>
<div>Plot 4, MIDC<br>Pune</div></div></header>
<div class="grid"><div><h2>Supplier</h2><b>Sharma Metals (Pvt)</b></div><div><h2>Terms</h2><div>Net 30 days</div></div></div>
<table><thead><tr><th>Item</th><th class="num">Quantity</th><th class="num">Value</th></tr></thead>
<tbody>{rows}</tbody>
<tfoot><tr class="total"><td>Total</td><td></td><td class="num">₹12,500.00</td></tr></tfoot></table>
<p>Please confirm within 2 days — thank you.</p><footer>Mehta Paints · PO-00007</footer></div></body></html>"""


def text_of(pdf: bytes) -> list[str]:
    """The strings shown on each page, in order."""
    pages = []
    for m in re.finditer(rb"stream\n(.*?)\nendstream", pdf, re.S):
        ops = zlib.decompress(m.group(1)).decode("cp1252")
        pages.append(" ".join(re.findall(r"\((.*?)\) Tj", ops)))
    return pages


def test_a_document_page_becomes_a_pdf_with_its_text_in_order():
    pdf = html_to_pdf(PAGE.replace("{rows}", "<tr><td>Copper wire</td><td class='num'>500 kg</td><td class='num'>₹12,500.00</td></tr>"),
                      "Purchase order PO-00007")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    [page] = text_of(pdf)
    for a, b in [("Purchase order PO-00007", "Mehta Paints"), ("Supplier", "Copper wire"), ("Copper wire", "Total"),
                 ("Total", "Please confirm")]:
        assert page.index(a) < page.index(b)
    assert "INR 12,500.00" in page and "₹" not in page              # the rupee sign as INR
    assert "Sharma Metals \\(Pvt\\)" in page                          # brackets escaped
    assert "red" not in page and "x" not in page.split()               # style and title are not printed
    assert b"/Title (Purchase order PO-00007)" in pdf


def test_a_long_table_runs_onto_more_pages_numbered():
    rows = "".join(f"<tr><td>Item {i}</td><td class='num'>{i}</td><td class='num'>1</td></tr>" for i in range(120))
    pages = text_of(html_to_pdf(PAGE.replace("{rows}", rows)))
    assert len(pages) >= 3
    assert "Page 1 of" in pages[0] and f"Page {len(pages)} of {len(pages)}" in pages[-1]
    assert "Item 0" in pages[0] and "Item 119" in pages[-1] and "Total" in pages[-1]


def test_widths_follow_helvetica():
    assert width("iiii", 10) < width("MMMM", 10)
    assert width("Total", 10, bold=True) > width("Total", 10)
