"""
Price Sentinel — Router Ordini.
Integrazione Intelligenza di Acquisto e Ottimizzazione Ordini (Regole A, B, C).
Modulo Sviluppo Ordini per Responsabili di Settore con invio WhatsApp.
"""

import urllib.parse
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_admin, get_current_user
from app.models.listino import ListinoMaster
from app.models.fatture import RigaFattura, Fattura
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.ordini import Ordine, RigaOrdine
from app.models.products import Product, SupplierProductAlias
from app.models.purchase_policy import ProductPurchasePolicy
from app.models.utenti import Utente

router = APIRouter()


# ── Schemas per Settore & WhatsApp ───────────────────

class SectorOrderItem(BaseModel):
    product_id: int
    sku_interno: Optional[str] = None
    canonical_name: str
    order_name: Optional[str] = None
    quantita: float = Field(..., gt=0)
    comparison_unit: Optional[str] = "piece"
    category: Optional[str] = None
    preferred_supplier_id: Optional[int] = None
    prezzo_unitario: Optional[float] = None


class SectorOrderDraftRequest(BaseModel):
    location_id: int
    settore: Optional[str] = None  # Beverage, Food, Materiali di consumo, etc.
    data_consegna: Optional[str] = None
    note: Optional[str] = None
    items: List[SectorOrderItem] = Field(..., min_items=1)


class SupplierOrderItemDetail(BaseModel):
    product_id: int
    sku_interno: Optional[str] = None
    nome_prodotto: str
    codice_fornitore: Optional[str] = None
    quantita: float
    uom: str
    prezzo_unitario: float
    subtotale: float
    is_concordato: bool


class SupplierOrderBundle(BaseModel):
    fornitore_id: int
    fornitore_nome: str
    partita_iva: Optional[str] = None
    email_contatto: Optional[str] = None
    telefono_contatto: Optional[str] = None
    totale_ordine: float
    numero_articoli: int
    totale_colli: float
    items: List[SupplierOrderItemDetail]
    whatsapp_message: str
    whatsapp_url: str


class SectorOrderDraftResponse(BaseModel):
    location_id: int
    location_nome: str
    location_indirizzo: Optional[str] = None
    settore: Optional[str] = None
    data_consegna: Optional[str] = None
    note: Optional[str] = None
    totale_complessivo: float
    totale_fornitori_coinvolti: int
    totale_articoli: int
    fornitori_ordini: List[SupplierOrderBundle]


class RigaRicezioneItem(BaseModel):
    riga_id: int
    quantita_ricevuta: float = Field(..., ge=0)
    stato_riga: str = Field("conforme", pattern="^(conforme|parziale|mancante|danneggiato)$")
    note_riga: Optional[str] = None


class RicezioneOrdineRequest(BaseModel):
    stato_ricezione: str = Field("ricevuto_conforme", pattern="^(ricevuto_conforme|ricevuto_parziale|ricevuto_con_riserva)$")
    note_ricezione: Optional[str] = None
    righe: List[RigaRicezioneItem]


class ConfirmSectorOrderRequest(BaseModel):
    location_id: int
    settore: Optional[str] = None
    data_consegna: Optional[str] = None
    note: Optional[str] = None
    bundles: List[SupplierOrderBundle]


# ── Schemas ──────────────────────────────────────────

class ItemOrdineInput(BaseModel):
    sku_interno: str = Field(..., description="SKU interno normalizzato")
    quantita: float = Field(..., gt=0, description="Quantità da ordinare")
    prezzo_inserito: Optional[float] = Field(None, description="Prezzo di acquisto manuale inserito dal buyer")


class ConfrontoPrezzoItem(BaseModel):
    fornitore_id: int
    fornitore_nome: str
    prezzo: float


class RigaOttimizzataResponse(BaseModel):
    sku_interno: str
    descrizione: str
    quantita: float
    prezzo_inserito: float
    prezzo_ottimale: float
    tipo_regola: str  # concordato, spot_ottimale, sconosciuto
    fornitore_id: int
    fornitore_nome: str
    is_anomalia: bool
    dettaglio_anomalia: Optional[str] = None
    confronto_prezzi: List[ConfrontoPrezzoItem] = []


