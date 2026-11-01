"""Focused, dependency-light checks for the new Santo Graal workbook import."""

from test_normalized_price_workbook import (
    test_new_workbook_does_not_treat_multi_unit_package_amount_as_unit_price,
    test_new_workbook_imports_package_prices_without_units_and_ignores_old_supplier_ids,
)


if __name__ == "__main__":
    test_new_workbook_imports_package_prices_without_units_and_ignores_old_supplier_ids()
    print("PASS: workbook imports per-source product IDs, package prices and supplier sectors")
    test_new_workbook_does_not_treat_multi_unit_package_amount_as_unit_price()
    print("PASS: package price is never converted to a unit price without confirmation")
