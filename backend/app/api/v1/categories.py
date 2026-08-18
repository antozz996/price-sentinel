"""
Price Sentinel — Categorie Master e Abilitazioni Fornitori Router.
Gestisce il catalogo categorie merci e l'associazione categorie ↔ fornitori.
"""

from datetime import datetime, timezone
from typing import List, Dict, Set
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, delete, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import noload

from app.api.deps import get_current_user, require_admin
from app.database import get_db
from app.models.categories import MasterCategory
from app.models.fornitori import Fornitore
from app.models.products import Product
from app.models.purchase_policy import SupplierCategoryCapability
from app.models.utenti import Utente
from app.schemas.categories import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    SupplierCapabilityToggle,
    SupplierCategoryMatrixRow,
    SupplierCategoryMatrixResponse,
    BulkSupplierCategoryUpdate,
)
from app.services.normalization import normalize_text

router = APIRouter()

# Default Ho.Re.Ca categories list
DEFAULT_HORECA_CATEGORIES = [
    {"nome": "Beverage & Soft Drinks", "descrizione": "Bibite gassate, succhi di frutta, energy drink, tonica", "colore": "#0ea5e9"},
    {"nome": "Birre", "descrizione": "Birre in bottiglia, fusti e lattine", "colore": "#f59e0b"},
    {"nome": "Alcolici & Superalcolici", "descrizione": "Liquori, amari, distillati, gin, rum, vodka, whisky", "colore": "#8b5cf6"},
    {"nome": "Vini, Spumanti & Champagne", "descrizione": "Vini bianchi, rossi, rosati, bollicine, prosecco e champagne", "colore": "#ec4899"},
    {"nome": "Acqua Minerale", "descrizione": "Acque minerali naturali ed effervescenti in vetro o PET", "colore": "#06b6d4"},
    {"nome": "Caffetteria & Bar", "descrizione": "Caffè in grani, cialde, tè, tisane, sciroppi bar", "colore": "#78350f"},
    {"nome": "Monouso & Tovagliato", "descrizione": "Bicchieri, cannucce, tovaglioli, tovaglie e posate monouso", "colore": "#10b981"},
    {"nome": "Detergenza & Igiene", "descrizione": "Detergenti pavimenti, lavastoviglie, sanificanti HACCP, carta mani", "colore": "#14b8a6"},
    {"nome": "Packaging & Asporto", "descrizione": "Vaschette, scatole pizza, sacchetti e contenitori delivery", "colore": "#64748b"},
    {"nome": "Ortofrutta Fresca", "descrizione": "Frutta e verdura fresca per cucina e bar", "colore": "#84cc16"},
    {"nome": "Carni & Salumi", "descrizione": "Carni fresche, hamburger, salumi e affettati", "colore": "#ef4444"},
    {"nome": "Ittico & Pesce", "descrizione": "Pesce fresco, crostacei, molluschi e congelato mare", "colore": "#3b82f6"},
    {"nome": "Latticini & Formaggi", "descrizione": "Latte, panna, burro, mozzarelle, formaggi freschi e stagionati", "colore": "#facc15"},
    {"nome": "Surgelati & Congelati", "descrizione": "Patate fritte, basi pizza surgelate, pane, dessert surgelati", "colore": "#6366f1"},
    {"nome": "Alimentari & Dispensa", "descrizione": "Olio, farina, pasta, salse, conserve, spezie e condimenti", "colore": "#d97706"},
    {"nome": "Attrezzature & Accessori", "descrizione": "Bicchieri in vetro, stoviglie, accessori bar e cucina", "colore": "#94a3b8"},
]


