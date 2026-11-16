"""Base comune delle righe d'acquisto per tutte le schermate di analisi.

Un solo posto per le regole che ogni report deve rispettare:

- netto riga = prezzo_unitario_fatturato x (1 - sconto/100), sempre per unità di
  fattura. prezzo_netto_normalizzato NON si usa: su alcune righe storiche contiene
  il prezzo già convertito nell'unità di listino;
- segno -1 per le note di credito TD04 e TD08 (nel database hanno quantità e
  prezzi positivi), +1 per tutto il resto;
- gli omaggi (is_omaggio, prezzo 0 o sconto 100%) restano nelle quantità ma non
  entrano nelle medie dei prezzi;
- filtro tenant come in services.tenant_scope;
- NOT EXISTS su skus_esclusi e righe_escluse_statistiche;
- unità di fattura normalizzata (N./NR = PZ, K./KGM = KG, vuota = N.D.);
- fattore di conversione per riga verso l'unità di confronto della voce, con
  l'alias del fornitore risolto per codice o per descrizione come nella
  riassociazione delle righe (api/v1/fatture.py, api/v1/product_identity.py) e
  con il flag reliable di normalize_price_for_comparison(strict_pack=True).

Due modi d'uso, con le stesse regole:

1. SQL aggregato: purchase_lines_select() -> .subquery(); le conversioni si
   caricano con load_conversions() e si uniscono alla query con
   conversion_table() + conversion_join() (una tabella VALUES calcolata in Python,
   così SQL e Python usano esattamente la stessa logica di conversione).
2. Python riga per riga: document_sign(), line_net_unit_price(),
   line_net_amount(), normalized_unit(), is_free_line(), line_conversion().
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, NamedTuple, Optional

from sqlalchemy import (
    Boolean,
    Integer,
    Numeric,
    String,
    and_,
    case,
    cast,
    column,
    exists,
    func,
    literal,
    or_,
    select,
    values,
)
from sqlalchemy.orm import noload

from app.models.esclusi import RigaEsclusaStatistiche, SKUEscluso
from app.models.fatture import Fattura, RigaFattura, TipoDocumento
from app.models.products import Product, SupplierProductAlias
from app.services.normalization import normalize_text, unit_family
from app.services.tenant_scope import invoice_tenant_filter

# ─────────────────────────────────────────────
# Segno del documento
# ─────────────────────────────────────────────

# TD08 è la nota di credito semplificata SdI: stesso segno della TD04.
CREDIT_NOTE_TYPES: tuple[TipoDocumento, ...] = (TipoDocumento.TD04, TipoDocumento.TD08)
_CREDIT_NOTE_CODES = frozenset(t.value for t in CREDIT_NOTE_TYPES)


def document_sign(tipo_documento: Any) -> int:
    """-1 per TD04/TD08, +1 per ogni altro tipo (TD01, TD24, TD25...)."""
    code = getattr(tipo_documento, "value", tipo_documento)
    return -1 if str(code or "").strip().upper() in _CREDIT_NOTE_CODES else 1


def sign_sql(tipo_documento=Fattura.tipo_documento):
    """Espressione SQL: -1 per le note di credito, 1 altrimenti."""
    return case((tipo_documento.in_(CREDIT_NOTE_TYPES), -1), else_=1)


# ─────────────────────────────────────────────
# Prezzo netto e importi
# ─────────────────────────────────────────────

def _dec(value: Any) -> Decimal:
    return Decimal(str(value)) if value is not None else Decimal("0")


def line_net_unit_price(prezzo_unitario: Any, sconto_percentuale: Any = 0) -> Decimal:
    """Prezzo netto per unità di fattura: pu x (1 - sconto/100). Sempre >= 0 come in fattura."""
    return _dec(prezzo_unitario) * (Decimal("1") - _dec(sconto_percentuale) / Decimal("100"))


def line_net_amount(prezzo_unitario: Any, sconto_percentuale: Any, quantita: Any, tipo_documento: Any) -> Decimal:
    """Importo netto della riga con il segno del documento (negativo per le note di credito)."""
    return document_sign(tipo_documento) * line_net_unit_price(prezzo_unitario, sconto_percentuale) * _dec(quantita)


def signed_quantity(quantita: Any, tipo_documento: Any) -> Decimal:
    return document_sign(tipo_documento) * _dec(quantita)


def net_unit_price_sql(riga=RigaFattura):
    """Espressione SQL del prezzo netto per unità di fattura."""
    return riga.prezzo_unitario_fatturato * (
        literal(1) - func.coalesce(riga.sconto_percentuale, 0) / literal(100)
    )


def signed_quantity_sql(riga=RigaFattura, tipo_documento=Fattura.tipo_documento):
    return sign_sql(tipo_documento) * riga.quantita


def signed_amount_sql(riga=RigaFattura, tipo_documento=Fattura.tipo_documento):
    """Importo netto della riga con segno, in SQL."""
    return sign_sql(tipo_documento) * net_unit_price_sql(riga) * riga.quantita


# ─────────────────────────────────────────────
# Omaggi
# ─────────────────────────────────────────────

def is_free_line(is_omaggio: Any, prezzo_unitario: Any, sconto_percentuale: Any = 0) -> bool:
    """Omaggio: flag dell'XML, prezzo 0 o sconto del 100% (stessa regola del parser)."""
    return bool(is_omaggio) or _dec(prezzo_unitario) <= 0 or _dec(sconto_percentuale) >= 100