class SintesiOttimizzazione(BaseModel):
    spesa_totale_blindata: float
    risparmio_preventivo_stimato: float
    numero_anomalie: int
    avvisi_preventivi: List[str]


class OttimizzaOrdineResponse(BaseModel):
    righe_ottimizzate: List[RigaOttimizzataResponse]
    sintesi: SintesiOttimizzazione


class CreaOrdineInput(BaseModel):
    location_id: int = Field(..., description="ID location che emette l'ordine")
    items: List[ItemOrdineInput] = Field(..., min_items=1)


# ── Endpoints ────────────────────────────────────────

def extract_sku(sku_input: str) -> str:
    """
    Estrae lo SKU effettivo da una stringa nel formato 'Nome Prodotto (SKU)'.
    Se non sono presenti parentesi tonde, restituisce la stringa originale.
    """
    if sku_input and ")" in sku_input and "(" in sku_input:
        return sku_input.split("(")[-1].replace(")", "").strip()
    return sku_input


@router.post(
    "/ottimizza",
    response_model=OttimizzaOrdineResponse,
    summary="Ottimizzazione preventiva prezzi e routing fornitori (Regole A, B, C)",
)
async def ottimizza_ordine(
    items: List[ItemOrdineInput],
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
) -> OttimizzaOrdineResponse:
    """
    Analizza un carrello d'acquisto preventivo:
    - Regola A: Prodotti concordati bloccati sul listino master
    - Regola B: Prodotti spot confrontati sulle fatture storiche per consigliare il prezzo minimo
    - Regola C: Calcolo del risparmio preventivo ed emissione di alert di anomalia precoce
    """
    righe_ottimizzate: List[RigaOttimizzataResponse] = []
    avvisi_preventivi: List[str] = []
    spesa_totale_blindata = 0.0
    risparmio_preventivo_stimato = 0.0
    numero_anomalie = 0

    for item in items:
        # Estraiamo lo SKU pulito normalizzato
        clean_sku = extract_sku(item.sku_interno)

        # 1. Recupero anagrafica o descrizione base del prodotto dagli alias o listino
        # Cerca descrizione nel listino master
        listino_stmt = select(ListinoMaster).where(ListinoMaster.sku_interno == clean_sku).limit(1)
        listino_res = await db.execute(listino_stmt)
        listino_item = listino_res.scalar_one_or_none()
        descrizione = listino_item.descrizione if listino_item else f"Prodotto {clean_sku}"

        # 2. REGOLA A: Verifica se c'è un contratto a prezzo fisso attivo (data_scadenza IS NULL)
        contract_stmt = select(ListinoMaster).where(
            and_(
                ListinoMaster.sku_interno == clean_sku,
                ListinoMaster.data_scadenza.is_(None)
            )
        ).limit(1)
        contract_res = await db.execute(contract_stmt)
        active_contract = contract_res.scalar_one_or_none()

        if active_contract:
            # Recupera dettagli fornitore
            fornitore_stmt = select(Fornitore).where(Fornitore.id == active_contract.fornitore_id)
            fornitore_res = await db.execute(fornitore_stmt)
            fornitore = fornitore_res.scalar_one()

            prezzo_ottimale = float(active_contract.prezzo_pattuito)
            prezzo_inserito = item.prezzo_inserito if item.prezzo_inserito is not None else prezzo_ottimale
            is_anomalia = prezzo_inserito != prezzo_ottimale
            
            dettaglio_anomalia = None
            if is_anomalia:
                numero_anomalie += 1
                dettaglio_anomalia = (
                    f"Prezzo inserito (€ {prezzo_inserito:.2f}) differisce "
                    f"dal prezzo blindato a contratto (€ {prezzo_ottimale:.2f})"
                )
                avvisi_preventivi.append(f"Anomalia {clean_sku}: {dettaglio_anomalia}")

            spesa_totale_blindata += prezzo_inserito * item.quantita

            righe_ottimizzate.append(
                RigaOttimizzataResponse(
                    sku_interno=clean_sku,
                    descrizione=descrizione,
                    quantita=item.quantita,
                    prezzo_inserito=prezzo_inserito,
                    prezzo_ottimale=prezzo_ottimale,
                    tipo_regola="concordato",
                    fornitore_id=fornitore.id,
                    fornitore_nome=fornitore.nome_azienda,
                    is_anomalia=is_anomalia,
                    dettaglio_anomalia=dettaglio_anomalia,
                    confronto_prezzi=[
                        ConfrontoPrezzoItem(
                            fornitore_id=fornitore.id,
                            fornitore_nome=fornitore.nome_azienda,
                            prezzo=prezzo_ottimale
                        )
                    ]
                )
            )

        # 3. REGOLA B: Prodotto fuori listino, compariamo i listini spot dei fornitori dalle fatture passate
        else:
            # Query per i prezzi storici di questo SKU raggruppati per fornitore
            # Utilizza le righe di fattura registrate
            spot_stmt = (
                select(
                    Fornitore.id,
                    Fornitore.nome_azienda,
                    func.min(RigaFattura.prezzo_unitario).label("prezzo_min")
                )
                .join(Fattura, RigaFattura.fattura_id == Fattura.id)
                .join(Fornitore, Fattura.fornitore_id == Fornitore.id)
                .where(RigaFattura.sku_interno == clean_sku)
                .group_by(Fornitore.id, Fornitore.nome_azienda)
                .order_by("prezzo_min")
            )
            spot_res = await db.execute(spot_stmt)
            spot_options = spot_res.all()

            if spot_options:
                best_option = spot_options[0]  # Il più economico grazie all'ordinamento
                prezzo_ottimale = float(best_option.prezzo_min)
                prezzo_inserito = item.prezzo_inserito if item.prezzo_inserito is not None else prezzo_ottimale
                
                # Se l'utente inserisce un prezzo superiore al prezzo spot migliore consigliato
                is_anomalia = prezzo_inserito > prezzo_ottimale
                dettaglio_anomalia = None
                if is_anomalia:
                    numero_anomalie += 1
                    dettaglio_anomalia = (
                        f"Prezzo inserito (€ {prezzo_inserito:.2f}) superiore "
                        f"al miglior prezzo spot disponibile (€ {prezzo_ottimale:.2f})"
                    )
                    avvisi_preventivi.append(f"Avviso Spot {clean_sku}: {dettaglio_anomalia}")

                # Calcola il risparmio teorico rispetto all'opzione più costosa
                max_price = float(max(o.prezzo_min for o in spot_options))
                risparmio = (max_price - prezzo_ottimale) * item.quantita
                if risparmio > 0:
                    risparmio_preventivo_stimato += risparmio

                confronto = [
                    ConfrontoPrezzoItem(
                        fornitore_id=opt.id,
                        fornitore_nome=opt.nome_azienda,
                        prezzo=float(opt.prezzo_min)
                    )
                    for opt in spot_options
                ]

                righe_ottimizzate.append(
                    RigaOttimizzataResponse(
                        sku_interno=clean_sku,
                        descrizione=descrizione,
                        quantita=item.quantita,
                        prezzo_inserito=prezzo_inserito,
                        prezzo_ottimale=prezzo_ottimale,
                        tipo_regola="spot_ottimale",
                        fornitore_id=best_option.id,
                        fornitore_nome=best_option.nome_azienda,
                        is_anomalia=is_anomalia,
                        dettaglio_anomalia=dettaglio_anomalia,
                        confronto_prezzi=confronto
                    )
                )
            else:
                # Prodotto sconosciuto (nessun acquisto o contratto storico)
                prezzo_inserito = item.prezzo_inserito if item.prezzo_inserito is not None else 0.0
                righe_ottimizzate.append(
                    RigaOttimizzataResponse(
                        sku_interno=clean_sku,
                        descrizione=descrizione,
                        quantita=item.quantita,
                        prezzo_inserito=prezzo_inserito,
                        prezzo_ottimale=prezzo_inserito,
                        tipo_regola="sconosciuto",
                        fornitore_id=1,  # Default fallback
                        fornitore_nome="Fornitore Generico",
                        is_anomalia=False,
                        confronto_prezzi=[]
                    )
                )

    sintesi = SintesiOttimizzazione(
        spesa_totale_blindata=round(spesa_totale_blindata, 2),
        risparmio_preventivo_stimato=round(risparmio_preventivo_stimato, 2),
        numero_anomalie=numero_anomalie,
        avvisi_preventivi=avvisi_preventivi
    )

    return OttimizzaOrdineResponse(righe_ottimizzate=righe_ottimizzate, sintesi=sintesi)


