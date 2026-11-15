"""Consumi per prodotto e Top prodotti: un solo calcolo per tabella, dettaglio, fatture, PDF ed Excel.

Le regole vengono tutte dalla base comune (services/purchase_lines.py):

- spesa = prezzo unitario x (1 - sconto) x quantità, con il segno del documento: le
  note di credito TD04/TD08 tolgono spesa e quantità (un reso può rendere negativo
  uno SKU nel periodo, se copre acquisti fatti prima del filtro di date);
- quantità convertite nell'unità di confronto della voce solo quando la conversione
  è affidabile (line_conversion con strict_pack); altrimenti la riga resta nella sua
  unità di fattura normalizzata e non viene mai sommata con unità diverse:
  "5.940 Lt + 6 PZ" invece di "5.946 PZ";
- prezzi medio, minimo e massimo per unità, solo sulle righe d'acquisto pagate (no
  note di credito, no omaggi); il medio è pesato sulla quantità;
- SKU esclusi e righe escluse dalle statistiche restano fuori; filtro tenant.

La parte che legge il database è load_lines(); tutto il resto lavora su righe già
lette (Row di purchase_lines_select o oggetti con gli stessi attributi), così i
test riproducono i casi reali senza database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import select

from app.models.esclusi import SKUEscluso
from app.models.fatture import Fattura
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.products import Product
from app.services.purchase_lines import (
    NO_UNIT,
    UNRELIABLE_NO_PRODUCT,
    ConversionKey,
    LineConversion,
    conversion_key,
    load_conversions,
    normalized_unit,
    purchase_lines_select,
)

ZERO = Decimal("0")
NO_LOCATION = "Sede non assegnata"
NO_SUPPLIER = "Fornitore non specificato"
SORT_KEYS = ("quantita", "spesa", "acquisti")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else ZERO


def _num(value: Optional[Decimal]) -> Optional[float]:
    return float(value) if value is not None else None


# ─────────────────────────────────────────────
# Filtri
# ─────────────────────────────────────────────

def parse_ids(raw: Any) -> Optional[list[int]]:
    """"1,2" o [1, 2] -> [1, 2]. Vuoto o non valido -> None (nessun filtro, come prima)."""
    if raw is None:
        return None
    if isinstance(raw, (list, tuple, set)):
        values = list(raw)
    elif isinstance(raw, str):
        values = raw.split(",")
    else:
        return None
    try:
        ids = [int(str(v).strip()) for v in values if str(v).strip()]
    except ValueError:
        return None
    return ids or None


def parse_skus(raw: Any) -> list[str]:
    """Lista SKU senza vuoti né doppioni, nell'ordine ricevuto ("A,B" o ["A", "B"])."""
    values = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    skus: list[str] = []
    for value in values:
        sku = str(value or "").strip()
        if sku and sku not in skus:
            skus.append(sku)
    return skus


@dataclass(frozen=True)
class ReportFilters:
    location_ids: Optional[tuple[int, ...]] = None
    fornitore_ids: Optional[tuple[int, ...]] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    skus: Optional[tuple[str, ...]] = None

    @classmethod
    def build(cls, *, location_ids=None, fornitore_ids=None, date_from=None, date_to=None, skus=None):
        locs = parse_ids(location_ids)
        forns = parse_ids(fornitore_ids)
        return cls(
            location_ids=tuple(locs) if locs else None,
            fornitore_ids=tuple(forns) if forns else None,
            date_from=date_from if isinstance(date_from, date) else None,
            date_to=date_to if isinstance(date_to, date) else None,
            skus=tuple(parse_skus(skus)) if skus is not None else None,
        )


# ─────────────────────────────────────────────
# Lettura (unica parte con il database)
# ─────────────────────────────────────────────

def lines_select(user, filters: ReportFilters):
    """Righe d'acquisto con SKU (regole comuni) più nome voce, sede e fornitore."""
    return (
        purchase_lines_select(
            user,
            date_from=filters.date_from,
            date_to=filters.date_to,
            location_ids=filters.location_ids,
            fornitore_ids=filters.fornitore_ids,
            skus=filters.skus,
            require_sku=True,
        )
        .add_columns(
            Product.canonical_name.label("nome_voce"),
            Location.nome_struttura.label("location_nome"),
            Fornitore.nome_azienda.label("fornitore_nome"),
        )
        .outerjoin(Location, Location.id == Fattura.location_id)
        .outerjoin(Fornitore, Fornitore.id == Fattura.fornitore_id)
    )