def is_free_sql(riga=RigaFattura):
    return or_(
        func.coalesce(riga.is_omaggio, False).is_(True),
        riga.prezzo_unitario_fatturato <= 0,
        func.coalesce(riga.sconto_percentuale, 0) >= 100,
    )


def counts_for_average(is_omaggio: Any, prezzo_unitario: Any, sconto_percentuale: Any, tipo_documento: Any) -> bool:
    """Una riga entra nelle medie/minimi dei prezzi solo se è un acquisto pagato (non omaggio, non nota di credito)."""
    return document_sign(tipo_documento) == 1 and not is_free_line(is_omaggio, prezzo_unitario, sconto_percentuale)


def counts_for_average_sql(riga=RigaFattura, tipo_documento=Fattura.tipo_documento):
    return and_(~tipo_documento.in_(CREDIT_NOTE_TYPES), ~is_free_sql(riga))


# ─────────────────────────────────────────────
# Esclusioni e tenant
# ─────────────────────────────────────────────

def not_excluded_sql(riga=RigaFattura):
    """NOT EXISTS su skus_esclusi (per SKU) e righe_escluse_statistiche (per riga)."""
    return and_(
        ~exists().where(SKUEscluso.sku_interno == riga.sku_interno),
        ~exists().where(RigaEsclusaStatistiche.riga_fattura_id == riga.id),
    )


def tenant_sql(user):
    """Stesso filtro tenant del resto del codice (le fatture senza tenant sono del tenant 1)."""
    return invoice_tenant_filter(user)


# ─────────────────────────────────────────────
# Unità di fattura normalizzata
# ─────────────────────────────────────────────

NO_UNIT = "N.D."

# Chiave: unità maiuscola, senza spazi e senza punti iniziali/finali.
UNIT_LABELS: dict[str, str] = {}
for _label, _spellings in {
    "PZ": ("PZ", "PZZ", "PEZZO", "PEZZI", "N", "NR", "NUM", "NUMERO", "PC", "PCE", "PIECE", "PIECES",
           "UNITA", "UNIT", "UN", "H87", "C62", "TA", "TN", "TANICA", "TANICHE"),
    "KG": ("KG", "K", "KGM", "KGS", "KGR", "KILO", "KILOGRAMMI", "CHILO", "CHILI", "CHILOGRAMMI"),
    "LT": ("LT", "L", "LTR", "LITRO", "LITRI", "LITER", "LITRE"),
    "CT": ("CT", "CRT", "CARTONE", "CARTONI"),
    "CNF": ("CNF", "CF", "CONF", "CONFEZIONE", "CONFEZIONI"),
    "BT": ("BT", "BTL", "BOT", "BOTT", "BOTTIGLIA", "BOTTIGLIE"),
    "GR": ("GR", "G", "GRM", "GRAMMI"),
}.items():
    for _spelling in _spellings:
        UNIT_LABELS[_spelling] = _label

