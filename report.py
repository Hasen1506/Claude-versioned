"""
PDF Report Generator
=====================
Generates a comprehensive supply chain report from the current state.
Uses ReportLab for PDF generation.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
import io
import time


def _g(obj, *keys, default=None):
    """(MF-18) Bilingual field getter — tolerate either camelCase (raw frontend state, the report's
    actual contract) or snake_case (the solver contract). The report reads RAW state while every
    solver reads transformed snake_case; with no shared schema, a key the report spells one way and
    the data carries the other silently becomes a default (0/0.95/52), printing a wrong number with
    no error. Accepting both spellings removes that silent-default trap. The structural fix is the
    canonical payload builder (MF-19) + a contract test (MF-34) that pins every field to its key."""
    for k in keys:
        if isinstance(obj, dict) and obj.get(k) is not None:
            return obj[k]
    return default


def generate_report(data):
    """Generate PDF report from app state. Returns bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('H1', parent=styles['Heading1'], fontSize=16,
                              textColor=HexColor('#0f3460'), spaceBefore=16, spaceAfter=8))
    styles.add(ParagraphStyle('H2', parent=styles['Heading2'], fontSize=12,
                              textColor=HexColor('#16213e'), spaceBefore=12, spaceAfter=6))
    styles.add(ParagraphStyle('Body', parent=styles['Normal'], fontSize=10,
                              leading=14, alignment=TA_JUSTIFY, spaceAfter=6))

    story = []
    config = data.get('config', {})
    products = data.get('products', [])
    cur = config.get('currency', '$')

    # Title
    story.append(Paragraph(f"{config.get('companyName', 'Enterprise')} — Supply Chain Report", styles['Title']))
    story.append(Paragraph(f"Generated: {time.strftime('%Y-%m-%d %H:%M')} | "
                           f"Service Level: {config.get('serviceLevel', 0.95)*100:.0f}% | "
                           f"WACC: {config.get('wacc', 10)}%", styles['Body']))
    story.append(Spacer(1, 12))

    # Executive Summary
    story.append(Paragraph("Executive Summary", styles['H1']))

    # (MF-15) Demand basis: prefer a forward-looking forecast when present; otherwise fall back to
    # recorded history. The old code summed ALL history (any number of past periods) and labelled it
    # "total annual demand" / "projected revenue" — that double-counts multi-year history and calls
    # past actuals a projection. Now the basis is explicit and the label matches what was summed.
    def _demand_basis(p):
        fc = p.get('forecast') or []
        if fc and any(float(x or 0) for x in fc):
            return float(sum(fc)), 'forecast', len(fc)
        hist = p.get('history', []) or []
        return float(sum(hist)), 'history', len(hist)

    bases = [_demand_basis(p) for p in products]
    total_demand = sum(d for d, _, _ in bases)
    total_mat = sum(sum(_g(b, 'cost', default=0) * _g(b, 'qtyPer', 'qty_per', default=1) for b in p.get('bom', [])) * d
                    for p, (d, _, _) in zip(products, bases))
    total_revenue = sum(_g(p, 'sellPrice', 'sell_price', default=0) * d for p, (d, _, _) in zip(products, bases))
    src_set = {s for _, s, _ in bases}
    if src_set == {'forecast'}:
        basis_label, rev_word = 'forecast horizon', 'Forecast revenue'
    elif src_set == {'history'}:
        max_n = max((n for _, _, n in bases), default=0)
        basis_label, rev_word = f'{max_n} recorded period(s), historical', 'Revenue at current price (historical basis)'
    else:
        basis_label, rev_word = 'mixed forecast/historical', 'Revenue (mixed basis)'
    story.append(Paragraph(
        f"This report covers {len(products)} product(s) with total demand of "
        f"{total_demand:,.0f} units ({basis_label}). {rev_word}: {cur}{total_revenue:,.0f}. "
        f"Material cost (same basis): {cur}{total_mat:,.0f}. "
        f"Gross margin: {(total_revenue - total_mat) / max(total_revenue, 1) * 100:.1f}%.",
        styles['Body']))

    # Product Details
    story.append(Paragraph("Product Details", styles['H1']))
    for p in products:
        story.append(Paragraph(p.get('name', 'Product'), styles['H2']))
        dem, dem_src, dem_n = _demand_basis(p)
        mat = sum(_g(b, 'cost', default=0) * _g(b, 'qtyPer', 'qty_per', default=1) for b in p.get('bom', []))
        dem_label = 'Demand (forecast horizon)' if dem_src == 'forecast' else f'Demand ({dem_n} recorded periods)'
        tbl_data = [
            ['Parameter', 'Value'],
            [dem_label, f"{dem:,.0f} units"],
            ['Selling Price', f"{cur}{_g(p, 'sellPrice', 'sell_price', default=0)}"],
            ['Unit Material Cost', f"{cur}{mat:.2f}"],
            ['Variable Cost', f"{cur}{_g(p, 'variableCost', 'variable_cost', default=0)}"],
            ['Setup Cost/Batch', f"{cur}{_g(p, 'setupCost', 'setup_cost', default=0)}"],
            ['Capacity', f"{_g(p, 'capacity', default=0)} units/week"],
            ['Shelf Life', f"{_g(p, 'shelfLife', 'shelf_life', default=52)} weeks"],
            ['Yield', f"{_g(p, 'yieldPct', 'yield_pct', default=0.95)*100:.0f}%"],
            ['BOM Parts', f"{len(p.get('bom', []))}"],
        ]
        t = Table(tbl_data, colWidths=[doc.width * 0.4, doc.width * 0.6])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#0f3460')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, HexColor('#f5f5f5')]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 8))

        # BOM
        if p.get('bom'):
            bom_data = [['Part', 'Qty/Unit', 'Cost', 'LT (wk)', 'MOQ', 'Source']]
            for b in p['bom']:
                bom_data.append([
                    b.get('name', ''),
                    str(_g(b, 'qtyPer', 'qty_per', default=1)),
                    f"{cur}{_g(b, 'cost', default=0)}",
                    str(_g(b, 'leadTime', 'lead_time', default=1)),
                    str(_g(b, 'moq', default=10)),
                    _g(b, 'supplierType', 'supplier_type', default='domestic'),
                ])
            bt = Table(bom_data, colWidths=[doc.width*0.25, doc.width*0.12, doc.width*0.12,
                                            doc.width*0.12, doc.width*0.12, doc.width*0.15])
            bt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a2234')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ]))
            story.append(bt)
            story.append(Spacer(1, 10))

    # Solver results (if provided)
    solver = data.get('solver_results', {})
    if solver:
        story.append(Paragraph("Optimization Results", styles['H1']))
        if solver.get('total_cost'):
            story.append(Paragraph(
                f"Total optimized cost: {cur}{solver['total_cost']:,.2f} "
                f"(solved in {solver.get('solve_time', '?')}s)", styles['Body']))
        if solver.get('cost_breakdown'):
            cb_data = [['Category', 'Amount']]
            for k, v in solver['cost_breakdown'].items():
                if k != 'total':
                    cb_data.append([k.replace('_', ' ').title(), f"{cur}{v:,.2f}"])
            cbt = Table(cb_data, colWidths=[doc.width * 0.5, doc.width * 0.5])
            cbt.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#0f3460')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(cbt)

    # MC results (if provided)
    mc = data.get('mc_results', {})
    if mc:
        story.append(Spacer(1, 8))
        story.append(Paragraph("Monte Carlo Risk Analysis", styles['H1']))
        story.append(Paragraph(
            f"Runs: {mc.get('n_runs', 0)} | "
            f"Avg Cost: {cur}{mc.get('avg_cost', 0):,.2f} | "
            f"VaR95: {cur}{mc.get('var95', 0):,.2f} | "
            f"CVaR95: {cur}{mc.get('cvar95', 0):,.2f} | "
            f"Fill: {mc.get('avg_fill', 0):.1f}% | "
            f"Fragility: {mc.get('fragility', 0):.2f}x",
            styles['Body']))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
