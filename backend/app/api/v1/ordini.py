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
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_admin, get_current_user
from app.models.listino import ListinoMaster
from app.models.fatture import RigaFattura, Fattura
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.ordini import Ordine, RigaOrdine
from app.models.products import Product, SupplierProductAlias
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
        
        # Cerca fornitore e prezzo migliore / pattuito
        chosen_supplier_id = it.preferred_supplier_id
        unit_price = it.prezzo_unitario
        uom = it.comparison_unit or product.comparison_unit or "CT"
        if uom.lower() == "piece":
            uom = "pz"
        is_concordato = False
        supplier_code = None

        if not chosen_supplier_id or unit_price is None:
            # Query listino_master per il miglior prezzo attivo
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
            chosen_supplier_id = 3 if 3 in fornitori_map else (fornitori_db[0].id if fornitori_db else 1)
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

        wa_encoded = urllib.parse.quote(wa_msg)
        wa_url = f"https://api.whatsapp.com/send?text={wa_encoded}"

        bundles.append(
            SupplierOrderBundle(
                fornitore_id=sup_id,
                fornitore_nome=sup_name,
                partita_iva=sup.partita_iva if sup else None,
                email_contatto=sup.email_contatto if sup else None,
                telefono_contatto=None,
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
            data_ordine=now,
            spesa_totale=bundle.totale_ordine,
            stato="inviato",
        )
        db.add(ordine)
        await db.flush()

        for it in bundle.items:
            riga = RigaOrdine(
                ordine_id=ordine.id,
                sku_interno=it.sku_interno or f"PROD-{it.product_id}",
                descrizione=it.nome_prodotto,
                quantita=it.quantita,
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
    summary="Elenco di tutti gli ordini generati",
)
async def list_ordini(
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
):
    """Restituisce la lista di tutti gli ordini d'acquisto preventivi memorizzati."""
    stmt = select(Ordine).order_by(Ordine.id.desc())
    res = await db.execute(stmt)
    ordini = res.scalars().all()
    
    return [
        {
            "id": o.id,
            "fornitore_id": o.fornitore_id,
            "fornitore_nome": o.fornitore.nome_azienda if o.fornitore else "Generico",
            "location_id": o.location_id,
            "location_nome": o.location.nome_struttura if o.location else "Generico",
            "data_ordine": o.data_ordine,
            "spesa_totale": float(o.spesa_totale),
            "stato": o.stato,
            "n_righe": len(o.righe)
        }
        for o in ordini
    ]
