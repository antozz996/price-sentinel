"""
Price Sentinel — Router Ordini.
Integrazione Intelligenza di Acquisto e Ottimizzazione Ordini (Regole A, B, C).
"""

from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_admin
from app.models.listino import ListinoMaster
from app.models.fatture import RigaFattura, Fattura
from app.models.fornitori import Fornitore
from app.models.location import Location
from app.models.ordini import Ordine, RigaOrdine

router = APIRouter()


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
        # 1. Recupero anagrafica o descrizione base del prodotto dagli alias o listino
        # Cerca descrizione nel listino master
        listino_stmt = select(ListinoMaster).where(ListinoMaster.sku_interno == item.sku_interno).limit(1)
        listino_res = await db.execute(listino_stmt)
        listino_item = listino_res.scalar_one_or_none()
        descrizione = listino_item.descrizione if listino_item else f"Prodotto {item.sku_interno}"

        # 2. REGOLA A: Verifica se c'è un contratto a prezzo fisso attivo (data_scadenza IS NULL)
        contract_stmt = select(ListinoMaster).where(
            and_(
                ListinoMaster.sku_interno == item.sku_interno,
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
                avvisi_preventivi.append(f"Anomalia {item.sku_interno}: {dettaglio_anomalia}")

            spesa_totale_blindata += prezzo_inserito * item.quantita

            righe_ottimizzate.append(
                RigaOttimizzataResponse(
                    sku_interno=item.sku_interno,
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
                .where(RigaFattura.sku_interno == item.sku_interno)
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
                    avvisi_preventivi.append(f"Avviso Spot {item.sku_interno}: {dettaglio_anomalia}")

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
                        sku_interno=item.sku_interno,
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
                        sku_interno=item.sku_interno,
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


@router.get(
    "/",
    summary="Elenco di tutti gli ordini generati",
)
async def list_ordini(
    db: AsyncSession = Depends(get_db),
    _admin = Depends(require_admin),
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