async def load_lines(db, user, filters: ReportFilters):
    """(righe, conversioni) per i filtri dati. Le conversioni vengono da load_conversions."""
    stmt = lines_select(user, filters)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return [], {}
    conversions = await load_conversions(db, stmt.subquery("consumi_righe"))
    return rows, conversions


async def excluded_skus(db, skus: Iterable[str]) -> list[str]:
    """SKU della lista presenti in skus_esclusi (il controllo vale anche per la selezione multipla)."""
    skus = list(skus)
    if not skus:
        return []
    return list((await db.scalars(select(SKUEscluso.sku_interno).where(SKUEscluso.sku_interno.in_(skus)))).all())


# ─────────────────────────────────────────────
# Quantità per unità
# ─────────────────────────────────────────────

@dataclass
class LineValues:
    """Una riga portata nella sua unità di riepilogo."""

    key: tuple[str, bool]          # (unità, convertita)
    quantita: Decimal              # senza segno, nell'unità di riepilogo
    prezzo: Decimal                # netto per unità di riepilogo
    fattura_unit: str              # unità di fattura normalizzata
    factor: Optional[Decimal]      # None se non convertita


def line_values(row: Any, conv: Optional[LineConversion]) -> LineValues:
    conv = conv or UNRELIABLE_NO_PRODUCT
    invoice_unit = normalized_unit(row.unita_misura)
    quantita = _dec(row.quantita)
    netto = _dec(row.netto_unitario)
    if conv.reliable and conv.factor and conv.factor > 0 and conv.comparison_unit:
        return LineValues((conv.comparison_unit, True), quantita * conv.factor, netto / conv.factor,
                          invoice_unit, conv.factor)
    return LineValues((invoice_unit, False), quantita, netto, invoice_unit, None)


@dataclass
class QuantityBucket:
    """Quantità e prezzi di un gruppo di righe nella stessa unità."""

    unita: str
    convertita: bool
    quantita: Decimal = ZERO          # con segno: i resi sono sottratti
    quantita_resa: Decimal = ZERO     # quantità resa con note di credito (positiva)
    quantita_omaggio: Decimal = ZERO
    spesa: Decimal = ZERO             # con segno
    importo_medio: Decimal = ZERO
    quantita_medio: Decimal = ZERO
    minimo: Optional[Decimal] = None
    massimo: Optional[Decimal] = None
    origini: set = field(default_factory=set)  # (unità di fattura, fattore) per l'etichetta

    def add(self, row: Any, values: LineValues) -> None:
        segno = int(row.segno)
        self.quantita += segno * values.quantita
        if segno < 0:
            self.quantita_resa += values.quantita
        elif row.is_omaggio:
            self.quantita_omaggio += values.quantita
        self.spesa += _dec(row.importo_netto)
        if row.in_media and values.quantita > 0 and values.prezzo > 0:
            self.importo_medio += values.prezzo * values.quantita
            self.quantita_medio += values.quantita
            self.minimo = values.prezzo if self.minimo is None else min(self.minimo, values.prezzo)
            self.massimo = values.prezzo if self.massimo is None else max(self.massimo, values.prezzo)
        self.origini.add((values.fattura_unit, values.factor))

    @property
    def etichetta(self) -> str:
        """Unità da mostrare: se tutte le righe convertite sono già nell'unità della voce
        (fattore 1, stessa unità di fattura) si mostra quella di fattura (BT invece di Pz)."""
        if self.convertita and len(self.origini) == 1:
            unit, factor = next(iter(self.origini))
            if factor == 1 and unit != NO_UNIT:
                return unit
        return self.unita

    @property
    def prezzo_medio(self) -> Optional[Decimal]:
        if self.quantita_medio <= 0:
            return None
        return self.importo_medio / self.quantita_medio

    def as_dict(self, label: Optional[str] = None) -> dict:
        return {
            "unita": label or self.etichetta,
            "convertita": self.convertita,
            "quantita": float(self.quantita),
            "quantita_resa": float(self.quantita_resa),
            "quantita_omaggio": float(self.quantita_omaggio),
            "spesa_totale": float(self.spesa),
            "prezzo_medio": _num(self.prezzo_medio),
            "prezzo_minimo": _num(self.minimo),
            "prezzo_massimo": _num(self.massimo),
        }


