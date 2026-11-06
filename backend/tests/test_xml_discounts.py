import os
import unittest
from decimal import Decimal

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused")
os.environ.setdefault("SECRET_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("ARUBA_WEBHOOK_API_KEY", "unit-test-placeholder-unit-test-placeholder")
os.environ.setdefault("LIQUIDSTOCK_INTEGRATION_SECRET", "unit-test-placeholder-unit-test-placeholder")

from app.services.xml_parser import parse_fattura_xml


def invoice(lines: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<FatturaElettronica>
  <FatturaElettronicaHeader>
    <CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>10000000001</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>Fornitore Sintetico</Denominazione></Anagrafica></DatiAnagrafici></CedentePrestatore>
    <CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>00000000001</IdCodice></IdFiscaleIVA>
      <Anagrafica><Denominazione>Locale Sintetico</Denominazione></Anagrafica></DatiAnagrafici></CessionarioCommittente>
  </FatturaElettronicaHeader>
  <FatturaElettronicaBody>
    <DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa>
      <Data>2026-10-10</Data><Numero>SYNTH-1</Numero></DatiGeneraliDocumento></DatiGenerali>
    <DatiBeniServizi>{lines}</DatiBeniServizi>
  </FatturaElettronicaBody>
</FatturaElettronica>"""


def line(price: str, qty: str, discounts: str, total: str | None) -> str:
    total_tag = f"<PrezzoTotale>{total}</PrezzoTotale>" if total is not None else ""
    return f"""<DettaglioLinee><NumeroLinea>1</NumeroLinea><Descrizione>Champagne sintetico</Descrizione>
      <Quantita>{qty}</Quantita><UnitaMisura>COL</UnitaMisura><PrezzoUnitario>{price}</PrezzoUnitario>
      {discounts}{total_tag}<AliquotaIVA>22.00</AliquotaIVA></DettaglioLinee>"""


def net_price(row) -> Decimal:
    return (row.prezzo_unitario * (1 - row.sconto_percentuale / 100)).quantize(Decimal("0.0001"))


PERCENT_THEN_AMOUNT = (
    "<ScontoMaggiorazione><Tipo>SC</Tipo><Percentuale>13.00</Percentuale></ScontoMaggiorazione>"
    "<ScontoMaggiorazione><Tipo>SC</Tipo><Importo>8.70</Importo></ScontoMaggiorazione>"
)


class PerUnitDiscountTest(unittest.TestCase):
    def test_amount_discount_applies_to_each_unit(self):
        row = parse_fattura_xml(invoice(line("53.6801", "60", PERCENT_THEN_AMOUNT, None))).righe[0]
        # 53.6801 x 0.87 - 8.70 = 38.0017 per unit, whatever the quantity
        self.assertEqual(net_price(row), Decimal("38.0017"))
        self.assertEqual(row.prezzo_netto_normalizzato, Decimal("38.0017"))

    def test_line_total_defines_the_stored_discount(self):
        row = parse_fattura_xml(invoice(line("53.6801", "60", PERCENT_THEN_AMOUNT, "2211.70"))).righe[0]
        self.assertEqual(row.prezzo_netto_normalizzato, Decimal("36.8617"))
        # The discount is stored with 4 decimals, like the database column.
        self.assertAlmostEqual(net_price(row), Decimal("36.8617"), delta=Decimal("0.0002"))

    def test_percent_discounts_are_compounded(self):
        discounts = (
            "<ScontoMaggiorazione><Tipo>SC</Tipo><Percentuale>13.00</Percentuale></ScontoMaggiorazione>"
            "<ScontoMaggiorazione><Tipo>SC</Tipo><Percentuale>3.00</Percentuale></ScontoMaggiorazione>"
        )
        row = parse_fattura_xml(invoice(line("68.6604", "12", discounts, None))).righe[0]
        self.assertEqual(net_price(row), Decimal("57.9425"))

    def test_line_without_discount_is_unchanged(self):
        row = parse_fattura_xml(invoice(line("10.00", "3", "", "30.00"))).righe[0]
        self.assertEqual(row.sconto_percentuale, Decimal("0"))
        self.assertEqual(net_price(row), Decimal("10.0000"))


if __name__ == "__main__":
    unittest.main()
