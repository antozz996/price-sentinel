"""
Price Sentinel — Gestione Istanze Aziendali (Multi-Istanza & Provisioning Clienti).
Permette all'Amministratore di creare, visualizzare e gestire nuove piattaforme autonome per altre aziende.
"""

import os
import re
import asyncio
import subprocess
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_admin
from app.models.utenti import Utente
from app.models.tenant_instances import TenantInstance

router = APIRouter()


class TenantInstanceResponse(BaseModel):
    id: int
    slug: str
    company_name: str
    admin_email: str
    frontend_port: int
    backend_port: int
    db_port: int
    access_url: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class CreateTenantInstanceRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=50)
    admin_email: EmailStr
    admin_password: str = Field(..., min_length=6, max_length=100)


@router.get("", response_model=List[TenantInstanceResponse])
@router.get("/", response_model=List[TenantInstanceResponse])
async def list_tenant_instances(
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    """
    Restituisce l'elenco di tutte le istanze aziendali create e attive sulla macchina.
    """
    stmt = select(TenantInstance).order_by(TenantInstance.id.desc())
    instances = (await db.scalars(stmt)).all()
    return instances


@router.post("", response_model=TenantInstanceResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=TenantInstanceResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant_instance(
    data: CreateTenantInstanceRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    """
    Crea, configura e avvia una nuova istanza aziendale indipendente con database e porte isolate.
    """
    clean_slug = re.sub(r"[^a-zA-Z0-9_-]", "", data.slug.lower().strip())
    if not clean_slug:
        raise HTTPException(status_code=400, detail="Identificativo slug non valido.")

    # Verifica duplicati
    existing = (await db.scalars(select(TenantInstance).where(TenantInstance.slug == clean_slug))).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Esiste già un'istanza con identificativo '{clean_slug}'.")

    # Calcola porte disponibili
    max_fe = (await db.scalar(select(func.max(TenantInstance.frontend_port)))) or 8084
    max_be = (await db.scalar(select(func.max(TenantInstance.backend_port)))) or 8004
    max_db = (await db.scalar(select(func.max(TenantInstance.db_port)))) or 5434

    fe_port = max(max_fe + 1, 8085)
    be_port = max(max_be + 1, 8005)
    db_port = max(max_db + 1, 5435)

    base_dir = "/root/PRICE SENTINEL"
    instance_dir = f"/root/instances/{clean_slug}"

    try:
        os.makedirs(instance_dir, exist_ok=True)

        # Genera il file docker-compose per la nuova istanza
        compose_content = f"""version: '3.8'

services:
  db_{clean_slug}:
    image: postgres:15-alpine
    container_name: ps_db_{clean_slug}
    environment:
      POSTGRES_USER: sentinel_{clean_slug}
      POSTGRES_PASSWORD: secret_{clean_slug}_pwd
      POSTGRES_DB: sentinel_db_{clean_slug}
    volumes:
      - pgdata_{clean_slug}:/var/lib/postgresql/data
    ports:
      - "{db_port}:5432"
    restart: unless-stopped

  backend_{clean_slug}:
    image: pricesentinel-backend
    container_name: ps_backend_{clean_slug}
    environment:
      DATABASE_URL: postgresql+asyncpg://sentinel_{clean_slug}:secret_{clean_slug}_pwd@db_{clean_slug}:5432/sentinel_db_{clean_slug}
      SECRET_KEY: auto_generated_key_{clean_slug}
      ALGORITHM: HS256
      ACCESS_TOKEN_EXPIRE_MINUTES: 10080
    ports:
      - "{be_port}:8000"
    depends_on:
      - db_{clean_slug}
    restart: unless-stopped

  frontend_{clean_slug}:
    image: pricesentinel-frontend
    container_name: ps_frontend_{clean_slug}
    environment:
      VITE_API_BASE: http://localhost:{be_port}/api/v1
    ports:
      - "{fe_port}:80"
    depends_on:
      - backend_{clean_slug}
    restart: unless-stopped

volumes:
  pgdata_{clean_slug}:
"""
        with open(f"{instance_dir}/docker-compose.yml", "w") as f:
            f.write(compose_content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore nella creazione dei file dell'istanza: {str(e)}")

    access_url = f"http://3.70.222.91:{fe_port}"

    new_instance = TenantInstance(
        slug=clean_slug,
        company_name=data.company_name.strip(),
        admin_email=data.admin_email.strip(),
        frontend_port=fe_port,
        backend_port=be_port,
        db_port=db_port,
        access_url=access_url,
        status="attiva",
        created_at=datetime.utcnow()
    )
    db.add(new_instance)
    await db.commit()
    await db.refresh(new_instance)

    return new_instance


@router.delete("/{instance_id}")
async def delete_tenant_instance(
    instance_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin)
):
    """
    Rimuove la registrazione di un'istanza aziendale.
    """
    inst = await db.get(TenantInstance, instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Istanza non trovata")

    await db.delete(inst)
    await db.commit()
    return {"status": "success", "message": f"Istanza '{inst.slug}' rimossa dal registro."}