_UNIT_KEY_SPACES = re.compile(r"\s+")


def unit_key(raw_unit: Any) -> str:
    return _UNIT_KEY_SPACES.sub("", str(raw_unit or "")).upper().strip(".")


def normalized_unit(raw_unit: Any) -> str:
    """Unità di fattura normalizzata per mostrare e raggruppare le quantità.

    N./NR -> PZ, K./KGM -> KG, LTR -> LT, CF/CONF -> CNF, vuota -> N.D.;
    un'unità sconosciuta resta maiuscola com'è (COL, SC...). CT e CNF restano
    distinti perché non è detto che contengano lo stesso numero di pezzi.
    """
    key = unit_key(raw_unit)
    if not key:
        return NO_UNIT
    return UNIT_LABELS.get(key, key)


def normalized_unit_sql(raw_unit=RigaFattura.unita_misura_fattura):
    """Stessa mappa di normalized_unit(), in SQL (PostgreSQL)."""
    key = func.upper(func.btrim(func.regexp_replace(func.coalesce(raw_unit, ""), r"\s+", "", "g"), "."))
    # Simple CASE (CASE key WHEN ...): the key expression is evaluated once per row.
    return case({"": NO_UNIT, **UNIT_LABELS}, value=key, else_=key)


# ─────────────────────────────────────────────
# Righe d'acquisto (query base)
# ─────────────────────────────────────────────

def purchase_lines_select(
    user,
    *,
    date_from=None,
    date_to=None,
    location_ids: Optional[Iterable[int]] = None,
    fornitore_ids: Optional[Iterable[int]] = None,
    skus: Optional[Iterable[str]] = None,
    require_sku: bool = False,
    include_excluded: bool = False,
    include_credit_notes: bool = True,
):
    """SELECT di una riga per riga di fattura, con tutte le regole comuni applicate.

    user: utente corrente (filtro tenant con invoice_tenant_filter). None = nessun
    filtro tenant, solo per script e test.
    date_from/date_to: estremi inclusi su fatture.data_documento.
    require_sku: solo righe collegate a una voce (sku_interno valorizzato).
    include_excluded: True per NON applicare skus_esclusi/righe_escluse_statistiche.
    include_credit_notes: False per tenere solo i documenti con segno +1.

    Colonne: riga_id, fattura_id, numero_documento, data_documento,
    tipo_documento, location_id, fornitore_id, sku_interno, product_id,
    comparison_unit, codice_fornitore, descrizione, unita_misura (grezza),
    unita (normalizzata), quantita (come in fattura), prezzo_unitario,
    sconto_percentuale, netto_unitario, segno, quantita_firmata, importo_netto
    (con segno), is_omaggio (regola is_free_line), in_media.
    """
    segno = sign_sql(Fattura.tipo_documento)
    stmt = (
        select(
            RigaFattura.id.label("riga_id"),
            Fattura.id.label("fattura_id"),
            Fattura.numero_documento.label("numero_documento"),
            Fattura.data_documento.label("data_documento"),
            Fattura.tipo_documento.label("tipo_documento"),
            Fattura.location_id.label("location_id"),
            Fattura.fornitore_id.label("fornitore_id"),
            RigaFattura.sku_interno.label("sku_interno"),
            Product.id.label("product_id"),
            Product.comparison_unit.label("comparison_unit"),
            RigaFattura.codice_fornitore_raw.label("codice_fornitore"),
            RigaFattura.descrizione_fornitore_raw.label("descrizione"),
            RigaFattura.unita_misura_fattura.label("unita_misura"),
            normalized_unit_sql(RigaFattura.unita_misura_fattura).label("unita"),
            RigaFattura.quantita.label("quantita"),
            RigaFattura.prezzo_unitario_fatturato.label("prezzo_unitario"),
            RigaFattura.sconto_percentuale.label("sconto_percentuale"),
            net_unit_price_sql(RigaFattura).label("netto_unitario"),
            segno.label("segno"),
            (segno * RigaFattura.quantita).label("quantita_firmata"),
            (segno * net_unit_price_sql(RigaFattura) * RigaFattura.quantita).label("importo_netto"),
            is_free_sql(RigaFattura).label("is_omaggio"),
            counts_for_average_sql(RigaFattura, Fattura.tipo_documento).label("in_media"),
        )
        .select_from(RigaFattura)
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .outerjoin(Product, Product.sku_interno == RigaFattura.sku_interno)
    )
    if user is not None:
        stmt = stmt.where(tenant_sql(user))
    if not include_excluded:
        stmt = stmt.where(not_excluded_sql(RigaFattura))
    if not include_credit_notes:
        stmt = stmt.where(~Fattura.tipo_documento.in_(CREDIT_NOTE_TYPES))
    if require_sku:
        stmt = stmt.where(RigaFattura.sku_interno.isnot(None), RigaFattura.sku_interno != "")
    if date_from is not None:
        stmt = stmt.where(Fattura.data_documento >= date_from)
    if date_to is not None:
        stmt = stmt.where(Fattura.data_documento <= date_to)
    if location_ids is not None:
        stmt = stmt.where(Fattura.location_id.in_(list(location_ids)))
    if fornitore_ids is not None:
        stmt = stmt.where(Fattura.fornitore_id.in_(list(fornitore_ids)))
    if skus is not None:
        stmt = stmt.where(RigaFattura.sku_interno.in_(list(skus)))
    return stmt


