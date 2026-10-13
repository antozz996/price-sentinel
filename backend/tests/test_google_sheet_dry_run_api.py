"""API tests for the admin-only Google Sheet dry-run endpoint."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.smart_price_sheet import google_sheet_dry_run
from app.schemas.smart_price_sheet import GoogleSheetDryRunRequest

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sheets_sync_synthetic.json"


@pytest.mark.asyncio
async def test_google_sheet_dry_run_returns_reviewable_report_without_database():
    snapshot = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload = GoogleSheetDryRunRequest(
        spreadsheet_id=snapshot["spreadsheet_id"],
        title="santo graal",
        values=snapshot["values"],
    )

    result = await google_sheet_dry_run(
        payload,
        user=SimpleNamespace(id=1, ruolo="admin"),
    )

    assert result["workbook_title"] == "santo graal"
    assert result["candidate_count"] == 30
    assert result["no_contract_writes"] is True
    assert result["rules"]["auto_commit_enabled"] is False
    assert all(item["status"] != "auto_eligible" for item in result["candidates"])


@pytest.mark.asyncio
async def test_google_sheet_dry_run_rejects_wrong_workbook_title():
    payload = GoogleSheetDryRunRequest(
        spreadsheet_id="1klQw-Ps7reJHu2Hii3T9GltpfbK7PQrnpalfFFygtGM",
        title="un altro file",
        values={},
    )

    with pytest.raises(HTTPException) as exc:
        await google_sheet_dry_run(
            payload,
            user=SimpleNamespace(id=1, ruolo="admin"),
        )

    assert exc.value.status_code == 422
