"""Excel della matrice del Listino Smart, con gli stessi filtri e ordinamento della schermata."""

from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE_COLUMNS = ["Prodotto", "Nome rapido", "SKU", "Categoria", "Reparto", "Unità", "Acquisti", "Quantità", "Spesa €", "Ultimo acquisto", "Consigliato", "Più economico"]
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
RECOMMENDED_FILL = PatternFill("solid", fgColor="C6EFCE")
NOT_COMPARABLE_FONT = Font(italic=True, color="808080")


def _number(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def _date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def export_suppliers(rows: list[dict], suppliers: list[dict]) -> list[dict]:
    """Fornitori con almeno un'offerta nelle righe esportate, nell'ordine della schermata."""
    with_offers = {int(sid) for row in rows for sid in (row.get("offers") or {})}
    seen, out = set(), []
    for supplier in suppliers:
        if supplier["id"] in with_offers and supplier["id"] not in seen:
            seen.add(supplier["id"])
            out.append(supplier)
    return out


def build_matrix_workbook(rows: list[dict], suppliers: list[dict], title: str) -> bytes:
    suppliers = export_suppliers(rows, suppliers)
    names = {s["id"]: s["name"] for s in suppliers}
    wb = Workbook()
    ws = wb.active
    ws.title = (title or "Listino Smart")[:31]
    headers = BASE_COLUMNS + [s["name"] for s in suppliers]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for row in rows:
        offers = row.get("offers") or {}
        recommended = row.get("recommended_supplier_id")
        cheapest = row.get("absolute_cheapest_supplier_id")
        values = [
            row.get("canonical_name"),
            row.get("order_name"),
            row.get("sku_interno"),
            row.get("category"),
            row.get("subcategory"),
            row.get("comparison_unit"),
            row.get("acquisti") or 0,
            _number(row.get("quantita")),
            _number(row.get("spesa")),
            _date(row.get("ultimo_acquisto")),
            names.get(recommended, ""),
            names.get(cheapest, ""),
        ]
        not_comparable = []
        for index, supplier in enumerate(suppliers):
            offer = offers.get(str(supplier["id"]))
            if not offer:
                values.append(None)
                continue
            normalized = _number(offer.get("unit_price_normalized"))
            if normalized is not None:
                values.append(normalized)
            else:
                price = _number(offer.get("price"))
                values.append(f"{price:.2f} {offer.get('uom') or ''}".strip() if price is not None else None)
                not_comparable.append(index)
        ws.append(values)
        r = ws.max_row
        ws.cell(r, 8).number_format = "#,##0.###"
        ws.cell(r, 9).number_format = "#,##0.00"
        ws.cell(r, 10).number_format = "DD/MM/YYYY"
        for index, supplier in enumerate(suppliers):
            cell = ws.cell(r, len(BASE_COLUMNS) + index + 1)
            if index in not_comparable:
                cell.font = NOT_COMPARABLE_FONT
            elif cell.value is not None:
                cell.number_format = "#,##0.00"
                if supplier["id"] == recommended:
                    cell.fill = RECOMMENDED_FILL
    widths = [48, 22, 22, 13, 16, 8, 10, 12, 12, 14, 22, 22] + [14] * len(suppliers)
    for index, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions
    note = wb.create_sheet("Note")
    for line in (
        f"Esportato il {date.today():%d/%m/%Y}",
        "Prezzi dei fornitori: per unità della voce (colonna Unità), senza IVA.",
        "In verde il fornitore consigliato.",
        "In grigio corsivo: prezzo non confrontabile (unità diversa o conversione incerta), riportato com'è.",
        "Quantità e spesa: acquisti da fattura nel periodo scelto.",
    ):
        note.append([line])
    note.column_dimensions["A"].width = 100
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