def _ordered(buckets: Mapping[tuple[str, bool], QuantityBucket]) -> list[tuple[tuple[str, bool], QuantityBucket]]:
    """Prima l'unità con più spesa, poi quantità, poi nome (ordine stabile)."""
    return sorted(buckets.items(), key=lambda kv: (-abs(kv[1].spesa), -abs(kv[1].quantita), kv[1].unita, kv[1].convertita))


def _bucket(buckets: dict, key: tuple[str, bool]) -> QuantityBucket:
    if key not in buckets:
        buckets[key] = QuantityBucket(unita=key[0], convertita=key[1])
    return buckets[key]


def format_quantity(value: Any) -> str:
    """Numero in formato italiano, al massimo 2 decimali: 5940 -> "5.940", -357 -> "-357", 12.5 -> "12,5"."""
    q = _dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    q = abs(q)
    integer, _, decimals = f"{q:.2f}".partition(".")
    integer = f"{int(integer):,}".replace(",", ".")
    decimals = decimals.rstrip("0")
    return f"{sign}{integer},{decimals}" if decimals else f"{sign}{integer}"


def quantities_text(parts: Iterable[Mapping[str, Any]]) -> str:
    """'5.940 Lt + 6 PZ': una voce per unità, mai sommate tra loro."""
    parts = list(parts)
    many = len(parts) > 1
    return " + ".join(
        f"{format_quantity(part['quantita'])} {part['unita']}"
        + (" (non convertito)" if many and not part.get("convertita", True) else "")
        for part in parts
    )


# ─────────────────────────────────────────────
# Tabella per SKU (schermo ed Excel)
# ─────────────────────────────────────────────

@dataclass
class SkuConsumption:
    sku_interno: str
    nome_voce: Optional[str] = None
    descrizioni: set = field(default_factory=set)
    fornitori: set = field(default_factory=set)
    buckets: dict = field(default_factory=dict)
    spesa: Decimal = ZERO
    spesa_resi: Decimal = ZERO        # importo delle note di credito (positivo)
    fatture_acquisto: set = field(default_factory=set)
    righe: int = 0

    def add(self, row: Any, conv: Optional[LineConversion]) -> None:
        values = line_values(row, conv)
        _bucket(self.buckets, values.key).add(row, values)
        importo = _dec(row.importo_netto)
        self.spesa += importo
        if int(row.segno) < 0:
            self.spesa_resi -= importo
        else:
            self.fatture_acquisto.add(row.fattura_id)
        if row.nome_voce and not self.nome_voce:
            self.nome_voce = row.nome_voce
        if row.descrizione:
            self.descrizioni.add(row.descrizione)
        self.fornitori.add(row.fornitore_nome or NO_SUPPLIER)
        self.righe += 1

    def as_dict(self) -> dict:
        ordered = [bucket for _, bucket in _ordered(self.buckets)]
        parts = [bucket.as_dict() for bucket in ordered]
        single = ordered[0] if len(ordered) == 1 else None
        return {
            "sku_interno": self.sku_interno,
            # Nome della voce; la descrizione del fornitore solo se la voce non ha nome.
            "descrizione": self.nome_voce or (max(self.descrizioni) if self.descrizioni else self.sku_interno),
            "fornitori": ", ".join(sorted(self.fornitori)) or "—",
            # Valori unici solo se tutte le righe stanno in una sola unità.
            "quantita_totale": float(single.quantita) if single else None,
            "unita_misura": single.etichetta if single else None,
            "quantita_omaggio": float(single.quantita_omaggio) if single else None,
            "quantita_resa": float(single.quantita_resa) if single else None,
            "prezzo_medio": _num(single.prezzo_medio) if single else None,
            "quantita_per_unita": parts,
            "quantita_testo": quantities_text(parts),
            "conversione_completa": all(bucket.convertita for bucket in ordered),
            "spesa_totale": float(self.spesa),
            "spesa_resi": float(self.spesa_resi),
            "numero_fatture": len(self.fatture_acquisto),
            "solo_resi": not self.fatture_acquisto,
        }