@router.get("/", response_model=List[CategoryResponse], summary="Lista tutte le categorie")
async def list_categories(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
):
    """
    Ritorna l'elenco delle categorie con conteggio prodotti e fornitori associati.
    """
    # 1. Fetch from master_categories
    query = select(MasterCategory).order_by(MasterCategory.nome)
    if active_only:
        query = query.where(MasterCategory.is_active.is_(True))
    categories = (await db.execute(query)).scalars().all()

    # 2. Count products per category
    prod_counts_stmt = (
        select(Product.category, func.count(Product.id))
        .where(Product.is_active.is_(True), Product.category.is_not(None))
        .group_by(Product.category)
    )
    prod_counts_raw = (await db.execute(prod_counts_stmt)).all()
    prod_counts = {cat.strip().casefold(): count for cat, count in prod_counts_raw if cat}

    # 3. Count enabled suppliers per category
    supp_counts_stmt = (
        select(SupplierCategoryCapability.category, func.count(SupplierCategoryCapability.supplier_id))
        .join(Fornitore, and_(Fornitore.id == SupplierCategoryCapability.supplier_id, Fornitore.archived_at.is_(None)))
        .where(SupplierCategoryCapability.enabled.is_(True))
        .group_by(SupplierCategoryCapability.category)
    )
    supp_counts_raw = (await db.execute(supp_counts_stmt)).all()
    supp_counts = {cat.strip().casefold(): count for cat, count in supp_counts_raw if cat}

    # Build response
    result = []
    for cat in categories:
        cf = cat.nome.strip().casefold()
        result.append(
            CategoryResponse(
                id=cat.id,
                nome=cat.nome,
                descrizione=cat.descrizione,
                colore=cat.colore or "#3b82f6",
                is_active=cat.is_active,
                product_count=prod_counts.get(cf, 0),
                supplier_count=supp_counts.get(cf, 0),
                created_at=cat.created_at,
                updated_at=cat.updated_at,
            )
        )
    return result