# ─────────────────────────────────────────────
# Conversione verso l'unità di confronto della voce
# ─────────────────────────────────────────────

@dataclass(frozen=True)
class LineConversion:
    """Unità di confronto della voce contenute in una unità di fattura.

    factor è None quando la conversione non è affidabile: in quel caso la
    quantità non si converte e va mostrata nella sua unità di fattura.
    """

    factor: Optional[Decimal]
    reliable: bool
    comparison_unit: Optional[str]  # Pz, CT, Kg, Lt (unità della voce) o None
    explanation: str = ""

    def quantity(self, quantita: Any) -> Optional[Decimal]:
        """Quantità nell'unità di confronto (con lo stesso segno ricevuto), None se non affidabile."""
        if not self.reliable or self.factor is None:
            return None
        return _dec(quantita) * self.factor

    def unit_price(self, net_unit_price: Any) -> Optional[Decimal]:
        """Prezzo per unità di confronto, None se non affidabile."""
        if not self.reliable or not self.factor:
            return None
        return _dec(net_unit_price) / self.factor


UNRELIABLE_NO_PRODUCT = LineConversion(None, False, None, "Riga non collegata a una voce")


def line_conversion(
    *,
    product: Optional[Product],
    alias: Optional[SupplierProductAlias] = None,
    unita_misura: Optional[str] = None,
    descrizione: Optional[str] = None,
    target_unit: Optional[str] = None,
    strict_pack: bool = True,
) -> LineConversion:
    """Fattore di conversione di una riga verso l'unità di confronto della voce.

    Usa normalize_price_for_comparison con strict_pack=True: unit_count=1 di
    default non è una confezione nota, e senza confezione/unità certa reliable=False.
    Il fattore non dipende dal prezzo (vale anche per gli omaggi a prezzo 0).
    target_unit: unità di confronto diversa da products.comparison_unit (es. listino).
    strict_pack=False solo dove il prezzo si confronta con i listini e con il
    controllo anomalie (Listino Smart), che usano la stessa regola non rigida.
    """
    if product is None:
        return UNRELIABLE_NO_PRODUCT
    from app.services.matching import normalize_price_for_comparison

    line = SimpleNamespace(
        prezzo_unitario_fatturato=Decimal("1"),
        sconto_percentuale=Decimal("0"),
        quantita=Decimal("1"),
        unita_misura_fattura=unita_misura or "",
        descrizione_fornitore_raw=descrizione or "",
    )
    result = normalize_price_for_comparison(
        line, product, alias=alias, target_comparison_unit=target_unit, strict_pack=strict_pack
    )
    target = unit_family(target_unit or product.comparison_unit)
    if not result.reliable:
        return LineConversion(None, False, target, result.explanation)
    return LineConversion(result.listino_units_per_invoice_unit, True, target, result.explanation)


