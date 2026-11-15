"""Accordi commerciali (premi fine anno, PFA) con le statistiche degli acquisti.

Regole (rapporto schermate 14/11/2026, gruppo SPESA):
- importo riga dal prezzo di fattura pu x (1 - sconto/100), segno -1 per TD04/TD08,
  omaggi esclusi (services/purchase_lines.py);
- quantità nell'unità dell'accordo = quantità di fattura x fattore della riga
  (collegamento fornitore-prodotto per codice o descrizione, come line_conversion);
  se anche una sola riga non è convertibile la quantità, il rientro fisso e il netto
  medio non si calcolano (unità non omogenee) invece di sommare cartoni e pezzi;
- periodo predefinito: anno solare in corso fino a oggi. Le righe NON si filtrano su
  data_inizio_validita (molte voci hanno la data di caricamento del listino);
- la soglia degli scaglioni si confronta con la spesa dell'anno solare (1/1 - data_a)
  di tutte le sedi, indipendentemente dal periodo scelto a video.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import noload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.v1.fatture import scaglione_percentage
from app.database import get_db
from app.models.utenti import Utente, RuoloUtente
from app.models.listino import ListinoMaster, PFATipo, UoMConversione
from app.models.fornitori import Fornitore
from app.models.fatture import RigaFattura
from app.models.alias import AliasProdotto
from app.models.products import Product, SupplierProductAlias
from app.schemas.accordi import AccordoCommercialeResponse, PFAScaglioneInfo
from app.services import purchase_lines as pl

router = APIRouter()

Q4 = Decimal("0.0001")


def _q(value: Optional[Decimal]) -> Optional[Decimal]:
    return None if value is None else value.quantize(Q4, rounding=ROUND_HALF_UP)


def rome_today() -> date:
    return datetime.now(ZoneInfo("Europe/Rome")).date()


def default_window(data_da: Optional[date], data_a: Optional[date], today: date) -> tuple[date, date]:
    """Senza date: anno solare in corso fino a oggi. Senza data_da: dal 1/1 dell'anno di data_a."""
    if data_a is None:
        data_a = today
    if data_da is None:
        data_da = date(data_a.year, 1, 1)
    return data_da, data_a


def pick_agreement_versions(versions: Iterable, data_a: date) -> list:
    """Una sola versione di listino per (fornitore, voce), così nessuna riga conta due volte.

    Vince la versione più recente già iniziata alla fine del periodo; se tutte
    iniziano dopo (data di caricamento successiva al periodo) si usa la prima.
    """
    by_key: dict[tuple, list] = {}
    for version in versions:
        by_key.setdefault((version.fornitore_id, version.sku_interno), []).append(version)
    chosen = []
    for group in by_key.values():
        started = [v for v in group if v.data_inizio_validita <= data_a]
        if started:
            chosen.append(max(started, key=lambda v: (v.data_inizio_validita, v.id)))
        else:
            chosen.append(min(group, key=lambda v: (v.data_inizio_validita, v.id)))
    return sorted(chosen, key=lambda v: v.id)


def line_factor(
    *,
    product: Optional[Product],
    alias: Optional[SupplierProductAlias],
    unita_misura: Optional[str],
    descrizione: Optional[str],
    agreement_unit: Optional[str],
    uom_rules: Iterable = (),
    legacy_alias: Optional[AliasProdotto] = None,
) -> Optional[Decimal]:
    """Unità dell'accordo contenute in una unità di fattura; None se non affidabile.

    1. collegamento fornitore-prodotto (confezione, volume, peso) con line_conversion;
    2. regola esplicita uom_conversioni del listino per quell'unità di fattura;
    3. coefficiente esplicito (diverso da 1) dell'alias legacy dello stesso codice;
    4. stessa unità normalizzata di fattura e di accordo: 1.
    """
    conversion = pl.line_conversion(
        product=product, alias=alias, unita_misura=unita_misura,
        descrizione=descrizione, target_unit=agreement_unit or None,
    )
    if conversion.reliable and conversion.factor is not None:
        return conversion.factor
    line_unit = pl.normalized_unit(unita_misura)
    for rule in uom_rules:
        if pl.normalized_unit(rule.uom_fattura) == line_unit and rule.coefficiente and Decimal(str(rule.coefficiente)) > 0:
            return Decimal(str(rule.coefficiente))
    if legacy_alias is not None and legacy_alias.coefficiente_conversione:
        coefficient = Decimal(str(legacy_alias.coefficiente_conversione))
        if coefficient > 0 and coefficient != 1:
            return coefficient
    if agreement_unit and line_unit != pl.NO_UNIT and line_unit == pl.normalized_unit(agreement_unit):
        return Decimal("1")
    return None


@dataclass
class AgreementTotals:
    quantita: Optional[Decimal]  # None: unità non omogenee
    fatturato: Decimal
    fatturato_anno: Decimal  # base della soglia scaglioni
    righe: int
    righe_non_convertibili: int