def aggregate_by_sku(rows: Iterable[Any], conversions: Mapping[ConversionKey, LineConversion]) -> list[dict]:
    """Una riga per SKU, ordinata per spesa netta decrescente (poi SKU)."""
    by_sku: dict[str, SkuConsumption] = {}
    for row in rows:
        item = by_sku.get(row.sku_interno)
        if item is None:
            item = by_sku[row.sku_interno] = SkuConsumption(row.sku_interno)
        item.add(row, conversions.get(conversion_key(row)))
    items = [item.as_dict() for item in by_sku.values()]
    items.sort(key=lambda i: (-i["spesa_totale"], i["sku_interno"]))
    return items


def _sort_quantity(item: Mapping[str, Any]) -> float:
    """Quantità per l'ordinamento: quella unica, altrimenti quella dell'unità principale."""
    if item.get("quantita_totale") is not None:
        return item["quantita_totale"]
    parts = item.get("quantita_per_unita") or []
    return parts[0]["quantita"] if parts else 0.0


def top_products(items: list[dict], sort_by: str = "quantita", limit: Optional[int] = 50) -> dict:
    """Classifica Top prodotti con il totale calcolato su TUTTE le voci (non solo le prime N)."""
    if sort_by == "spesa":
        key = lambda i: (-i["spesa_totale"], i["sku_interno"])  # noqa: E731
    elif sort_by == "acquisti":
        key = lambda i: (-i["numero_fatture"], -i["spesa_totale"], i["sku_interno"])  # noqa: E731
    else:
        key = lambda i: (-_sort_quantity(i), i["sku_interno"])  # noqa: E731
    ordered = sorted(items, key=key)
    totale = sum((_dec(i["spesa_totale"]) for i in items), ZERO)
    return {
        "prodotti": ordered[:limit] if limit else ordered,
        "totale_spesa": float(totale),
        "numero_prodotti": len(items),
    }


# ─────────────────────────────────────────────
# Dettaglio (uno o più SKU): sede, mese, prezzi
# ─────────────────────────────────────────────

def consumption_detail(rows: Iterable[Any], conversions: Mapping[ConversionKey, LineConversion]) -> dict:
    """Dettaglio consolidato. Quantità e prezzi unici solo se tutte le righe hanno la stessa unità."""
    totals: dict = {}
    by_location: dict[str, dict] = {}
    by_month: dict[str, dict] = {}
    skus: set = set()
    spesa = ZERO
    for row in rows:
        values = line_values(row, conversions.get(conversion_key(row)))
        importo = _dec(row.importo_netto)
        spesa += importo
        skus.add(row.sku_interno)
        _bucket(totals, values.key).add(row, values)
        mese = row.data_documento.strftime("%Y-%m") if row.data_documento else "n.d."
        for groups, name in ((by_location, row.location_nome or NO_LOCATION), (by_month, mese)):
            group = groups.setdefault(name, {"spesa": ZERO, "buckets": {}})
            group["spesa"] += importo
            _bucket(group["buckets"], values.key).add(row, values)

    ordered = _ordered(totals)
    labels = {key: bucket.etichetta for key, bucket in ordered}
    order = {key: i for i, (key, _) in enumerate(ordered)}
    single = ordered[0][1] if len(ordered) == 1 else None

    def group_dict(name_field: str, name: str, group: dict) -> dict:
        parts = [
            {"unita": labels[key], "convertita": key[1], "quantita": float(bucket.quantita)}
            for key, bucket in sorted(group["buckets"].items(), key=lambda kv: order[kv[0]])
        ]
        return {
            name_field: name,
            "spesa_totale": float(group["spesa"]),
            "quantita_totale": parts[0]["quantita"] if single and parts else None,
            "quantita_per_unita": parts,
        }

    locations = [group_dict("location_nome", name, g) for name, g in by_location.items()]
    locations.sort(key=lambda g: (-g["spesa_totale"], g["location_nome"]))
    months = [group_dict("mese", name, g) for name, g in by_month.items()]
    months.sort(key=lambda g: g["mese"], reverse=True)
    parts = [bucket.as_dict(labels[key]) for key, bucket in ordered]
    return {
        "numero_prodotti": len(skus),
        "consumo_per_location": locations,
        "consumo_per_mese": months,
        "spesa_totale": float(spesa),
        "unita_misura": single.etichetta if single else None,
        "quantita_totale": float(single.quantita) if single else None,
        "quantita_per_unita": parts,
        "quantita_testo": quantities_text(parts),
        # Prezzi solo nella stessa unità: con unità diverse non si confrontano.
        "prezzo_minimo": _num(single.minimo) if single else None,
        "prezzo_massimo": _num(single.massimo) if single else None,
        "prezzo_medio": _num(single.prezzo_medio) if single else None,
    }


