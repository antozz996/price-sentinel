"""
Price Sentinel — Impostazioni Aziendali & White-Label.
Permette di personalizzare il nome aziendale, payoff, contatti e branding dell'istanza.
"""

from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.utenti import Utente
from app.models.company_settings import CompanySettings

router = APIRouter()


class CompanySettingsResponse(BaseModel):
    id: int
    company_name: str
    app_subtitle: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: str = "#3b82f6"
    support_email: Optional[str] = None
    currency_symbol: str = "€"

    class Config:
        from_attributes = True


class CompanySettingsUpdateRequest(BaseModel):
    company_name: str = Field(..., min_length=2, max_length=255)
    app_subtitle: Optional[str] = Field(None, max_length=255)
    logo_url: Optional[str] = None
    primary_color: Optional[str] = Field("#3b82f6", max_length=50)
    support_email: Optional[str] = Field(None, max_length=255)
    currency_symbol: Optional[str] = Field("€", max_length=10)


@router.get("", response_model=CompanySettingsResponse)
@router.get("/", response_model=CompanySettingsResponse)
async def get_company_settings(db: AsyncSession = Depends(get_db)):
    """
    Restituisce le impostazioni di branding dell'istanza corrente (pubblico per header/login).
    """
    settings = await db.get(CompanySettings, 1)
    if not settings:
        settings = CompanySettings(
            id=1,
            company_name="Price Sentinel",
            app_subtitle="Audit & Purchasing Platform",
            support_email="support@pricesentinel.it",
            primary_color="#3b82f6",
            currency_symbol="€",
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.put("", response_model=CompanySettingsResponse)
@router.put("/", response_model=CompanySettingsResponse)
async def update_company_settings(
    data: CompanySettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: Utente = Depends(require_admin),
):
    """
    Aggiorna i parametri di branding e configurazione aziendale (solo Amministratore).
    """
    settings = await db.get(CompanySettings, 1)
    if not settings:
        settings = CompanySettings(id=1)
        db.add(settings)

    settings.company_name = data.company_name
    settings.app_subtitle = data.app_subtitle
    settings.logo_url = data.logo_url
    if data.primary_color:
        settings.primary_color = data.primary_color
    settings.support_email = data.support_email
    if data.currency_symbol:
        settings.currency_symbol = data.currency_symbol

    await db.commit()
    await db.refresh(settings)
    return settings
