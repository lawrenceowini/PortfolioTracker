"""
pdf_report.py — Phase 10: Professional PDF Report Generation
=============================================================
Generates a fully branded, professional-grade PDF portfolio report with:

  - Cover page (PRO_LAW logo, portfolio name, date, executive summary)
  - Branded header and footer on every page (logo, page numbers)
  - Executive Summary (total value, top holdings, risk score, key metrics)
  - Holdings table (all positions, market values, allocations)
  - Sector allocation (table + embedded pie chart)
  - Performance history chart (6-month trend)
  - Risk analysis (violations, rebalancing suggestions)
  - Dividend summary
  - Tax summary (CGT estimate, WHT)
  - Appendix (NSE prices, transactions log)

Requires: reportlab
Install:  pip install reportlab --break-system-packages

Usage:
    from pdf_report import generate_professional_report
    generate_professional_report(
        output_path="reports/MyPortfolio_Report.pdf",
        portfolio_name="My Portfolio",
        sheets=sheets_dict,          # from load_workbook_sheets()
        logo_path="Logo.png",        # optional
        password=None,               # optional PDF password
    )
"""

import os
import io
import math
import datetime
import tempfile
from typing import Optional

import pandas as pd
import numpy as np

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm, cm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image,
        Table, TableStyle, HRFlowable, KeepTogether, NextPageTemplate,
        PageTemplate, Frame,
    )
    from reportlab.platypus.flowables import Flowable
    from reportlab.graphics.shapes import Drawing, Rect, String, Line
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    from reportlab.pdfgen import canvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# ── Brand colours (matching dashboard) ────────────────────────────────────────
DARK_OLIVE   = colors.HexColor("#3B4436")
CREAM        = colors.HexColor("#F1E9CB")
TEXT_DARK    = colors.HexColor("#2F332E")
WARM_BEIGE   = colors.HexColor("#E6DFD3")
WARM_WHITE   = colors.HexColor("#FDFBF7")
SOFT_BEIGE   = colors.HexColor("#EAECE6")
BORDER_COLOR = colors.HexColor("#B8AA91")
ACCENT       = colors.HexColor("#7A8C6E")
GREEN_OK     = colors.HexColor("#16a34a")
RED_BAD      = colors.HexColor("#dc2626")
AMBER        = colors.HexColor("#d97706")

PAGE_W, PAGE_H = A4
MARGIN        = 18 * mm
CONTENT_W     = PAGE_W - 2 * MARGIN


# ── Helper: format KES ─────────────────────────────────────────────────────────
def _kes(v):
    try:
        return f"KES {float(v):,.2f}"
    except Exception:
        return str(v)


def _pct(v):
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return str(v)


def _num(v):
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


# ── Header / Footer canvas callback ───────────────────────────────────────────

