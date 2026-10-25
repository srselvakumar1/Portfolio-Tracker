import os
from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from model.applog import log

FONT_NORMAL = 'Helvetica'
FONT_BOLD = 'Helvetica-Bold'

# Try to register a Unicode-supporting font (like Arial Unicode)
arial_path = "/System/Library/Fonts/Supplemental/Georgia.ttf"
if not os.path.exists(arial_path):
    arial_path = "/Library/Fonts/Georgia.ttf"
arial_bold_path = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
if not os.path.exists(arial_bold_path):
    arial_bold_path = "/Library/Fonts/Georgia Bold.ttf"

if os.path.exists(arial_path) and os.path.exists(arial_bold_path):
    try:
        pdfmetrics.registerFont(TTFont('ArialCustom', arial_path))
        pdfmetrics.registerFont(TTFont('ArialCustom-Bold', arial_bold_path))
        FONT_NORMAL = 'ArialCustom'
        FONT_BOLD = 'ArialCustom-Bold'
    except Exception:
        log.exception("PDF export: could not load the Georgia font; using Helvetica")

from model.database import db_session

_SYMBOLS = {"INR": "₹", "JPY": "¥", "USD": "$", "GBP": "£", "CNY": "¥"}


def _currency_prefix(code: str) -> str:
    """₹ for INR, ¥ for JPY, $ for USD, £ for GBP; otherwise the code and a space."""
    code = str(code or "INR").upper()
    return _SYMBOLS.get(code, code + " ")

def _get_broker_holdings(broker_name: str, currency_filter: str) -> list:
    """Fetch holdings for a specific broker to detail in the PDF."""
    with db_session() as conn:
        cursor = conn.cursor()
        query = '''
            SELECT
                h.symbol,
                h.qty,
                h.avg_price,
                COALESCE(NULLIF(m.current_price, 0.0), h.avg_price),
                h.running_pnl,
                h.realized_pnl,
                h.currency
            FROM holdings h
            LEFT JOIN marketdata m ON h.symbol = m.symbol
            WHERE h.broker = ? AND (h.qty > 0 OR h.running_pnl != 0 OR h.realized_pnl != 0)
        '''
        params = [broker_name]
        if currency_filter != "All":
            query += " AND h.currency = ?"
            params.append(currency_filter.upper())
            
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        holdings = []
        for row in rows:
            qty = float(row[1] or 0.0)
            avg_price = float(row[2] or 0.0)
            mkt_price = float(row[3] or 0.0)
            running_pnl = float(row[4] or 0.0)
            real_pnl = float(row[5] or 0.0)
            
            invested = qty * avg_price
            current_val = qty * mkt_price
            unrealized = current_val - invested
            
            holdings.append({
                "symbol": row[0],
                "qty": qty,
                "avg_price": avg_price,
                "mkt_price": mkt_price,
                "invested": invested,
                "current_val": current_val,
                "unrealized_pnl": unrealized,
                "running_pnl": running_pnl,
                "realized_pnl": real_pnl
            })
            
        # Sort by current value descending
        holdings.sort(key=lambda x: x["current_val"], reverse=True)
        return holdings

