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

def generate_vendor_passport_pdf(vendor_data: dict) -> bytes:
    """
    Genera un PDF 'Vendor Passport' in memory-buffer.
    Parametri attesi in vendor_data:
      - 'vendor_name': str
      - 'assorbimento': list of dicts (es. [{'cat': 'Spirits', 'volume': '500 L'}, ...])
      - 'frequenza': str
      - 'location_servite': int
    
    IMPORTANT: Nesun prezzo viene esposto. Solo volumi.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=40, leftMargin=40, topMargin=50, bottomMargin=50
    )
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'MainTitle', 
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor("#1A202C"),
        spaceAfter=20,
    )
    subtitle_style = ParagraphStyle(
        'SubTitle',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor("#718096"),
        spaceAfter=30,
    )
    
    elements = []
    
    # Intestazione Strategica
    elements.append(Paragraph("<b>PRICE SENTINEL</b> - VENDOR PASSPORT", title_style))
    elements.append(Paragraph(
        "Rapporto Direzionale per l'Analisi della Capacità di Assorbimento<br/>"
        "<i>Documento strettamente confidenziale per finalità negoziali</i>", subtitle_style)
    )
    elements.append(Spacer(1, 0.2 * inch))
    
    # Informazioni Generali
    elements.append(Paragraph(f"<b>Analisi relativa al Fornitore:</b> {vendor_data.get('vendor_name', 'N/A')}", styles["Normal"]))
    elements.append(Paragraph(f"<b>Location servite dal fornitore:</b> {vendor_data.get('location_servite', 0)} Sedi", styles["Normal"]))
    elements.append(Paragraph(f"<b>Frequenza media riordino:</b> {vendor_data.get('frequenza', 'N/A')}", styles["Normal"]))
    elements.append(Spacer(1, 0.3 * inch))
    
    # Tabella Assorbimento Volumi
    elements.append(Paragraph("<b>Capacità di Assorbimento Volumi (No Prezzi Inclusi)</b>", styles["Heading3"]))
    
    # Costruiamo i dati della tabella
    data_matrix = [["Categoria", "Volume Totale Periodo", "Unità"]]
    for item in vendor_data.get("assorbimento", []):
        data_matrix.append([
            item.get("categoria", "Altro"),
            str(item.get("volume", 0)),
            item.get("unita", "")
        ])
        
    table = Table(data_matrix, colWidths=[2.5*inch, 2.5*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2B6CB0")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#EDF2F7")),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 0.5 * inch))
    
    # Disclaimer
    disclaimer = Paragraph(
        "<font size=8 color=gray>Questo documento attesta esclusivamente la "
        "capacità di assorbimento logistico-merceologica del gruppo. "
        "I prezzi di acquisto storici sono omessi per garantire la "
        "massima neutralità nelle dinamiche di asta al ribasso.</font>",
        styles["Normal"]
    )
    elements.append(disclaimer)

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


def generate_consumption_invoices_pdf(title: str, invoices: list, filter_desc: str = "") -> bytes:
    """
    Genera un PDF di riepilogo delle fatture che compongono il consumo di uno o più SKU.
    """
    import io
    from datetime import datetime
    
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
        f"<b>Analisi articolo/i:</b> {title}<br/>"
        f"<i>Report generato il {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}</i>" + 
        (f"<br/><b>Filtri attivi:</b> {filter_desc}" if filter_desc else ""), 
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
    
    totale_quantita = 0.0
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
        
        totale_quantita += qta
        totale_spesa += tot
        
        data_matrix.append([
            Paragraph(data_doc_formatted, cell_style),
            Paragraph(str(inv.get("numero_documento", "")), cell_style),
            Paragraph(str(inv.get("location_nome", "")), cell_style),
            Paragraph(str(inv.get("fornitore_nome", "")), cell_style),
            Paragraph(str(inv.get("prodotto_descrizione", "")), cell_style),
            Paragraph(f"{qta:,.1f}", cell_style),
            Paragraph(f"€ {pu:,.2f}", cell_style),
            Paragraph(f"€ {tot:,.2f}", cell_style),
        ])
        
    # Append Total row
    data_matrix.append([
        Paragraph("<b>TOTALE COMPLESSIVO</b>", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph(f"<b>{totale_quantita:,.1f}</b>", cell_bold_style),
        Paragraph("", cell_bold_style),
        Paragraph(f"<b>€ {totale_spesa:,.2f}</b>", cell_bold_style),
    ])
    
    # Page width is 595. Margins are 30 on each side. Printable is 535 points.
    col_widths = [55, 55, 75, 75, 125, 40, 50, 60]
    
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