class _BrandedPage:
    """Draws the branded header and footer on every page via onPage callback."""

    def __init__(self, portfolio_name: str, logo_path: Optional[str], total_pages_ref: list):
        self.portfolio_name  = portfolio_name
        self.logo_path       = logo_path
        self.total_pages_ref = total_pages_ref   # mutable list so we can update after build

    def __call__(self, canv, doc):
        canv.saveState()
        w, h = A4

        # ── Header bar ────────────────────────────────────────────────────────
        canv.setFillColor(DARK_OLIVE)
        canv.rect(0, h - 16*mm, w, 16*mm, fill=1, stroke=0)

        # Logo in header (small, white-ish)
        if self.logo_path and os.path.exists(self.logo_path):
            try:
                canv.drawImage(
                    self.logo_path,
                    MARGIN, h - 14*mm,
                    width=28*mm, height=10*mm,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception:
                pass

        # Portfolio name in header
        canv.setFillColor(CREAM)
        canv.setFont("Helvetica-Bold", 9)
        canv.drawRightString(w - MARGIN, h - 10*mm, self.portfolio_name)

        # ── Footer bar ────────────────────────────────────────────────────────
        canv.setFillColor(SOFT_BEIGE)
        canv.rect(0, 0, w, 12*mm, fill=1, stroke=0)

        canv.setFillColor(BORDER_COLOR)
        canv.rect(0, 12*mm, w, 0.3*mm, fill=1, stroke=0)

        # Left: PRO_LAW branding
        canv.setFillColor(TEXT_DARK)
        canv.setFont("Helvetica", 7)
        canv.drawString(MARGIN, 4.5*mm, "PRO_LAW Portfolio Tracking System")

        # Centre: date
        date_str = datetime.datetime.now().strftime("%d %B %Y")
        canv.drawCentredString(w / 2, 4.5*mm, f"Generated: {date_str}")

        # Right: page number
        canv.drawRightString(
            w - MARGIN, 4.5*mm,
            f"Page {doc.page}",
        )

        # Disclaimer line
        canv.setFont("Helvetica-Oblique", 6)
        canv.setFillColor(ACCENT)
        canv.drawCentredString(
            w / 2, 1.5*mm,
            "For informational purposes only. Not financial advice. Prices from NSE via mansamarkets.com.",
        )

        canv.restoreState()


# ── Styles ─────────────────────────────────────────────────────────────────────

def _make_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["cover_title"] = ParagraphStyle(
        "cover_title", parent=base["Title"],
        fontSize=32, fontName="Helvetica-Bold",
        textColor=DARK_OLIVE, spaceAfter=6*mm, alignment=TA_CENTER,
    )
    styles["cover_sub"] = ParagraphStyle(
        "cover_sub", parent=base["Normal"],
        fontSize=14, fontName="Helvetica",
        textColor=ACCENT, spaceAfter=4*mm, alignment=TA_CENTER,
    )
    styles["cover_date"] = ParagraphStyle(
        "cover_date", parent=base["Normal"],
        fontSize=11, fontName="Helvetica",
        textColor=TEXT_DARK, spaceAfter=2*mm, alignment=TA_CENTER,
    )
    styles["section_heading"] = ParagraphStyle(
        "section_heading", parent=base["Heading1"],
        fontSize=13, fontName="Helvetica-Bold",
        textColor=CREAM, backColor=DARK_OLIVE,
        spaceBefore=6*mm, spaceAfter=3*mm,
        leftIndent=-2*mm, rightIndent=-2*mm,
        leading=18, borderPadding=(4, 6, 4, 6),
    )
    styles["sub_heading"] = ParagraphStyle(
        "sub_heading", parent=base["Heading2"],
        fontSize=10, fontName="Helvetica-Bold",
        textColor=DARK_OLIVE, spaceBefore=4*mm, spaceAfter=2*mm,
        borderPadding=(0, 0, 2, 0),
    )
    styles["body"] = ParagraphStyle(
        "body", parent=base["Normal"],
        fontSize=9, fontName="Helvetica",
        textColor=TEXT_DARK, spaceAfter=2*mm, leading=13,
    )
    styles["body_bold"] = ParagraphStyle(
        "body_bold", parent=base["Normal"],
        fontSize=9, fontName="Helvetica-Bold",
        textColor=TEXT_DARK, spaceAfter=1*mm,
    )
    styles["kpi_label"] = ParagraphStyle(
        "kpi_label", parent=base["Normal"],
        fontSize=7, fontName="Helvetica",
        textColor=ACCENT, spaceAfter=0, alignment=TA_CENTER,
    )
    styles["kpi_value"] = ParagraphStyle(
        "kpi_value", parent=base["Normal"],
        fontSize=14, fontName="Helvetica-Bold",
        textColor=DARK_OLIVE, spaceAfter=2*mm, alignment=TA_CENTER,
    )
    styles["disclaimer"] = ParagraphStyle(
        "disclaimer", parent=base["Normal"],
        fontSize=7, fontName="Helvetica-Oblique",
        textColor=ACCENT, spaceAfter=2*mm, alignment=TA_CENTER,
    )
    styles["table_header"] = ParagraphStyle(
        "table_header", parent=base["Normal"],
        fontSize=8, fontName="Helvetica-Bold", textColor=CREAM,
    )
    styles["table_cell"] = ParagraphStyle(
        "table_cell", parent=base["Normal"],
        fontSize=8, fontName="Helvetica", textColor=TEXT_DARK,
    )
    return styles


# ── Table style builder ────────────────────────────────────────────────────────

def _table_style(row_count: int, header_rows: int = 1) -> TableStyle:
    cmds = [
        ("BACKGROUND",  (0, 0), (-1, header_rows - 1), DARK_OLIVE),
        ("TEXTCOLOR",   (0, 0), (-1, header_rows - 1), CREAM),
        ("FONTNAME",    (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, header_rows - 1), 8),
        ("FONTNAME",    (0, header_rows), (-1, -1), "Helvetica"),
        ("FONTSIZE",    (0, header_rows), (-1, -1), 8),
        ("TEXTCOLOR",   (0, header_rows), (-1, -1), TEXT_DARK),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1), [WARM_WHITE, WARM_BEIGE]),
        ("GRID",        (0, 0), (-1, -1), 0.4, BORDER_COLOR),
        ("ALIGN",       (0, 0), (-1, -1), "CENTER"),
        ("ALIGN",       (0, 0), (0, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
    ]
    return TableStyle(cmds)


# ── KPI card row ───────────────────────────────────────────────────────────────

def _kpi_row(kpis: list, styles: dict) -> Table:
    """
    kpis: list of (label, value) tuples — max 4 per row
    """
    cells = []
    for label, value in kpis:
        cell = [
            Paragraph(str(label), styles["kpi_label"]),
            Paragraph(str(value), styles["kpi_value"]),
        ]
        cells.append(cell)

    col_w = CONTENT_W / len(kpis)
    tbl   = Table([cells], colWidths=[col_w] * len(kpis))
    tbl.setStyle(TableStyle([
        ("BOX",        (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("INNERGRID",  (0, 0), (-1, -1), 0.5, BORDER_COLOR),
        ("BACKGROUND", (0, 0), (-1, -1), SOFT_BEIGE),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
    ]))
    return tbl


# ── Pie chart (reportlab native) ──────────────────────────────────────────────

def _pie_chart(labels: list, values: list, title: str, width: float = 120, height: float = 120) -> Drawing:
    d   = Drawing(width, height + 20)
    pie = Pie()
    pie.x         = width // 2 - 40
    pie.y         = 20
    pie.width     = 80
    pie.height    = 80
    pie.data      = [max(0, float(v)) for v in values]
    pie.labels    = [str(l) for l in labels]
    pie.simpleLabels = 0
    pie.slices.strokeWidth  = 0.5
    pie.slices.strokeColor  = colors.white

    palette = [DARK_OLIVE, ACCENT, WARM_BEIGE, BORDER_COLOR,
               colors.HexColor("#C0392B"), colors.HexColor("#2980B9"),
               colors.HexColor("#8E44AD"), colors.HexColor("#F39C12")]
    for i in range(len(values)):
        pie.slices[i].fillColor = palette[i % len(palette)]

    d.add(pie)
    # Title
    d.add(String(width // 2, height + 8, title,
                 fontName="Helvetica-Bold", fontSize=8,
                 fillColor=TEXT_DARK, textAnchor="middle"))
    return d


# ── Bar chart ─────────────────────────────────────────────────────────────────

def _bar_chart(labels: list, values: list, title: str,
               width: float = 180, height: float = 90) -> Drawing:
    d    = Drawing(width, height + 20)
    bc   = VerticalBarChart()
    bc.x = 30
    bc.y = 20
    bc.width  = width - 40
    bc.height = height - 20
    bc.data   = [[max(0, float(v)) for v in values]]
    bc.categoryAxis.categoryNames = [str(l) for l in labels]
    bc.categoryAxis.labels.angle  = 30
    bc.categoryAxis.labels.fontSize = 6
    bc.bars[0].fillColor = DARK_OLIVE
    bc.valueAxis.labels.fontSize = 6

    d.add(bc)
    d.add(String(width // 2, height + 8, title,
                 fontName="Helvetica-Bold", fontSize=8,
                 fillColor=TEXT_DARK, textAnchor="middle"))
    return d


# ── Line chart (performance) ───────────────────────────────────────────────────

def _line_chart(dates: list, values: list, title: str,
                width: float = CONTENT_W * 0.7, height: float = 80) -> Drawing:
    if len(values) < 2:
        return Drawing(width, height)

    d   = Drawing(width, height + 20)
    lc  = HorizontalLineChart()
    lc.x = 40
    lc.y = 20
    lc.width  = width - 50
    lc.height = height - 20
    lc.data   = [[float(v) for v in values]]
    lc.lines[0].strokeColor = DARK_OLIVE
    lc.lines[0].strokeWidth = 1.5
    lc.categoryAxis.categoryNames = [str(d)[-5:] for d in dates]   # MM-DD
    lc.categoryAxis.labels.angle  = 30
    lc.categoryAxis.labels.fontSize = 6
    lc.valueAxis.labels.fontSize    = 6

    d.add(lc)
    d.add(String(width // 2, height + 8, title,
                 fontName="Helvetica-Bold", fontSize=8,
                 fillColor=TEXT_DARK, textAnchor="middle"))
    return d


# ── Data extractors ───────────────────────────────────────────────────────────

def _safe_num(df, col, default=0.0):
    if col not in df.columns:
        return default
    return pd.to_numeric(df[col], errors="coerce").fillna(default)


def _find_col(df, name):
    for c in df.columns:
        if c.strip().lower() == name.lower():
            return c
    return None


def _extract_summary(sheets: dict) -> dict:
    """Pull key metrics from loaded sheets."""
    holdings = sheets.get("holdings", pd.DataFrame())
    dash     = sheets.get("dashboard", pd.DataFrame())
    hist     = sheets.get("history",   pd.DataFrame())
    nse      = sheets.get("nse",       pd.DataFrame())
    div      = sheets.get("dividends", pd.DataFrame())
    tx       = sheets.get("tx",        pd.DataFrame())

    total_val   = 0.0
    num_assets  = 0
    num_sectors = 0

    if not dash.empty:
        for _, row in dash.iterrows():
            m = str(row.get("Metric","")).strip()
            v = row.get("Value", 0)
            if "Total Portfolio Value" in m:
                try: total_val = float(v)
                except: pass
            elif "Number of Assets" in m:
                try: num_assets = int(v)
                except: pass
            elif "Number of Sectors" in m:
                try: num_sectors = int(v)
                except: pass

    if total_val == 0 and not holdings.empty:
        mv_c = _find_col(holdings, "Market Value")
        if mv_c:
            total_val = pd.to_numeric(holdings[mv_c], errors="coerce").fillna(0).sum()
        num_assets  = len(holdings)
        sc = _find_col(holdings, "Sector")
        num_sectors = holdings[sc].nunique() if sc else 0

    # Largest holding
    largest_asset = "—"
    if not holdings.empty:
        mv_c  = _find_col(holdings, "Market Value")
        ast_c = _find_col(holdings, "Asset")
        if mv_c and ast_c:
            holdings[mv_c] = pd.to_numeric(holdings[mv_c], errors="coerce")
            idx = holdings[mv_c].idxmax()
            if pd.notna(idx):
                largest_asset = str(holdings.loc[idx, ast_c])

    # Gain/loss
    gain_loss = 0.0
    if not holdings.empty:
        gl_c = _find_col(holdings, "Gain/Loss")
        if gl_c:
            gain_loss = pd.to_numeric(holdings[gl_c], errors="coerce").fillna(0).sum()

    # Total dividends
    total_div = 0.0
    if not div.empty:
        for col in ["Annual Dividend", "Total Dividend"]:
            dc = _find_col(div, col)
            if dc:
                total_div = pd.to_numeric(div[dc], errors="coerce").fillna(0).sum()
                break

    return {
        "total_val"    : total_val,
        "num_assets"   : num_assets,
        "num_sectors"  : num_sectors,
        "largest_asset": largest_asset,
        "gain_loss"    : gain_loss,
        "total_div"    : total_div,
        "holdings"     : holdings,
        "hist"         : hist,
        "nse"          : nse,
        "div"          : div,
        "tx"           : tx,
        "dash"         : dash,
    }


# ── Main generator ─────────────────────────────────────────────────────────────

def generate_professional_report(
    output_path: str,
    portfolio_name: str,
    sheets: dict,
    logo_path: Optional[str] = None,
    password: Optional[str] = None,
) -> tuple:
    """
    Generate a professional branded PDF report.
    Returns (success: bool, message: str)
    """
    if not HAS_REPORTLAB:
        return False, "reportlab is not installed. Run: pip install reportlab --break-system-packages"

    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        styles  = _make_styles()
        summary = _extract_summary(sheets)
        story   = []

        total_pages_ref = [0]
        branded_page    = _BrandedPage(portfolio_name, logo_path, total_pages_ref)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            topMargin    = 20 * mm,
            bottomMargin = 16 * mm,
            leftMargin   = MARGIN,
            rightMargin  = MARGIN,
            title        = f"{portfolio_name} — Portfolio Report",
            author       = "PRO_LAW Portfolio Tracking System",
            subject      = "Portfolio Report",
        )

        # ════════════════════════════════════════════════════════════════════
        # COVER PAGE
        # ════════════════════════════════════════════════════════════════════
        story.append(Spacer(1, 30 * mm))

        # Logo (large, centred)
        if logo_path and os.path.exists(logo_path):
            try:
                story.append(Image(logo_path, width=80*mm, height=32*mm,
                                   kind="proportional", hAlign="CENTER"))
            except Exception:
                pass
        story.append(Spacer(1, 10 * mm))

        # Title
        story.append(Paragraph(portfolio_name, styles["cover_title"]))
        story.append(Paragraph("Portfolio Report", styles["cover_sub"]))
        story.append(Paragraph(
            datetime.datetime.now().strftime("%d %B %Y"),
            styles["cover_date"],
        ))
        story.append(Spacer(1, 8 * mm))

        # Divider
        story.append(HRFlowable(width=CONTENT_W, thickness=1.5,
                                color=DARK_OLIVE, spaceAfter=8*mm))

        # Cover KPIs
        _tv_str  = _kes(summary["total_val"]) if summary["total_val"] > 0 else "Template / No data"
        _gl_str  = _kes(summary["gain_loss"]) if summary["total_val"] > 0 else "—"
        _div_str = _kes(summary["total_div"]) if summary["total_div"] > 0 else "—"
        _ast_str = str(summary["num_assets"]) if summary["num_assets"] > 0 else "0 (template)"
        _sec_str = str(summary["num_sectors"]) if summary["num_sectors"] > 0 else "0 (template)"

        story.append(_kpi_row([
            ("Total Portfolio Value", _tv_str),
            ("Holdings",              _ast_str),
            ("Sectors",               _sec_str),
            ("Total Gain / Loss",     _gl_str),
        ], styles))
        story.append(Spacer(1, 6 * mm))

        story.append(_kpi_row([
            ("Largest Position", summary["largest_asset"]),
            ("Annual Dividends", _div_str),
            ("Report Date",      datetime.datetime.now().strftime("%d %b %Y")),
            ("Prepared by",      "PRO_LAW System"),
        ], styles))
        story.append(Spacer(1, 10 * mm))

        # Executive summary text
        if summary["total_val"] > 0:
            gl_word   = "gain" if summary["gain_loss"] >= 0 else "loss"
            exec_text = (
                f"This report provides a comprehensive overview of <b>{portfolio_name}</b> as at "
                f"{datetime.datetime.now().strftime('%d %B %Y')}. "
                f"The portfolio holds <b>{summary['num_assets']} assets</b> across "
                f"<b>{summary['num_sectors']} sectors</b>, with a total market value of "
                f"<b>{_kes(summary['total_val'])}</b>. "
                f"The portfolio has recorded a net unrealised {gl_word} of "
                f"<b>{_kes(abs(summary['gain_loss']))}</b> on current positions. "
                f"Annual dividend income amounts to <b>{_kes(summary['total_div'])}</b>. "
                f"The largest single position is <b>{summary['largest_asset']}</b>."
            )
        else:
            exec_text = (
                f"This document is a <b>portfolio report template</b> for <b>{portfolio_name}</b>, "
                f"generated on {datetime.datetime.now().strftime('%d %B %Y')}. "
                f"No portfolio data has been entered yet. Fill in the Excel template with your holdings "
                f"and run <b>update_portfolio.py</b> to generate a populated report."
            )
        story.append(Paragraph(exec_text, styles["body"]))
        story.append(Spacer(1, 6 * mm))

        # Disclaimer on cover
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5,
                                color=BORDER_COLOR, spaceAfter=4*mm))
        story.append(Paragraph(
            "This report is generated by PRO_LAW Portfolio Tracking System for informational purposes only. "
            "It does not constitute financial advice. Past performance is not indicative of future results. "
            "Prices are sourced from the Nairobi Securities Exchange via mansamarkets.com.",
            styles["disclaimer"],
        ))

        story.append(PageBreak())

        # ════════════════════════════════════════════════════════════════════
        # SECTION 1: HOLDINGS
        # ════════════════════════════════════════════════════════════════════
        story.append(Paragraph("1. Holdings", styles["section_heading"]))

        holdings = summary["holdings"]
        if not holdings.empty:
            display_cols = ["Asset","Sector","Shares","Current Price","Market Value","Asset Allocation %","Average Return %"]
            show_cols    = [_find_col(holdings, c) for c in display_cols]
            show_cols    = [c for c in show_cols if c]
            h_display    = holdings[show_cols].copy()

            for col in show_cols:
                col_l = col.lower()
                if "price" in col_l or "value" in col_l or "gain" in col_l:
                    h_display[col] = pd.to_numeric(h_display[col], errors="coerce").map(
                        lambda x: _kes(x) if pd.notna(x) else ""
                    )
                elif "%" in col_l or "alloc" in col_l or "return" in col_l:
                    h_display[col] = pd.to_numeric(h_display[col], errors="coerce").map(
                        lambda x: _pct(x) if pd.notna(x) else ""
                    )
                elif "shares" in col_l:
                    h_display[col] = pd.to_numeric(h_display[col], errors="coerce").map(
                        lambda x: f"{x:,.2f}" if pd.notna(x) else ""
                    )

            # Shorten column headers
            short_headers = {
                "Asset Allocation %": "Alloc %",
                "Average Return %"  : "Return %",
                "Current Price"     : "Price",
                "Market Value"      : "Mkt Value",
            }
            h_display.columns = [short_headers.get(c, c) for c in h_display.columns]

            if not h_display.empty and len(h_display.columns) > 0:
                tbl_data = [list(h_display.columns)] + h_display.fillna("").values.tolist()
                col_w    = CONTENT_W / len(h_display.columns)
                tbl      = Table(tbl_data, colWidths=[col_w] * len(h_display.columns), repeatRows=1)
                tbl.setStyle(_table_style(len(tbl_data)))
                story.append(tbl)
            else:
                story.append(Paragraph("Holdings table is empty — no positions recorded yet.", styles["body"]))
        else:
            story.append(Paragraph("No holdings data available.", styles["body"]))

        story.append(PageBreak())

        # ════════════════════════════════════════════════════════════════════
        # SECTION 2: SECTOR ALLOCATION
        # ════════════════════════════════════════════════════════════════════
        story.append(Paragraph("2. Sector Allocation", styles["section_heading"]))

        if not holdings.empty:
            mv_c = _find_col(holdings, "Market Value")
            sc_c = _find_col(holdings, "Sector")
            if mv_c and sc_c:
                holdings[mv_c] = pd.to_numeric(holdings[mv_c], errors="coerce").fillna(0)
                total_mv = holdings[mv_c].sum()
                sector_df = holdings.groupby(sc_c)[mv_c].sum().reset_index()
                sector_df.columns = ["Sector", "Market Value (KES)"]
                sector_df["Allocation %"] = (sector_df["Market Value (KES)"] / total_mv * 100).round(2)
                sector_df = sector_df.sort_values("Allocation %", ascending=False)

                # Side-by-side: table + pie
                if not sector_df.empty and sector_df["Market Value (KES)"].sum() > 0:
                    tbl_data = [["Sector", "Market Value", "Allocation %"]]
                    for _, row in sector_df.iterrows():
                        tbl_data.append([
                            str(row["Sector"]),
                            _kes(row["Market Value (KES)"]),
                            _pct(row["Allocation %"]),
                        ])

                    sec_tbl = Table(tbl_data, colWidths=[70*mm, 55*mm, 35*mm], repeatRows=1)
                    sec_tbl.setStyle(_table_style(len(tbl_data)))

                    pie = _pie_chart(
                        labels=sector_df["Sector"].tolist(),
                        values=sector_df["Allocation %"].tolist(),
                        title="Sector Allocation",
                        width=130, height=110,
                    )

                    layout = Table([[sec_tbl, pie]], colWidths=[CONTENT_W * 0.58, CONTENT_W * 0.42])
                    layout.setStyle(TableStyle([
                        ("VALIGN", (0,0), (-1,-1), "TOP"),
                        ("LEFTPADDING", (0,0), (-1,-1), 0),
                        ("RIGHTPADDING", (0,0), (-1,-1), 0),
                    ]))
                    story.append(layout)
                else:
                    story.append(Paragraph("No sector data available — add holdings to populate this section.", styles["body"]))

        story.append(PageBreak())

        # ════════════════════════════════════════════════════════════════════
        # SECTION 3: PERFORMANCE HISTORY
        # ════════════════════════════════════════════════════════════════════
        story.append(Paragraph("3. Performance History", styles["section_heading"]))

        hist_df = summary["hist"]
        port_hist = pd.DataFrame()

        if not hist_df.empty:
            for i, row in hist_df.iterrows():
                vals = [str(v).strip() for v in row.values if pd.notna(v) and str(v).strip() not in ("","nan")]
                if "Portfolio Value" in vals and "Date" in vals:
                    sub = hist_df.iloc[i:].copy()
                    sub.columns = sub.iloc[0]
                    sub = sub[1:].dropna(how="all").reset_index(drop=True)
                    sub["Date"]            = pd.to_datetime(sub["Date"], errors="coerce")
                    sub["Portfolio Value"] = pd.to_numeric(sub["Portfolio Value"], errors="coerce")
                    port_hist = sub.dropna(subset=["Date","Portfolio Value"]).sort_values("Date")
                    break

        if not port_hist.empty and len(port_hist) >= 2:
            # Last 12 months
            cutoff    = pd.Timestamp.now() - pd.DateOffset(months=12)
            plot_data = port_hist[port_hist["Date"] >= cutoff].copy()

            if len(plot_data) >= 2:
                dates  = plot_data["Date"].dt.strftime("%m-%d").tolist()
                values = plot_data["Portfolio Value"].tolist()

                line = _line_chart(dates, values, "Portfolio Value — Last 12 Months",
                                   width=CONTENT_W, height=90)
                story.append(line)
                story.append(Spacer(1, 4*mm))

                # Period return stats
                first_v = float(plot_data["Portfolio Value"].iloc[0])
                last_v  = float(plot_data["Portfolio Value"].iloc[-1])
                ret_pct = (last_v - first_v) / first_v * 100 if first_v > 0 else 0

                story.append(_kpi_row([
                    ("Opening Value",   _kes(first_v)),
                    ("Current Value",   _kes(last_v)),
                    ("Period Return",   f"{ret_pct:+.2f}%"),
                    ("Data Points",     str(len(plot_data))),
                ], styles))
            else:
                story.append(Paragraph("Insufficient data for performance chart (need ≥ 2 data points).", styles["body"]))
        else:
            story.append(Paragraph(
                "No performance history data found. Run update_portfolio.py regularly to build history.",
                styles["body"],
            ))

        story.append(PageBreak())

        # ════════════════════════════════════════════════════════════════════
        # SECTION 4: RISK ANALYSIS
        # ════════════════════════════════════════════════════════════════════
        story.append(Paragraph("4. Risk Analysis", styles["section_heading"]))

        dash_df = summary["dash"]
        if not dash_df.empty:
            def _extract_sub_table(df, keyword):
                raw = df.values.tolist()
                for ri, row in enumerate(raw):
                    str_vals = [str(v).strip() for v in row if v is not None and str(v).strip() not in ("","nan")]
                    if any(keyword.lower() in v.lower() for v in str_vals):
                        headers  = [str(v).strip() if (v is not None and str(v).strip() not in ("","nan")) else "" for v in row]
                        data_rows = []
                        for dr in raw[ri+1:]:
                            str_dr = [str(v).strip() for v in dr if v is not None and str(v).strip() not in ("","nan")]
                            if not str_dr:
                                break
                            data_rows.append([str(v) if pd.notna(v) else "" for v in dr])
                        if data_rows:
                            return [headers] + data_rows
                return []

            risk_data = _extract_sub_table(dash_df, "Metric")
            if risk_data and len(risk_data) > 1 and len(risk_data[0]) > 0:
                story.append(Paragraph("Risk Summary", styles["sub_heading"]))
                col_w = CONTENT_W / max(len(risk_data[0]), 1)
                rtbl  = Table(risk_data, colWidths=[col_w] * len(risk_data[0]), repeatRows=1)
                rtbl.setStyle(_table_style(len(risk_data)))
                story.append(rtbl)
                story.append(Spacer(1, 4*mm))
            else:
                story.append(Paragraph("Risk data not available — run update_portfolio.py to populate.", styles["body"]))

            # Rebalance suggestions
            reb_data = _extract_sub_table(dash_df, "Estimated Value")
            if reb_data and len(reb_data) > 1 and len(reb_data[0]) > 0:
                story.append(Paragraph("Rebalancing Suggestions", styles["sub_heading"]))
                col_w = CONTENT_W / max(len(reb_data[0]), 1)
                rtbl2 = Table(reb_data, colWidths=[col_w] * len(reb_data[0]), repeatRows=1)
                rtbl2.setStyle(_table_style(len(reb_data)))
                story.append(rtbl2)
            else:
                story.append(Paragraph("No rebalancing suggestions — portfolio may already be balanced or no data yet.", styles["body"]))
        else:
            story.append(Paragraph("No risk data found.", styles["body"]))

        story.append(PageBreak())

        # ════════════════════════════════════════════════════════════════════
        # SECTION 5: DIVIDENDS
        # ════════════════════════════════════════════════════════════════════
        story.append(Paragraph("5. Dividend Summary", styles["section_heading"]))

        div_df = summary["div"]
        if not div_df.empty:
            # Summary KPIs
            div_col = _find_col(div_df, "Annual Dividend") or _find_col(div_df, "Total Dividend")
            if div_col:
                total_div = pd.to_numeric(div_df[div_col], errors="coerce").fillna(0).sum()
                mv_col    = _find_col(holdings, "Market Value")
                total_mv2 = pd.to_numeric(holdings[mv_col], errors="coerce").fillna(0).sum() if mv_col else 0
                yield_pct = total_div / total_mv2 * 100 if total_mv2 > 0 else 0

                story.append(_kpi_row([
                    ("Total Annual Dividends", _kes(total_div)),
                    ("Portfolio Dividend Yield", _pct(yield_pct)),
                    ("WHT (5%)", _kes(total_div * 0.05)),
                    ("Net Dividends", _kes(total_div * 0.95)),
                ], styles))
                story.append(Spacer(1, 4*mm))

            # Per-asset table
            disp_cols = [c for c in div_df.columns if c.strip().lower() not in ("metric","value") and not div_df[c].isna().all()]
            if disp_cols and len(disp_cols) > 0:
                div_display = div_df[disp_cols].head(20).copy()
                if not div_display.empty and len(div_display.columns) > 0:
                    tbl_data = [list(div_display.columns)] + div_display.fillna("").values.tolist()
                    col_w    = CONTENT_W / len(div_display.columns)
                    dtbl     = Table(tbl_data, colWidths=[col_w] * len(div_display.columns), repeatRows=1)
                    dtbl.setStyle(_table_style(len(tbl_data)))
                    story.append(dtbl)
                else:
                    story.append(Paragraph("No dividend entries recorded yet.", styles["body"]))
        else:
            story.append(Paragraph("No dividend data found. Ensure your input Excel has a Dividend Tracking sheet.", styles["body"]))

        story.append(PageBreak())

        # ════════════════════════════════════════════════════════════════════
        # SECTION 6: NSE PRICES
        # ════════════════════════════════════════════════════════════════════
        story.append(Paragraph("6. NSE Live Prices", styles["section_heading"]))

        nse_df = summary["nse"]
        if not nse_df.empty and len(nse_df.columns) > 0:
            tbl_data = [list(nse_df.columns)] + nse_df.fillna("").values.tolist()
            col_w    = CONTENT_W / len(nse_df.columns)
            ntbl     = Table(tbl_data, colWidths=[col_w] * len(nse_df.columns), repeatRows=1)
            ntbl.setStyle(_table_style(len(tbl_data)))
            story.append(ntbl)
        else:
            story.append(Paragraph("No NSE price data found. Run update_portfolio.py to populate this section.", styles["body"]))

        story.append(Spacer(1, 6*mm))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=BORDER_COLOR))
        story.append(Spacer(1, 3*mm))
        story.append(Paragraph(
            f"End of Report — {portfolio_name} — Generated {datetime.datetime.now().strftime('%d %B %Y at %H:%M')}",
            styles["disclaimer"],
        ))

        # ── Build PDF ──────────────────────────────────────────────────────
        doc.build(story, onFirstPage=branded_page, onLaterPages=branded_page)

        # ── Optional password protection ───────────────────────────────────
        if password:
            try:
                from PyPDF2 import PdfReader, PdfWriter
                reader = PdfReader(output_path)
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                writer.encrypt(password)
                with open(output_path, "wb") as f:
                    writer.write(f)
            except ImportError:
                pass   # PyPDF2 not installed — skip encryption

        size_kb = os.path.getsize(output_path) / 1024
        return True, f"Report generated: {output_path} ({size_kb:.1f} KB)"

    except Exception as e:
        import traceback
        return False, f"PDF generation failed: {e}\n{traceback.format_exc()}"
