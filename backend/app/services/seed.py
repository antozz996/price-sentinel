"""
Price Sentinel — Seed Script.
Popola il database con dati iniziali per lo sviluppo:
- 1 Admin utente
- 3 Location di esempio
- 2 Fornitori di esempio
- 5 voci Listino Master di esempio

Eseguire: docker-compose exec backend python -m app.services.seed
"""

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import async_session_factory
from app.models import Base
from app.models.utenti import Utente, RuoloUtente
from app.models.location import Location, TipologiaLocation
from app.models.fornitori import Fornitore
from app.models.listino import ListinoMaster, PFATipo
from app.services.auth import hash_password


async def seed():
    """Popola il database con dati di sviluppo."""

    async with async_session_factory() as session:
        # ── Check se già popolato ──
        existing = await session.execute(select(Utente).limit(1))
        if existing.scalar_one_or_none():
            print("⚠️  Database già popolato. Seed saltato.")
            return

        print("🌱 Seeding database...")

        # ── 1. Admin Utente ──
        admin = Utente(
            email="admin@pricesentinel.it",
            password_hash=hash_password("admin2025!"),
            ruolo=RuoloUtente.admin,
            location_id=None,  # Admin vede tutto
            attivo=True,
        )
        session.add(admin)
        print("  ✅ Admin: admin@pricesentinel.it / admin2025!")

        # ── 2. Location ──
        locations = [
            Location(
                nome_struttura="Lido Playa Luna",
                piva_riferimento="01234567890",
                tipologia=TipologiaLocation.balneare,
            ),
            Location(
                nome_struttura="Ristorante Il Vesuvio",
                piva_riferimento="09876543210",
                tipologia=TipologiaLocation.ristorante,
            ),
            Location(
                nome_struttura="Club Neon Nights",
                piva_riferimento="11223344556",
                tipologia=TipologiaLocation.discoteca,
            ),
        ]
        session.add_all(locations)
        await session.flush()
        print(f"  ✅ {len(locations)} Location create")

        # ── 3. Manager per location 1 ──
        manager = Utente(
            email="manager.playa@pricesentinel.it",
            password_hash=hash_password("manager2025!"),
            ruolo=RuoloUtente.manager,
            location_id=locations[0].id,
            attivo=True,
        )
        session.add(manager)
        print("  ✅ Manager: manager.playa@pricesentinel.it / manager2025!")

        # ── 4. Fornitori ──
        fornitori = [
            Fornitore(
                partita_iva="12345678901",
                nome_azienda="Drinks & Spirits Srl",
                attivo_whitelist=True,
                email_contatto="ordini@drinkspirits.it",
            ),
            Fornitore(
                partita_iva="98765432109",
                nome_azienda="FoodService Italia SpA",
                attivo_whitelist=True,
                email_contatto="fatture@foodservice.it",
            ),
        ]
        session.add_all(fornitori)
        await session.flush()
        print(f"  ✅ {len(fornitori)} Fornitori creati")

        # ── 5. Listino Master ──
        listino_items = [
            ListinoMaster(
                fornitore_id=fornitori[0].id,
                sku_interno="GIN-HENDRICKS-70CL",
                descrizione="Gin Hendrick's 70cl",
                prezzo_pattuito=Decimal("22.5000"),
                unita_misura="Pz",
                data_inizio_validita=date(2025, 1, 1),
                data_scadenza=None,
                pfa_tipo=PFATipo.percentuale,
                pfa_valore=Decimal("0.0200"),
            ),
            ListinoMaster(
                fornitore_id=fornitori[0].id,
                sku_interno="VODKA-BELVEDERE-LT1",
                descrizione="Vodka Belvedere 1 litro",
                prezzo_pattuito=Decimal("28.0000"),
                unita_misura="Pz",
                data_inizio_validita=date(2025, 1, 1),
                data_scadenza=None,
                pfa_tipo=None,
                pfa_valore=None,
            ),
            ListinoMaster(
                fornitore_id=fornitori[0].id,
                sku_interno="RUM-DIPLOMATICO-70CL",
                descrizione="Rum Diplomatico Reserva Exclusiva 70cl",
                prezzo_pattuito=Decimal("32.0000"),
                unita_misura="Pz",
                data_inizio_validita=date(2025, 1, 1),
                data_scadenza=None,
                pfa_tipo=PFATipo.fisso,
                pfa_valore=Decimal("1.5000"),
            ),
            ListinoMaster(
                fornitore_id=fornitori[1].id,
                sku_interno="MOZZ-BUFALA-KG",
                descrizione="Mozzarella di Bufala Campana DOP",
                prezzo_pattuito=Decimal("12.8000"),
                unita_misura="Kg",
                data_inizio_validita=date(2025, 1, 1),
                data_scadenza=None,
                pfa_tipo=None,
                pfa_valore=None,
            ),
            ListinoMaster(
                fornitore_id=fornitori[1].id,
                sku_interno="POMOD-SANMARZ-KG",
                descrizione="Pomodoro San Marzano DOP pelato",
                prezzo_pattuito=Decimal("3.2000"),
                unita_misura="Kg",
                data_inizio_validita=date(2025, 1, 1),
                data_scadenza=None,
                pfa_tipo=PFATipo.percentuale,
                pfa_valore=Decimal("0.0100"),
            ),
        ]
        session.add_all(listino_items)
        print(f"  ✅ {len(listino_items)} voci Listino Master create")

        await session.commit()
        print("\n🎉 Seed completato con successo!")
        print("─" * 50)
        print("Login Admin:   admin@pricesentinel.it / admin2025!")
        print("Login Manager: manager.playa@pricesentinel.it / manager2025!")


if __name__ == "__main__":
    asyncio.run(seed())
