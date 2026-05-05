"""
Price Sentinel — XML Parser FatturaPA (Completo).
Sprint 2: parsing reale con namespace FatturaPA, normalizzazione prezzi,
gestione omaggi, routing per TipoDocumento.

Spec §2.2, §2.3
"""

import base64
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from lxml import etree


# ─────────────────────────────────────────────
# Namespace FatturaPA (v1.2.2)
# ─────────────────────────────────────────────
NAMESPACES = {
    "p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2",
}

# Fallback: alcune fatture usano il namespace 1.2.1 o nessun namespace
NAMESPACE_ALTERNATIVES = [
    {"p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"},
    {"p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2.1"},
    {"p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2.2"},
    {},  # Nessun namespace
]


@dataclass
class RigaParsata:
    """Singola riga estratta dal blocco DettaglioLinee."""
    numero_linea: int = 0
    codice_articolo: str | None = None  # CodiceValore dal blocco CodiceArticolo
    tipo_codice: str | None = None      # TipoCodice (es. EAN, FORNITORE)
    descrizione: str = ""
    prezzo_unitario: Decimal = Decimal("0")
    quantita: Decimal = Decimal("0")
    unita_misura: str | None = None
    sconto_percentuale: Decimal = Decimal("0")
    aliquota_iva: Decimal | None = None
    is_omaggio: bool = False

    @property
    def prezzo_netto_normalizzato(self) -> Decimal:
        """
        Formula dal Master Spec §2.3:
        Prezzo_Netto_Normalizzato = PrezzoUnitario * (1 - ScontoMaggiorazione/100)
        Il confronto col listino avviene SEMPRE su questo valore imponibile netto.
        """
        sconto_fattore = Decimal("1") - (self.sconto_percentuale / Decimal("100"))
        return (self.prezzo_unitario * sconto_fattore).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )


@dataclass
class FatturaParsata:
    """Risultato del parsing di un XML FatturaPA."""
    piva_cedente: str = ""          # P.IVA del fornitore
    denominazione_cedente: str = "" # Nome del fornitore
    piva_cessionario: str = ""      # P.IVA della location
    numero_documento: str = ""
    data_documento: str = ""        # YYYY-MM-DD
    data_ricezione_sdi: str = ""    # Data SDI
    tipo_documento: str = ""        # TD01, TD04, TD08
    totale_imponibile: Decimal = Decimal("0")
    divisa: str = "EUR"
    righe: list[RigaParsata] = field(default_factory=list)
    errori: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errori) == 0 and self.piva_cedente != ""


def calcola_hash_idempotenza(piva: str, numero: str, data: str) -> str:
    """
    Spec §2.2 Step 3: SHA256(P.IVA_fornitore + numero_documento + data).
    Garantisce idempotenza contro i retry automatici di Aruba.
    """
    raw = f"{piva}|{numero}|{data}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def decode_xml_base64(xml_b64: str) -> str:
    """Decodifica il payload Base64 ricevuto dal webhook Aruba."""
    return base64.b64decode(xml_b64).decode("utf-8")


def _to_local_xpath(xpath: str) -> str:
    """Modifica l'xpath ignorando del tutto i namespaces."""
    parts = xpath.replace("p:", "").split("/")
    new_parts = []
    for p in parts:
        if p in ("", "."):
            new_parts.append(p)
        else:
            new_parts.append(f"*[local-name()='{p}']")
    return "/".join(new_parts)


def _find(element, xpath: str) -> Optional[etree._Element]:
    """Cerca un elemento usando local-name() xpath."""
    loc_xpath = _to_local_xpath(xpath)
    try:
        res = element.xpath(loc_xpath)
        return res[0] if res else None
    except Exception:
        return None


def _findall(element, xpath: str) -> list:
    """Trova tutti gli elementi usando local-name() xpath."""
    loc_xpath = _to_local_xpath(xpath)
    try:
        return element.xpath(loc_xpath)
    except Exception:
        return []


def _text(element, xpath: str, default: str = "") -> str:
    """Estrai testo da un sotto-elemento."""
    el = _find(element, xpath)
    return el.text.strip() if el is not None and el.text else default


def _decimal(element, xpath: str, default: str = "0") -> Decimal:
    """Estrai Decimal da un sotto-elemento."""
    text = _text(element, xpath, default)
    try:
        return Decimal(text.replace(",", "."))
    except Exception:
        return Decimal(default)