class AliasIndex:
    """Collegamenti fornitore-prodotto indicizzati come li risolve la riassociazione delle righe.

    - riga con codice articolo: alias (fornitore, codice), e solo se è della stessa voce;
    - riga senza codice: alias (fornitore, descrizione normalizzata) della stessa voce.
    A parità vince l'alias approvato con id più basso (scelta deterministica).
    """

    def __init__(self, aliases: Iterable[SupplierProductAlias]):
        self._by_code: dict[tuple[int, str], SupplierProductAlias] = {}
        self._by_description: dict[tuple[int, str], list[SupplierProductAlias]] = {}
        ordered = sorted(aliases, key=lambda a: (getattr(a, "status", "approved") != "approved", a.id or 0))
        for alias in ordered:
            code = (alias.supplier_code or "").strip()
            if code:
                self._by_code.setdefault((alias.supplier_id, code), alias)
            description = alias.normalized_description or normalize_text(alias.raw_description or "")
            if description:
                self._by_description.setdefault((alias.supplier_id, description), []).append(alias)

    def resolve(
        self,
        fornitore_id: int,
        product_id: Optional[int],
        codice: Optional[str],
        descrizione: Optional[str],
    ) -> Optional[SupplierProductAlias]:
        code = (codice or "").strip()
        if code:
            alias = self._by_code.get((fornitore_id, code))
            if alias is not None and (product_id is None or alias.product_id == product_id):
                return alias
            return None
        for alias in self._by_description.get((fornitore_id, normalize_text(descrizione or "")), []):
            if product_id is None or alias.product_id == product_id:
                return alias
        return None


class ConversionKey(NamedTuple):
    """Tutto ciò da cui dipende il fattore di una riga (non dal prezzo né dalla quantità)."""

    fornitore_id: int
    product_id: Optional[int]
    codice_fornitore: Optional[str]
    descrizione: Optional[str]
    unita_misura: Optional[str]


def conversion_key(row: Any) -> ConversionKey:
    """Chiave di conversione da una riga di purchase_lines_select (Row o oggetto con quegli attributi)."""
    return ConversionKey(
        row.fornitore_id, row.product_id, row.codice_fornitore, row.descrizione, row.unita_misura
    )


def compute_conversions(
    keys: Iterable[ConversionKey],
    products: Mapping[int, Product],
    alias_index: AliasIndex,
) -> dict[ConversionKey, LineConversion]:
    conversions: dict[ConversionKey, LineConversion] = {}
    for key in keys:
        product = products.get(key.product_id) if key.product_id is not None else None
        alias = alias_index.resolve(key.fornitore_id, key.product_id, key.codice_fornitore, key.descrizione)
        conversions[key] = line_conversion(
            product=product, alias=alias, unita_misura=key.unita_misura, descrizione=key.descrizione
        )
    return conversions