@router.post(
    "/crea",
    response_model=List[int],
    summary="Salva ed emette l'ordine d'acquisto suddiviso per fornitore",
)
async def crea_ordine(
    data: CreaOrdineInput,
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
) -> List[int]:
    """
    Esegue l'ottimizzazione e suddivide gli articoli del carrello,
    generando e salvando a database un documento d'ordine per ciascun fornitore coinvolto.
    """
    # 1. Chiama internamente l'ottimizzatore
    ottimizzazione = await ottimizza_ordine(items=data.items, db=db, _admin=_admin)
    
    # Raggruppa le righe per fornitore
    fornitore_groups: Dict[int, List[RigaOttimizzataResponse]] = {}
    for riga in ottimizzazione.righe_ottimizzate:
        if riga.fornitore_id not in fornitore_groups:
            fornitore_groups[riga.fornitore_id] = []
        fornitore_groups[riga.fornitore_id].append(riga)

    generated_ids: List[int] = []

    # 2. Crea un ordine per ciascun fornitore
    for fornitore_id, righe in fornitore_groups.items():
        totale = sum(r.prezzo_inserito * r.quantita for r in righe)
        
        ordine = Ordine(
            fornitore_id=fornitore_id,
            location_id=data.location_id,
            data_ordine=datetime.utcnow(),
            spesa_totale=totale,
            stato="inviato"
        )
        db.add(ordine)
        await db.flush()  # Ottiene l'ID dell'ordine

        for r in righe:
            riga_db = RigaOrdine(
                ordine_id=ordine.id,
                sku_interno=r.sku_interno,
                descrizione=r.descrizione,
                quantita=r.quantita,
                prezzo_pattuito=r.prezzo_ottimale,
                prezzo_inserito=r.prezzo_inserito,
                stato_ottimizzazione=r.tipo_regola if not r.is_anomalia else "anomalo"
            )
            db.add(riga_db)

        generated_ids.append(ordine.id)

    await db.commit()
    return generated_ids


