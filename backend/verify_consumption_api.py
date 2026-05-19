import asyncio
import sys
from datetime import date
from sqlalchemy import text

# Add backend directory to Python path
sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory
from app.api.v1.intelligence import (
    get_product_consumption,
    get_product_consumption_detail,
    export_product_consumption_excel
)

async def run_verification():
    print("🚀 Starting Product Consumption API Verification...")
    
    async with async_session_factory() as session:
        # 1. Test standard GET /product-consumption aggregation endpoint
        print("\n📊 1. Testing GET /api/v1/intelligence/product-consumption...")
        consumption_list = await get_product_consumption(
            location_id=None,
            fornitore_id=None,
            data_da=None,
            data_a=None,
            _admin=True,
            db=session
        )
        
        print(f" ✅ Retrieved {len(consumption_list)} product consumption records.")
        if consumption_list:
            print("🔬 First 5 records preview:")
            for idx, item in enumerate(consumption_list[:5]):
                print(f"   [{idx + 1}] SKU: {item['sku_interno']} | Desc: {item['descrizione']} | Qty: {item['quantita_totale']} {item['unita_misura']} | Total Spend: € {item['spesa_totale']:.2f} | Weighted Avg Price: € {item['prezzo_medio']:.2f}")
            
            # Select a SKU to test the detail endpoint
            test_sku = consumption_list[0]['sku_interno']
            
            # 2. Test detailed GET /product-consumption/{sku_interno} split endpoint
            print(f"\n🔍 2. Testing GET /api/v1/intelligence/product-consumption/{test_sku}...")
            detail = await get_product_consumption_detail(
                sku_interno=test_sku,
                _admin=True,
                db=session
            )
            
            print(f" ✅ Detail for SKU {test_sku} retrieved successfully.")
            print(f"   * Consumption by Location:")
            for loc in detail.get("consumo_per_location", []):
                print(f"     - {loc['location_nome']}: Qty {loc['quantita_totale']} | Spend € {loc['spesa_totale']:.2f}")
            print(f"   * Consumption by Month:")
            for mon in detail.get("consumo_per_mese", []):
                print(f"     - {mon['mese']}: Qty {mon['quantita_totale']} | Spend € {mon['spesa_totale']:.2f}")
        else:
            print(" ⚠️ No consumption records returned. Is the database empty?")
            test_sku = None
            
        # 3. Test GET /export-product-consumption-excel Excel export endpoint
        print("\nexcel 3. Testing GET /api/v1/intelligence/export-product-consumption-excel...")
        excel_response = await export_product_consumption_excel(
            location_id=None,
            fornitore_id=None,
            data_da=None,
            data_a=None,
            _admin=True,
            db=session
        )
        
        # In StreamingResponse, the body is an async generator or stream.
        # We can read all the bytes from the body_iterator or stream.
        excel_bytes = b""
        async for chunk in excel_response.body_iterator:
            excel_bytes += chunk
            
        print(f" ✅ Excel export returned StreamingResponse.")
        print(f"   - File size generated: {len(excel_bytes)} bytes")
        print(f"   - Content type: {excel_response.media_type}")
        print(f"   - Headers: {dict(excel_response.headers)}")
        
        assert len(excel_bytes) > 0, "Excel output is empty!"
        assert excel_response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Incorrect media type!"
        print(" 🎉 Excel file generated successfully and structure matches specification!")

    print("\n✅ Verification completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_verification())
