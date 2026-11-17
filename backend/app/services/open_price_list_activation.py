"""Listino sempre aperto: applica al listino le modifiche del fornitore alla loro data.

Gira nel ciclo di automazione (main._automation_loop). listino_master resta
append-only: la riga vecchia si chiude il giorno prima della decorrenza e ne nasce
una nuova con origine «listino_aperto». Dopo ogni modifica si ricontrollano le
fatture del fornitore dalla decorrenza, con le stesse regole dell'importazione.
Idempotente: una modifica applicata cambia stato e non si riprende; gli arretrati
(decorrenza passata) si applicano con la loro data.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload, selectinload

from app.models.listino import ORIGINE_LISTINO_APERTO, ListinoMaster, PFAScaglione, UoMConversione
from app.models.supplier_price_link import (
    STATO_APPLICATO,
    STATO_PROGRAMMATO,
    STATO_SOSTITUITO,
    TIPO_NON_TRATTATO,
    SupplierPriceChange,
)
from app.services.open_price_list_rules import offer_lock_key, today_rome
from app.services.variant_price_import import previous_price_end

logger = logging.getLogger("price_sentinel.listino_aperto")

LOCK_KEY = 7_280_151  # un solo giro alla volta (il monitor usa 7_280_150)
MAX_PER_RUN = 500
MOTIVO_LISTINO_CAMBIATO = "listino_cambiato"  # un caricamento più recente ha già cambiato il prezzo


@dataclass(frozen=True)
class ListinoPlan:
    """Cosa fare della riga di listino da cui il fornitore è partito."""
    applicabile: bool
    chiudi_al: date | None = None
    nuova_dal: date | None = None
    nuova_al: date | None = None


def plan_listino_update(*, tipo: str, decorrenza: date, inizio: date, scadenza: date | None,
                        riga_piu_recente: bool) -> ListinoPlan:
    """Non si applica se il prezzo di partenza è già stato sostituito (conta l'ultimo
    caricamento) o è scaduto prima della decorrenza. Altrimenti la riga vecchia finisce
    il giorno prima (mai prima del suo inizio) e la nuova eredita la scadenza della vecchia."""
    if riga_piu_recente or (scadenza is not None and scadenza < decorrenza):
        return ListinoPlan(applicabile=False)
    chiudi_al = previous_price_end(inizio, decorrenza)
    if scadenza is not None:
        chiudi_al = min(chiudi_al, scadenza)
    if tipo == TIPO_NON_TRATTATO:
        return ListinoPlan(applicabile=True, chiudi_al=chiudi_al)
    return ListinoPlan(applicabile=True, chiudi_al=chiudi_al, nuova_dal=decorrenza, nuova_al=scadenza)


async def _newer_row_exists(db: AsyncSession, origin: ListinoMaster) -> bool:
    return bool(await db.scalar(select(ListinoMaster.id).where(
        ListinoMaster.fornitore_id == origin.fornitore_id,
        ListinoMaster.sku_interno == origin.sku_interno,
        ListinoMaster.supplier_product_alias_id.is_not_distinct_from(origin.supplier_product_alias_id),
        ListinoMaster.id > origin.id,
    ).limit(1)))


def _copy_row(origin: ListinoMaster, change: SupplierPriceChange, plan: ListinoPlan) -> ListinoMaster:
    row = ListinoMaster(
        fornitore_id=origin.fornitore_id, sku_interno=origin.sku_interno, descrizione=origin.descrizione,
        prezzo_pattuito=Decimal(str(change.prezzo_nuovo)), unita_misura=origin.unita_misura or change.unita_misura,
        data_inizio_validita=plan.nuova_dal, data_scadenza=plan.nuova_al,
        pfa_tipo=origin.pfa_tipo, pfa_valore=origin.pfa_valore,
        supplier_product_alias_id=origin.supplier_product_alias_id, origine=ORIGINE_LISTINO_APERTO,
    )
    row.pfa_scaglioni = [PFAScaglione(soglia_da=s.soglia_da, soglia_a=s.soglia_a,
                                      valore_percentuale=s.valore_percentuale) for s in origin.pfa_scaglioni]
    row.uom_conversioni = [UoMConversione(uom_fattura=c.uom_fattura, coefficiente=c.coefficiente)
                           for c in origin.uom_conversioni]
    return row


async def recheck_invoices(db: AsyncSession, *, fornitore_id: int, sku_interno: str, dal: date) -> dict:
    """Ricalcola le anomalie delle righe di fattura (TD01) del prodotto dalla data indicata.

    Stessa logica della riassociazione: listino valido alla data del documento,
    prezzo convertito nell'unità del listino solo se la conversione è affidabile;
    le anomalie già lavorate (contestate, in reclamo...) non si toccano.
    """
    from app.models.fatture import Fattura, RigaFattura, TipoDocumento
    from app.models.products import Product, SupplierProductAlias
    from app.services.anomaly_policy import refresh_line_anomaly
    from app.services.matching import _get_listino_attivo, invoice_delta_total, normalize_price_for_comparison
    from app.services.purchase_lines import AliasIndex

    result = {"righe": 0, "anomalie_nuove": 0}
    rows = (await db.execute(
        select(RigaFattura, Fattura)
        .join(Fattura, Fattura.id == RigaFattura.fattura_id)
        .options(noload("*"))
        .where(
            Fattura.fornitore_id == fornitore_id,
            Fattura.tipo_documento == TipoDocumento.TD01,
            Fattura.data_documento >= dal,
            RigaFattura.sku_interno == sku_interno,
        )
    )).all()
    if not rows:
        return result
    product = await db.scalar(select(Product).options(noload("*")).where(Product.sku_interno == sku_interno))
    if product is None:
        return result
    aliases = AliasIndex((await db.scalars(
        select(SupplierProductAlias).options(noload("*")).where(SupplierProductAlias.supplier_id == fornitore_id)
    )).all())
    for riga, fattura in rows:
        alias = aliases.resolve(fornitore_id, product.id, riga.codice_fornitore_raw, riga.descrizione_fornitore_raw)
        listino = await _get_listino_attivo(db, fornitore_id, sku_interno, fattura.data_documento,
                                            supplier_alias_id=getattr(alias, "id", None))
        if listino is None:
            continue
        normalized = normalize_price_for_comparison(riga, product, alias=alias,
                                                    target_comparison_unit=listino.unita_misura)
        if not normalized.reliable:
            continue
        compared = normalized.normalized_unit_price
        delta = compared - Decimal(str(listino.prezzo_pattuito))
        result["righe"] += 1
        if await refresh_line_anomaly(
            db, riga_fattura_id=riga.id, xml_raw_id=fattura.xml_raw_id, listino_price=listino.prezzo_pattuito,
            compared_price=compared, delta_unit=delta,
            delta_total=invoice_delta_total(delta, riga.quantita, normalized),
            reason="listino_aperto", below_threshold_reason="listino_aperto",
        ):
            result["anomalie_nuove"] += 1
    return result


async def _apply_one(db: AsyncSession, change_id: int, today: date, now: datetime, summary: dict) -> None:
    change = await db.get(SupplierPriceChange, change_id)
    if change is None:
        return
    await db.execute(select(func.pg_advisory_xact_lock(offer_lock_key(change.fornitore_id, change.chiave_offerta))))
    # Dopo il lock: il fornitore può averla appena sostituita dalla sua pagina.
    await db.refresh(change, with_for_update=True)
    if change.stato != STATO_PROGRAMMATO or change.decorrenza > today:
        return
    origin = await db.scalar(
        select(ListinoMaster)
        .options(noload("*"), selectinload(ListinoMaster.pfa_scaglioni), selectinload(ListinoMaster.uom_conversioni))
        .where(ListinoMaster.id == change.listino_id_origine, ListinoMaster.fornitore_id == change.fornitore_id)
        .with_for_update(of=ListinoMaster)
    )
    plan = ListinoPlan(applicabile=False) if origin is None else plan_listino_update(
        tipo=change.tipo, decorrenza=change.decorrenza, inizio=origin.data_inizio_validita,
        scadenza=origin.data_scadenza, riga_piu_recente=await _newer_row_exists(db, origin),
    )
    if not plan.applicabile:
        change.stato = STATO_SOSTITUITO
        change.motivo_trattenuta = MOTIVO_LISTINO_CAMBIATO
        change.decisione_at = now
        summary["superate"] += 1
        return
    origin.data_scadenza = plan.chiudi_al
    new_row = None
    if plan.nuova_dal is not None:
        new_row = _copy_row(origin, change, plan)
        db.add(new_row)
    await db.flush()
    change.stato = STATO_APPLICATO
    change.applicato_at = now
    change.applicato_listino_id = new_row.id if new_row is not None else origin.id
    summary["chiusi" if new_row is None else "applicate"] += 1
    checked = await recheck_invoices(db, fornitore_id=change.fornitore_id, sku_interno=change.sku_interno,
                                     dal=change.decorrenza)
    summary["righe_ricontrollate"] += checked["righe"]
    summary["anomalie_nuove"] += checked["anomalie_nuove"]


async def apply_due_price_changes(db: AsyncSession, *, today: date | None = None,
                                  now: datetime | None = None) -> dict:
    """Applica le modifiche programmate con decorrenza fino a oggi (ora di Roma)."""
    today = today or today_rome()
    now = now or datetime.now(timezone.utc)
    summary = {"applicate": 0, "chiusi": 0, "superate": 0, "righe_ricontrollate": 0, "anomalie_nuove": 0}
    if not await db.scalar(select(func.pg_try_advisory_xact_lock(LOCK_KEY))):
        return {**summary, "saltato": True}
    # Solo gli id, senza lock: il lock per offerta si prende prima della riga
    # (stesso ordine della pagina del fornitore, niente stallo).
    ids = (await db.scalars(
        select(SupplierPriceChange.id)
        .where(SupplierPriceChange.stato == STATO_PROGRAMMATO, SupplierPriceChange.decorrenza <= today)
        .order_by(SupplierPriceChange.decorrenza, SupplierPriceChange.id)
        .limit(MAX_PER_RUN)
    )).all()
    for change_id in ids:
        await _apply_one(db, change_id, today, now, summary)
    if ids:
        logger.info("listino_aperto_applicato %s", summary)
    return summary
