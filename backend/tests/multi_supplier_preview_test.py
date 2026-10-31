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



def parse_rows(headers, rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    payload = BytesIO()
    workbook.save(payload)
    payload.seek(0)
    return parse_multi_supplier_excel(payload)


def test_reject_ambiguous_prices() -> None:
    # The old regex silently converted -2.50 and "circa 2.50" to +2.50.
    for value in ("-2,50", "circa 2.50", "2.50%", "2.12345", "1.234,56"):
        result = parse_rows(
            ["PRODOTTO", "UNITA DI MISURA", "MARR"],
            [["Pomodori pelati", "Kg", value]],
        )
        assert not result.is_valid, f"Unsafe monetary value accepted: {value}"
        assert result.errors, f"No user-facing validation error for {value}"


def test_accept_explicit_monetary_cells() -> None:
    for value in (2.5, "2,50", "€ 2,50", "2.50 EUR", "0,0001"):
        result = parse_rows(
            ["PRODOTTO", "UNITA DI MISURA", "MARR"],
            [["Pomodori pelati", "Kg", value]],
        )
        assert result.is_valid, f"Safe monetary value rejected: {value}"
        assert len(result.records) == 1


def test_duplicate_sku_and_supplier_are_blocked() -> None:
    duplicate_product = parse_rows(
        ["PRODOTTO", "UNITA DI MISURA", "MARR"],
        [
            ["Pomodori pelati", "Kg", 2.5],
            ["Pomodori/pelati", "Kg", 3.1],
        ],
    )
    assert not duplicate_product.is_valid
    assert any("SKU duplicato" in error.message for error in duplicate_product.errors)

    duplicate_supplier = parse_rows(
        ["PRODOTTO", "UNITA DI MISURA", "MARR", " marr "],
        [["Pomodori pelati", "Kg", 2.5, 2.7]],
    )
    assert not duplicate_supplier.is_valid
    assert any("fornitore duplicata" in error.message for error in duplicate_supplier.errors)


def test_empty_and_unusable_product_blocked() -> None:
    blank_quotes = parse_rows(
        ["PRODOTTO", "UNITA DI MISURA", "MARR"],
        [["Pomodori pelati", "Kg", None]],
    )
    assert not blank_quotes.is_valid
    assert any("Nessuna quotazione valida" in error.message for error in blank_quotes.errors)

    too_long_sku = parse_rows(
        ["PRODOTTO", "UNITA DI MISURA", "MARR"],
        [["A" * 101, "Kg", 2.5]],
    )
    assert not too_long_sku.is_valid
    assert any("100 caratteri" in error.message for error in too_long_sku.errors)

if __name__ == "__main__":
    test_preview_parsing()
    test_reject_ambiguous_prices()
    test_accept_explicit_monetary_cells()
    test_duplicate_sku_and_supplier_are_blocked()
    test_empty_and_unusable_product_blocked()
    print("PASS: comparative Excel parser rejects unsafe prices, duplicate rows and empty approvals")