def _format_whatsapp_text(
    supplier_name: str,
    location_name: str,
    location_address: Optional[str],
    delivery_date: Optional[str],
    sector: Optional[str],
    order_notes: Optional[str],
    items: List[SupplierOrderItemDetail],
    total_amount: float,
) -> str:
    lines = [
        f"📦 *ORDINE D'ACQUISTO — {supplier_name.upper()}*",
        "",
        f"📍 *Destinazione:* {location_name}" + (f" ({location_address})" if location_address else ""),
        f"📅 *Consegna richiesta:* {delivery_date or 'Prima possibile'}",
    ]
    if sector:
        lines.append(f"🏷️ *Settore / Reparto:* {sector}")
    
    lines.append("")
    lines.append("*ARTICOLI RICHIESTI:*")
    for it in items:
        qty = it.quantita
        qty_str = f"{int(qty)}" if qty == int(qty) else f"{qty:.2f}"
        name = it.nome_prodotto
        uom = it.uom or "pz"
        code_str = f" [Cod. {it.codice_fornitore}]" if it.codice_fornitore else ""
        lines.append(f"• *{qty_str} {uom}* × {name}{code_str}")
    
    lines.append("")
    lines.append(f"💰 *Totale stimato:* € {total_amount:.2f} + IVA")
    if order_notes and order_notes.strip():
        lines.append(f"📝 *Note:* {order_notes.strip()}")
    
    lines.append("")
    lines.append("Si prega di confermare la ricezione e la presa in carico. Grazie!")
    return "\n".join(lines)