def generate_broker_report_pdf(filepath: str, metrics: dict, currency_filter: str):
    doc = SimpleDocTemplate(filepath, pagesize=landscape(letter),
                            rightMargin=30, leftMargin=30, topMargin=60, bottomMargin=40)
    
    elements = []
    styles = getSampleStyleSheet()
    


    section_style = ParagraphStyle(
        'SectionStyle',
        parent=styles['Heading2'],
        fontName=FONT_BOLD,
        fontSize=16,
        textColor=colors.HexColor("#0f172a"), # Slate 900
        spaceAfter=15,
        spaceBefore=25
    )
    
    subsection_style = ParagraphStyle(
        'SubSectionStyle',
        parent=styles['Heading3'],
        fontName=FONT_BOLD,
        fontSize=14,
        textColor=colors.HexColor("#334155"), # Slate 700
        spaceAfter=10,
        spaceBefore=15
    )

    # Header is now drawn via canvas in draw_header_footer
    
    # Vibrant colors for premium look
    header_bg = colors.HexColor("#6366f1") # Indigo 500
    header_fg = colors.white
    row_even_bg = colors.HexColor("#f8fafc") # Slate 50
    row_odd_bg = colors.white
    profit_color = colors.HexColor("#10b981") # Emerald 500
    loss_color = colors.HexColor("#ef4444") # Red 500
    
    from collections import defaultdict
    grouped = defaultdict(list)
    for broker, data in metrics.items():
        c = data.get("currency", "INR")
        grouped[c].append((broker, data))
        
    valid_currencies = [c for c in sorted(grouped.keys()) if currency_filter == "All" or c == currency_filter]
    
    for c in valid_currencies:
        brokers_data = grouped[c]
        brokers_data.sort(key=lambda x: x[1].get("overall_pnl", 0.0), reverse=True)
        
        prefix = _currency_prefix(c)
        
        # 1. Summary Table (Broker Level)
        elements.append(Paragraph(f"Broker Summary - {c}", section_style))
        
        summary_data = [
            ["Broker", "Invested", "Current Value", "Unrealized P&L", "Unrealized Loss", "Realized P&L", "Realized Loss", "Total P&L", "XIRR"]
        ]
        
        total_inv = 0.0
        total_curr = 0.0
        total_unrealized = 0.0
        total_unrealized_loss = 0.0
        total_realized = 0.0
        total_realized_loss = 0.0
        total_overall = 0.0
        
        for broker, data in brokers_data:
            inv = data.get("total_invested", 0.0)
            curr = data.get("total_value", 0.0)
            overall = data.get("overall_pnl", 0.0)
            unrealized = data.get("unrealized_pnl", 0.0)
            unrealized_loss = data.get("unrealized_loss", 0.0)
            realized = data.get("realized_pnl", 0.0)
            realized_loss = data.get("realized_loss", 0.0)
            xirr = data.get("overall_xirr", 0.0)
            
            total_inv += inv
            total_curr += curr
            total_unrealized += unrealized
            total_unrealized_loss += unrealized_loss
            total_realized += realized
            total_realized_loss += realized_loss
            total_overall += overall
            
            # Formatting
            inv_str = f"{prefix}{inv:,.0f}"
            curr_str = f"{prefix}{curr:,.0f}"
            un_str = f"{prefix}{unrealized:,.0f}"
            un_loss_str = f"{prefix}{unrealized_loss:,.0f}"
            real_str = f"{prefix}{realized:,.0f}"
            real_loss_str = f"{prefix}{realized_loss:,.0f}"
            tot_str = f"{prefix}{overall:,.0f}"
            xirr_str = f"{xirr:.2f}%" if xirr else "0.00%"
            
            summary_data.append([broker, inv_str, curr_str, un_str, un_loss_str, real_str, real_loss_str, tot_str, xirr_str])
            
        summary_data.append([
            f"TOTAL ({c})", 
            f"{prefix}{total_inv:,.0f}", 
            f"{prefix}{total_curr:,.0f}", 
            f"{prefix}{total_unrealized:,.0f}", 
            f"{prefix}{total_unrealized_loss:,.0f}", 
            f"{prefix}{total_realized:,.0f}", 
            f"{prefix}{total_realized_loss:,.0f}", 
            f"{prefix}{total_overall:,.0f}", 
            ""
        ])
            
        summary_table = Table(summary_data, colWidths=[1.1*inch, 0.9*inch, 0.9*inch, 1*inch, 1*inch, 1*inch, 1*inch, 1*inch, 0.8*inch])
        
        # Base table style
        ts_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), header_bg),
            ('TEXTCOLOR', (0, 0), (-1, 0), header_fg),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),  # Broker name left aligned
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'), # Numbers right aligned
            ('FONTNAME', (0, 0), (-1, -1), FONT_NORMAL),
                    ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [row_odd_bg, row_even_bg])
        ]
        
        # Conditional text colors
        for i in range(1, len(summary_data) - 1):
            row = brokers_data[i-1][1]
            val_un = row.get("unrealized_pnl", 0.0) or 0.0
            ts_commands.append(('TEXTCOLOR', (3, i), (3, i), profit_color if val_un >= 0 else loss_color))
            ts_commands.append(('TEXTCOLOR', (4, i), (4, i), loss_color))
            val_real = row.get("realized_pnl", 0.0) or 0.0
            ts_commands.append(('TEXTCOLOR', (5, i), (5, i), profit_color if val_real >= 0 else loss_color))
            ts_commands.append(('TEXTCOLOR', (6, i), (6, i), loss_color))
            val_tot = row.get("overall_pnl", 0.0) or 0.0
            ts_commands.append(('TEXTCOLOR', (7, i), (7, i), profit_color if val_tot >= 0 else loss_color))
            val_xirr = row.get("overall_xirr", 0.0) or 0.0
            ts_commands.append(('TEXTCOLOR', (8, i), (8, i), profit_color if val_xirr >= 0 else loss_color))
            
        last_idx = len(summary_data) - 1
        ts_commands.append(('BACKGROUND', (0, last_idx), (-1, last_idx), colors.HexColor("#e2e8f0")))
        ts_commands.append(('FONTNAME', (0, last_idx), (-1, last_idx), FONT_BOLD))
        ts_commands.append(('TOPPADDING', (0, last_idx), (-1, last_idx), 10))
        ts_commands.append(('BOTTOMPADDING', (0, last_idx), (-1, last_idx), 10))
        ts_commands.append(('TEXTCOLOR', (3, last_idx), (3, last_idx), profit_color if total_unrealized >= 0 else loss_color))
        ts_commands.append(('TEXTCOLOR', (4, last_idx), (4, last_idx), loss_color))
        ts_commands.append(('TEXTCOLOR', (5, last_idx), (5, last_idx), profit_color if total_realized >= 0 else loss_color))
        ts_commands.append(('TEXTCOLOR', (6, last_idx), (6, last_idx), loss_color))
        ts_commands.append(('TEXTCOLOR', (7, last_idx), (7, last_idx), profit_color if total_overall >= 0 else loss_color))

        summary_table.setStyle(TableStyle(ts_commands))
        elements.append(summary_table)
        elements.append(Spacer(1, 30))
        
        # 1.5 Add Chart for this currency
        elements.append(Paragraph(f"Investment vs Current Value ({c})", section_style))
        
        drawing = Drawing(600, 220)
        bc = VerticalBarChart()
        bc.x = 60
        bc.y = 40
        bc.height = 160
        bc.width = 480
        
        chart_brokers = sorted(brokers_data, key=lambda x: x[1].get("total_value", 0.0), reverse=True)
        
        data_inv = []
        data_curr = []
        category_names = []
        
        for b, data in chart_brokers:
            category_names.append(b if len(b) <= 12 else b[:10] + "..")
            data_inv.append(data.get("total_invested", 0.0))
            data_curr.append(data.get("total_value", 0.0))
            
        bc.data = [data_inv, data_curr]
        bc.categoryAxis.categoryNames = category_names
        bc.categoryAxis.labels.fontSize = 10
        bc.categoryAxis.labels.fontName = FONT_BOLD
        bc.valueAxis.labels.fontSize = 10
        bc.valueAxis.valueMin = 0
        bc.bars[0].fillColor = colors.HexColor("#3b82f6") # Blue
        bc.bars[1].fillColor = colors.HexColor("#f59e0b") # Amber
        
        # Color specific bars red if they are at a loss
        for idx, (b, data) in enumerate(chart_brokers):
            inv = data.get("total_invested", 0.0)
            curr = data.get("total_value", 0.0)
            if curr < inv:
                bc.bars[(1, idx)].fillColor = colors.HexColor("#ef4444")
        
        legend = Legend()
        legend.x = 550
        legend.y = 200
        legend.dxTextSpace = 5
        legend.dy = 5
        legend.fontSize = 11
        legend.fontName = FONT_NORMAL
        legend.alignment = 'right'
        legend.colorNamePairs = [
            (bc.bars[0].fillColor, 'Invested'), 
            (bc.bars[1].fillColor, 'Value (Profit)'),
            (colors.HexColor("#ef4444"), 'Value (Loss)')
        ]
        
        drawing.add(bc)
        drawing.add(legend)
        
        elements.append(drawing)
        elements.append(Spacer(1, 30))
        
        # 2. Detailed Breakdown per Broker
        for broker, data in brokers_data:
            holdings = _get_broker_holdings(broker, c)
            if not holdings:
                continue
                
            active = [h for h in holdings if h["qty"] > 0]
            inactive = [h for h in holdings if h["qty"] <= 0]
                
            broker_elements = []
            
            # Broker Header
            broker_elements.append(Paragraph(f"Broker: {broker} ({c})", section_style))
            
            # Broker KPI Box
            b_inv = data.get("total_invested", 0.0)
            b_curr = data.get("total_value", 0.0)
            b_pnl = data.get("overall_pnl", 0.0)
            b_xirr = data.get("overall_xirr", 0.0)
            
            kpi_data = [
                ["Total Invested", "Current Value", "Overall P&L", "Overall XIRR"],
                [f"{prefix}{b_inv:,.2f}", f"{prefix}{b_curr:,.2f}", f"{prefix}{b_pnl:,.2f}", f"{b_xirr:.2f}%" if b_xirr else "0.00%"]
            ]
            kpi_table = Table(kpi_data, colWidths=[2*inch, 2*inch, 2*inch, 2*inch])
            kpi_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#f1f5f9")), # Slate 100
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor("#64748b")), # Slate 500
                ('TEXTCOLOR', (0, 1), (1, 1), colors.HexColor("#0f172a")), # Slate 900
                ('TEXTCOLOR', (2, 1), (2, 1), profit_color if b_pnl >= 0 else loss_color),
                ('TEXTCOLOR', (3, 1), (3, 1), profit_color if b_xirr >= 0 else loss_color),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, -1), FONT_NORMAL),
                    ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                ('FONTNAME', (0, 1), (-1, 1), FONT_BOLD),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('FONTSIZE', (0, 1), (-1, 1), 14),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
                ('TOPPADDING', (0, 1), (-1, 1), 2),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 12),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
                ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ]))
            broker_elements.append(kpi_table)
            broker_elements.append(Spacer(1, 15))
            
            # Active Holdings
            if active:
                broker_elements.append(Paragraph("Active Holdings", subsection_style))
                
                h_data = [["Symbol", "Qty", "Avg Price", "Mkt Price", "Invested", "Current Value", "Unrealized", "Realized"]]
                for h in active:
                    sym = h["symbol"]
                    qty_str = f"{h['qty']:g}"
                    avg_str = f"{h['avg_price']:,.2f}"
                    mkt_str = f"{h['mkt_price']:,.2f}"
                    inv_str = f"{h['invested']:,.0f}"
                    curr_str = f"{h['current_val']:,.0f}"
                    un_str = f"{h['unrealized_pnl']:,.0f}"
                    real_str = f"{h['realized_pnl']:,.0f}"
                    h_data.append([sym, qty_str, avg_str, mkt_str, inv_str, curr_str, un_str, real_str])
                    
                h_table = Table(h_data, colWidths=[1.5*inch, 0.8*inch, 1*inch, 1*inch, 1.2*inch, 1.2*inch, 1*inch, 1*inch])
                
                h_ts = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#334155")), # Slate 700
                    ('TEXTCOLOR', (0, 0), (-1, 0), header_fg),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('ALIGN', (0, 1), (0, -1), 'LEFT'),
                    ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                    ('FONTNAME', (0, 0), (-1, -1), FONT_NORMAL),
                    ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('TOPPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [row_odd_bg, row_even_bg])
                ]
                
                for i in range(1, len(h_data)):
                    val_un = active[i-1]["unrealized_pnl"]
                    h_ts.append(('TEXTCOLOR', (6, i), (6, i), profit_color if val_un >= 0 else loss_color))
                    val_real = active[i-1]["realized_pnl"]
                    h_ts.append(('TEXTCOLOR', (7, i), (7, i), profit_color if val_real >= 0 else loss_color))
                    
                h_table.setStyle(TableStyle(h_ts))
                broker_elements.append(h_table)
                broker_elements.append(Spacer(1, 15))
                
            # Inactive Holdings
            if inactive:
                broker_elements.append(Paragraph("Inactive Holdings (Closed Positions)", subsection_style))
                
                in_data = [["Symbol", "Realized P&L"]]
                for h in inactive:
                    sym = h["symbol"]
                    real_str = f"{h['realized_pnl']:,.0f}"
                    in_data.append([sym, real_str])
                    
                in_table = Table(in_data, colWidths=[3*inch, 2*inch])
                
                in_ts = [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#64748b")), # Slate 500
                    ('TEXTCOLOR', (0, 0), (-1, 0), header_fg),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('ALIGN', (0, 1), (0, -1), 'LEFT'),
                    ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
                    ('FONTNAME', (0, 0), (-1, -1), FONT_NORMAL),
                    ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('TOPPADDING', (0, 0), (-1, 0), 8),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [row_odd_bg, row_even_bg])
                ]
                
                for i in range(1, len(in_data)):
                    val_real = inactive[i-1]["realized_pnl"]
                    in_ts.append(('TEXTCOLOR', (1, i), (1, i), profit_color if val_real >= 0 else loss_color))
                    
                in_table.setStyle(TableStyle(in_ts))
                broker_elements.append(in_table)
                broker_elements.append(Spacer(1, 20))
                
            elements.extend(broker_elements)
            
    def draw_header_footer(canvas, doc):
        canvas.saveState()
        
        # Header strip
        canvas.setFillColor(colors.HexColor("#0f172a")) # Dark slate
        canvas.rect(0, doc.pagesize[1] - 40, doc.pagesize[0], 40, fill=1, stroke=0)
        
        canvas.setFillColor(colors.white)
        canvas.setFont(FONT_BOLD, 14)
        canvas.drawString(doc.leftMargin, doc.pagesize[1] - 25, "Portfolio Performance Report")
        
        canvas.setFont(FONT_NORMAL, 10)
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, doc.pagesize[1] - 25, f"Currency: {currency_filter}")
        
        # Footer strip
        canvas.setFillColor(colors.HexColor("#f8fafc"))
        canvas.rect(0, 0, doc.pagesize[0], 30, fill=1, stroke=0)
        
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.setFont(FONT_NORMAL, 9)
        canvas.drawString(doc.leftMargin, 10, f"Generated on {datetime.now().strftime('%d %b %Y, %I:%M %p')}")
        
        canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 10, f"Page {doc.page}")
        
        canvas.restoreState()
            
    doc.build(elements, onFirstPage=draw_header_footer, onLaterPages=draw_header_footer)
