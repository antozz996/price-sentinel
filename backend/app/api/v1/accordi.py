from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.utenti import Utente, RuoloUtente
from app.models.listino import ListinoMaster, PFATipo, UoMConversione
from app.models.fornitori import Fornitore
from app.models.fatture import RigaFattura, Fattura
from app.models.alias import AliasProdotto
from app.schemas.accordi import AccordoCommercialeResponse, PFAScaglioneInfo

router = APIRouter()

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

    # 1. Fetch active ListinoMaster items that have pfa_tipo set
    query = select(ListinoMaster).join(Fornitore).where(
        and_(
            ListinoMaster.pfa_tipo.is_not(None),
            ListinoMaster.data_scadenza.is_(None)
        )
    ).options(
        selectinload(ListinoMaster.fornitore),
        selectinload(ListinoMaster.pfa_scaglioni)
    )

    if fornitore_id:
        query = query.where(ListinoMaster.fornitore_id == fornitore_id)

    res = await db.execute(query)
    agreements = res.scalars().all()

    if not agreements:
        return []

    sku_list = [ag.sku_interno for ag in agreements]

    # Fetch all alias records for these SKUs to support historical/unmatched links
    alias_query = select(AliasProdotto).where(AliasProdotto.sku_interno.in_(sku_list))
    alias_res = await db.execute(alias_query)
    aliases = alias_res.scalars().all()

    alias_by_sku = {}
    alias_by_raw_code = {}
    for al in aliases:
        alias_by_sku[(al.fornitore_id, al.sku_interno)] = al
        alias_by_raw_code[(al.fornitore_id, al.codice_fornitore_originale.strip().lower())] = al

    # Fetch all UoM conversion rules for these agreements
    uom_query = select(UoMConversione).where(UoMConversione.listino_id.in_([ag.id for ag in agreements]))
    uom_res = await db.execute(uom_query)
    uom_convs = uom_res.scalars().all()
    uom_conv_by_listino = {}
    for uc in uom_convs:
        uom_conv_by_listino.setdefault(uc.listino_id, []).append(uc)

    # Fetch invoice lines matching our agreements
    rf_query = select(RigaFattura).join(Fattura).where(
        (RigaFattura.sku_interno.in_(sku_list)) |
        (
            and_(
                RigaFattura.sku_interno.is_(None),
                RigaFattura.codice_fornitore_raw.in_(
                    [al.codice_fornitore_originale for al in aliases]
                )
            )
        )
    ).options(selectinload(RigaFattura.fattura))

    if location_id:
        rf_query = rf_query.where(Fattura.location_id == location_id)
    if data_da:
        rf_query = rf_query.where(Fattura.data_documento >= data_da)
    if data_a:
        rf_query = rf_query.where(Fattura.data_documento <= data_a)

    rf_res = await db.execute(rf_query)
    invoice_lines = rf_res.scalars().all()

    # Group lines by (fornitore_id, sku_interno)
    lines_by_agreement = {}
    for line in invoice_lines:
        fid = line.fattura.fornitore_id
        sku = line.sku_interno
        if not sku:
            raw_code = line.codice_fornitore_raw.strip().lower() if line.codice_fornitore_raw else ""
            al = alias_by_raw_code.get((fid, raw_code))
            if al:
                sku = al.sku_interno
        
        if sku:
            lines_by_agreement.setdefault((fid, sku), []).append(line)

    results = []
    for ag in agreements:
        key = (ag.fornitore_id, ag.sku_interno)
        matching_lines = lines_by_agreement.get(key, [])

        total_qty = Decimal("0.0")
        total_spent = Decimal("0.0")

        # Sum up quantities (scaled by UoM) and amounts
        for line in matching_lines:
            coef = Decimal("1.0")
            al = alias_by_sku.get(key)
            if not al and line.codice_fornitore_raw:
                raw_code = line.codice_fornitore_raw.strip().lower()
                al = alias_by_raw_code.get((ag.fornitore_id, raw_code))

            if al and al.coefficiente_conversione and al.coefficiente_conversione != 0:
                coef = Decimal(str(al.coefficiente_conversione))
            else:
                conversions = uom_conv_by_listino.get(ag.id, [])
                if line.unita_misura_fattura and ag.unita_misura and line.unita_misura_fattura.lower() != ag.unita_misura.lower():
                    for uc in conversions:
                        if uc.uom_fattura.lower() == line.unita_misura_fattura.lower():
                            coef = Decimal(str(uc.coefficiente))
                            break

            qty = Decimal(str(line.quantita))
            val = Decimal(str(line.prezzo_netto_normalizzato)) * qty
            scaled_qty = qty * coef

            # TD04 represents Credit Notes, subtract them
            if line.fattura.tipo_documento.value == "TD04":
                total_qty -= scaled_qty
                total_spent -= val
            else:
                total_qty += scaled_qty
                total_spent += val

        # Calculate rebate based on agreement type
        total_reconciled_rebate = Decimal("0.0")
        if ag.pfa_tipo == PFATipo.fisso and ag.pfa_valore:
            total_reconciled_rebate = total_qty * Decimal(str(ag.pfa_valore))
        elif ag.pfa_tipo == PFATipo.percentuale and ag.pfa_valore:
            total_reconciled_rebate = total_spent * Decimal(str(ag.pfa_valore))
        elif ag.pfa_tipo == PFATipo.scaglioni:
            # Determine active percentage based on cumulative spent
            active_pct = Decimal("0.0")
            for sc in ag.pfa_scaglioni:
                soglia_da = Decimal(str(sc.soglia_da))
                soglia_a = Decimal(str(sc.soglia_a)) if sc.soglia_a is not None else None
                if total_spent >= soglia_da:
                    if soglia_a is None or total_spent < soglia_a:
                        active_pct = Decimal(str(sc.valore_percentuale))
                        break
            
            # Fallback to highest threshold met if not matching intermediate ranges
            if active_pct == Decimal("0.0") and ag.pfa_scaglioni:
                matching_scs = [sc for sc in ag.pfa_scaglioni if total_spent >= Decimal(str(sc.soglia_da))]
                if matching_scs:
                    matching_scs.sort(key=lambda x: x.soglia_da, reverse=True)
                    active_pct = Decimal(str(matching_scs[0].valore_percentuale))
            
            total_reconciled_rebate = total_spent * active_pct

        if total_reconciled_rebate < 0:
            total_reconciled_rebate = Decimal("0.0")

        # Compute contract net price after rebate
        netto_rientro_contratto = None
        if ag.pfa_tipo == PFATipo.fisso and ag.pfa_valore:
            netto_rientro_contratto = ag.prezzo_pattuito - ag.pfa_valore
        elif ag.pfa_tipo == PFATipo.percentuale and ag.pfa_valore:
            netto_rientro_contratto = ag.prezzo_pattuito * (Decimal("1.0") - ag.pfa_valore)
        elif ag.pfa_tipo == PFATipo.scaglioni and ag.pfa_scaglioni:
            active_pct = Decimal("0.0")
            for sc in ag.pfa_scaglioni:
                soglia_da = Decimal(str(sc.soglia_da))
                soglia_a = Decimal(str(sc.soglia_a)) if sc.soglia_a is not None else None
                if total_spent >= soglia_da:
                    if soglia_a is None or total_spent < soglia_a:
                        active_pct = Decimal(str(sc.valore_percentuale))
                        break
            if active_pct == Decimal("0.0") and ag.pfa_scaglioni:
                matching_scs = [sc for sc in ag.pfa_scaglioni if total_spent >= Decimal(str(sc.soglia_da))]
                if matching_scs:
                    matching_scs.sort(key=lambda x: x.soglia_da, reverse=True)
                    active_pct = Decimal(str(matching_scs[0].valore_percentuale))
            netto_rientro_contratto = ag.prezzo_pattuito * (Decimal("1.0") - active_pct)

        # Average actual net unit price
        netto_rientro_medio = Decimal("0.0")
        if total_qty > 0:
            netto_rientro_medio = ((total_spent - total_reconciled_rebate) / total_qty).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

        results.append(
            AccordoCommercialeResponse(
                listino_id=ag.id,
                sku_interno=ag.sku_interno,
                descrizione=ag.descrizione,
                fornitore_id=ag.fornitore_id,
                fornitore_nome=ag.fornitore.nome_azienda,
                unita_misura=ag.unita_misura,
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
                netto_rientro_contratto=netto_rientro_contratto,
                quantita_acquistata=total_qty,
                totale_fatturato=total_spent,
                rientro_accumulato=total_reconciled_rebate,
                netto_rientro_medio=netto_rientro_medio
            )
        )

    return results
