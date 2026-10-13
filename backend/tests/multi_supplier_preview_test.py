"""Regression checks for a write-free comparative price list preview."""

import asyncio
from io import BytesIO

from openpyxl import Workbook
from starlette.datastructures import UploadFile

from app.api.v1.listino import import_multi_supplier


class NoWriteDb:
    def __getattr__(self, name):
        raise AssertionError(f"dry-run accessed database operation: {name}")


async def test_preview_parses_rows_without_database_access():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["PRODOTTO", "UNITA DI MISURA", "MARR", "DAC"])
    sheet.append(["Pomodori pelati", "Kg", 2.5, 2.7])
    payload = BytesIO()
    workbook.save(payload)
    payload.seek(0)

    result = await import_multi_supplier(
        file=UploadFile(filename="comparativo.xlsx", file=payload),
        dry_run=True,
        _admin=None,
        db=NoWriteDb(),
    )

    assert result["mode"] == "dry_run"
    assert result["total_rows"] == 1
    assert result["suppliers_detected"] == ["MARR", "DAC"]
    assert result["records_preview"] == [{
        "sku_interno": "POMODORI-PELATI",
        "descrizione": "Pomodori pelati",
        "unita_misura": "Kg",
        "prezzi": {"MARR": "2.5", "DAC": "2.7"},
    }]


if __name__ == "__main__":
    asyncio.run(test_preview_parses_rows_without_database_access())
    print("PASS: comparative preview shows parsed content and performs no DB writes")
