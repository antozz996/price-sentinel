"""
Price Sentinel — SuperAdmin God Mode Router.
Control Room globale protetta da Master Secret Token per la supervisione
e gestione di tutte le istanze aziendali, impersonazione e statistiche SaaS.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tenant_instances import TenantInstance
from app.models.utenti import Utente, RuoloUtente
from app.models.fatture import Fattura
from app.models.ordini import Ordine
from app.models.location import Location
from app.services.auth import hash_password, create_access_token

router = APIRouter()

# Master Token per la God Mode Room (configurabile da env o default sicuro)
GOD_MODE_TOKEN = os.getenv("GOD_MODE_TOKEN", "sentinel_god_master_key_2026")


def verify_god_token(x_god_token: Optional[str] = Header(None)) -> bool:
    if not x_god_token or x_god_token.strip() != GOD_MODE_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Master Token God Mode non valido o assente"
        )
    return True


class GodAuthRequest(BaseModel):
    token: str


class CreateTenantRequest(BaseModel):
    company_name: str = Field(..., min_length=2)
    slug: str = Field(..., min_length=2)
    admin_email: str = Field(..., min_length=3)
    admin_password: str = Field(..., min_length=1)


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=1)


@router.post("/auth", summary="Verifica Master Token God Mode")
async def authenticate_god_mode(data: GodAuthRequest):
    if data.token.strip() != GOD_MODE_TOKEN:
        raise HTTPException(status_code=401, detail="Master Token non valido")
    return {"status": "authenticated", "message": "Accesso God Mode autorizzato", "token": GOD_MODE_TOKEN}


@router.get("/overview", summary="Statistiche e telemetria globale SaaS")
async def get_god_overview(
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_god_token)
) -> Dict[str, Any]:
    tenants = (await db.scalars(select(TenantInstance).order_by(TenantInstance.id))).all()
    
    tot_fatture = (await db.scalars(select(func.count(Fattura.id)))).first() or 0
    tot_ordini = (await db.scalars(select(func.count(Ordine.id)))).first() or 0
    tot_utenti = (await db.scalars(select(func.count(Utente.id)))).first() or 0
    tot_locations = (await db.scalars(select(func.count(Location.id)))).first() or 0
    tot_volume = (await db.scalars(select(func.coalesce(func.sum(Fattura.totale_imponibile), 0)))).first() or 0

    return {
        "total_tenants": len(tenants),
        "total_invoices": tot_fatture,
        "total_orders": tot_ordini,
        "total_users": tot_utenti,
        "total_locations": tot_locations,
        "total_spend_volume": float(tot_volume),
        "system_status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_connected": True
    }


@router.get("/tenants", summary="Lista dettagliata di tutti i tenant e aziende")
async def list_all_tenants(
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_god_token)
) -> List[Dict[str, Any]]:
    tenants = (await db.scalars(select(TenantInstance).order_by(TenantInstance.id))).all()
    results = []

    for t in tenants:
        t_id = t.id
        n_fatture = (await db.scalars(select(func.count(Fattura.id)).where(Fattura.tenant_id == t_id))).first() or 0
        n_ordini = (await db.scalars(select(func.count(Ordine.id)).where(Ordine.tenant_id == t_id))).first() or 0
        n_utenti = (await db.scalars(select(func.count(Utente.id)).where(Utente.tenant_id == t_id))).first() or 0
        vol = (await db.scalars(select(func.coalesce(func.sum(Fattura.totale_imponibile), 0)).where(Fattura.tenant_id == t_id))).first() or 0

        # Verifica se l'admin utente esiste
        admin_user = (await db.scalars(select(Utente).where(Utente.email == t.admin_email))).first()

        results.append({
            "id": t.id,
            "slug": t.slug,
            "company_name": t.company_name,
            "admin_email": t.admin_email,
            "frontend_port": t.frontend_port,
            "backend_port": t.backend_port,
            "db_port": t.db_port,
            "access_url": t.access_url,
            "status": t.status or "attiva",
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "invoices_count": n_fatture,
            "orders_count": n_ordini,
            "users_count": n_utenti,
            "spend_volume": float(vol),
            "admin_active": admin_user.attivo if admin_user else False,
        })

    return results


@router.post("/tenants", summary="Crea una nuova azienda / istanza tenant")
async def create_new_tenant(
    data: CreateTenantRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_god_token)
):
    clean_slug = data.slug.strip().lower().replace(" ", "-")
    existing = (await db.scalars(select(TenantInstance).where(TenantInstance.slug == clean_slug))).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Lo slug '{clean_slug}' è già in uso")

    # Calcola ID e porte
    all_instances = (await db.scalars(select(TenantInstance))).all()
    fe_port = 8085 + len(all_instances)
    be_port = 8005 + len(all_instances)
    db_port = 5435 + len(all_instances)

    new_inst = TenantInstance(
        slug=clean_slug,
        company_name=data.company_name.strip(),
        admin_email=data.admin_email.strip(),
        frontend_port=fe_port,
        backend_port=be_port,
        db_port=db_port,
        access_url=f"/#company={clean_slug}",
        status="attiva",
        created_at=datetime.now(timezone.utc)
    )
    db.add(new_inst)
    await db.flush()
    await db.refresh(new_inst)

    # Crea l'utente amministratore con il tenant_id assegnato
    existing_user = (await db.scalars(select(Utente).where(Utente.email == data.admin_email.strip()))).first()
    if existing_user:
        existing_user.tenant_id = new_inst.id
        existing_user.password_hash = hash_password(data.admin_password.strip())
        existing_user.nome_completo = f"Admin {data.company_name.strip()}"
        existing_user.ruolo = RuoloUtente.admin
        existing_user.attivo = True
    else:
        new_admin = Utente(
            email=data.admin_email.strip(),
            password_hash=hash_password(data.admin_password.strip()),
            nome_completo=f"Admin {data.company_name.strip()}",
            ruolo=RuoloUtente.admin,
            ruolo_dettagliato="admin",
            tenant_id=new_inst.id,
            attivo=True
        )
        db.add(new_admin)

    await db.commit()
    return {"status": "success", "tenant_id": new_inst.id, "company_name": new_inst.company_name}


@router.post("/tenants/{tenant_id}/impersonate", summary="Genera JWT per accedere direttamente come admin del tenant")
async def impersonate_tenant_admin(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_god_token)
):
    tenant = await db.get(TenantInstance, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Azienda non trovata")

    admin = (await db.scalars(select(Utente).where(Utente.tenant_id == tenant_id, Utente.ruolo == RuoloUtente.admin))).first()
    if not admin:
        admin = (await db.scalars(select(Utente).where(Utente.email == tenant.admin_email))).first()

    if not admin:
        raise HTTPException(status_code=404, detail=f"Nessun utente admin trovato per '{tenant.company_name}'")

    token = create_access_token(
        user_id=admin.id,
        ruolo=admin.ruolo.value,
        location_id=admin.location_id,
        tenant_id=tenant_id
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "ruolo": admin.ruolo.value,
        "ruolo_dettagliato": admin.ruolo_dettagliato or "admin",
        "nome_completo": admin.nome_completo,
        "email": admin.email,
        "tenant_id": tenant_id,
        "company_name": tenant.company_name
    }


@router.post("/tenants/{tenant_id}/reset-password", summary="Resetta la password per l'admin dell'azienda")
async def reset_tenant_password(
    tenant_id: int,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_god_token)
):
    tenant = await db.get(TenantInstance, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Azienda non trovata")

    admin = (await db.scalars(select(Utente).where(Utente.email == tenant.admin_email))).first()
    if not admin:
        admin = (await db.scalars(select(Utente).where(Utente.tenant_id == tenant_id, Utente.ruolo == RuoloUtente.admin))).first()

    if not admin:
        raise HTTPException(status_code=404, detail="Utente admin non trovato per questa azienda")

    admin.password_hash = hash_password(data.new_password.strip())
    await db.commit()
    return {"status": "success", "message": f"Password per {admin.email} reimpostata con successo"}


@router.delete("/tenants/{tenant_id}", summary="Elimina la registrazione di un'azienda")
async def delete_tenant(
    tenant_id: int,
    db: AsyncSession = Depends(get_db),
    _auth: bool = Depends(verify_god_token)
):
    if tenant_id == 1:
        raise HTTPException(status_code=400, detail="Impossibile eliminare l'istanza principale del sistema (ID 1)")

    tenant = await db.get(TenantInstance, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Azienda non trovata")

    await db.delete(tenant)
    await db.commit()
    return {"status": "success", "message": f"Azienda '{tenant.company_name}' rimossa dalla gestione."}