@router.post(
    "/settore/elabora",
    response_model=SectorOrderDraftResponse,
    summary="Elabora il fabbisogno di settore, raggruppa per fornitore e genera i testi WhatsApp",
)
async def elabora_ordine_settore(
    data: SectorOrderDraftRequest,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
) -> SectorOrderDraftResponse:
    # 1. Recupera la location
    loc = await db.get(Location, data.location_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location selezionata non trovata")
    
    # 2. Recupera tutti i fornitori per lookup
    fornitori_db = (await db.scalars(select(Fornitore))).all()
    fornitori_map = {f.id: f for f in fornitori_db}

    # 3. Raggruppamento per fornitore
    supplier_items_map: Dict[int, List[SupplierOrderItemDetail]] = {}
    
    today = date.today()
    for it in data.items:
        product = await db.get(Product, it.product_id)
        if not product:
            continue
        
        # 1. Cerca forzatura/policy di acquisto attiva per questo prodotto (per sede o globale)
        policy_stmt = (
            select(ProductPurchasePolicy)
            .where(
                ProductPurchasePolicy.product_id == product.id,
                ProductPurchasePolicy.is_active.is_(True),
                ProductPurchasePolicy.valid_from <= today,
                or_(ProductPurchasePolicy.valid_to.is_(None), ProductPurchasePolicy.valid_to >= today),
                or_(ProductPurchasePolicy.location_id == data.location_id, ProductPurchasePolicy.location_id.is_(None))
            )
            .order_by(
                case((ProductPurchasePolicy.location_id.is_not(None), 0), else_=1),
                ProductPurchasePolicy.id.desc()
            )
        )
        policy = (await db.scalars(policy_stmt)).first()

        chosen_supplier_id = None
        if policy and policy.preferred_supplier_id:
            chosen_supplier_id = policy.preferred_supplier_id
        elif it.preferred_supplier_id:
            chosen_supplier_id = it.preferred_supplier_id

        unit_price = it.prezzo_unitario
        uom = it.comparison_unit or product.comparison_unit or "CT"
        if uom.lower() == "piece":
            uom = "pz"
        is_concordato = False
        supplier_code = None

        if chosen_supplier_id:
            # Query listino_master per il fornitore forzato/preferito
            if product.sku_interno:
                listino_query = select(ListinoMaster).where(
                    ListinoMaster.sku_interno == product.sku_interno,
                    ListinoMaster.fornitore_id == chosen_supplier_id,
                    ListinoMaster.data_inizio_validita <= today,
                    or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= today)
                ).order_by(ListinoMaster.prezzo_pattuito.asc())
                sup_listino = (await db.execute(listino_query)).scalars().first()
                if sup_listino:
                    unit_price = float(sup_listino.prezzo_pattuito)
                    if not it.comparison_unit and sup_listino.unita_misura:
                        uom = sup_listino.unita_misura
                    is_concordato = True
        else:
            # Nessuna forzatura: cerca il fornitore con miglior prezzo attivo
            if product.sku_interno:
                listino_query = select(ListinoMaster).where(
                    ListinoMaster.sku_interno == product.sku_interno,
                    ListinoMaster.data_inizio_validita <= today,
                    or_(ListinoMaster.data_scadenza.is_(None), ListinoMaster.data_scadenza >= today)
                ).order_by(ListinoMaster.prezzo_pattuito.asc())
                best_listino = (await db.execute(listino_query)).scalars().first()
                if best_listino:
                    chosen_supplier_id = best_listino.fornitore_id
                    unit_price = float(best_listino.prezzo_pattuito)
                    if not it.comparison_unit and best_listino.unita_misura:
                        uom = best_listino.unita_misura
                    is_concordato = True

        # Fallback se ancora nullo
        if not chosen_supplier_id:
            chosen_supplier_id = fornitori_db[0].id if fornitori_db else 1
        if unit_price is None:
            unit_price = 0.0

        # Cerca codice articolo fornitore tramite alias
        if product.id:
            alias = (await db.scalars(
                select(SupplierProductAlias).where(
                    SupplierProductAlias.product_id == product.id,
                    SupplierProductAlias.supplier_id == chosen_supplier_id,
                    SupplierProductAlias.status == "approved"
                )
            )).first()
            if alias:
                supplier_code = alias.supplier_code

        display_name = it.order_name or product.order_name or it.canonical_name or product.canonical_name
        subtotal = round(unit_price * it.quantita, 2)

        item_detail = SupplierOrderItemDetail(
            product_id=product.id,
            sku_interno=product.sku_interno,
            nome_prodotto=display_name,
            codice_fornitore=supplier_code,
            quantita=it.quantita,
            uom=uom,
            prezzo_unitario=unit_price,
            subtotale=subtotal,
            is_concordato=is_concordato,
        )

        if chosen_supplier_id not in supplier_items_map:
            supplier_items_map[chosen_supplier_id] = []
        supplier_items_map[chosen_supplier_id].append(item_detail)

    # 4. Costruisci i bundles fornitore con messaggi WhatsApp
    bundles: List[SupplierOrderBundle] = []
    totale_complessivo = 0.0
    totale_articoli = 0

    for sup_id, items in supplier_items_map.items():
        sup = fornitori_map.get(sup_id)
        sup_name = sup.nome_azienda if sup else f"Fornitore #{sup_id}"
        totale_bundle = round(sum(i.subtotale for i in items), 2)
        totale_colli = sum(i.quantita for i in items)
        totale_complessivo += totale_bundle
        totale_articoli += len(items)

        loc_addr = getattr(loc, "indirizzo", None) or getattr(loc, "citta", None)

        wa_msg = _format_whatsapp_text(
            supplier_name=sup_name,
            location_name=loc.nome_struttura,
            location_address=loc_addr,
            delivery_date=data.data_consegna,
            sector=data.settore,
            order_notes=data.note,
            items=items,
            total_amount=totale_bundle,
        )

        clean_phone = None
        if sup and getattr(sup, "telefono_contatto", None):
            raw_phone = str(sup.telefono_contatto).strip()
            digits = "".join(ch for ch in raw_phone if ch.isdigit() or ch == "+")
            if digits:
                if digits.startswith("+"):
                    clean_phone = digits[1:]
                elif digits.startswith("00"):
                    clean_phone = digits[2:]
                elif len(digits) == 10 and not digits.startswith("39"):
                    clean_phone = "39" + digits
                else:
                    clean_phone = digits

        wa_encoded = urllib.parse.quote(wa_msg)
        if clean_phone:
            wa_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={wa_encoded}"
        else:
            wa_url = f"https://api.whatsapp.com/send?text={wa_encoded}"

        bundles.append(
            SupplierOrderBundle(
                fornitore_id=sup_id,
                fornitore_nome=sup_name,
                partita_iva=sup.partita_iva if sup else None,
                email_contatto=sup.email_contatto if sup else None,
                telefono_contatto=sup.telefono_contatto if sup else None,
                totale_ordine=totale_bundle,
                numero_articoli=len(items),
                totale_colli=totale_colli,
                items=items,
                whatsapp_message=wa_msg,
                whatsapp_url=wa_url,
            )
        )

    bundles.sort(key=lambda b: b.fornitore_nome)

    return SectorOrderDraftResponse(
        location_id=loc.id,
        location_nome=loc.nome_struttura,
        location_indirizzo=getattr(loc, "indirizzo", None),
        settore=data.settore,
        data_consegna=data.data_consegna,
        note=data.note,
        totale_complessivo=round(totale_complessivo, 2),
        totale_fornitori_coinvolti=len(bundles),
        totale_articoli=totale_articoli,
        fornitori_ordini=bundles,
    )


