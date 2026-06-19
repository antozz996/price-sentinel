import asyncio
import sys
from datetime import date

# Add backend directory to Python path
sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory
from app.api.v1.intelligence import get_cross_supplier_matrix, export_vendor_passport

async def run_tests():
    print("🚀 Starting Cross-Supplier Date Filter Integration Tests...")
    
    async with async_session_factory() as session:
        # Test 1: Get complete cross-supplier matrix (no date filters)
        print("\n📊 Test 1: Getting cross-supplier matrix without filters...")
        matrix_all = await get_cross_supplier_matrix(
            db=session,
            _admin=True
        )
        print(f" ✅ Success! Retrieved {len(matrix_all)} SKU entries.")

        # Test 2: Get cross-supplier matrix with date range
        print("\n📊 Test 2: Getting cross-supplier matrix with date range...")
        data_da = date(2026, 1, 1)
        data_a = date(2026, 6, 19)
        matrix_filtered = await get_cross_supplier_matrix(
            data_da=data_da,
            data_a=data_a,
            db=session,
            _admin=True
        )
        print(f" ✅ Success! Retrieved {len(matrix_filtered)} SKU entries with date filters active.")
        
        # Test 3: Export Vendor Passport PDF with date range
        print("\n📊 Test 3: Testing export-vendor-passport with date range...")
        # Get first supplier ID from listini
        from app.models.fornitori import Fornitore
        from sqlalchemy import select
        supplier = await session.scalar(select(Fornitore).limit(1))
        if supplier:
            print(f"   Using Supplier: {supplier.nome_azienda} (ID: {supplier.id})")
            pdf_res = await export_vendor_passport(
                fornitore_id=supplier.id,
                data_da=data_da,
                data_a=data_a,
                db=session,
                _admin=True
            )
            print(f" ✅ Success! Generated passport PDF: {len(pdf_res.body)} bytes.")
        else:
            print(" ⚠️ No suppliers found to test passport export.")

    print("\n🎉 All integration tests passed successfully!")

if __name__ == "__main__":
    asyncio.run(run_tests())