def parse_fattura_xml(xml_string: str) -> FatturaParsata:
    """
    Parser XML FatturaPA completo — Spec §2.2, §2.3.

    Gestisce:
    - Namespace variabili (v1.2, v1.2.1, v1.2.2, nessuno)
    - Estrazione header (CedentePrestatore, CessionarioCommittente)
    - TipoDocumento per routing (TD01/TD04/TD08) — Spec §2.2 Step 5
    - DettaglioLinee con normalizzazione prezzi
    - ScontoMaggiorazione (anche multipli)
    - Rilevamento omaggi (Prezzo=0 o Sconto=100%) — Spec §3.3
    - CodiceArticolo per matching Livello 1

    Returns:
        FatturaParsata con tutte le righe estratte e normalizzate
    """
    result = FatturaParsata()

    try:
        root = etree.fromstring(xml_string.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        result.errori.append(f"XML non valido: {e}")
        return result

    # ── Header ──
    header = _find(root, ".//FatturaElettronicaHeader")
    if header is None:
        result.errori.append("FatturaElettronicaHeader non trovato")
        return result

    # Cedente (Fornitore)
    result.piva_cedente = _text(
        header, ".//CedentePrestatore/DatiAnagrafici/IdFiscaleIVA/IdCodice"
    )
    result.denominazione_cedente = _text(
        header, ".//CedentePrestatore/DatiAnagrafici/Anagrafica/Denominazione"
    )

    # Cessionario (Location — la nostra P.IVA)
    result.piva_cessionario = _text(
        header, ".//CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA/IdCodice"
    )
    # Fallback su CodiceFiscale se P.IVA non presente
    if not result.piva_cessionario:
        result.piva_cessionario = _text(
            header, ".//CessionarioCommittente/DatiAnagrafici/CodiceFiscale"
        )

    if not result.piva_cedente:
        result.errori.append("P.IVA cedente non trovata nell'XML")

    # ── Body (potrebbe essere multiplo in lotti, prendiamo il primo) ──
    body = _find(root, ".//FatturaElettronicaBody")
    if body is None:
        result.errori.append("FatturaElettronicaBody non trovato")
        return result

    # Dati Generali
    dg = _find(body, ".//DatiGenerali/DatiGeneraliDocumento")
    if dg is not None:
        result.tipo_documento = _text(dg, "TipoDocumento")
        result.numero_documento = _text(dg, "Numero")
        result.data_documento = _text(dg, "Data")
        result.divisa = _text(dg, "Divisa", "EUR")

    # Data ricezione SDI (DatiTrasmissione)
    result.data_ricezione_sdi = _text(
        header, ".//DatiTrasmissione/DataOraRicezione", result.data_documento
    )

    # ── Totale Imponibile ──
    riepilogo_list = _findall(body, ".//DatiBeniServizi/DatiRiepilogo")
    totale = Decimal("0")
    for riepilogo in riepilogo_list:
        totale += _decimal(riepilogo, "ImponibileImporto")
    result.totale_imponibile = totale

    # ── Righe (DettaglioLinee) — Spec §2.3 ──
    linee = _findall(body, ".//DatiBeniServizi/DettaglioLinee")

    for linea in linee:
        riga = RigaParsata()

        riga.numero_linea = int(_text(linea, "NumeroLinea", "0"))
        riga.descrizione = _text(linea, "Descrizione")
        riga.prezzo_unitario = _decimal(linea, "PrezzoUnitario")
        riga.quantita = _decimal(linea, "Quantita", "1")
        riga.unita_misura = _text(linea, "UnitaMisura") or None
        riga.aliquota_iva = _decimal(linea, "AliquotaIVA")

        # ── CodiceArticolo (può essere multiplo) ──
        codici = _findall(linea, "CodiceArticolo")
        for codice in codici:
            tipo = _text(codice, "CodiceTipo")
            valore = _text(codice, "CodiceValore")
            if valore:
                riga.codice_articolo = valore
                riga.tipo_codice = tipo
                break  # Prendi il primo codice disponibile

        # ── ScontoMaggiorazione (può essere multiplo — Spec §2.3) ──
        sconti = _findall(linea, "ScontoMaggiorazione")
        sconto_totale = Decimal("0")
        for sconto_el in sconti:
            tipo_sm = _text(sconto_el, "Tipo")  # SC = Sconto, MG = Maggiorazione
            perc = _decimal(sconto_el, "Percentuale")
            if tipo_sm == "SC":
                sconto_totale += perc
            elif tipo_sm == "MG":
                sconto_totale -= perc  # Maggiorazione riduce lo sconto effettivo
        riga.sconto_percentuale = sconto_totale

        # ── Rilevamento Omaggi — Spec §3.3 ──
        if riga.prezzo_unitario == Decimal("0") or riga.sconto_percentuale >= Decimal("100"):
            riga.is_omaggio = True

        result.righe.append(riga)

    return result
