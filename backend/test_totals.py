import asyncio
import re
from sqlalchemy import select
from app.database import async_session_factory
from app.models.fatture import XMLRaw
from decimal import Decimal

async def main():
    async with async_session_factory() as session:
        result = await session.execute(select(XMLRaw.payload))
        payloads = result.scalars().all()
        
        sum_imponibile_td01 = Decimal("0")
        sum_imposta_td01 = Decimal("0")
        sum_totale_doc_td01 = Decimal("0")
        
        sum_imponibile_td04 = Decimal("0")
        sum_imposta_td04 = Decimal("0")
        sum_totale_doc_td04 = Decimal("0")
        
        for payload in payloads:
            # Extract TipoDocumento
            tipo_match = re.search(r'<TipoDocumento>(.*?)</TipoDocumento>', payload)
            tipo = tipo_match.group(1).strip() if tipo_match else "TD01"
            
            # Extract ImponibileImporto from DatiRiepilogo
            imponibili = re.findall(r'<ImponibileImporto>\s*([\d\.]+)\s*</ImponibileImporto>', payload)
            imponibile_val = sum(Decimal(x) for x in imponibili)
            
            # Extract Imposta from DatiRiepilogo
            imposte = re.findall(r'<Imposta>\s*([\d\.]+)\s*</Imposta>', payload)
            imposta_val = sum(Decimal(x) for x in imposte)
            
            # Extract ImportoTotaleDocumento if exists
            tot_doc_match = re.search(r'<ImportoTotaleDocumento>\s*([\d\.]+)\s*</ImportoTotaleDocumento>', payload)
            if tot_doc_match:
                tot_doc_val = Decimal(tot_doc_match.group(1))
            else:
                tot_doc_val = Decimal("0")
            
            if tipo == "TD04":
                sum_imponibile_td04 += imponibile_val
                sum_imposta_td04 += imposta_val
                sum_totale_doc_td04 += tot_doc_val
            else:
                sum_imponibile_td01 += imponibile_val
                sum_imposta_td01 += imposta_val
                sum_totale_doc_td01 += tot_doc_val
                
        print("\n=== TD01 (FATTURE ATTIVE) ===")
        print(f"Imponibile: € {sum_imponibile_td01:.2f}")
        print(f"Imposta:    € {sum_imposta_td01:.2f}")
        print(f"Lordo (Imp+Imp): € {sum_imponibile_td01 + sum_imposta_td01:.2f}")
        print(f"ImportoTotaleDocumento (se presente): € {sum_totale_doc_td01:.2f}")
        
        print("\n=== TD04 (NOTE DI CREDITO) ===")
        print(f"Imponibile: € {sum_imponibile_td04:.2f}")
        print(f"Imposta:    € {sum_imposta_td04:.2f}")
        print(f"Lordo (Imp+Imp): € {sum_imponibile_td04 + sum_imposta_td04:.2f}")
        print(f"ImportoTotaleDocumento (se presence): € {sum_totale_doc_td04:.2f}")
        
        print("\n=== CONFRONTO ===")
        net_imponibile = sum_imponibile_td01 - sum_imponibile_td04
        net_lordo = (sum_imponibile_td01 + sum_imposta_td01) - (sum_imponibile_td04 + sum_imposta_td04)
        print(f"Netto Imponibile: € {net_imponibile:.2f}")
        print(f"Netto Lordo (Imponibile + Imposta): € {net_lordo:.2f}")

if __name__ == "__main__":
    asyncio.run(main())