@router.post(
    "/settore/salva",
    summary="Salva definitivamente gli ordini di settore nel gestionale",
)
async def salva_ordini_settore(
    data: ConfirmSectorOrderRequest,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
):
    saved_ids = []
    now = datetime.utcnow()

    for bundle in data.bundles:
        ordine = Ordine(
            fornitore_id=bundle.fornitore_id,
            location_id=data.location_id,
            user_id=_user.id,
            settore=data.settore,
            data_consegna=data.data_consegna,
            note=data.note,
            whatsapp_message=bundle.whatsapp_message,
            data_ordine=now,
            spesa_totale=bundle.totale_ordine,
            stato="inviato",
        )
        db.add(ordine)
        await db.flush()

        for it in bundle.items:
            riga = RigaOrdine(
                ordine_id=ordine.id,
                product_id=it.product_id,
                sku_interno=it.sku_interno or f"PROD-{it.product_id}",
                descrizione=it.nome_prodotto,
                quantita=it.quantita,
                uom=it.uom or "CT",
                prezzo_pattuito=it.prezzo_unitario,
                prezzo_inserito=it.prezzo_unitario,
                stato_ottimizzazione="concordato" if it.is_concordato else "settore",
            )
            db.add(riga)

        saved_ids.append(ordine.id)

    await db.commit()
    return {
        "status": "success",
        "ordini_creati": len(saved_ids),
        "ordini_ids": saved_ids,
        "message": f"Salvati {len(saved_ids)} ordini d'acquisto nel gestionale con successo!",
    }


