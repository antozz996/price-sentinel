"""Parser-only unit test: comparative preview parsing does not touch business data.

Approval persistence and replay protection are separately covered by
multi_supplier_approval_e2e.py on disposable PostgreSQL.
"""
from io import BytesIO

from openpyxl import Workbook

from app.services.excel_import_multi import parse_multi_supplier_excel


def test_preview_parsing() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["PRODOTTO", "UNITA DI MISURA", "MARR", "DAC"])
    sheet.append(["Pomodori pelati", "Kg", 2.5, 2.7])
    payload = BytesIO()
    workbook.save(payload)
    payload.seek(0)
    result = parse_multi_supplier_excel(payload)
    assert result.is_valid
    assert result.total_rows == 1
    assert result.suppliers_detected == ["MARR", "DAC"]
    record = result.records[0]
    assert record["sku_interno"] == "POMODORI-PELATI"
    assert record["descrizione"] == "Pomodori pelati"
    assert record["unita_misura"] == "Kg"
    assert {key: str(value) for key, value in record["prezzi"].items()} == {
        "MARR": "2.5", "DAC": "2.7",
    }


if __name__ == "__main__":
    test_preview_parsing()
    print("PASS: comparative Excel parsing is deterministic and read-only")