def agreement_totals(
    lines: Iterable,
    factor_of: Callable[[object], Optional[Decimal]],
    *,
    data_da: date,
    data_a: date,
    location_id: Optional[int] = None,
) -> AgreementTotals:
    """Somma le righe (colonne di purchase_lines_select) di un accordo.

    Periodo e sede valgono per quantità e fatturato; la spesa dell'anno solare di
    data_a (tutte le sedi) serve solo alla soglia degli scaglioni.
    """
    year_start = date(data_a.year, 1, 1)
    quantity = Decimal("0")
    spent = Decimal("0")
    year_spent = Decimal("0")
    count = 0
    unconvertible = 0
    for line in lines:
        amount = Decimal(str(line.importo_netto))
        if year_start <= line.data_documento <= data_a:
            year_spent += amount
        if not (data_da <= line.data_documento <= data_a):
            continue
        if location_id is not None and line.location_id != location_id:
            continue
        count += 1
        spent += amount
        factor = factor_of(line)
        if factor is None:
            unconvertible += 1
        else:
            quantity += Decimal(str(line.quantita_firmata)) * factor
    return AgreementTotals(
        quantita=None if unconvertible else quantity,
        fatturato=spent,
        fatturato_anno=year_spent,
        righe=count,
        righe_non_convertibili=unconvertible,
    )


def agreement_rebate(ag, totals: AgreementTotals) -> Optional[Decimal]:
    """Rientro maturato nel periodo; None se il PFA fisso non ha una quantità affidabile."""
    rebate = Decimal("0")
    if ag.pfa_tipo == PFATipo.fisso and ag.pfa_valore:
        if totals.quantita is None:
            return None
        rebate = totals.quantita * Decimal(str(ag.pfa_valore))
    elif ag.pfa_tipo == PFATipo.percentuale and ag.pfa_valore:
        rebate = totals.fatturato * Decimal(str(ag.pfa_valore))
    elif ag.pfa_tipo == PFATipo.scaglioni:
        rebate = totals.fatturato * scaglione_percentage(ag.pfa_scaglioni, totals.fatturato_anno)
    return max(rebate, Decimal("0"))


def contract_net_price(ag, totals: AgreementTotals) -> Optional[Decimal]:
    if ag.pfa_tipo == PFATipo.fisso and ag.pfa_valore:
        return Decimal(str(ag.prezzo_pattuito)) - Decimal(str(ag.pfa_valore))
    if ag.pfa_tipo == PFATipo.percentuale and ag.pfa_valore:
        return Decimal(str(ag.prezzo_pattuito)) * (Decimal("1") - Decimal(str(ag.pfa_valore)))
    if ag.pfa_tipo == PFATipo.scaglioni and ag.pfa_scaglioni:
        pct = scaglione_percentage(ag.pfa_scaglioni, totals.fatturato_anno)
        return Decimal(str(ag.prezzo_pattuito)) * (Decimal("1") - pct)
    return None