@router.get(
    "/",
    summary="Registro completo di tutti gli ordini generati con filtri e ricerca",
)
async def list_ordini(
    location_id: Optional[int] = Query(None),
    fornitore_id: Optional[int] = Query(None),
    settore: Optional[str] = Query(None),
    stato: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
):
    """Restituisce la lista filtrata e paginata del Registro Ordini."""
    stmt = select(Ordine).order_by(Ordine.id.desc())

    # User Scoping
    if _user.ruolo != "admin" and _user.ruolo_dettagliato != "admin":
        if _user.location_id:
            stmt = stmt.where(Ordine.location_id == _user.location_id)
        if _user.settore_abilitato and _user.settore_abilitato != "all":
            allowed_sectors = [s.strip() for s in _user.settore_abilitato.split(",") if s.strip()]
            if allowed_sectors:
                stmt = stmt.where(Ordine.settore.in_(allowed_sectors))

    # Param Filters
    if location_id:
        stmt = stmt.where(Ordine.location_id == location_id)
    if fornitore_id:
        stmt = stmt.where(Ordine.fornitore_id == fornitore_id)
    if settore and settore != "all":
        stmt = stmt.where(Ordine.settore == settore)
    if stato and stato != "all":
        if stato in ("da_ricevere", "ricevuto_conforme", "ricevuto_parziale", "ricevuto_con_riserva"):
            stmt = stmt.where(Ordine.stato_ricezione == stato)
        else:
            stmt = stmt.where(Ordine.stato == stato)

    res = await db.execute(stmt)
    ordini = res.scalars().all()

    # Search filter
    if search and search.strip():
        q = search.strip().lower()
        ordini = [
            o for o in ordini
            if (q in str(o.id)
                or (o.fornitore and q in o.fornitore.nome_azienda.lower())
                or (o.location and q in o.location.nome_struttura.lower())
                or (o.settore and q in o.settore.lower())
                or (o.user and q in (o.user.nome_completo or o.user.email).lower()))
        ]

    return [
        {
            "id": o.id,
            "fornitore_id": o.fornitore_id,
            "fornitore_nome": o.fornitore.nome_azienda if o.fornitore else f"Fornitore #{o.fornitore_id}",
            "location_id": o.location_id,
            "location_nome": o.location.nome_struttura if o.location else f"Sede #{o.location_id}",
            "user_id": o.user_id,
            "user_nome": o.user.nome_completo if o.user else (o.user.email if o.user else "Operatore"),
            "user_ruolo": o.user.ruolo_dettagliato if o.user else None,
            "settore": o.settore or "Generico",
            "data_ordine": o.data_ordine.isoformat() if o.data_ordine else None,
            "data_consegna": o.data_consegna,
            "note": o.note,
            "whatsapp_message": o.whatsapp_message,
            "spesa_totale": float(o.spesa_totale),
            "stato": o.stato,
            "stato_ricezione": o.stato_ricezione,
            "data_ricezione": o.data_ricezione.isoformat() if o.data_ricezione else None,
            "ricevuto_da_nome": o.ricevuto_da.nome_completo if o.ricevuto_da else None,
            "note_ricezione": o.note_ricezione,
            "n_righe": len(o.righe),
            "totale_colli": sum(float(r.quantita) for r in o.righe),
            "totale_colli_ricevuti": sum(float(r.quantita_ricevuta or 0) for r in o.righe)
        }
        for o in ordini
    ]


