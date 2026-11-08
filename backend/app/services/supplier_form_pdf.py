"""Supplier-facing PDF of a submitted or approved price form, shareable on WhatsApp.

Read-only: it renders what the supplier sent, next to the previous agreed price.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# unit -> (base unit, factor to base): prices are compared per kg, per litre or per single unit
_BASE_UNITS = {
    "KG": ("KG", Decimal(1)), "G": ("KG", Decimal("0.001")),
    "L": ("L", Decimal(1)), "CL": ("L", Decimal("0.01")), "ML": ("L", Decimal("0.001")),
}


@dataclass
class PdfOffer:
    price: Decimal
    quantity: Decimal
    unit: str


@dataclass
class PdfItem:
    description: str
    offers: list[PdfOffer] = field(default_factory=list)
    not_handled: bool = False
    previous_price: Decimal | None = None
    previous_quantity: Decimal | None = None
    previous_unit: str | None = None


@dataclass
class PdfForm:
    company_name: str
    supplier_name: str
    form_id: int
    status: str  # submitted | approved
    request_type: str  # confirmation | new_listino
    submitted_at: datetime | None
    valid_from: date | None
    valid_to: date | None
    items: list[PdfItem]


def money(value: Decimal) -> str:
    amount = f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"
    return "€ " + amount.replace(",", "X").replace(".", ",").replace("X", ".")


def quantity_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def per_unit(price: Decimal, quantity: Decimal | None, unit: str | None) -> tuple[Decimal, str] | None:
    """Price for one base unit (1 KG, 1 L or one piece/package), or None if unknown."""
    if not unit:
        return None
    unit = unit.strip().upper()
    quantity = quantity if quantity and quantity > 0 else Decimal(1)
    base, factor = _BASE_UNITS.get(unit, (unit, Decimal(1)))
    return price / (quantity * factor), base


def _format(quantity: Decimal | None, unit: str | None) -> str:
    if not unit:
        return "—"
    if quantity is None or quantity == 1:
        return f"1 {unit}"
    return f"{quantity_text(quantity)} {unit}"


def _unit_price_text(offer: PdfOffer) -> str:
    """'€ 12,00/KG' for weight/volume packs, '€ 1,50/unità' for multi-piece packs, '' when it adds nothing."""
    unit = offer.unit.strip().upper()
    if unit in _BASE_UNITS:
        if offer.quantity == 1 and unit in ("KG", "L"):
            return ""
        value, base = per_unit(offer.price, offer.quantity, unit)
        return f"{money(value)}/{base}"
    if offer.quantity > 1 and offer.quantity == offer.quantity.to_integral_value():
        return f"{money(offer.price / offer.quantity)}/unità"
    return ""


def generate_supplier_form_pdf(form: PdfForm) -> bytes:
    buffer = BytesIO()
    generated = datetime.now()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=f"Listino {form.supplier_name}", author=form.company_name,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle("T", parent=styles["Heading1"], textColor=colors.HexColor("#1d4ed8"),
                           fontSize=17, leading=21, spaceAfter=4)
    body = ParagraphStyle("B", parent=styles["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("S", parent=styles["Normal"], fontSize=8, leading=10.5, textColor=colors.HexColor("#475569"))
    cell = ParagraphStyle("C", parent=styles["Normal"], fontSize=8.5, leading=10.5)

    if form.status == "approved":
        banner, banner_color = "Listino approvato", "#166534"
    else:
        sent = f" il {form.submitted_at:%d/%m/%Y}" if form.submitted_at else ""
        banner, banner_color = f"Risposta inviata{sent} — in revisione: i prezzi non sono ancora approvati", "#b45309"
    validity = "non indicata"
    if form.valid_from:
        validity = f"dal {form.valid_from:%d/%m/%Y}" + (f" al {form.valid_to:%d/%m/%Y}" if form.valid_to else " fino a nuovo listino")

    story = [
        Paragraph(f"Listino prezzi — {escape(form.supplier_name)}", title),
        Paragraph(f"<b>{escape(form.company_name)}</b> · Modulo n. {form.form_id}", body),
        Paragraph(f'<font color="{banner_color}"><b>{escape(banner)}</b></font>', body),
        Paragraph(f"<b>Validità:</b> {escape(validity)}", body),
        Spacer(1, 4 * mm),
    ]

    confirmation = form.request_type == "confirmation"
    header = ["Prodotto", "Formato", "Prezzo", "Prezzo unitario"] + (["Precedente"] if confirmation else [])
    rows: list[list] = [header]
    not_handled: list[str] = []
    for item in sorted(form.items, key=lambda i: i.description.casefold()):
        if item.not_handled:
            not_handled.append(item.description)
            continue
        for index, offer in enumerate(item.offers):
            unit_text = _unit_price_text(offer)
            row = [Paragraph(escape(item.description) + (" <i>(altro formato)</i>" if index else ""), cell),
                   _format(offer.quantity, offer.unit), money(offer.price), unit_text]
            if confirmation:
                if index or item.previous_price is None:
                    row.append("—")
                else:
                    previous = money(item.previous_price) + (
                        f" / {_format(item.previous_quantity, item.previous_unit)}" if item.previous_unit else "")
                    row.append(Paragraph(escape(previous), cell))
            rows.append(row)

    widths = [66, 22, 24, 30, 40] if confirmation else [80, 30, 30, 42]
    table = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]
    table.setStyle(TableStyle(style))
    story.append(table if len(rows) > 1 else Paragraph("Nessun prodotto quotato.", body))

    note = ("Il prezzo si riferisce al formato indicato; il prezzo unitario è calcolato per 1 KG, 1 L "
            "o per singola unità della confezione.")
    story += [Spacer(1, 3 * mm), Paragraph(escape(note), small)]
    if not_handled:
        story += [Spacer(1, 5 * mm), Paragraph(f"<b>Prodotti non trattati ({len(not_handled)})</b>", body),
                  Paragraph(escape(", ".join(sorted(not_handled, key=str.casefold))), cell)]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(14 * mm, 9 * mm, f"{form.company_name} · {form.supplier_name} · modulo n. {form.form_id} · "
                                            f"generato il {generated:%d/%m/%Y %H:%M}")
        canvas.drawRightString(A4[0] - 14 * mm, 9 * mm, f"pagina {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
