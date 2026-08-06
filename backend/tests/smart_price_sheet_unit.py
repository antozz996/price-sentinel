"""Database-free regression tests for clipboard parsing and purchase ranking."""

import json
from decimal import Decimal

from app.services.purchase_recommendation import rank_supplier_offers
from app.services.smart_price_sheet import parse_clipboard_table, parse_decimal_price


results: list[str] = []


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    results.append(name)


def offer(supplier_id: int, price: str, source: str = "contratto") -> dict:
    return {
        "supplier_id": supplier_id,
        "supplier_name": f"Supplier {supplier_id}",
        "unit_price_normalized": price,
        "source_type": source,
    }


table = parse_clipboard_table("Prodotto\tSupplier A\tSupplier B\nAcqua\t1,20\t1.18\nVino\t\t8")
check("TSV headers", table["supplier_headers"] == ["Supplier A", "Supplier B"])
check("blank cells preserved", table["rows"][1]["values"] == ["", "8"])

csv_table = parse_clipboard_table('Prodotto;Supplier A\n"Acqua, vetro";1,25')
check("semicolon CSV quoted value", csv_table["rows"][0]["product_ref"] == "Acqua, vetro")
check("Italian decimal", parse_decimal_price("€ 1.234,5678") == Decimal("1234.5678"))
check("international decimal", parse_decimal_price("1,234.50") == Decimal("1234.50"))
check("empty price ignored", parse_decimal_price("-") is None)

try:
    parse_decimal_price("1,12345")
    raise AssertionError("too many decimals accepted")
except ValueError:
    results.append("too many decimals rejected")

base = rank_supplier_offers([offer(1, "9.90"), offer(2, "10.00")])
check("default chooses cheapest", base["selected_offer"]["supplier_id"] == 1)
check("cheapest is explicit", base["absolute_cheapest"]["supplier_id"] == 1)

blocked = rank_supplier_offers(
    [offer(1, "8.00"), offer(2, "9.00")],
    {1: {"status": "blocked", "quality_score": 5, "reason": "quality incident"}},
)
check("blocked cheapest not recommended", blocked["recommended_offer"]["supplier_id"] == 2)
check("blocked remains visible as absolute", blocked["absolute_cheapest"]["supplier_id"] == 1)

quality = rank_supplier_offers(
    [offer(1, "10.00"), offer(2, "10.40")],
    {
        1: {"status": "approved", "quality_score": 2},
        2: {"status": "approved", "quality_score": 5},
    },
    {"minimum_quality": 1, "max_price_premium_percent": "5"},
)
check("quality can win inside premium", quality["recommended_offer"]["supplier_id"] == 2)

preferred = rank_supplier_offers(
    [offer(1, "10.00"), offer(2, "10.30")],
    policy={"preferred_supplier_id": 2, "max_price_premium_absolute": "0.50"},
)
check("preferred wins inside absolute premium", preferred["recommended_offer"]["supplier_id"] == 2)

spot = rank_supplier_offers(
    [offer(1, "7.00", "spot"), offer(2, "8.00")],
    policy={"allow_spot": False},
)
check("spot excluded by policy", spot["recommended_offer"]["supplier_id"] == 2)

manual = rank_supplier_offers(
    [offer(1, "10.00")],
    policy={"selection_mode": "manual", "preferred_supplier_id": 1},
)
check("manual uses configured supplier", manual["recommended_offer"]["supplier_id"] == 1 and manual["selected_offer"]["supplier_id"] == 1)
check("valid manual policy needs no further choice", manual["requires_manual_selection"] is False)

absolute_mode = rank_supplier_offers(
    [offer(1, "8.00"), offer(2, "9.00")],
    {1: {"status": "blocked", "quality_score": 1}},
    {"selection_mode": "absolute_lowest"},
)
check("absolute mode keeps qualitative warning", absolute_mode["selected_offer"]["supplier_id"] == 1 and bool(absolute_mode["warnings"]))

no_offer = rank_supplier_offers(
    [offer(1, "10.00")],
    {1: {"status": "discouraged", "quality_score": 5}},
)
check("all ineligible requires review", no_offer["recommended_offer"] is None and bool(no_offer["warnings"]))

print(json.dumps({"status": "PASS", "tests": len(results), "results": results}, indent=2))
