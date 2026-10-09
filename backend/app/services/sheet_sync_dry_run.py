"""Read-only normalization of sector price matrices for the Google Sheets Sync Engine.

NO database imports or writes. Everything stays a staged *candidate*: Sheet edits
and Gemini output are not contractual price agreements.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class SupplierColumn:
    index: int
    name: str
    unit_index: int | None = None
    note_index: int | None = None


@dataclass(frozen=True)
class SheetLayout:
    title: str
    sector: str
    product_index: int
    unit_index: int
    columns: tuple[SupplierColumn, ...]
    first_row: int = 2
    reference_only: bool = False
    packaging_note_index: int | None = None
    max_columns: str = "O"
    max_rows: int = 1000


SOURCES = (
    SheetLayout("FOOD", "food", 0, 1, (
        SupplierColumn(2, "MARR"), SupplierColumn(3, "MELIUS"),
        SupplierColumn(4, "DAC"), SupplierColumn(5, "ORIZZONTI", note_index=6),
        SupplierColumn(7, "DI PALO"), SupplierColumn(8, "FONTANELLA CARNI"),
    ), max_columns="J"),
    SheetLayout("BEVERAGE", "beverage", 0, 1, (
        SupplierColumn(2, "NAVAS"), SupplierColumn(3, "ORIZZONTI"),
        SupplierColumn(4, "3F"), SupplierColumn(5, "PASCARELLA"),
        SupplierColumn(6, "CASA D'AMBRA"),
    ), max_columns="L"),
    SheetLayout("COMPARAZIONE MATERIALI", "materiali", 1, 2, (
        SupplierColumn(3, "VEMO"), SupplierColumn(4, "KITO"),
        SupplierColumn(5, "EUROCARTA"), SupplierColumn(6, "ALPHA"),
        SupplierColumn(7, "PROMOCART", note_index=9),
        SupplierColumn(8, "MUNDO"),
    ), packaging_note_index=11, max_columns="N"),
    SheetLayout("FRUTTA E VERDURA", "ortofrutta", 0, 1, (
        SupplierColumn(2, "MG FRUTTA", note_index=3),
        SupplierColumn(4, "DEMETRA", unit_index=5, note_index=6),
        SupplierColumn(7, "BONTA DELL'ORTO", unit_index=8, note_index=9),
    ), max_columns="J"),
    SheetLayout("GIOCATTOLI", "giocattoli", 2, 3, (
        SupplierColumn(11, "ANTONIO"), SupplierColumn(12, "GIOVANNI"),
    ), reference_only=True, packaging_note_index=6, max_columns="O"),
)

# Supporting and derived tabs must never be imported twice.
SUPPORT_TABS = (
    "BEVERAGE DA INVIARE", "ORIZZONTI BEVERAGE", "KITO VEMO ",
    "MATERIALI DA INVIARE", "PRICE SENTINEL di FRUTTA E VERDURA 1",
    "DASHBOARD FORNITORI", "ORDINI DAC", "ORDINI MELIUS", "ORDINI MARR",
    "ORDINE - MG FRUTTA", "ORDINE - BONTA DELL'ORTO",
    "ORDINE - DEMETRA", "CONTROLLO_ESCLUSIONI",
)
EXCLUSION_TAB = "CONTROLLO_ESCLUSIONI"
EMPTY_MARKERS = {"", "-", "NO", "N/D", "NON TROVATO", "NULL", "N.A.", "N.A", "—"}
ERROR_PREFIXES = ("#REF!", "#VALUE!", "#DIV/0!", "#N/A", "#ERROR!", "#NUM!")


def _cell(row: list[Any], i: int | None) -> Any:
    return row[i] if i is not None and i < len(row) else None


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _label(value: Any) -> str:
    return re.sub(r"\s+", " ", _text(value)).casefold()


def _column(index: int) -> str:
    result = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _price(value: Any) -> tuple[str | None, str]:
    """Keep exact entered/returned value; never infer comma-formatted strings."""
    if value is None or isinstance(value, bool):
        return None, "missing"
    if isinstance(value, str):
        raw = value.strip()
        if raw.upper() in EMPTY_MARKERS:
            return None, "missing"
        if raw.upper().startswith(ERROR_PREFIXES):
            return None, "formula_error"
        # The Google API is called with UNFORMATTED_VALUE. Textual currency,
        # malformed numbers and manually typed amounts are never auto-trusted.
        return None, "textual_price"
    if not isinstance(value, (int, float)):
        return None, "unsupported_price"
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None, "invalid_price"
    if not amount.is_finite() or amount <= 0:
        return None, "zero_or_negative"
    return format(amount, "f"), "valid"


def _base_unit(text: str) -> str | None:
    val = re.sub(r"\s+", "", _text(text).upper()).replace("€/", "")
    if val in {"KG", "KILO", "KILOGRAMMO", "KILOGRAMMI"}:
        return "kg"
    if val in {"PZ", "N.", "N", "PEZZO", "PEZZI", "CAD"}:
        return "pz"
    if val in {"LT", "L", "LITRO", "LITRI"}:
        return "lt"
    return None  # CT, CS, FS and custom pack sizes require explicit mapping.


def _excluded_index(rows: list[list[Any]], food_rows: list[list[Any]]) -> tuple[set[tuple[str, str]], list[dict]]:
    exclusions: set[tuple[str, str]] = set()
    anomalies: list[dict] = []
    for rownum, r in enumerate(rows[1:], start=2):
        if _text(_cell(r, 5)).upper() != "ESCLUSO":
            continue
        product = _text(_cell(r, 1))
        supplier = _text(_cell(r, 2))
        source_row = _cell(r, 0)
        try:
            source_row = int(source_row)
        except (ValueError, TypeError):
            anomalies.append({"tab": EXCLUSION_TAB, "row": rownum,
                              "code": "invalid_exclusion_row"})
            # Still exclude by verified product + supplier.
            source_row = None
        if source_row and (source_row < 2 or source_row > len(food_rows)
                           or _label(_cell(food_rows[source_row - 1], 0)) != _label(product)):
            anomalies.append({"tab": EXCLUSION_TAB, "row": rownum,
                              "code": "exclusion_row_drift", "product": product})
        if not product or not supplier:
            anomalies.append({"tab": EXCLUSION_TAB, "row": rownum,
                              "code": "incomplete_exclusion"})
            continue
        exclusions.add((_label(product), _label(supplier)))
    return exclusions, anomalies


def stage_snapshot(
    value_ranges: Mapping[str, list[list[Any]]],
    *,
    spreadsheet_id: str = "",
    notes: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Return an immutable-in-spirit preview; no persistent writes or network calls."""
    notes = notes or {}
    food_rows = value_ranges.get("FOOD", [])
    exclusions, warnings = _excluded_index(
        value_ranges.get(EXCLUSION_TAB, []), food_rows
    )
    candidates: list[dict] = []
    sector_summary: list[dict] = []
    missing_sources: list[str] = []
    for layout in SOURCES:
        if layout.title == "FOOD" and EXCLUSION_TAB not in value_ranges:
            missing_sources.append(EXCLUSION_TAB)
            warnings.append({"tab": layout.title, "code": "missing_exclusions_fail_closed"})
            continue
        rows = value_ranges.get(layout.title)
        if rows is None:
            missing_sources.append(layout.title)
            continue
        if not rows:
            warnings.append({"tab": layout.title, "code": "empty_source"})
            continue
        hdr = rows[0]
        # Fail closed if the supplier order in Sheets diverges from our mapping.
        for col in layout.columns:
            actual = _text(_cell(hdr, col.index))
            expected = col.name
            if layout.title == "GIOCATTOLI":
                continue  # L/M are pricing columns but not supplier names.
            if _label(actual) != _label(expected):
                warnings.append({"tab": layout.title, "code": "supplier_header_mismatch",
                                 "column": _column(col.index), "actual": actual,
                                 "expected": expected})
                missing_sources.append(layout.title)
                break
        if layout.title in missing_sources:
            continue
        seen_products: set[str] = set()
        tally = {"sector": layout.sector, "tab": layout.title, "products": 0,
                 "quotes": 0, "excluded": 0, "blocked": 0, "review": 0,
                 "skipped_empty": 0, "duplicate_products": 0}
        for rownum, row in enumerate(rows[layout.first_row - 1:layout.max_rows],
                                      start=layout.first_row):
            product = _text(_cell(row, layout.product_index))
            if not product:
                continue
            if _label(product) in seen_products:
                tally["duplicate_products"] += 1
                warnings.append({"tab": layout.title, "row": rownum,
                                 "code": "duplicate_product_name", "product": product})
            seen_products.add(_label(product))
            tally["products"] += 1
            base_uom = _text(_cell(row, layout.unit_index))
            for supplier in layout.columns:
                raw = _cell(row, supplier.index)
                value, value_state = _price(raw)
                if value_state == "missing":
                    tally["skipped_empty"] += 1
                    continue
                issues: list[str] = []
                status = "needs_approval"  # NEVER auto-authorize from a spreadsheet.
                price_uom = (_text(_cell(row, supplier.unit_index))
                             if supplier.unit_index is not None else base_uom)
                if value_state != "valid":
                    status = "blocked"
                    issues.append(value_state)
                if (_label(product), _label(supplier.name)) in exclusions and layout.title == "FOOD":
                    status = "blocked"
                    issues.append("sheet_exclusion")
                if layout.reference_only:
                    issues.append("supplier_identity_and_net_price_need_verification")
                if layout.title == "FRUTTA E VERDURA" and supplier.unit_index is not None:
                    wanted, quoted = _base_unit(base_uom), _base_unit(price_uom)
                    if wanted is None or quoted is None:
                        issues.append("unit_mapping_needed")
                    elif wanted != quoted:
                        status = "blocked"
                        issues.append("unit_mismatch_needs_conversion")
                if not base_uom or not price_uom:
                    issues.append("unit_not_specified")
                if value is not None and Decimal(value).as_tuple().exponent < -4:
                    issues.append("precision_review")
                if layout.title == "BEVERAGE" and supplier.name == "ORIZZONTI":
                    issues.append("derived_supplier_lookup")
                # An item is not a pattuito until Price Sentinel confirms the
                # agreed price, source and effective date.
                issues.extend(("canonical_id_not_mapped", "agreement_not_approved"))
                if status == "blocked":
                    tally["blocked"] += 1
                else:
                    tally["review"] += 1
                if "sheet_exclusion" in issues:
                    tally["excluded"] += 1
                tally["quotes"] += 1
                cellref = f"{_column(supplier.index)}{rownum}"
                original_note = notes.get(layout.title, {}).get(cellref)
                supplier_note = _text(_cell(row, supplier.note_index))
                packaging_note = _text(_cell(row, layout.packaging_note_index))
                data = {
                    "sector": layout.sector, "source_sheet": layout.title,
                    "source_row": rownum, "source_cell": cellref, "product": product,
                    "supplier": supplier.name, "reference_unit": base_uom,
                    "supplier_price_unit": price_uom, "quoted_value": raw,
                    "numeric_price": value, "status": status, "reasons": sorted(set(issues)),
                    "row_note": supplier_note or None,
                    "packaging_note": packaging_note or None,
                    "cell_note": original_note or None,
                }
                # Hash is an observation fingerprint, NOT the canonical product key.
                stable = {k: v for k, v in data.items() if k not in {"source_row", "source_cell"}}
                data["observation_hash"] = hashlib.sha256(
                    json.dumps(stable, ensure_ascii=False, sort_keys=True, default=str)
                    .encode("utf-8")
                ).hexdigest()
                candidates.append(data)
        sector_summary.append(tally)
    report = {
        "mode": "dry_run_only",
        "spreadsheet_id": spreadsheet_id,
        "source_title_expected": "santo graal",
        "no_contract_writes": True,
        "candidate_count": len(candidates),
        "sector_summary": sector_summary,
        "missing_sources": sorted(set(missing_sources)),
        "warnings": warnings,
        "candidates": candidates,
        "rules": {
            "agreement": "valid_until_next_approved_listino_unless_explicit_expiry",
            "auto_commit_enabled": False,
            "canonical_product_mapping": "requires_explicit_approval",
            "source": "Google Sheets staging, not approved supplier contract",
        },
    }
    return report
