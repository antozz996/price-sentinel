"""
Price Sentinel — Schemas per Categorie Master e Abilitazioni Fornitori.
"""

from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class CategoryBase(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    descrizione: Optional[str] = None
    colore: Optional[str] = Field(default="#3b82f6", max_length=30)
    is_active: bool = True


class CategoryCreate(CategoryBase):
    pass


class CategoryUpdate(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=100)
    descrizione: Optional[str] = None
    colore: Optional[str] = Field(None, max_length=30)
    is_active: Optional[bool] = None


class CategoryResponse(BaseModel):
    id: int
    nome: str
    descrizione: Optional[str] = None
    colore: Optional[str] = "#3b82f6"
    is_active: bool = True
    product_count: int = 0
    supplier_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SupplierCapabilityItem(BaseModel):
    category: str
    enabled: bool
    reason: Optional[str] = None


class SupplierCapabilityToggle(BaseModel):
    supplier_id: int
    category: str
    enabled: bool
    reason: Optional[str] = None


class SupplierCategoryMatrixRow(BaseModel):
    supplier_id: int
    supplier_name: str
    partita_iva: str
    attivo_whitelist: bool
    categories: Dict[str, bool] = {}  # category_name -> is_enabled


class SupplierCategoryMatrixResponse(BaseModel):
    categories: List[CategoryResponse]
    suppliers: List[SupplierCategoryMatrixRow]
    total_suppliers: int
    total_categories: int


class BulkSupplierCategoryUpdate(BaseModel):
    supplier_id: int
    capabilities: List[SupplierCapabilityItem]
