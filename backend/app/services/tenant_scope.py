"""Tenant ownership belongs to Fattura: every invoice-derived record follows it."""

from sqlalchemy import or_

from app.models.fatture import Fattura

DEFAULT_TENANT_ID = 1


def user_tenant_id(user) -> int:
    return getattr(user, "tenant_id", None) or DEFAULT_TENANT_ID


def invoice_tenant_filter(user):
    """SQL condition limiting invoices to the tenant of this user."""
    tenant_id = user_tenant_id(user)
    if tenant_id == DEFAULT_TENANT_ID:
        # Invoices with no tenant predate multi-tenancy and belong to the first one.
        return or_(Fattura.tenant_id == tenant_id, Fattura.tenant_id.is_(None))
    return Fattura.tenant_id == tenant_id


def invoice_belongs_to_user(fattura: Fattura, user) -> bool:
    return (fattura.tenant_id or DEFAULT_TENANT_ID) == user_tenant_id(user)
