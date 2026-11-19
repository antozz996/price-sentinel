"""Riapre i prezzi chiusi solo perché il modulo diceva «valido fino al».

Regola nuova: se il fornitore non manda il listino nuovo, restano i prezzi a sistema.
Prima l'approvazione di un modulo metteva come scadenza la data «valido fino al»:
qui si tolgono quelle scadenze, solo dove il prezzo è ancora l'ultimo di quel
fornitore per quel prodotto (nessun prezzo successivo dello stesso fornitore).

Senza --commit mostra cosa farebbe e non salva nulla.
    docker compose ... exec -T backend python -m scripts.riapri_prezzi_moduli [--commit]
"""
import argparse
import asyncio
from collections import Counter

from sqlalchemy import and_, select

from app.database import async_session_factory, engine
from app.models.fornitori import Fornitore
from app.models.listino import ORIGINE_MODULO_FORNITORE, ListinoMaster
from app.models.supplier_price_form import SupplierPriceFormRequest


async def run(commit: bool) -> None:
    async with async_session_factory() as db:
        windows = set((await db.execute(select(
            SupplierPriceFormRequest.supplier_id, SupplierPriceFormRequest.validita_inviata_da,
            SupplierPriceFormRequest.validita_inviata_a,
        ).where(
            SupplierPriceFormRequest.status == "approved",
            SupplierPriceFormRequest.validita_inviata_a.is_not(None),
        ))).all())
        rows = (await db.execute(select(ListinoMaster).where(
            ListinoMaster.origine == ORIGINE_MODULO_FORNITORE,
            ListinoMaster.data_scadenza.is_not(None),
        ).with_for_update())).scalars().all()
        candidates = [r for r in rows if (r.fornitore_id, r.data_inizio_validita, r.data_scadenza) in windows]
        reopened = []
        for row in candidates:
            newer = await db.scalar(select(ListinoMaster.id).where(
                ListinoMaster.fornitore_id == row.fornitore_id,
                ListinoMaster.sku_interno == row.sku_interno,
                ListinoMaster.id != row.id,
                ListinoMaster.data_inizio_validita > row.data_inizio_validita,
            ).limit(1))
            open_twin = await db.scalar(select(ListinoMaster.id).where(and_(
                ListinoMaster.fornitore_id == row.fornitore_id,
                ListinoMaster.supplier_product_alias_id == row.supplier_product_alias_id,
                ListinoMaster.id != row.id,
                ListinoMaster.data_scadenza.is_(None),
            )).limit(1)) if row.supplier_product_alias_id else None
            if newer or open_twin:
                continue
            reopened.append((row.fornitore_id, row.data_scadenza))
            row.data_scadenza = None
        names = dict((await db.execute(select(Fornitore.id, Fornitore.nome_azienda))).all())
        print(f"Prezzi da moduli con scadenza: {len(rows)} · legati a «valido fino al»: {len(candidates)} · da riaprire: {len(reopened)}")
        for (supplier_id, end), count in sorted(Counter(reopened).items(), key=lambda kv: kv[0][1]):
            print(f"  {names.get(supplier_id, supplier_id)}: {count} prezzi che scadevano il {end:%d/%m/%Y}")
        if commit:
            await db.commit()
            print("Salvato.")
        else:
            await db.rollback()
            print("Prova a secco: nulla salvato. Per salvare aggiungere --commit.")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    asyncio.run(run(parser.parse_args().commit))