@router.get(
    "/{ordine_id}",
    summary="Dettaglio completo di un singolo ordine con righe e stato ricezione",
)
async def get_ordine_detail(
    ordine_id: int,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
):
    ordine = await db.get(Ordine, ordine_id)
    if not ordine:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    # Check permission
    if _user.ruolo != "admin" and _user.ruolo_dettagliato != "admin":
        if _user.location_id and ordine.location_id != _user.location_id:
            raise HTTPException(status_code=403, detail="Accesso non autorizzato all'ordine di questa sede")

    return {
        "id": ordine.id,
        "fornitore_id": ordine.fornitore_id,
        "fornitore_nome": ordine.fornitore.nome_azienda if ordine.fornitore else f"Fornitore #{ordine.fornitore_id}",
        "fornitore_piva": ordine.fornitore.partita_iva if ordine.fornitore else None,
        "fornitore_telefono": ordine.fornitore.telefono_contatto if ordine.fornitore else None,
        "fornitore_email": ordine.fornitore.email_contatto if ordine.fornitore else None,
        "location_id": ordine.location_id,
        "location_nome": ordine.location.nome_struttura if ordine.location else f"Sede #{ordine.location_id}",
        "user_id": ordine.user_id,
        "user_nome": ordine.user.nome_completo if ordine.user else (ordine.user.email if ordine.user else "Operatore"),
        "settore": ordine.settore or "Generico",
        "data_ordine": ordine.data_ordine.isoformat() if ordine.data_ordine else None,
        "data_consegna": ordine.data_consegna,
        "note": ordine.note,
        "whatsapp_message": ordine.whatsapp_message,
        "spesa_totale": float(ordine.spesa_totale),
        "stato": ordine.stato,
        "stato_ricezione": ordine.stato_ricezione,
        "data_ricezione": ordine.data_ricezione.isoformat() if ordine.data_ricezione else None,
        "ricevuto_da_nome": ordine.ricevuto_da.nome_completo if ordine.ricevuto_da else None,
        "note_ricezione": ordine.note_ricezione,
        "righe": [
            {
                "id": r.id,
                "product_id": r.product_id,
                "sku_interno": r.sku_interno,
                "descrizione": r.descrizione,
                "quantita": float(r.quantita),
                "quantita_ricevuta": float(r.quantita_ricevuta) if r.quantita_ricevuta is not None else float(r.quantita),
                "uom": r.uom or "CT",
                "prezzo_pattuito": float(r.prezzo_pattuito),
                "prezzo_inserito": float(r.prezzo_inserito),
                "subtotale": round(float(r.quantita) * float(r.prezzo_inserito), 2),
                "stato_ottimizzazione": r.stato_ottimizzazione,
                "stato_riga": r.stato_riga or "in_attesa",
                "note_riga": r.note_riga
            }
            for r in ordine.righe
        ]
    }


@router.post(
    "/{ordine_id}/ricezione",
    summary="Valida la ricezione e scarico merci dell'ordine",
)
async def convalida_ricezione_ordine(
    ordine_id: int,
    data: RicezioneOrdineRequest,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(get_current_user),
):
    """
    Registra lo scarico merci dell'ordine: salva la quantità effettivamente ricevuta per ogni riga,
    i colli danneggiati o mancanti e aggiorna lo stato globale della consegna.
    """
    ordine = await db.get(Ordine, ordine_id)
    if not ordine:
        raise HTTPException(status_code=404, detail="Ordine non trovato")

    if user.ruolo != "admin" and user.ruolo_dettagliato != "admin":
        if user.location_id and ordine.location_id != user.location_id:
            raise HTTPException(status_code=403, detail="Non puoi validare ordini di un'altra sede")

    righe_map = {r.id: r for r in ordine.righe}

    for item in data.righe:
        if item.riga_id in righe_map:
            r = righe_map[item.riga_id]
            r.quantita_ricevuta = item.quantita_ricevuta
            r.stato_riga = item.stato_riga
            r.note_riga = item.note_riga

    ordine.stato_ricezione = data.stato_ricezione
    ordine.data_ricezione = datetime.utcnow()
    ordine.ricevuto_da_id = user.id
    ordine.note_ricezione = data.note_ricezione

    if data.stato_ricezione == "ricevuto_conforme":
        ordine.stato = "consegnato"

    await db.commit()
    await db.refresh(ordine)

    return {
        "status": "success",
        "ordine_id": ordine.id,
        "stato_ricezione": ordine.stato_ricezione,
        "message": f"Ricezione merci dell'ordine #{ordine.id} registrata con successo!"
    }

