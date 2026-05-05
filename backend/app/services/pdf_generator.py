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
