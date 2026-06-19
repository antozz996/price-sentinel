import asyncio
import sys
from datetime import date
from sqlalchemy import text

sys.path.append("/root/PRICE SENTINEL/backend")
from app.database import async_session_factory
from app.api.v1.intelligence import get_product_consumption_invoices_pdf

async def main():
    print("Testing PDF Generation Endpoint...")
    async with async_session_factory() as session:
        # Find a real SKU and location in the database
        res = await session.execute(text("""
            SELECT rf.sku_interno, f.location_id 
            FROM righe_fattura rf
            JOIN fatture f ON rf.fattura_id = f.id
            WHERE rf.sku_interno IS NOT NULL
            LIMIT 1
        """))
        row = res.first()
        if not row:
            print("No rows found in database!")
            return
            
        sku = row[0]
        location_id = row[1]
        print(f"Using SKU: {sku}, Location ID: {location_id}")
        
        # Test calling get_product_consumption_invoices_pdf with location_ids filter
        pdf_response = await get_product_consumption_invoices_pdf(
            sku_interno=sku,
            location_ids=str(location_id),
            fornitore_id=None,
            data_da=None,
            data_a=None,
            _admin=True,
            db=session
        )
        
        print("PDF Response received:")
        print(f"Status: OK")
        print(f"Media type: {pdf_response.media_type}")
        print(f"Bytes length: {len(pdf_response.body)}")
        print(f"Headers: {dict(pdf_response.headers)}")
        assert len(pdf_response.body) > 0, "PDF output is empty!"
        print("🎉 PDF generated successfully with location filter!")

if __name__ == "__main__":
    asyncio.run(main())
