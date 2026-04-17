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
    total_demand = sum(sum(p.get('history', [])) for p in products)
    total_mat = sum(sum(b.get('cost', 0) * b.get('qtyPer', 1) for b in p.get('bom', []))
                    * sum(p.get('history', [])) for p in products)
    total_revenue = sum(p.get('sellPrice', 0) * sum(p.get('history', [])) for p in products)
    story.append(Paragraph(
        f"This report covers {len(products)} product(s) with total annual demand of "
        f"{total_demand:,} units. Projected revenue: {cur}{total_revenue:,.0f}. "
        f"Projected material cost: {cur}{total_mat:,.0f}. "
        f"Gross margin: {(total_revenue - total_mat) / max(total_revenue, 1) * 100:.1f}%.",
        styles['Body']))

    # Product Details
    story.append(Paragraph("Product Details", styles['H1']))
    for p in products:
        story.append(Paragraph(p.get('name', 'Product'), styles['H2']))
        ann = sum(p.get('history', []))
        mat = sum(b.get('cost', 0) * b.get('qtyPer', 1) for b in p.get('bom', []))
        tbl_data = [
            ['Parameter', 'Value'],
            ['Annual Demand', f"{ann:,} units"],
            ['Selling Price', f"{cur}{p.get('sellPrice', 0)}"],
            ['Unit Material Cost', f"{cur}{mat:.2f}"],
            ['Variable Cost', f"{cur}{p.get('variableCost', 0)}"],
            ['Setup Cost/Batch', f"{cur}{p.get('setupCost', 0)}"],
            ['Capacity', f"{p.get('capacity', 0)} units/week"],
            ['Shelf Life', f"{p.get('shelfLife', 52)} weeks"],
            ['Yield', f"{p.get('yieldPct', 0.95)*100:.0f}%"],
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
                    str(b.get('qtyPer', 1)),
                    f"{cur}{b.get('cost', 0)}",
                    str(b.get('leadTime', 1)),
                    str(b.get('moq', 10)),
                    b.get('supplierType', 'domestic'),
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
