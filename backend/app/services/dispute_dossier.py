"""Dossier Excel di contestazione, ricavato dalle anomalie (rapporto 14/11/2026, A14).

Il vecchio export ricalcolava i rincari da zero: media semplice di prezzi in
unità di fattura miste, listino valido OGGI anche per i mesi passati, note di
credito come acquisti. Le anomalie invece hanno già il prezzo convertito
nell'unità del listino valido alla data della fattura e il sovrapprezzo totale:
il dossier elenca esattamente le anomalie visibili nella ValidationRoom (stessi
filtri di GET /anomalie), quindi il totale del dossier è SUM(delta_totale).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any, Iterable, Optional

from sqlalchemy import and_, extract, select
from sqlalchemy.orm import noload

from app.models.anomalie import Anomalia, StatoValidazione, comparison_quantity
from app.models.esclusi import SKUEscluso
from app.models.fatture import Fattura, RigaFattura
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster
from app.models.location import Location
from app.models.products import Product
from app.services.anomaly_policy import operational_anomaly_filter
from app.services.normalization import unit_family
from app.services.price_trend import listino_valid_at
from app.services.purchase_lines import normalized_unit
from app.services.tenant_scope import invoice_tenant_filter


def visible_anomaly_conditions(user, stato: Optional[StatoValidazione] = None) -> list:
    """Le stesse condizioni di GET /anomalie (ValidationRoom): tenant, SKU esclusi, soglia, sede del manager."""
    conditions = [
        invoice_tenant_filter(user),
        RigaFattura.sku_interno.is_(None) | ~RigaFattura.sku_interno.in_(select(SKUEscluso.sku_interno)),
        operational_anomaly_filter(),
    ]
    if stato is not None:
        conditions.append(Anomalia.stato_validazione == stato)
    ruolo = getattr(getattr(user, "ruolo", None), "value", getattr(user, "ruolo", None))
    if ruolo == "manager":
        conditions.append(Fattura.location_id == user.location_id)
    return conditions


async def comparison_units(db, lines: Iterable[tuple[Any, Optional[str], Optional[int], Optional[date]]]) -> dict:
    """Unità dei prezzi snapshot per riga: unità del listino valido alla data, altrimenti quella della voce.

    lines: (chiave, sku_interno, fornitore_id, data_documento). È la stessa regola
    del controllo prezzi (matching: target_comparison_unit=listino.unita_misura).
    """
    lines = [line for line in lines if line[1]]
    skus = {line[1] for line in lines}
    if not skus:
        return {}
    products = {
        p.sku_interno: p for p in (await db.scalars(
            select(Product).options(noload("*")).where(Product.sku_interno.in_(skus))
        )).all()
    }
    listini: dict[tuple[str, int], list] = {}
    for item in (await db.scalars(
        select(ListinoMaster).options(noload("*")).where(ListinoMaster.sku_interno.in_(skus))
    )).all():
        listini.setdefault((item.sku_interno, item.fornitore_id), []).append(item)

    units = {}
    for key, sku, fornitore_id, day in lines:
        product = products.get(sku)
        listino = listino_valid_at(listini.get((sku, fornitore_id), ()), day) if day is not None else None
        raw = (listino.unita_misura if listino is not None else None) or (product.comparison_unit if product else None)
        units[key] = unit_family(raw)
    return units


@dataclass(frozen=True)
class DossierRow:
    anomalia_id: int
    data_documento: date
    numero_documento: str
    fornitore: str
    sede: str
    sku_interno: Optional[str]
    descrizione: str
    quantita_fattura: Decimal
    unita_fattura: str
    quantita_confronto: Decimal
    unita_confronto: Optional[str]
    prezzo_listino: Decimal
    prezzo_fatturato: Decimal
    delta_prezzo: Decimal
    delta_totale: Decimal


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def dossier_row(anomalia: Any, riga: Any, fattura: Any, fornitore: Optional[str], sede: Optional[str],
                unita_confronto: Optional[str]) -> DossierRow:
    return DossierRow(
        anomalia_id=anomalia.id,
        data_documento=fattura.data_documento,
        numero_documento=fattura.numero_documento,
        fornitore=fornitore or "Fornitore ND",
        sede=sede or "-",
        sku_interno=riga.sku_interno,
        descrizione=riga.descrizione_fornitore_raw or "",
        quantita_fattura=_dec(riga.quantita),
        unita_fattura=normalized_unit(riga.unita_misura_fattura),
        quantita_confronto=comparison_quantity(anomalia.delta_totale, anomalia.delta_prezzo, riga.quantita) or Decimal("0"),
        unita_confronto=unita_confronto,
        prezzo_listino=_dec(anomalia.prezzo_listino_snapshot),
        prezzo_fatturato=_dec(anomalia.prezzo_fatturato_snapshot),
        delta_prezzo=_dec(anomalia.delta_prezzo),
        delta_totale=_dec(anomalia.delta_totale),
    )


async def load_dossier_rows(
    db,
    user,
    *,
    stato: Optional[StatoValidazione] = StatoValidazione.da_verificare,
    location_id: Optional[int] = None,
    anno: Optional[int] = None,
) -> list[DossierRow]:
    stmt = (
        select(Anomalia, RigaFattura, Fattura, Fornitore.nome_azienda, Location.nome_struttura)
        .options(noload("*"))
        .join(RigaFattura, Anomalia.riga_fattura_id == RigaFattura.id)
        .join(Fattura, RigaFattura.fattura_id == Fattura.id)
        .outerjoin(Fornitore, Fornitore.id == Fattura.fornitore_id)
        .outerjoin(Location, Location.id == Fattura.location_id)
        .where(and_(*visible_anomaly_conditions(user, stato)))
        .order_by(Fornitore.nome_azienda, Fattura.data_documento, Fattura.numero_documento, Anomalia.id)
    )
    if location_id is not None:
        stmt = stmt.where(Fattura.location_id == location_id)
    if anno is not None:
        stmt = stmt.where(extract("year", Fattura.data_documento) == anno)
    records = (await db.execute(stmt)).all()
    units = await comparison_units(db, [
        (anomalia.id, riga.sku_interno, fattura.fornitore_id, fattura.data_documento)
        for anomalia, riga, fattura, _f, _s in records
    ])
    return [
        dossier_row(anomalia, riga, fattura, fornitore, sede, units.get(anomalia.id))
        for anomalia, riga, fattura, fornitore, sede in records
    ]


def dossier_total(rows: Iterable[DossierRow]) -> Decimal:
    return sum((row.delta_totale for row in rows), Decimal("0"))


DETAIL_HEADERS = [
    "Data fattura", "Numero fattura", "Fornitore", "Sede", "SKU", "Prodotto",
    "Quantità in fattura", "U.M. fattura", "Quantità confrontata", "Unità di confronto",
    "Prezzo listino (€)", "Prezzo fatturato (€)", "Differenza unitaria (€)", "Sovrapprezzo (€)",
]


def build_dossier_workbook(rows: list[DossierRow]) -> BytesIO:
    """Foglio 1: una riga per anomalia e il totale. Foglio 2: totale per fornitore e mese."""
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rincari da contestare"
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    thin = Side(style="thin", color="DDDDDD")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    money_cols = {11, 12, 14}
    unit_price_col = 13
    qty_cols = {7, 9}

    def style_header(sheet, count):
        for col in range(1, count + 1):
            cell = sheet.cell(row=1, column=col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border

    ws.append(DETAIL_HEADERS)
    style_header(ws, len(DETAIL_HEADERS))
    for row in rows:
        ws.append([
            row.data_documento, row.numero_documento, row.fornitore, row.sede, row.sku_interno or "",
            row.descrizione, float(row.quantita_fattura), row.unita_fattura, float(row.quantita_confronto),
            row.unita_confronto or "n.d.", float(row.prezzo_listino), float(row.prezzo_fatturato),
            float(row.delta_prezzo), float(row.delta_totale),
        ])
        line = ws.max_row
        for col in range(1, len(DETAIL_HEADERS) + 1):
            cell = ws.cell(row=line, column=col)
            cell.border = border
            if col == 1:
                cell.number_format = "DD/MM/YYYY"
            elif col in money_cols:
                cell.number_format = "€ #,##0.00"
            elif col == unit_price_col:
                cell.number_format = "€ #,##0.0000"
            elif col in qty_cols:
                cell.number_format = "#,##0.00"
    total = dossier_total(rows)
    ws.append(["TOTALE"] + [""] * (len(DETAIL_HEADERS) - 2) + [float(total)])
    total_row = ws.max_row
    for col in range(1, len(DETAIL_HEADERS) + 1):
        cell = ws.cell(row=total_row, column=col)
        cell.font = Font(name="Calibri", size=11, bold=True)
        cell.border = border
    ws.cell(row=total_row, column=len(DETAIL_HEADERS)).number_format = "€ #,##0.00"
    widths = [12, 14, 28, 22, 24, 40, 12, 10, 12, 10, 14, 14, 14, 14]
    for idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"

    summary = wb.create_sheet("Riepilogo fornitori")
    summary_headers = ["Fornitore", "Mese", "Anomalie", "Sovrapprezzo (€)"]
    summary.append(summary_headers)
    style_header(summary, len(summary_headers))
    groups: dict[tuple[str, str], list[DossierRow]] = {}
    for row in rows:
        groups.setdefault((row.fornitore, row.data_documento.strftime("%Y-%m")), []).append(row)
    for (fornitore, mese), items in sorted(groups.items()):
        summary.append([fornitore, mese, len(items), float(dossier_total(items))])
        summary.cell(row=summary.max_row, column=4).number_format = "€ #,##0.00"
    summary.append(["TOTALE", "", len(rows), float(total)])
    summary.cell(row=summary.max_row, column=4).number_format = "€ #,##0.00"
    for col in range(1, 5):
        summary.cell(row=summary.max_row, column=col).font = Font(name="Calibri", size=11, bold=True)
    for idx, width in enumerate([32, 10, 10, 16], start=1):
        summary.column_dimensions[get_column_letter(idx)].width = width

    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream
