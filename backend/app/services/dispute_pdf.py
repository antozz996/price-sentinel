"""Generate a supplier-facing dispute dossier without mutating source data."""

from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.disputes import DisputeCase


def generate_dispute_pdf(case: DisputeCase) -> bytes:
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Contestazione {case.case_code}",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "DisputeTitle",
        parent=styles["Heading1"],
        textColor=colors.HexColor("#1d4ed8"),
        fontSize=20,
        leading=24,
        spaceAfter=10,
    )
    muted = ParagraphStyle(
        "DisputeMuted",
        parent=styles["Normal"],
        textColor=colors.HexColor("#475569"),
        fontSize=9,
        leading=12,
    )
    body = ParagraphStyle(
        "DisputeBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
    )
    story = [
        Paragraph("PRICE SENTINEL — DOSSIER CONTESTAZIONE", title),
        Paragraph(
            f"<b>Codice:</b> {escape(case.case_code)}<br/>"
            f"<b>Locale:</b> {escape(case.location_name or str(case.location_id))}<br/>"
            f"<b>Fornitore:</b> {escape(case.supplier_name or str(case.supplier_id))}<br/>"
            f"<b>Stato:</b> {escape(case.status)}",
            body,
        ),
        Spacer(1, 6 * mm),
    ]
    rows = [["Motivo", "Documento / evidenza", "Importo"]]
    for item in case.anomalies:
        evidence = item.evidence_snapshot or {}
        reference = (
            evidence.get("invoice_number")
            or evidence.get("fattura_id")
            or evidence.get("riga_fattura_id")
            or "—"
        )
        rows.append(
            [
                Paragraph(escape(item.reason_snapshot), muted),
                Paragraph(escape(str(reference)), muted),
                f"€ {item.claimed_amount:.2f}",
            ]
        )
    table = Table(rows, colWidths=[72 * mm, 65 * mm, 30 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            Paragraph("<b>Righe contestate</b>", styles["Heading2"]),
            table,
            Spacer(1, 6 * mm),
            Paragraph(
                f"<b>Importo richiesto:</b> € {case.requested_amount:.2f}<br/>"
                f"<b>Importo riconosciuto:</b> € {case.recognized_amount:.2f}<br/>"
                f"<b>Importo recuperato:</b> € {case.recovered_amount:.2f}<br/>"
                f"<b>Residuo:</b> € {case.unrecovered_amount:.2f}",
                body,
            ),
            Spacer(1, 5 * mm),
            Paragraph(
                "Si richiede la verifica delle evidenze riportate e, ove dovuta, "
                "l'emissione della relativa nota di credito. L'apertura o la copia "
                "di questo documento non costituiscono prova di consegna.",
                muted,
            ),
        ]
    )
    if case.due_date:
        story.append(
            Paragraph(
                f"<br/><b>Riscontro richiesto entro:</b> {case.due_date:%d/%m/%Y}",
                body,
            )
        )
    document.build(story)
    return buffer.getvalue()
