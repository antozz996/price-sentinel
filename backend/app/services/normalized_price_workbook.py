"""Read-only parser for the normalized PRICE SENTINEL category workbook."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
from io import BytesIO
import re
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter


EXPECTED_TABS = {
    "FOOD": "Food",
    "BEVERAGE": "Beverage",
    "FRUTTA E VERDURA": "Food",
    "MATERIALI": "Materiali",
    "GIOCATTOLI": "Giocattoli",
    "ALTRO": "Altro",
}
REQUIRED_HEADERS = {
    "sottocategoria": "Sottocategoria",
    "prodotto di riferimento": "Prodotto di riferimento",
    "fornitore": "Fornitore",
    "dicitura del fornitore": "Dicitura del fornitore",
    "codice fornitore": "Codice fornitore",
    "marca": "Marca",
    "formato / confezione": "Formato / confezione",
    "prezzo confezione": "Prezzo confezione",
    "quantita confronto": "Quantità confronto",
    "unita confronto": "Unità confronto",
    "prezzo unitario": "Prezzo unitario",
    "stato": "Stato",
    "origine": "Origine",
    "data prezzo": "Data prezzo",
    "cadenza aggiornamento": "Cadenza aggiornamento",
}
APPROVED_STATUS = "prezzo attuale approvato"
EXCLUDED_STATUS = "duplicata - non importare"


def _normalize(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("à", "a").replace("á", "a").replace("è", "e").replace("é", "e")
    text = text.replace("ì", "i").replace("ò", "o").replace("ù", "u")
    return re.sub(r"\s+", " ", text)


def _text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _parse_price(value: Any) -> tuple[str | None, str]:
    if value is None or isinstance(value, bool):
        return None, "missing"
    if isinstance(value, (int, float, Decimal)):
        raw = str(value)
    else:
        raw = _text(value)
        if not raw:
            return None, "missing"
        raw = re.sub(r"^(?:€|EUR)\s*|\s*(?:€|EUR)$", "", raw, flags=re.IGNORECASE).strip()
        raw = raw.replace(" ", "")
        # Accept unambiguous Italian decimal notation and grouped thousands.
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d+", raw):
            raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"\d+(?:,\d+)?", raw):
            raw = raw.replace(",", ".")
        elif not re.fullmatch(r"\d+(?:\.\d+)?", raw):
            return None, "invalid_price"
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None, "invalid_price"
    if not amount.is_finite() or amount <= 0:
        return None, "zero_or_negative"
    return format(amount, "f"), "valid"


def parse_normalized_price_workbook(file_bytes: bytes) -> dict[str, Any]:
    """Return the same candidate shape as the Google Sheet dry-run, without DB writes."""
    try:
        workbook = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("File Excel non leggibile. Usa il workbook migrato in formato .xlsx.") from exc

    try:
        missing = sorted(set(EXPECTED_TABS) - set(workbook.sheetnames))
        if missing:
            raise ValueError("Nel file mancano le schede categoria: " + ", ".join(missing))

        candidates: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        sector_summary: list[dict[str, Any]] = []
        duplicate_keys: Counter[tuple[str, str, str]] = Counter()
        staged_rows: list[dict[str, Any]] = []
        excluded_count = 0

        for tab, sector in EXPECTED_TABS.items():
            sheet = workbook[tab]
            iterator = sheet.iter_rows(values_only=True)
            header: list[Any] | None = None
            header_row_number = 0
            for row_number, row in enumerate(iterator, start=1):
                normalized_headers = {_normalize(value): index for index, value in enumerate(row) if value is not None}
                if set(REQUIRED_HEADERS).issubset(normalized_headers):
                    header = list(row)
                    header_row_number = row_number
                    break
                if row_number >= 15:
                    break
            if header is None:
                raise ValueError(f"La scheda {tab} non contiene l’intestazione prevista del file migrato.")
            indices = {_normalize(value): index for index, value in enumerate(header) if value is not None}
            tally = {"sector": sector, "tab": tab, "products": 0, "quotes": 0,
                     "excluded": 0, "blocked": 0, "review": 0, "skipped_empty": 0,
                     "duplicate_products": 0}
            seen_product_names: set[str] = set()
            for row_number, row in enumerate(iterator, start=header_row_number + 1):
                if row_number - header_row_number > 5000:
                    raise ValueError(f"La scheda {tab} supera il limite di 5.000 righe dati.")
                product = _text(row[indices["prodotto di riferimento"]] if indices["prodotto di riferimento"] < len(row) else None)
                supplier = _text(row[indices["fornitore"]] if indices["fornitore"] < len(row) else None)
                if not product and not supplier:
                    continue
                if not product or not supplier:
                    warnings.append({"tab": tab, "row": row_number, "code": "incomplete_offer_row"})
                    continue

                state = _normalize(row[indices["stato"]] if indices["stato"] < len(row) else None)
                if state == EXCLUDED_STATUS:
                    excluded_count += 1
                    tally["excluded"] += 1
                    continue

                tally["products"] += int(_normalize(product) not in seen_product_names)
                seen_product_names.add(_normalize(product))
                base_unit = _text(row[indices["unita confronto"]] if indices["unita confronto"] < len(row) else None)
                raw_price = row[indices["prezzo unitario"]] if indices["prezzo unitario"] < len(row) else None
                price, price_state = _parse_price(raw_price)
                reasons: list[str] = ["canonical_id_not_mapped"]
                status = "needs_mapping"
                if state != APPROVED_STATUS:
                    status = "blocked"
                    reasons.append("not_current_approved")
                if price_state != "valid":
                    status = "blocked"
                    reasons.append(price_state)
                if not base_unit:
                    status = "blocked"
                    reasons.append("unit_not_specified")
                elif _normalize(base_unit) == "altro":
                    status = "blocked"
                    reasons.append("unit_mapping_needed")
                if price is not None and Decimal(price).as_tuple().exponent < -4:
                    reasons.append("precision_review")

                subcategory = _text(row[indices["sottocategoria"]] if indices["sottocategoria"] < len(row) else None) or None
                if tab == "FRUTTA E VERDURA" and not subcategory:
                    subcategory = "Frutta"
                offer = {
                    "sector": sector,
                    "subcategory": subcategory,
                    "source_sheet": tab,
                    "source_row": row_number,
                    "source_original_row": row_number,
                    "source_cell": f"{get_column_letter(indices['prezzo unitario'] + 1)}{row_number}",
                    "product": product,
                    "supplier": supplier,
                    "price_role": "negotiated_agreement",
                    "requires_product_mapping": True,
                    "reference_unit": base_unit or None,
                    "supplier_price_unit": base_unit or None,
                    "quoted_value": raw_price,
                    "numeric_price": price,
                    "status": status,
                    "reasons": reasons,
                    "row_note": _text(row[indices["dicitura del fornitore"]] if indices["dicitura del fornitore"] < len(row) else None) or None,
                    "packaging_note": "; ".join(
                        f"{label}: {value}" for key, label in (
                            ("codice fornitore", "Codice fornitore"), ("marca", "Marca"),
                            ("formato / confezione", "Formato / confezione"),
                            ("prezzo confezione", "Prezzo confezione"),
                            ("quantita confronto", "Quantità confronto"),
                            ("unita confronto", "Unità confronto"),
                        )
                        if (value := _text(row[indices[key]] if indices[key] < len(row) else None))
                    ) or None,
                    "cell_note": _text(row[indices["origine"]] if indices["origine"] < len(row) else None) or None,
                }
                if state != APPROVED_STATUS:
                    reasons.append("not_current_approved")
                duplicate_key = (tab, _normalize(product), _normalize(supplier))
                duplicate_keys[duplicate_key] += 1
                staged_rows.append(offer)
                tally["quotes"] += 1
            sector_summary.append(tally)

        duplicate_offer_count = 0
        for offer in staged_rows:
            duplicate_key = (offer["source_sheet"], _normalize(offer["product"]), _normalize(offer["supplier"]))
            if duplicate_keys[duplicate_key] > 1:
                offer["status"] = "blocked"
                offer["reasons"] = sorted(set(offer["reasons"] + ["duplicate_supplier_product_offer"]))
                duplicate_offer_count += 1
            if offer["status"] == "blocked":
                next(item for item in sector_summary if item["tab"] == offer["source_sheet"])["blocked"] += 1
            else:
                next(item for item in sector_summary if item["tab"] == offer["source_sheet"])["review"] += 1
            candidates.append(offer)

        if len(candidates) > 5000:
            raise ValueError("Il workbook supera il limite di 5.000 offerte per un’unica anteprima.")

        if excluded_count:
            warnings.append({"code": "explicitly_excluded_rows", "count": excluded_count})
        if duplicate_offer_count:
            warnings.append({"code": "duplicate_supplier_product_offer", "count": duplicate_offer_count})
        return {
            "mode": "dry_run_only",
            "spreadsheet_id": "workbook:" + hashlib.sha256(file_bytes).hexdigest(),
            "source_title_expected": "PRICE SENTINEL — SANTO GRAAL migrato",
            "workbook_title": "PRICE SENTINEL — SANTO GRAAL migrato",
            "no_contract_writes": True,
            "candidate_count": len(candidates),
            "sector_summary": sector_summary,
            "food_audit": None,
            "missing_sources": [],
            "warnings": warnings,
            "candidates": candidates,
            "rules": {
                "agreement": "valid_until_next_approved_listino_unless_explicit_expiry",
                "auto_commit_enabled": False,
                "canonical_product_mapping": "required_before_import",
                "source": "Prezzi correnti approvati del workbook migrato.",
                "price_semantics": "negotiated_agreement",
            },
            "excluded_count": excluded_count,
        }
    finally:
        workbook.close()
