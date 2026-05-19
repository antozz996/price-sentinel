import asyncio
import re
from sqlalchemy import select
from app.database import async_session_factory
from app.models.fatture import XMLRaw

async def main():
    async with async_session_factory() as session:
        result = await session.execute(select(XMLRaw.payload))
        payloads = result.scalars().all()
        
        cedenti = {}
        cessionari = {}
        
        for payload in payloads:
            # Extract CedentePrestatore block
            cedente_match = re.search(r'<CedentePrestatore>(.*?)</CedentePrestatore>', payload, re.DOTALL)
            if cedente_match:
                ced_block = cedente_match.group(1)
                piva_match = re.search(r'<IdCodice>\s*(\d+)\s*</IdCodice>', ced_block)
                den_match = re.search(r'<Denominazione>\s*(.*?)\s*</Denominazione>', ced_block)
                if piva_match and den_match:
                    cedenti[piva_match.group(1).strip()] = den_match.group(1).strip()
            
            # Extract CessionarioCommittente block
            cessionario_match = re.search(r'<CessionarioCommittente>(.*?)</CessionarioCommittente>', payload, re.DOTALL)
            if cessionario_match:
                cess_block = cessionario_match.group(1)
                piva_match = re.search(r'<IdCodice>\s*(\d+)\s*</IdCodice>', cess_block)
                den_match = re.search(r'<Denominazione>\s*(.*?)\s*</Denominazione>', cess_block)
                if piva_match and den_match:
                    cessionari[piva_match.group(1).strip()] = den_match.group(1).strip()
                    
        print("\n=== FORNITORI TROVATI NEI TUOI XML ===")
        for piva, den in cedenti.items():
            print(f"P.IVA: {piva} | Denominazione: {den}")
            
        print("\n=== LOCATION TROVATE NEI TUOI XML ===")
        for piva, den in cessionari.items():
            print(f"P.IVA: {piva} | Denominazione: {den}")

if __name__ == "__main__":
    asyncio.run(main())
