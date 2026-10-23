from io import BytesIO

from openpyxl import Workbook

from app.services.normalized_price_workbook import (
    EXPECTED_TABS,
    REQUIRED_HEADERS,
    parse_normalized_price_workbook,
)


HEADERS = list(REQUIRED_HEADERS.values())


def make_workbook() -> bytes:
    workbook = Workbook()
    first = workbook.active
    first.title = "FOOD"
    for tab in EXPECTED_TABS:
        sheet = first if tab == "FOOD" else workbook.create_sheet(tab)
        sheet.append([f"{tab} — PREZZI ATTUALI"])
        sheet.append(["Prezzi attuali approvati"])
        sheet.append(["Aggiornamenti come nuove righe"])
        sheet.append(HEADERS)
    workbook["FOOD"].append([
        "Carni", "Entrecôte", "MARR", "ENTRECOTE PRUSSIANA", "A123", "Marca A",
        "Confezione 2 kg", "€ 30,00", 1, "kg", "15,00", "Prezzo attuale approvato",
        "FOOD!C2", None, "mensile",
    ])
    workbook["FOOD"].append([
        "Carni", "Pollo", "DAC", "Pollo intero", "", "", "1 conf", "€ 8,00", 1,
        "", "8,00", "Prezzo attuale approvato", "FOOD!D3", None, "mensile",
    ])
    workbook["FOOD"].append([
        "Carni", "Duplicato", "DAC", "Duplicato A", "", "", "1 kg", "€ 2,00", 1,
        "kg", "2,00", "Prezzo attuale approvato", "FOOD!D4", None, "mensile",
    ])
    workbook["FOOD"].append([
        "Carni", "Duplicato", "DAC", "Duplicato B", "", "", "2 kg", "€ 3,00", 1,
        "kg", "3,00", "Prezzo attuale approvato", "FOOD!D5", None, "mensile",
    ])
    workbook["FOOD"].append([
        "Carni", "Ignorato", "MARR", "", "", "", "", "", "", "", "",
        "Duplicata - non importare", "FOOD!C6", None, "",
    ])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_normalized_workbook_preview_keeps_only_approved_offers_and_blocks_unclear_rows() -> None:
    report = parse_normalized_price_workbook(make_workbook())

    assert report["mode"] == "dry_run_only"
    assert report["no_contract_writes"] is True
    assert report["candidate_count"] == 4
    assert report["excluded_count"] == 1
    offers = report["candidates"]
    entrecote = next(item for item in offers if item["product"] == "Entrecôte")
    assert entrecote["numeric_price"] == "15.00"
    assert entrecote["reference_unit"] == "kg"
    assert entrecote["packaging_note"] is not None
    assert entrecote["status"] == "needs_mapping"

    chicken = next(item for item in offers if item["product"] == "Pollo")
    assert chicken["status"] == "blocked"
    assert "unit_not_specified" in chicken["reasons"]

    duplicate_rows = [item for item in offers if item["product"] == "Duplicato"]
    assert len(duplicate_rows) == 2
    assert all(item["status"] == "blocked" for item in duplicate_rows)
    assert all("duplicate_supplier_product_offer" in item["reasons"] for item in duplicate_rows)


def test_normalized_workbook_rejects_missing_category_sheet() -> None:
    workbook = Workbook()
    workbook.active.title = "FOOD"
    buffer = BytesIO()
    workbook.save(buffer)
    try:
        parse_normalized_price_workbook(buffer.getvalue())
    except ValueError as error:
        assert "mancano le schede categoria" in str(error).lower()
    else:
        raise AssertionError("Missing category sheets must fail closed")