async def load_conversions(db, lines_subquery) -> dict[ConversionKey, LineConversion]:
    """Calcola il fattore per ogni combinazione distinta presente nella subquery delle righe.

    lines_subquery: purchase_lines_select(...).subquery(). Le combinazioni distinte
    (fornitore, voce, codice, descrizione, unità) sono poche rispetto alle righe.
    """
    pl = lines_subquery.c
    rows = (await db.execute(
        select(pl.fornitore_id, pl.product_id, pl.codice_fornitore, pl.descrizione, pl.unita_misura).distinct()
    )).all()
    keys = [ConversionKey(*row) for row in rows]
    if not keys:
        return {}
    product_ids = {k.product_id for k in keys if k.product_id is not None}
    supplier_ids = {k.fornitore_id for k in keys}
    products: dict[int, Product] = {}
    if product_ids:
        products = {
            p.id: p
            for p in (await db.scalars(
                select(Product).options(noload("*")).where(Product.id.in_(product_ids))
            )).all()
        }
    aliases = (await db.scalars(
        select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.supplier_id.in_(supplier_ids))
    )).all()
    return compute_conversions(keys, products, AliasIndex(aliases))


def conversion_table(conversions: Mapping[ConversionKey, LineConversion], name: str = "conv"):
    """Subquery SQL (VALUES) con le conversioni, da unire alle righe con conversion_join().

    Colonne: fornitore_id, product_id, codice_fornitore, descrizione, unita_misura,
    factor (NULL se non affidabile), reliable, comparison_unit. I valori sono
    scritti come letterali: nessun limite al numero di parametri del driver.
    """
    rows = [
        (
            key.fornitore_id, key.product_id, key.codice_fornitore, key.descrizione, key.unita_misura,
            conv.factor if conv.reliable else None, bool(conv.reliable), conv.comparison_unit,
        )
        for key, conv in conversions.items()
    ]
    if not rows:
        # A VALUES list cannot be empty: one row that matches no invoice line.
        rows = [(-1, None, None, None, None, None, False, None)]
    data = values(
        column("fornitore_id", Integer),
        column("product_id", Integer),
        column("codice_fornitore", String),
        column("descrizione", String),
        column("unita_misura", String),
        column("factor", Numeric(20, 8)),
        column("reliable", Boolean),
        column("comparison_unit", String),
        name=f"{name}_values",
        literal_binds=True,
    ).data(rows)
    # Explicit casts: a column with only NULLs would otherwise be typed as text.
    return select(
        cast(data.c.fornitore_id, Integer).label("fornitore_id"),
        cast(data.c.product_id, Integer).label("product_id"),
        cast(data.c.codice_fornitore, String).label("codice_fornitore"),
        cast(data.c.descrizione, String).label("descrizione"),
        cast(data.c.unita_misura, String).label("unita_misura"),
        cast(data.c.factor, Numeric(20, 8)).label("factor"),
        cast(data.c.reliable, Boolean).label("reliable"),
        cast(data.c.comparison_unit, String).label("comparison_unit"),
    ).select_from(data).subquery(name)


def conversion_join(lines_subquery, conv):
    """Condizione di join (LEFT OUTER) tra la subquery delle righe e conversion_table()."""
    pl = lines_subquery.c
    return and_(
        pl.fornitore_id == conv.c.fornitore_id,
        pl.product_id.is_not_distinct_from(conv.c.product_id),
        pl.codice_fornitore.is_not_distinct_from(conv.c.codice_fornitore),
        pl.descrizione.is_not_distinct_from(conv.c.descrizione),
        pl.unita_misura.is_not_distinct_from(conv.c.unita_misura),
    )


def converted_quantity_sql(lines_subquery, conv):
    """Quantità con segno nell'unità di confronto; NULL se la conversione non è affidabile."""
    return case(
        (conv.c.reliable.is_(True), lines_subquery.c.quantita_firmata * conv.c.factor),
        else_=None,
    )


def converted_unit_price_sql(lines_subquery, conv):
    """Prezzo netto per unità di confronto; NULL se la conversione non è affidabile."""
    return case(
        (and_(conv.c.reliable.is_(True), conv.c.factor > 0), lines_subquery.c.netto_unitario / conv.c.factor),
        else_=None,
    )
