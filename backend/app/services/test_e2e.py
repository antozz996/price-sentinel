#!/usr/bin/env python3
"""
Price Sentinel — Script di test End-to-End.
Genera un XML FatturaPA di esempio, lo invia al webhook Aruba,
e verifica che la pipeline funzioni correttamente.

Utilizzo:
  docker-compose exec -T backend python -m app.services.test_e2e
"""

import asyncio
import base64
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func

from app.database import async_session_factory
from app.models.alias import AliasProdotto
from app.models.anomalie import Anomalia
from app.models.utenti import Utente
from app.models.fatture import Fattura, RigaFattura, XMLRaw, StatoIngestion
from app.models.fornitori import Fornitore
from app.services.ingestion import process_xml_raw
from app.services.xml_parser import parse_fattura_xml, calcola_hash_idempotenza


# ─────────────────────────────────────────────
# XML FatturaPA di Test
# ─────────────────────────────────────────────

TEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
                       versione="FPR12">
  <FatturaElettronicaHeader>
    <DatiTrasmissione>
      <IdTrasmittente>
        <IdPaese>IT</IdPaese>
        <IdCodice>12345678901</IdCodice>
      </IdTrasmittente>
      <ProgressivoInvio>00001</ProgressivoInvio>
      <FormatoTrasmissione>FPR12</FormatoTrasmissione>
    </DatiTrasmissione>
    <CedentePrestatore>
      <DatiAnagrafici>
        <IdFiscaleIVA>
          <IdPaese>IT</IdPaese>
          <IdCodice>12345678901</IdCodice>
        </IdFiscaleIVA>
        <Anagrafica>
          <Denominazione>Drinks &amp; Spirits Srl</Denominazione>
        </Anagrafica>
      </DatiAnagrafici>
    </CedentePrestatore>
    <CessionarioCommittente>
      <DatiAnagrafici>
        <IdFiscaleIVA>
          <IdPaese>IT</IdPaese>
          <IdCodice>01234567890</IdCodice>
        </IdFiscaleIVA>
        <Anagrafica>
          <Denominazione>Lido Playa Luna</Denominazione>
        </Anagrafica>
      </DatiAnagrafici>
    </CessionarioCommittente>
  </FatturaElettronicaHeader>

  <FatturaElettronicaBody>
    <DatiGenerali>
      <DatiGeneraliDocumento>
        <TipoDocumento>TD01</TipoDocumento>
        <Divisa>EUR</Divisa>
        <Data>2025-03-15</Data>
        <Numero>FT-2025-0042</Numero>
      </DatiGeneraliDocumento>
    </DatiGenerali>

    <DatiBeniServizi>
      <!-- Riga 1: Gin Hendrick's — PREZZO CORRETTO (22.50) -->
      <DettaglioLinee>
        <NumeroLinea>1</NumeroLinea>
        <CodiceArticolo>
          <CodiceTipo>FORNITORE</CodiceTipo>
          <CodiceValore>DS-GH70</CodiceValore>
        </CodiceArticolo>
        <Descrizione>Gin Hendricks 70cl</Descrizione>
        <Quantita>6.00</Quantita>
        <UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>22.5000</PrezzoUnitario>
        <PrezzoTotale>135.00</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>

      <!-- Riga 2: Vodka Belvedere — SOVRAPPREZZO (+2.00) -->
      <DettaglioLinee>
        <NumeroLinea>2</NumeroLinea>
        <CodiceArticolo>
          <CodiceTipo>FORNITORE</CodiceTipo>
          <CodiceValore>DS-VB1L</CodiceValore>
        </CodiceArticolo>
        <Descrizione>Vodka Belvedere 1lt</Descrizione>
        <Quantita>4.00</Quantita>
        <UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>30.0000</PrezzoUnitario>
        <PrezzoTotale>120.00</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>

      <!-- Riga 3: Prodotto con Sconto 10% -->
      <DettaglioLinee>
        <NumeroLinea>3</NumeroLinea>
        <CodiceArticolo>
          <CodiceTipo>FORNITORE</CodiceTipo>
          <CodiceValore>DS-RD70</CodiceValore>
        </CodiceArticolo>
        <Descrizione>Rum Diplomatico Reserva 70cl</Descrizione>
        <Quantita>3.00</Quantita>
        <UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>36.0000</PrezzoUnitario>
        <ScontoMaggiorazione>
          <Tipo>SC</Tipo>
          <Percentuale>10.00</Percentuale>
        </ScontoMaggiorazione>
        <PrezzoTotale>97.20</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>

      <!-- Riga 4: Omaggio (sconto 100%) -->
      <DettaglioLinee>
        <NumeroLinea>4</NumeroLinea>
        <Descrizione>Campione omaggio Gin Tonic Kit</Descrizione>
        <Quantita>1.00</Quantita>
        <UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>0.0000</PrezzoUnitario>
        <PrezzoTotale>0.00</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>

      <!-- Riga 5: Prodotto sconosciuto (andrà in Parking) -->
      <DettaglioLinee>
        <NumeroLinea>5</NumeroLinea>
        <CodiceArticolo>
          <CodiceTipo>FORNITORE</CodiceTipo>
          <CodiceValore>DS-NEWPROD</CodiceValore>
        </CodiceArticolo>
        <Descrizione>Nuovo Amaro Premium XYZ</Descrizione>
        <Quantita>2.00</Quantita>
        <UnitaMisura>PZ</UnitaMisura>
        <PrezzoUnitario>18.0000</PrezzoUnitario>
        <PrezzoTotale>36.00</PrezzoTotale>
        <AliquotaIVA>22.00</AliquotaIVA>
      </DettaglioLinee>

      <DatiRiepilogo>
        <AliquotaIVA>22.00</AliquotaIVA>
        <ImponibileImporto>388.20</ImponibileImporto>
        <Imposta>85.40</Imposta>
      </DatiRiepilogo>
    </DatiBeniServizi>
  </FatturaElettronicaBody>