# ─────────────────────────────────────────────
# Fatture che generano il consumo (finestra e PDF)
# ─────────────────────────────────────────────

def invoice_rows(rows: Iterable[Any], conversions: Mapping[ConversionKey, LineConversion]) -> list[dict]:
    """Una riga per riga di fattura, con quantità e importo firmati (le note di credito negative).

    unita_riepilogo/quantita_riepilogo: unità e quantità con cui la riga entra nel totale
    (la stessa regola della tabella), così finestra e PDF non sommano unità diverse.
    """
    rows = list(rows)
    computed = []
    totals: dict = {}
    for row in rows:
        values = line_values(row, conversions.get(conversion_key(row)))
        _bucket(totals, values.key).add(row, values)
        computed.append((row, values))
    labels = {key: bucket.etichetta for key, bucket in totals.items()}
    result = []
    for row, values in computed:
        segno = int(row.segno)
        tipo = getattr(row.tipo_documento, "value", row.tipo_documento)
        result.append({
            "riga_id": row.riga_id,
            "fattura_id": row.fattura_id,
            "numero_documento": row.numero_documento,
            "data_documento": row.data_documento.isoformat() if row.data_documento else None,
            "tipo_documento": tipo,
            "is_reso": segno < 0,
            "location_nome": row.location_nome or NO_LOCATION,
            "fornitore_nome": row.fornitore_nome or NO_SUPPLIER,
            "prodotto_descrizione": row.descrizione,
            "sku_interno": row.sku_interno,
            "quantita": float(segno * _dec(row.quantita)),
            "unita_misura": values.fattura_unit,
            "prezzo_unitario": float(_dec(row.netto_unitario)),
            "spesa_totale": float(_dec(row.importo_netto)),
            "is_omaggio": bool(row.is_omaggio),
            "unita_riepilogo": labels[values.key],
            "riepilogo_convertito": values.key[1],
            "quantita_riepilogo": float(segno * values.quantita),
        })
    result.sort(key=lambda r: (r["data_documento"] or "", str(r["numero_documento"] or ""), -(r["riga_id"] or 0)),
                reverse=True)
    return result


def invoice_totals(invoices: Iterable[Mapping[str, Any]]) -> list[dict]:
    """Totali della finestra fatture: una voce per unità di riepilogo (mai sommate tra loro)."""
    totals: dict[tuple[str, bool], dict] = {}
    for inv in invoices:
        key = (inv["unita_riepilogo"], bool(inv["riepilogo_convertito"]))
        entry = totals.setdefault(key, {"unita": key[0], "convertita": key[1], "quantita": ZERO, "spesa": ZERO})
        entry["quantita"] += _dec(inv["quantita_riepilogo"])
        entry["spesa"] += _dec(inv["spesa_totale"])
    ordered = sorted(totals.values(), key=lambda e: (-abs(e["spesa"]), e["unita"]))
    return [
        {"unita": e["unita"], "convertita": e["convertita"], "quantita": float(e["quantita"]),
         "spesa_totale": float(e["spesa"])}
        for e in ordered
    ]


MIXED_UNITS = "unità diverse"