@router.post("/", response_model=CategoryResponse, status_code=status.HTTP_201_CREATED, summary="Crea nuova categoria")
async def create_category(
    data: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    """Crea una nuova categoria master."""
    clean_name = data.nome.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Il nome della categoria non può essere vuoto")

    existing = await db.scalar(
        select(MasterCategory).where(
            func.lower(func.btrim(MasterCategory.nome)) == clean_name.casefold()
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Categoria '{clean_name}' già esistente")

    now = datetime.now(timezone.utc)
    cat = MasterCategory(
        nome=clean_name,
        descrizione=data.descrizione.strip() if data.descrizione else None,
        colore=data.colore or "#3b82f6",
        is_active=data.is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(cat)
    await db.flush()
    await db.refresh(cat)

    return CategoryResponse(
        id=cat.id,
        nome=cat.nome,
        descrizione=cat.descrizione,
        colore=cat.colore,
        is_active=cat.is_active,
        product_count=0,
        supplier_count=0,
        created_at=cat.created_at,
        updated_at=cat.updated_at,
    )


@router.post("/seed-defaults", summary="Carica categorie standard Ho.Re.Ca.")
async def seed_default_categories(
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    """
    Popola le categorie standard se non già presenti.
    """
    created_count = 0
    now = datetime.now(timezone.utc)

    for item in DEFAULT_HORECA_CATEGORIES:
        clean_name = item["nome"].strip()
        existing = await db.scalar(
            select(MasterCategory).where(
                func.lower(func.btrim(MasterCategory.nome)) == clean_name.casefold()
            )
        )
        if not existing:
            cat = MasterCategory(
                nome=clean_name,
                descrizione=item["descrizione"],
                colore=item["colore"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(cat)
            created_count += 1

    await db.flush()
    return {"status": "ok", "created": created_count, "message": f"{created_count} categorie create con successo."}


@router.put("/{category_id}", response_model=CategoryResponse, summary="Modifica categoria")
@router.patch("/{category_id}", response_model=CategoryResponse, summary="Modifica categoria")
async def update_category(
    category_id: int,
    data: CategoryUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    """Aggiorna i dettagli di una categoria."""
    cat = await db.get(MasterCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria non trovata")

    old_name = cat.nome

    if data.nome is not None:
        clean_name = data.nome.strip()
        if not clean_name:
            raise HTTPException(status_code=400, detail="Il nome non può essere vuoto")
        # Check uniqueness if name changed
        if clean_name.casefold() != old_name.casefold():
            existing = await db.scalar(
                select(MasterCategory).where(
                    func.lower(func.btrim(MasterCategory.nome)) == clean_name.casefold(),
                    MasterCategory.id != category_id,
                )
            )
            if existing:
                raise HTTPException(status_code=409, detail=f"Categoria '{clean_name}' già esistente")
            
            # Cascade name update in products and capabilities
            await db.execute(
                update(Product)
                .where(func.lower(func.btrim(Product.category)) == old_name.casefold())
                .values(category=clean_name)
            )
            await db.execute(
                update(SupplierCategoryCapability)
                .where(func.lower(func.btrim(SupplierCategoryCapability.category)) == old_name.casefold())
                .values(category=clean_name)
            )
            cat.nome = clean_name

    if data.descrizione is not None:
        cat.descrizione = data.descrizione.strip() if data.descrizione else None
    if data.colore is not None:
        cat.colore = data.colore.strip() if data.colore else "#3b82f6"
    if data.is_active is not None:
        cat.is_active = data.is_active

    cat.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(cat)

    # Get counts
    prod_count = await db.scalar(
        select(func.count(Product.id)).where(
            Product.is_active.is_(True),
            func.lower(func.btrim(Product.category)) == cat.nome.casefold(),
        )
    ) or 0
    supp_count = await db.scalar(
        select(func.count(SupplierCategoryCapability.supplier_id))
        .join(Fornitore, and_(Fornitore.id == SupplierCategoryCapability.supplier_id, Fornitore.archived_at.is_(None)))
        .where(
            SupplierCategoryCapability.enabled.is_(True),
            func.lower(func.btrim(SupplierCategoryCapability.category)) == cat.nome.casefold(),
        )
    ) or 0

    return CategoryResponse(
        id=cat.id,
        nome=cat.nome,
        descrizione=cat.descrizione,
        colore=cat.colore,
        is_active=cat.is_active,
        product_count=prod_count,
        supplier_count=supp_count,
        created_at=cat.created_at,
        updated_at=cat.updated_at,
    )


@router.delete("/{category_id}", status_code=status.HTTP_200_OK, summary="Elimina categoria")
async def delete_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    """Elimina una categoria master."""
    cat = await db.get(MasterCategory, category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria non trovata")

    cat_name = cat.nome
    await db.delete(cat)
    await db.flush()
    return {"status": "ok", "message": f"Categoria '{cat_name}' eliminata con successo."}


# ──────────────────────────────────────────────────────────────────────
# Matrice Fornitori ↔ Categorie
# ──────────────────────────────────────────────────────────────────────

@router.get("/matrix", response_model=SupplierCategoryMatrixResponse, summary="Matrice completa Fornitori ↔ Categorie")
async def get_supplier_category_matrix(
    db: AsyncSession = Depends(get_db),
    _user: Utente = Depends(get_current_user),
):
    """
    Ritorna tutte le categorie e tutti i fornitori con le loro associazioni.
    """
    # 1. Get all active master categories
    categories_raw = (
        await db.execute(
            select(MasterCategory).where(MasterCategory.is_active.is_(True)).order_by(MasterCategory.nome)
        )
    ).scalars().all()

    # 2. Get all non-archived suppliers
    suppliers = (
        await db.execute(
            select(Fornitore)
            .options(noload("*"))
            .where(Fornitore.archived_at.is_(None))
            .order_by(Fornitore.nome_azienda)
        )
    ).scalars().all()

    # 3. Get all supplier capabilities
    capabilities = (
        await db.execute(
            select(SupplierCategoryCapability)
        )
    ).scalars().all()

    # Map capabilities: (supplier_id, category_casefold) -> bool
    cap_map: Dict[tuple[int, str], bool] = {}
    for c in capabilities:
        cap_map[(c.supplier_id, c.category.strip().casefold())] = c.enabled

    # Count products per category
    prod_counts_stmt = (
        select(Product.category, func.count(Product.id))
        .where(Product.is_active.is_(True), Product.category.is_not(None))
        .group_by(Product.category)
    )
    prod_counts = {
        cat.strip().casefold(): count
        for cat, count in (await db.execute(prod_counts_stmt)).all()
        if cat
    }

    # Count suppliers per category
    supp_counts: Dict[str, int] = {}
    for (supp_id, cat_cf), enabled in cap_map.items():
        if enabled:
            supp_counts[cat_cf] = supp_counts.get(cat_cf, 0) + 1

    cat_responses = [
        CategoryResponse(
            id=c.id,
            nome=c.nome,
            descrizione=c.descrizione,
            colore=c.colore or "#3b82f6",
            is_active=c.is_active,
            product_count=prod_counts.get(c.nome.strip().casefold(), 0),
            supplier_count=supp_counts.get(c.nome.strip().casefold(), 0),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in categories_raw
    ]

    # Build supplier matrix rows
    matrix_rows = []
    for s in suppliers:
        supplier_caps = {}
        for c in categories_raw:
            cf = c.nome.strip().casefold()
            supplier_caps[c.nome] = cap_map.get((s.id, cf), False)

        matrix_rows.append(
            SupplierCategoryMatrixRow(
                supplier_id=s.id,
                supplier_name=s.nome_azienda,
                partita_iva=s.partita_iva,
                attivo_whitelist=s.attivo_whitelist,
                categories=supplier_caps,
            )
        )

    return SupplierCategoryMatrixResponse(
        categories=cat_responses,
        suppliers=matrix_rows,
        total_suppliers=len(suppliers),
        total_categories=len(cat_responses),
    )


@router.post("/toggle", summary="Attiva o disattiva una categoria per un fornitore")
async def toggle_supplier_capability(
    data: SupplierCapabilityToggle,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    """
    Abilita/disabilita una specifica categoria per un fornitore.
    """
    supplier = await db.get(Fornitore, data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    clean_category = data.category.strip()
    capability = await db.scalar(
        select(SupplierCategoryCapability).where(
            SupplierCategoryCapability.supplier_id == supplier.id,
            func.lower(func.btrim(SupplierCategoryCapability.category)) == clean_category.casefold(),
        )
    )

    now = datetime.now(timezone.utc)
    if capability:
        capability.enabled = data.enabled
        capability.reason = data.reason
        capability.updated_by = user.id
        capability.updated_at = now
    else:
        capability = SupplierCategoryCapability(
            supplier_id=supplier.id,
            category=clean_category,
            enabled=data.enabled,
            reason=data.reason,
            created_by=user.id,
            updated_by=user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(capability)

    await db.flush()
    return {
        "status": "ok",
        "supplier_id": supplier.id,
        "supplier_name": supplier.nome_azienda,
        "category": clean_category,
        "enabled": data.enabled,
    }


@router.put("/matrix", summary="Salva configurazione massiva categorie per un fornitore")
async def bulk_update_supplier_matrix(
    data: BulkSupplierCategoryUpdate,
    db: AsyncSession = Depends(get_db),
    user: Utente = Depends(require_admin),
):
    """
    Salva tutte le associazioni categoria per un fornitore.
    """
    supplier = await db.get(Fornitore, data.supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail="Fornitore non trovato")

    now = datetime.now(timezone.utc)
    for item in data.capabilities:
        clean_cat = item.category.strip()
        capability = await db.scalar(
            select(SupplierCategoryCapability).where(
                SupplierCategoryCapability.supplier_id == supplier.id,
                func.lower(func.btrim(SupplierCategoryCapability.category)) == clean_cat.casefold(),
            )
        )
        if capability:
            capability.enabled = item.enabled
            capability.reason = item.reason
            capability.updated_by = user.id
            capability.updated_at = now
        else:
            capability = SupplierCategoryCapability(
                supplier_id=supplier.id,
                category=clean_cat,
                enabled=item.enabled,
                reason=item.reason,
                created_by=user.id,
                updated_by=user.id,
                created_at=now,
                updated_at=now,
            )
            db.add(capability)

    await db.flush()
    return {"status": "ok", "message": "Associazioni aggiornate con successo."}