@router.get(
    "/",
    response_model=list[AccordoCommercialeResponse],
    summary="Lista accordi commerciali con statistiche acquisti",
)
async def list_accordi_commerciali(
    fornitore_id: int | None = Query(None),
    location_id: int | None = Query(None),
    data_da: date | None = Query(None),
    data_a: date | None = Query(None),
    current_user: Utente = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Resolve FastAPI Query defaults when called programmatically in tests
    if not isinstance(fornitore_id, int):
        fornitore_id = None
    if not isinstance(location_id, int):
        location_id = None
    if not isinstance(data_da, date):
        data_da = None
    if not isinstance(data_a, date):
        data_a = None

    # Enforce role-based access control (RBAC)
    if current_user.ruolo == RuoloUtente.manager:
        location_id = current_user.location_id

    data_da, data_a = default_window(data_da, data_a, rome_today())

    # 1. Listini con PFA validi in almeno un giorno del periodo (anche con scadenza
    #    futura), di fornitori non archiviati. Nessun filtro su data_inizio_validita.
    query = select(ListinoMaster).join(Fornitore).where(
        and_(
            ListinoMaster.pfa_tipo.is_not(None),
            or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= data_da),
            Fornitore.archived_at.is_(None),
        )
    ).options(
        selectinload(ListinoMaster.fornitore),
        selectinload(ListinoMaster.pfa_scaglioni)
    )
    if fornitore_id:
        query = query.where(ListinoMaster.fornitore_id == fornitore_id)

    agreements = pick_agreement_versions((await db.execute(query)).scalars().all(), data_a)
    if not agreements:
        return []

    sku_list = sorted({ag.sku_interno for ag in agreements})
    supplier_ids = sorted({ag.fornitore_id for ag in agreements})

    products = {
        p.sku_interno: p
        for p in (await db.execute(
            select(Product).options(noload("*")).where(Product.sku_interno.in_(sku_list))
        )).scalars().all()
    }
    alias_index = pl.AliasIndex((await db.execute(
        select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.supplier_id.in_(supplier_ids))
    )).scalars().all())

    # Alias legacy: collegano righe senza voce per codice, e solo per codice.
    legacy_aliases = (await db.execute(
        select(AliasProdotto).where(AliasProdotto.sku_interno.in_(sku_list))
    )).scalars().all()
    legacy_by_code = {
        (al.fornitore_id, (al.codice_fornitore_originale or "").strip().lower()): al
        for al in legacy_aliases
    }

    uom_rules_by_listino: dict[int, list] = {}
    for rule in (await db.execute(
        select(UoMConversione).where(UoMConversione.listino_id.in_([ag.id for ag in agreements]))
    )).scalars().all():
        uom_rules_by_listino.setdefault(rule.listino_id, []).append(rule)

    # 2. Righe d'acquisto dall'inizio dell'anno di data_a (soglia scaglioni) o da
    #    data_da se precede, senza filtro sede (la sede si applica in agreement_totals).
    legacy_codes = sorted({al.codice_fornitore_originale for al in legacy_aliases if al.codice_fornitore_originale})
    sku_condition = RigaFattura.sku_interno.in_(sku_list)
    if legacy_codes:
        sku_condition = or_(
            sku_condition,
            and_(RigaFattura.sku_interno.is_(None), RigaFattura.codice_fornitore_raw.in_(legacy_codes)),
        )
    lines_stmt = pl.purchase_lines_select(
        current_user,
        date_from=min(data_da, date(data_a.year, 1, 1)),
        date_to=data_a,
        fornitore_ids=supplier_ids,
        # Spesa contrattuale: anche le righe escluse dalle statistiche prezzi sono acquisti.
        include_excluded=True,
    ).where(sku_condition, ~pl.is_free_sql())
    lines = (await db.execute(lines_stmt)).all()

    lines_by_agreement: dict[tuple, list] = {}
    for line in lines:
        sku = line.sku_interno
        legacy = legacy_by_code.get((line.fornitore_id, (line.codice_fornitore or "").strip().lower()))
        if not sku and legacy is not None:
            sku = legacy.sku_interno
        if sku:
            lines_by_agreement.setdefault((line.fornitore_id, sku), []).append(line)

    results = []
    for ag in agreements:
        product = products.get(ag.sku_interno)
        agreement_unit = ag.unita_misura or None
        rules = uom_rules_by_listino.get(ag.id, [])

        def factor_of(line, ag=ag, product=product, agreement_unit=agreement_unit, rules=rules):
            return line_factor(
                product=product,
                alias=alias_index.resolve(
                    line.fornitore_id, getattr(product, "id", None), line.codice_fornitore, line.descrizione
                ),
                unita_misura=line.unita_misura,
                descrizione=line.descrizione,
                agreement_unit=agreement_unit,
                uom_rules=rules,
                legacy_alias=legacy_by_code.get(
                    (line.fornitore_id, (line.codice_fornitore or "").strip().lower())
                ),
            )

        totals = agreement_totals(
            lines_by_agreement.get((ag.fornitore_id, ag.sku_interno), []),
            factor_of,
            data_da=data_da,
            data_a=data_a,
            location_id=location_id,
        )
        rebate = agreement_rebate(ag, totals)
        net_average = None
        if totals.quantita is not None and totals.quantita > 0 and rebate is not None:
            net_average = (totals.fatturato - rebate) / totals.quantita

        results.append(
            AccordoCommercialeResponse(
                listino_id=ag.id,
                sku_interno=ag.sku_interno,
                descrizione=ag.descrizione,
                fornitore_id=ag.fornitore_id,
                fornitore_nome=ag.fornitore.nome_azienda,
                unita_misura=ag.unita_misura or getattr(product, "comparison_unit", None),
                prezzo_pattuito=ag.prezzo_pattuito,
                pfa_tipo=ag.pfa_tipo.value,
                pfa_valore=ag.pfa_valore,
                pfa_scaglioni=[
                    PFAScaglioneInfo(
                        id=sc.id,
                        listino_id=sc.listino_id,
                        soglia_da=sc.soglia_da,
                        soglia_a=sc.soglia_a,
                        valore_percentuale=sc.valore_percentuale
                    ) for sc in ag.pfa_scaglioni
                ],
                netto_rientro_contratto=_q(contract_net_price(ag, totals)),
                quantita_acquistata=_q(totals.quantita),
                totale_fatturato=_q(totals.fatturato),
                rientro_accumulato=_q(rebate),
                netto_rientro_medio=_q(net_average),
                unita_non_omogenee=totals.quantita is None,
                righe_non_convertibili=totals.righe_non_convertibili,
                periodo_da=data_da,
                periodo_a=data_a,
            )
        )

    return results