</p:FatturaElettronica>
"""


async def run_test():
    """Esegue il test end-to-end della pipeline di ingestion."""

    print("=" * 60)
    print("🧪 PRICE SENTINEL — Test End-to-End Pipeline")
    print("=" * 60)

    async with async_session_factory() as db:

        # ── Step 0: Crea Alias per i codici fornitore ──
        print("\n📎 Step 0: Creazione alias codici fornitore...")

        admin_result = await db.execute(select(Utente).where(Utente.ruolo == "admin"))
        admin = admin_result.scalars().first()
        if not admin:
            print("  ❌ Admin non trovato. Esegui prima il seed.")
            return

        aliases = [
            ("DS-GH70", "GIN-HENDRICKS-70CL"),
            ("DS-VB1L", "VODKA-BELVEDERE-LT1"),
            ("DS-RD70", "RUM-DIPLOMATICO-70CL"),
        ]

        forn_result = await db.execute(
            select(Fornitore).where(Fornitore.partita_iva == "12345678901")
        )
        fornitore = forn_result.scalar_one_or_none()
        if not fornitore:
            print("  ❌ Fornitore non trovato. Esegui prima il seed.")
            return

        for codice_forn, sku in aliases:
            existing = await db.execute(
                select(AliasProdotto).where(
                    AliasProdotto.fornitore_id == fornitore.id,
                    AliasProdotto.codice_fornitore_originale == codice_forn,
                )
            )
            if not existing.scalar_one_or_none():
                alias = AliasProdotto(
                    fornitore_id=fornitore.id,
                    codice_fornitore_originale=codice_forn,
                    sku_interno=sku,
                    confermato_da_user_id=admin.id,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(alias)
                print(f"  ✅ Alias: {codice_forn} → {sku}")

        await db.flush()

        # ── Step 1: Parsing XML ──
        print("\n📄 Step 1: Parsing XML FatturaPA...")
        parsed = parse_fattura_xml(TEST_XML)
        print(f"  P.IVA Cedente:     {parsed.piva_cedente}")
        print(f"  P.IVA Cessionario: {parsed.piva_cessionario}")
        print(f"  Tipo Documento:    {parsed.tipo_documento}")
        print(f"  Numero:            {parsed.numero_documento}")
        print(f"  Data:              {parsed.data_documento}")
        print(f"  Righe:             {len(parsed.righe)}")
        print(f"  Valid:             {parsed.is_valid}")

        if not parsed.is_valid:
            print(f"  ❌ Errori: {parsed.errori}")
            return

        for r in parsed.righe:
            omaggio_flag = " 🎁" if r.is_omaggio else ""
            sconto_flag = f" (-{r.sconto_percentuale}%)" if r.sconto_percentuale else ""
            print(f"    L{r.numero_linea}: {r.descrizione[:40]:40s} €{r.prezzo_netto_normalizzato:>8.4f}{sconto_flag}{omaggio_flag}")

        # ── Step 2: Hash Idempotenza ──
        hash_id = calcola_hash_idempotenza(
            parsed.piva_cedente, parsed.numero_documento, parsed.data_documento
        )
        print(f"\n🔑 Step 2: Hash idempotenza: {hash_id[:16]}...")

        # Rimuovi XML duplicato da test precedenti
        existing = await db.execute(
            select(XMLRaw).where(XMLRaw.hash_idempotenza == hash_id)
        )
        old = existing.scalar_one_or_none()
        if old:
            print("  ⚠️  XML già presente dal test precedente, lo rimuovo...")
            await db.delete(old)
            await db.flush()

        # ── Step 3: Salva XMLRaw ──
        print("\n💾 Step 3: Salvataggio XMLRaw...")
        xml_raw = XMLRaw(
            payload=TEST_XML,
            nome_file="test_fattura_e2e.xml",
            hash_idempotenza=hash_id,
            stato_ingestion=StatoIngestion.ricevuto,
            data_ricezione=datetime.now(timezone.utc),
        )
        db.add(xml_raw)
        await db.flush()
        print(f"  ✅ XMLRaw id={xml_raw.id}")

        # ── Step 4: Pipeline di Ingestion ──
        print("\n⚙️  Step 4: Pipeline di Ingestion...")
        report = await process_xml_raw(db, xml_raw.id, parsed)

        print(f"  Status:           {report.get('status')}")
        print(f"  Righe totali:     {report.get('righe_totali', 0)}")
        print(f"  Righe matched:    {report.get('righe_matched', 0)}")
        print(f"  Righe parking:    {report.get('righe_parking', 0)}")
        print(f"  Righe omaggio:    {report.get('righe_omaggio', 0)}")
        print(f"  Anomalie:         {report.get('anomalie_generate', 0)}")

        # ── Step 5: Verifica risultati ──
        print("\n🔍 Step 5: Verifica risultati nel DB...")

        # Conta fatture
        fat_count = await db.execute(select(func.count(Fattura.id)))
        print(f"  Fatture nel DB:      {fat_count.scalar()}")

        # Conta righe
        righe_count = await db.execute(select(func.count(RigaFattura.id)))
        print(f"  Righe fattura nel DB: {righe_count.scalar()}")

        # Conta anomalie
        anom_count = await db.execute(select(func.count(Anomalia.id)))
        print(f"  Anomalie nel DB:     {anom_count.scalar()}")

        # Dettaglio anomalie
        anomalie = await db.execute(select(Anomalia))
        for a in anomalie.scalars().all():
            print(f"    🚨 Anomalia #{a.id}: delta=€{a.delta_prezzo} totale=€{a.delta_totale} stato={a.stato_validazione.value}")

        await db.commit()

        print("\n" + "=" * 60)
        print("✅ TEST END-TO-END COMPLETATO")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_test())
