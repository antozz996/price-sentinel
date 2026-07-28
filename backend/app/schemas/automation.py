"""Contracts for safe operational monitoring."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AutomationAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_type: str
    severity: str
    status: str
    location_id: int | None
    entity_type: str
    entity_id: str
    title: str
    message: str
    details: dict
    first_detected_at: datetime
    last_detected_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class AutomationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    alerts_detected: int
    alerts_created: int
    alerts_resolved: int
    error_code: str | None
    run_metadata: dict
