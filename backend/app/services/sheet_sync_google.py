"""Google Sheets API transport: strictly read-only OAuth scope and GET requests."""
from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from app.services.sheet_sync_dry_run import EXCLUSION_TAB, SOURCES, SUPPORT_TABS

READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
API_ROOT = "https://sheets.googleapis.com/v4/spreadsheets"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{15,200}$")


class GoogleSheetsReadOnly:
    def __init__(self, spreadsheet_id: str, *, credentials: Any | None = None):
        """Use Application Default Credentials (ADC), including keyless WIF.

        The optional credentials argument is used by isolated tests only.
        GitHub Actions should provide GOOGLE_APPLICATION_CREDENTIALS via
        google-github-actions/auth, not a long-lived service-account key.
        """
        if not ID_PATTERN.fullmatch(spreadsheet_id):
            raise ValueError("Invalid spreadsheet ID")
        if credentials is None:
            # Import lazily; pure source/parser tests run without cloud auth.
            import google.auth

            credentials, _project = google.auth.default(scopes=[READONLY_SCOPE])
        self._credentials = credentials
        self._id = spreadsheet_id

    async def _request(self, *, suffix: str = "", **kwargs: Any) -> dict[str, Any]:
        from google.auth.transport.requests import Request

        if not self._credentials.valid:
            await asyncio.to_thread(self._credentials.refresh, Request())
        url = f"{API_ROOT}/{self._id}{suffix}"
        async with httpx.AsyncClient(timeout=50, follow_redirects=False) as client:
            # All access is GET, token has read-only scope, no mutation API exists.
            response = await client.get(
                url, headers={"Authorization": f"Bearer {self._credentials.token}"},
                **kwargs
            )
            response.raise_for_status()
            return response.json()

    async def metadata(self) -> dict:
        return await self._request(params={"fields": (
            "spreadsheetId,properties(title,locale,timeZone),"
            "sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))"
        )})

    async def read_snapshot(
        self, *, with_cell_notes: bool = True, expected_title: str = "santo graal"
    ) -> dict[str, Any]:
        meta = await self.metadata()
        actual_title = meta.get("properties", {}).get("title", "")
        if expected_title and actual_title != expected_title:
            raise ValueError(f"Wrong source workbook: expected {expected_title!r}, received {actual_title!r}")
        sheet_props = {
            sheet["properties"]["title"]: sheet["properties"]
            for sheet in meta.get("sheets", [])
        }
        requested_names = [s.title for s in SOURCES] + [EXCLUSION_TAB]
        missing = [name for name in requested_names if name not in sheet_props]
        if missing:
            raise ValueError(f"Required source tabs missing: {', '.join(missing)}")
        ranges = []
        for layout in SOURCES:
            n = min(sheet_props[layout.title].get("gridProperties", {}).get("rowCount", 1000),
                    layout.max_rows)
            escaped = layout.title.replace("'", "''")
            ranges.append(f"'{escaped}'!A1:{layout.max_columns}{n}")
        exclusions_rows = min(
            sheet_props[EXCLUSION_TAB].get("gridProperties", {}).get("rowCount", 100),
            100
        )
        ranges.append(f"'{EXCLUSION_TAB}'!A1:F{exclusions_rows}")
        response = await self._request(
            suffix="/values:batchGet",
            params={
                "ranges": ranges,
                "valueRenderOption": "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "FORMATTED_STRING",
            },
        )
        values = {
            name: entry.get("values", [])
            for name, entry in zip(requested_names, response.get("valueRanges", []))
        }
        if len(response.get("valueRanges", [])) != len(requested_names):
            raise RuntimeError("Google Sheets returned an incomplete batch; aborting")
        cell_notes: dict[str, dict[str, str]] = {}
        if with_cell_notes:
            # Notes are explicitly requested as separate read-only grid metadata.
            notes_data = await self._request(params={
                "ranges": ranges,
                "includeGridData": "true",
                "fields": (
                    "sheets(properties(title),data(startRow,startColumn,"
                    "rowData(values(note))))"
                ),
            })
            from app.services.sheet_sync_dry_run import _column
            for sheet in notes_data.get("sheets", []):
                tab = sheet["properties"]["title"]
                notes_for_tab = cell_notes.setdefault(tab, {})
                for grid in sheet.get("data", []):
                    sr = grid.get("startRow", 0)
                    sc = grid.get("startColumn", 0)
                    for r, row in enumerate(grid.get("rowData", [])):
                        for c, cell in enumerate(row.get("values", [])):
                            if cell.get("note"):
                                notes_for_tab[f"{_column(sc+c)}{sr+r+1}"] = cell["note"]
        return {
            "spreadsheet_id": self._id,
            "title": actual_title,
            "locale": meta.get("properties", {}).get("locale"),
            "timeZone": meta.get("properties", {}).get("timeZone"),
            "sheet_ids": {name: prop.get("sheetId") for name, prop in sheet_props.items()},
            "all_tab_names": list(sheet_props),
            "support_tabs": [name for name in SUPPORT_TABS if name in sheet_props],
            "unknown_tabs": [name for name in sheet_props if name not in requested_names
                             and name not in SUPPORT_TABS],
            "values": values,
            "notes": cell_notes,
        }
