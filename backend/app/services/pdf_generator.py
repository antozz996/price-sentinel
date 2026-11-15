"""
Price Sentinel — Vendor Passport Report Generator (Sprint 4)
Usa ReportLab per generare documenti strategici eliminando i prezzi attuali.
"""

import io
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_consumption_invoices_pdf(title: str, invoices: list, filter_desc: str = "") -> bytes:
    """
    Genera un PDF di riepilogo delle fatture che compongono il consumo di uno o più SKU.
    """
    import io
    from datetime import datetime
    import html
    from xml.sax.saxutils import escape as _xml_escape

    from app.services.consumption_report import format_quantity, invoice_totals, quantities_text

    def escape(value) -> str:
        # Testo da fattura dentro un Paragraph: niente markup, ma "&amp;" resta "&".
        return _xml_escape(html.unescape(str(value or "")))
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=40
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'MainTitle', 
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor("#1A202C"),
        spaceAfter=10,
    )
    subtitle_style = ParagraphStyle(
        'SubTitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor("#718096"),
        spaceAfter=20,
    )
    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor("#2D3748")
    )
    cell_bold_style = ParagraphStyle(
        'TableCellBold',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor("#1A202C"),
        fontName='Helvetica-Bold'
    )
    header_cell_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.whitesmoke,
        fontName='Helvetica-Bold'
    )

    elements = []
    
    # Header
    elements.append(Paragraph("<b>PRICE SENTINEL</b> - RIEPILOGO FATTURE DI CONSUMO", title_style))
    elements.append(Paragraph(
        f"<b>Analisi articolo/i:</b> {escape(title)}<br/>"
        f"<i>Report generato il {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>" + 
        (f"<br/><b>Filtri attivi:</b> {escape(filter_desc)}" if filter_desc else ""), 
        subtitle_style
    ))
    elements.append(Spacer(1, 10))
    
    # Invoices table data matrix
    data_matrix = [[
        Paragraph("Data", header_cell_style),
        Paragraph("N. Doc", header_cell_style),
        Paragraph("Sede", header_cell_style),
        Paragraph("Fornitore", header_cell_style),
        Paragraph("Prodotto (Raw)", header_cell_style),
        Paragraph("Qtà", header_cell_style),
        Paragraph("P. Unit.", header_cell_style),
        Paragraph("Totale", header_cell_style),
    ]]
    
    totale_spesa = 0.0

    for inv in invoices:
        data_doc = inv.get("data_documento", "")
        # Format date as DD/MM/YYYY if YYYY-MM-DD
        if len(data_doc) == 10 and data_doc[4] == '-' and data_doc[7] == '-':
            parts = data_doc.split('-')
            data_doc_formatted = f"{parts[2]}/{parts[1]}/{parts[0]}"
        else:
            data_doc_formatted = data_doc
            
        qta = inv.get("quantita", 0.0)
        pu = inv.get("prezzo_unitario", 0.0)
        tot = inv.get("spesa_totale", 0.0)
        
        totale_spesa += tot
        unita = inv.get("unita_misura") or ""
        numero = escape(str(inv.get("numero_documento", "")))
        if inv.get("is_reso"):
            numero += "<br/><i>nota di credito</i>"

        data_matrix.append([
            Paragraph(data_doc_formatted, cell_style),
            Paragraph(numero, cell_style),
            Paragraph(escape(str(inv.get("location_nome", ""))), cell_style),
            Paragraph(escape(str(inv.get("fornitore_nome", ""))), cell_style),
            Paragraph(escape(str(inv.get("prodotto_descrizione", ""))), cell_style),
            # Quantità con la sua unità e con il segno (i resi sono negativi).
            Paragraph(escape(f"{format_quantity(qta)} {unita}".strip()), cell_style),
            Paragraph(f"€ {pu:,.2f}", cell_style),
            Paragraph(f"€ {tot:,.2f}", cell_style),
        ])

    # Totale: una quantità per unità, mai sommate tra loro ("5.940 Lt + 6 PZ").
    has_summary = all("unita_riepilogo" in inv for inv in invoices)
    totale_quantita = quantities_text(invoice_totals(invoices)) if invoices and has_summary else ""
    data_matrix.append([
        Paragraph("<b>TOTALE COMPLESSIVO</b>", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph(f"<b>{escape(totale_quantita)}</b>", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph(f"<b>€ {totale_spesa:,.2f}</b>", cell_bold_style),
    ])

    # Page width is 595. Margins are 30 on each side. Printable is 535 points.
    col_widths = [50, 55, 70, 70, 110, 65, 50, 65]
    
    table = Table(data_matrix, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A202C")),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor("#F7FAFC")]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor("#EDF2F7")), # total row background
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor("#CBD5E0")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 20))
    
    disclaimer = Paragraph(
        "<font size=7 color=gray>Documento ad uso interno generato automaticamente da Price Sentinel. "
        "Tutti i dati storici derivano dall'elaborazione delle fatture elettroniche ricevute.</font>",
        styles["Normal"]
    )
    elements.append(disclaimer)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.read()