# ─────────────────────────────────────────────
# Excel: stesse righe dello schermo
# ─────────────────────────────────────────────

CONSUMPTION_EXCEL_HEADERS = [
    "SKU Interno", "Prodotto", "Fornitori", "Quantità netta", "Unità", "Quantità per unità",
    "di cui Omaggi", "di cui Resi", "Prezzo Medio Netto (€/unità)", "Spesa Netta (€)", "Fatture d'acquisto",
]
TOP_EXCEL_HEADERS = [
    "Posizione", "SKU Interno", "Prodotto", "Fornitori", "Quantità netta", "Unità", "Quantità per unità",
    "di cui Resi", "Fatture d'acquisto", "Prezzo Medio Netto (€/unità)", "Spesa Netta (€)",
]


def _blank(value):
    return "" if value is None else value


def consumption_excel_rows(items: Iterable[Mapping[str, Any]]) -> list[list]:
    """Righe dell'Excel Consumi: gli stessi dizionari della tabella a schermo."""
    return [
        [
            i["sku_interno"], i["descrizione"], i["fornitori"], _blank(i["quantita_totale"]),
            i["unita_misura"] or MIXED_UNITS, i["quantita_testo"], _blank(i["quantita_omaggio"]),
            _blank(i["quantita_resa"]), "n.d." if i["prezzo_medio"] is None else i["prezzo_medio"],
            i["spesa_totale"], i["numero_fatture"],
        ]
        for i in items
    ]


def top_excel_rows(items: Iterable[Mapping[str, Any]]) -> list[list]:
    return [
        [
            pos, i["sku_interno"], i["descrizione"], i["fornitori"], _blank(i["quantita_totale"]),
            i["unita_misura"] or MIXED_UNITS, i["quantita_testo"], _blank(i["quantita_resa"]),
            i["numero_fatture"], "n.d." if i["prezzo_medio"] is None else i["prezzo_medio"], i["spesa_totale"],
        ]
        for pos, i in enumerate(items, start=1)
    ]


def build_workbook(sheet_title: str, headers: list[str], rows: list[list], *, money_cols=(), number_cols=(),
                   int_cols=(), center_cols=(), total_row: Optional[list] = None):
    """Workbook con lo stile dei report (intestazione navy, bordi sottili). Colonne numerate da 1."""
    from io import BytesIO

    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.views.sheetView[0].showGridLines = True
    ws.append(headers)
    thin = Side(style="thin", color="DDDDDD")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border
    body = list(rows) + ([total_row] if total_row else [])
    for offset, values in enumerate(body):
        ws.append(values)
        row_num = offset + 2
        is_total = total_row is not None and offset == len(body) - 1
        for col in range(1, len(values) + 1):
            cell = ws.cell(row=row_num, column=col)
            cell.border = border
            cell.font = Font(name="Calibri", size=11, bold=is_total)
            numeric = isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool)
            if col in money_cols and numeric:
                cell.number_format = "€ #,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif col in number_cols and numeric:
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            elif col in int_cols and numeric:
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right")
            elif col in center_cols:
                cell.alignment = Alignment(horizontal="center")
            else:
                cell.alignment = Alignment(horizontal="left")
    for col in ws.columns:
        width = max(len(f"€ {c.value:.2f}" if isinstance(c.value, float) else str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(width + 4, 12), 70)
    stream = BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream


def report_title(skus: list[str], rows: Iterable[Any]) -> str:
    """Titolo del PDF: nome della voce (canonical_name), non una descrizione grezza presa a caso."""
    names: dict[str, str] = {}
    raw: dict[str, set] = {}
    for row in rows:
        if row.nome_voce:
            names.setdefault(row.sku_interno, row.nome_voce)
        if row.descrizione:
            raw.setdefault(row.sku_interno, set()).add(row.descrizione)
    if len(skus) == 1:
        sku = skus[0]
        name = names.get(sku) or (max(raw[sku]) if raw.get(sku) else None)
        return f"{sku} - {name}" if name else sku
    shown = [names.get(s) or s for s in skus[:3]]
    return f"Consolidato di {len(skus)} articoli ({', '.join(shown)}{'...' if len(skus) > 3 else ''})"
