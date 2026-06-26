from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import require_admin, get_current_user
from app.database import get_db

router = APIRouter()

@router.get("/", summary="Lista di tutti gli SKU nel sistema")
async def get_all_skus(
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ritorna la lista di tutti gli SKU unici associati a righe fattura,
    ordinata per frequenza di acquisto.
    """
    sql = """
        SELECT 
            sku_interno, 
            MAX(descrizione_fornitore_raw) as nome_prodotto,
            COUNT(id) as total_acquisti
        FROM righe_fattura 
        WHERE sku_interno IS NOT NULL 
        GROUP BY sku_interno
        ORDER BY total_acquisti DESC
    """
    res = await db.execute(text(sql))
    
    results = []
    for r in res.all():
        results.append({
            "sku_interno": r.sku_interno,
            "nome_prodotto": r.nome_prodotto,
            "total_acquisti": r.total_acquisti
        })
    return results

@router.put("/rename", summary="Rinomina globalmente uno SKU")
async def rename_sku(
    old_sku: str = Body(..., embed=True),
    new_sku: str = Body(..., embed=True),
    _admin = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggiorna il codice sku_interno in tutte le tabelle dipendenti (fatture, listini, alias).
    """
    if not old_sku or not new_sku:
        raise HTTPException(status_code=400, detail="Specificare old_sku e new_sku")
        
    try:
        # Update righe_fattura
        await db.execute(
            text("UPDATE righe_fattura SET sku_interno = :new_sku WHERE sku_interno = :old_sku"),
            {"new_sku": new_sku, "old_sku": old_sku}
        )
        # Update listino_master
        await db.execute(
            text("UPDATE listino_master SET sku_interno = :new_sku WHERE sku_interno = :old_sku"),
            {"new_sku": new_sku, "old_sku": old_sku}
        )
        # Update alias_prodotti
        await db.execute(
            text("UPDATE alias_prodotti SET sku_interno = :new_sku WHERE sku_interno = :old_sku"),
            {"new_sku": new_sku, "old_sku": old_sku}
        )
        # Update approvazioni_prezzo
        await db.execute(
            text("UPDATE approvazioni_prezzo SET sku_interno = :new_sku WHERE sku_interno = :old_sku"),
            {"new_sku": new_sku, "old_sku": old_sku}
        )
        
        await db.commit()
        return {"success": True, "message": f"SKU '{old_sku}' rinominato in '{new_sku}'"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
