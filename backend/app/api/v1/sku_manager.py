from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import require_admin, get_current_user
from app.database import get_db

router = APIRouter()

@router.get("", summary="Lista di tutti gli SKU nel sistema")
@router.get("/", summary="Lista di tutti gli SKU nel sistema")
async def get_all_skus(
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Ritorna la lista di tutti gli SKU unici associati a righe fattura, prodotti e listini,
    ordinata per frequenza di acquisto, escludendo gli SKU in blacklist.
    """
    sql = """
        WITH all_skus AS (
            -- 1. Righe fattura con SKU interno
            SELECT 
                rf.sku_interno as sku, 
                MAX(COALESCE(p.canonical_name, lm.descrizione, rf.descrizione_fornitore_raw, rf.sku_interno)) as nome_prodotto,
                COUNT(rf.id) as total_acquisti
            FROM righe_fattura rf
            LEFT JOIN products p ON p.sku_interno = rf.sku_interno
            LEFT JOIN listino_master lm ON lm.sku_interno = rf.sku_interno AND lm.data_scadenza IS NULL
            WHERE rf.sku_interno IS NOT NULL 
              AND rf.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
            GROUP BY rf.sku_interno

            UNION ALL

            -- 2. Righe fattura senza SKU interno (usano descrizione raw)
            SELECT 
                rf.descrizione_fornitore_raw as sku, 
                rf.descrizione_fornitore_raw as nome_prodotto,
                COUNT(rf.id) as total_acquisti
            FROM righe_fattura rf
            WHERE rf.sku_interno IS NULL 
              AND rf.descrizione_fornitore_raw IS NOT NULL 
              AND LENGTH(TRIM(rf.descrizione_fornitore_raw)) > 0
              AND rf.descrizione_fornitore_raw NOT IN (SELECT sku_interno FROM skus_esclusi)
            GROUP BY rf.descrizione_fornitore_raw

            UNION ALL

            -- 3. Catalogo Products
            SELECT 
                p.sku_interno as sku,
                COALESCE(p.canonical_name, p.sku_interno) as nome_prodotto,
                0 as total_acquisti
            FROM products p
            WHERE p.sku_interno IS NOT NULL
              AND p.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)

            UNION ALL

            -- 4. Alias da SupplierProductAlias
            SELECT 
                spa.raw_description as sku,
                COALESCE(p.canonical_name, spa.raw_description) as nome_prodotto,
                0 as total_acquisti
            FROM supplier_product_aliases spa
            LEFT JOIN products p ON p.id = spa.product_id
            WHERE spa.raw_description IS NOT NULL
              AND spa.raw_description NOT IN (SELECT sku_interno FROM skus_esclusi)

            UNION ALL

            -- 5. Listino Master
            SELECT 
                lm.sku_interno as sku,
                COALESCE(lm.descrizione, lm.sku_interno) as nome_prodotto,
                0 as total_acquisti
            FROM listino_master lm
            WHERE lm.sku_interno IS NOT NULL
              AND lm.sku_interno NOT IN (SELECT sku_interno FROM skus_esclusi)
        )
        SELECT 
            sku as sku_interno, 
            MAX(nome_prodotto) as nome_prodotto,
            SUM(total_acquisti) as total_acquisti
        FROM all_skus
        WHERE sku IS NOT NULL AND LENGTH(TRIM(sku)) > 0
        GROUP BY sku
        ORDER BY total_acquisti DESC, nome_prodotto ASC
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

@router.get("/excluded", summary="Lista di tutti gli SKU esclusi")
async def get_excluded_skus(
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ritorna la lista di tutti gli SKU esclusi dal sistema."""
    from app.models.esclusi import SKUEscluso
    stmt = select(SKUEscluso).order_by(SKUEscluso.created_at.desc())
    res = await db.execute(stmt)
    records = res.scalars().all()
    return [
        {
            "sku_interno": r.sku_interno,
            "created_at": r.created_at,
        }
        for r in records
    ]

@router.post("/excluded", summary="Esclude uno SKU dalle analisi")
async def exclude_sku(
    sku_interno: str = Body(..., embed=True),
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggiunge uno SKU alla lista dei prodotti esclusi."""
    from app.models.esclusi import SKUEscluso
    
    if not sku_interno:
        raise HTTPException(status_code=400, detail="Specificare sku_interno")
        
    # Verifica se è già escluso
    stmt = select(SKUEscluso).where(SKUEscluso.sku_interno == sku_interno)
    res = await db.execute(stmt)
    exists = res.scalar_one_or_none()
    if exists:
        return {"success": True, "message": f"SKU '{sku_interno}' già escluso"}
        
    new_exclude = SKUEscluso(sku_interno=sku_interno)
    db.add(new_exclude)
    await db.commit()
    return {"success": True, "message": f"SKU '{sku_interno}' escluso con successo"}

@router.delete("/excluded/{sku_interno}", summary="Ripristina uno SKU escluso")
async def restore_excluded_sku(
    sku_interno: str,
    _user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rimuove uno SKU dalla lista dei prodotti esclusi, ripristinandolo nelle analisi."""
    from app.models.esclusi import SKUEscluso
    
    stmt = select(SKUEscluso).where(SKUEscluso.sku_interno == sku_interno)
    res = await db.execute(stmt)
    record = res.scalar_one_or_none()
    
    if not record:
        raise HTTPException(status_code=404, detail="SKU non trovato tra quelli esclusi")
        
    await db.delete(record)
    await db.commit()
    return {"success": True, "message": f"SKU '{sku_interno}' ripristinato con successo"}

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
        # Update products
        await db.execute(
            text("UPDATE products SET sku_interno = :new_sku WHERE sku_interno = :old_sku"),
            {"new_sku": new_sku, "old_sku": old_sku}
        )
        
        await db.commit()
        return {"success": True, "message": f"SKU '{old_sku}' rinominato in '{new_sku}'"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

