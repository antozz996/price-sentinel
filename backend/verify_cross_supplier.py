import asyncio
import sys

# Add backend directory to Python path
sys.path.append("/root/PRICE SENTINEL/backend")

from app.database import async_session_factory
from app.api.v1.intelligence import get_cross_supplier_matrix

async def run_verification():
    print("🚀 Starting Cross-Supplier Pricing Matrix API Verification...")
    
    async with async_session_factory() as session:
        print("\n📊 Testing GET /api/v1/intelligence/cross-supplier...")
        matrix = await get_cross_supplier_matrix(
            db=session,
            _admin=True
        )
        
        print(f" ✅ Retrieved matrix with {len(matrix)} SKU entries.")
        if matrix:
            print("🔬 First 5 SKU entries preview:")
            for idx, (sku, data) in enumerate(list(matrix.items())[:5]):
                print(f"   [{idx + 1}] SKU: {sku} | Desc: {data['descrizione']}")
                for forn_id, price_info in data["prezzi"].items():
                    print(f"     - Supplier ID {forn_id}: Price €{price_info['prezzo']:.2f} ({price_info['tipo']})")
        else:
            print(" ⚠️ No products in matrix. Is the database empty or contains no valid matched/contract data?")
            
    print("\n✅ Verification completed successfully!")

if __name__ == "__main__":
    asyncio.run(run_verification())
