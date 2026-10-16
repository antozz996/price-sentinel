"""Read-only normalization of agreed supplier prices from the Santo Graal workbook.

NO database imports or writes. Commercial agreement is established by the source
workbook; candidates still need product/supplier identity mapping and data checks.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    subcategory: str | None = None
    source_row_index: int | None = None
    first_row: int = 2
    reference_only: bool = False
    packaging_note_index: int | None = None
    max_columns: str = "O"
    max_rows: int = 1000


SOURCES = (
    SheetLayout("Carne", "Food", 0, 1, (
        SupplierColumn(2, "MARR"), SupplierColumn(3, "MELIUS"),
        SupplierColumn(4, "DAC"), SupplierColumn(5, "ORIZZONTI", note_index=6),
        SupplierColumn(7, "DI PALO"), SupplierColumn(8, "FONTANELLA CARNI"),
    ), subcategory="Carne", source_row_index=10, max_columns="L"),
    SheetLayout("Pesce", "Food", 0, 1, (
        SupplierColumn(2, "MARR"), SupplierColumn(3, "MELIUS"),
        SupplierColumn(4, "DAC"), SupplierColumn(5, "ORIZZONTI", note_index=6),
        SupplierColumn(7, "DI PALO"), SupplierColumn(8, "FONTANELLA CARNI"),
    ), subcategory="Pesce", source_row_index=10, max_columns="L"),
    SheetLayout("Varie", "Food", 0, 1, (
        SupplierColumn(2, "MARR"), SupplierColumn(3, "MELIUS"),
        SupplierColumn(4, "DAC"), SupplierColumn(5, "ORIZZONTI", note_index=6),
        SupplierColumn(7, "DI PALO"), SupplierColumn(8, "FONTANELLA CARNI"),
    ), source_row_index=10, max_columns="L"),
    SheetLayout("BEVERAGE", "Beverage", 0, 1, (
        SupplierColumn(2, "NAVAS"), SupplierColumn(3, "ORIZZONTI"),
        SupplierColumn(4, "3F"), SupplierColumn(5, "PASCARELLA"),
        SupplierColumn(6, "CASA D'AMBRA"),
    ), max_columns="L"),
    SheetLayout("COMPARAZIONE MATERIALI", "Materiali", 1, 2, (
        SupplierColumn(3, "VEMO"), SupplierColumn(4, "KITO"),
        SupplierColumn(5, "EUROCARTA"), SupplierColumn(6, "ALPHA"),
        SupplierColumn(7, "PROMOCART", note_index=9),
        SupplierColumn(8, "MUNDO"),
    ), packaging_note_index=11, max_columns="N"),
    SheetLayout("FRUTTA E VERDURA", "Food", 0, 1, (
        SupplierColumn(2, "MG FRUTTA", note_index=3),
        SupplierColumn(4, "DEMETRA", unit_index=5, note_index=6),
        SupplierColumn(7, "BONTA DELL'ORTO", unit_index=8, note_index=9),
    ), subcategory="Frutta", max_columns="J"),
    SheetLayout("GIOCATTOLI", "Giocattoli", 2, 3, (
        SupplierColumn(11, "ANTONIO"), SupplierColumn(12, "GIOVANNI"),
    ), reference_only=True, packaging_note_index=6, max_columns="O"),
)
FOOD_CATEGORY_TABS = frozenset({"Carne", "Pesce", "Varie"})

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


def _header_index(header: list[Any], name: str) -> int | None:
    wanted = _label(name)
    return next((i for i, value in enumerate(header) if _label(value) == wanted), None)


def _resolve_food_layout(layout: SheetLayout, header: list[Any]) -> SheetLayout:
    """Resolve category-tab columns by header, tolerating inserted description columns."""
    if layout.title not in FOOD_CATEGORY_TABS:
        return layout
    columns = tuple(
        replace(col, index=found) if (found := _header_index(header, col.name)) is not None else col
        for col in layout.columns
    )
    origin_index = _header_index(header, "RIGA FOOD ORIGINALE")
    return replace(
        layout,
        columns=columns,
        source_row_index=origin_index if origin_index is not None else layout.source_row_index,
    )


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


def _food_origin_index(value_ranges: Mapping[str, list[list[Any]]]) -> tuple[dict[int, str], list[dict]]:
    """Map original FOOD row numbers to products using the trace column in split tabs."""
    origins: dict[int, str] = {}
    warnings: list[dict] = []
    for title in FOOD_CATEGORY_TABS:
        rows = value_ranges.get(title)
        if not rows:
            continue
        origin_index = _header_index(rows[0], "RIGA FOOD ORIGINALE")
        if origin_index is None:
            warnings.append({"tab": title, "code": "invalid_food_origin_header"})
            continue
        for rownum, row in enumerate(rows[1:], start=2):
            product = _text(_cell(row, 0))
            if not product:
                continue
            try:
                original_row = int(_cell(row, origin_index))
            except (ValueError, TypeError):
                warnings.append({"tab": title, "row": rownum,
                                 "code": "invalid_food_origin_row"})
                continue
            if original_row < 2:
                warnings.append({"tab": title, "row": rownum,
                                 "code": "invalid_food_origin_row"})
                continue
            if original_row in origins:
                warnings.append({"tab": title, "row": rownum,
                                 "code": "duplicate_food_origin_row"})
                continue
            origins[original_row] = product
    return origins, warnings


def _excluded_index(
    rows: list[list[Any]], food_origins: Mapping[int, str]
) -> tuple[set[tuple[int | None, str, str]], list[dict]]:
    exclusions: set[tuple[int | None, str, str]] = set()
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
            source_row = None
        if source_row is not None and (
            source_row < 2 or _label(food_origins.get(source_row)) != _label(product)
        ):
            anomalies.append({"tab": EXCLUSION_TAB, "row": rownum,
                              "code": "exclusion_row_drift", "product": product})
        if not product or not supplier:
            anomalies.append({"tab": EXCLUSION_TAB, "row": rownum,
                              "code": "incomplete_exclusion"})
            continue
        exclusions.add((source_row, _label(product), _label(supplier)))
    return exclusions, anomalies


def stage_snapshot(
    value_ranges: Mapping[str, list[list[Any]]],
    *,
    spreadsheet_id: str = "",
    notes: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Return an immutable-in-spirit preview; no persistent writes or network calls."""
    notes = notes or {}
    food_origins, origin_warnings = _food_origin_index(value_ranges)
    exclusion_rows = value_ranges.get(EXCLUSION_TAB, [])
    expected_control_headers = {0: "RIGA", 1: "PRODOTTO", 2: "FORNITORE", 5: "STATO"}
    exclusion_valid = bool(exclusion_rows) and all(
        _label(_cell(exclusion_rows[0], index)) == _label(expected)
        for index, expected in expected_control_headers.items()
    )
    exclusions, warnings = _excluded_index(
        exclusion_rows if exclusion_valid else [], food_origins
    )
    warnings.extend(origin_warnings)
    if not exclusion_valid:
        warnings.append({"tab": EXCLUSION_TAB, "code": "invalid_exclusion_register_fail_closed"})
    candidates: list[dict] = []
    sector_summary: list[dict] = []
    missing_sources: list[str] = []
    for base_layout in SOURCES:
        rows = value_ranges.get(base_layout.title)
        layout = _resolve_food_layout(base_layout, rows[0]) if rows else base_layout
        if layout.title in FOOD_CATEGORY_TABS and not exclusion_valid:
            missing_sources.append(EXCLUSION_TAB)
            continue
        rows = value_ranges.get(layout.title)
        if rows is None:
            missing_sources.append(layout.title)
            continue
        if not rows:
            warnings.append({"tab": layout.title, "code": "empty_source"})
            continue
        hdr = rows[0]
        if layout.source_row_index is not None and _label(
            _cell(hdr, layout.source_row_index)
        ) != _label("RIGA FOOD ORIGINALE"):
            warnings.append({"tab": layout.title, "code": "invalid_food_origin_header"})
            missing_sources.append(layout.title)
            continue
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
            source_original_row = None
            if layout.source_row_index is not None:
                try:
                    source_original_row = int(_cell(row, layout.source_row_index))
                    if source_original_row < 2:
                        source_original_row = None
                except (ValueError, TypeError):
                    source_original_row = None
            for supplier in layout.columns:
                raw = _cell(row, supplier.index)
                value, value_state = _price(raw)
                if value_state == "missing":
                    tally["skipped_empty"] += 1
                    continue
                issues: list[str] = []
                status = "needs_mapping"  # Prices are agreed; canonical product/supplier linkage is still needed.
                price_uom = (_text(_cell(row, supplier.unit_index))
                             if supplier.unit_index is not None else base_uom)
                if value_state != "valid":
                    status = "blocked"
                    issues.append(value_state)
                if layout.source_row_index is not None:
                    if source_original_row is None:
                        status = "blocked"
                        issues.append("source_row_reference_missing")
                    elif (
                        (source_original_row, _label(product), _label(supplier.name)) in exclusions
                        or (None, _label(product), _label(supplier.name)) in exclusions
                    ):
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
                # The price is already commercially agreed; only target identity mapping remains.
                issues.append("canonical_id_not_mapped")
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
                    "sector": layout.sector, "subcategory": layout.subcategory,
                    "source_sheet": layout.title,
                    "source_row": rownum, "source_original_row": source_original_row,
                    "source_cell": cellref, "product": product,
                    "supplier": supplier.name, "price_role": "negotiated_agreement",
                    "requires_product_mapping": True, "reference_unit": base_uom,
                    "supplier_price_unit": price_uom, "quoted_value": raw,
                    "numeric_price": value, "status": status, "reasons": sorted(set(issues)),
                    "row_note": supplier_note or None,
                    "packaging_note": packaging_note or None,
                    "cell_note": original_note or None,
                }
                # Hash is an observation fingerprint, NOT the canonical product key.
                stable = {k: v for k, v in data.items()
                          if k not in {"source_row", "source_original_row", "source_cell"}}
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
            "canonical_product_mapping": "required_before_import",
            "source": "Santo Graal records negotiated supplier prices; no separate commercial approval is required.",
            "price_semantics": "negotiated_agreement",
        },
    }
    return report
