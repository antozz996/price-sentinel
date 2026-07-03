"""
Price Sentinel — Modulo Normalizzazione Testo e Attributi.
Fase 2: Funzioni helper per la normalizzazione di descrizioni grezze di fattura.
"""

import re
import unicodedata
from typing import Optional


def normalize_text(text: str) -> str:
    """
    Normalizza una descrizione di testo:
    - Converte in lowercase
    - Rimuove gli accenti
    - Normalizza gli apostrofi
    - Converte la virgola decimale in punto nei numeri
    - Riconosce ed espande le abbreviazioni comuni
    - Corregge errori comuni nei brand
    - Rimuove punteggiatura superflua
    """
    if not text:
        return ""

    # Converte in lowercase
    normalized = text.lower()

    # Rimuove gli accenti
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", normalized)
        if unicodedata.category(c) != "Mn"
    )

    # Converte virgola decimale in punto nei numeri (es. 0,50 -> 0.50)
    normalized = re.sub(r"(\d+),(\d+)", r"\1.\2", normalized)

    # Normalizza gli apostrofi
    normalized = normalized.replace("’", "'").replace("‘", "'")

    # Corregge errori comuni nei brand
    brand_map = {
        r"\bhendrix\b": "hendrick's",
        r"\bhendricks\b": "hendrick's",
        r"\bbeafeater\b": "beefeater",
        r"\bjegermeister\b": "jagermeister",
        r"\bjegermaster\b": "jagermeister",
        r"\bjagermeister\b": "jagermeister",
    }
    for pattern, replacement in brand_map.items():
        normalized = re.sub(pattern, replacement, normalized)

    # Espande abbreviazioni comuni
    abbrev_map = {
        r"\bbott\b": "bottiglia",
        r"\bpz\b": "pezzi",
        r"\bconf\b": "confezione",
        r"\bcart\b": "cartone",
        r"\blt\b": "litro",
        r"\bcl\b": "centilitri",
        r"\bml\b": "millilitri",
    }
    for pattern, replacement in abbrev_map.items():
        normalized = re.sub(pattern, replacement, normalized)

    # Rimuove punteggiatura inutile (mantiene lettere, cifre, spazi, dot, single quotes, hyphens, slashes, x, *)
    normalized = re.sub(r"[^\w\s\.\'\-\/x\*]", " ", normalized)

    # Rimuove spazi doppi
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized


def extract_volume_ml(text: str) -> Optional[int]:
    """
    Estrae il volume espresso in millilitri (ml) dalla descrizione.
    Riconosce:
    - 100cl, cl 100 -> 1000
    - 1lt, lt 1, 1 l -> 1000
    - 1000ml -> 1000
    - Fallback per volumi decimali senza unità (es. 0,50 -> 500ml)
    """
    cleaned = text.lower()
    # Converte virgole in punti nei numeri
    cleaned = re.sub(r"(\d+),(\d+)", r"\1.\2", cleaned)

    # 1. Pattern <valore><unita> (es. "100cl", "1lt", "0.75l", "1000ml")
    pattern1 = r"(\d+(?:\.\d+)?)\s*(ml|cl|lt|l)\b"
    for val_str, unit in re.findall(pattern1, cleaned):
        try:
            val = float(val_str)
            if unit == "ml":
                return int(val)
            elif unit == "cl":
                return int(val * 10)
            elif unit in ("lt", "l"):
                return int(val * 1000)
        except ValueError:
            pass

    # 2. Pattern <unita><valore> (es. "cl 100", "lt 1", "l 1.5", "ml 1000")
    pattern2 = r"\b(ml|cl|lt|l)\s*(\d+(?:\.\d+)?)"
    for unit, val_str in re.findall(pattern2, cleaned):
        try:
            val = float(val_str)
            if unit == "ml":
                return int(val)
            elif unit == "cl":
                return int(val * 10)
            elif unit in ("lt", "l"):
                return int(val * 1000)
        except ValueError:
            pass

    # 3. Fallback per volumi decimali standalone (es. "0.50" o "1.5")
    pattern3 = r"\b(0\.\d+|1\.\d+|2\.\d+)\b"
    for val_str in re.findall(pattern3, cleaned):
        try:
            val = float(val_str)
            if val in (0.2, 0.25, 0.33, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 0.50):
                return int(val * 1000)
        except ValueError:
            pass

    return None


def extract_weight_g(text: str) -> Optional[int]:
    """
    Estrae il peso espresso in grammi (g) dalla descrizione.
    Riconosce:
    - 500g, 500gr -> 500
    - 1kg, 1 kg -> 1000
    """
    cleaned = text.lower()
    cleaned = re.sub(r"(\d+),(\d+)", r"\1.\2", cleaned)

    # 1. Pattern <valore><unita> (es. "500g", "1kg", "1.5kg")
    pattern1 = r"(\d+(?:\.\d+)?)\s*(g|gr|kg|chilo|chili)\b"
    for val_str, unit in re.findall(pattern1, cleaned):
        try:
            val = float(val_str)
            if unit in ("g", "gr"):
                return int(val)
            elif unit in ("kg", "chilo", "chili"):
                return int(val * 1000)
        except ValueError:
            pass

    # 2. Pattern <unita><valore> (es. "g 500", "kg 1.5")
    pattern2 = r"\b(g|gr|kg)\s*(\d+(?:\.\d+)?)"
    for unit, val_str in re.findall(pattern2, cleaned):
        try:
            val = float(val_str)
            if unit in ("g", "gr"):
                return int(val)
            elif unit == "kg":
                return int(val * 1000)
        except ValueError:
            pass

    return None


def extract_pack_qty(text: str) -> Optional[int]:
    """
    Estrae il numero di pezzi per confezione (pack_qty).
    Riconosce:
    - x24
    - 24 pz
    - cartone 24
    - conf 6
    - cassa 12
    - 24x...
    """
    cleaned = text.lower()

    # Pattern x24, x 24, x6
    pattern_x = r"\bx\s*(\d+)\b"
    matches_x = re.findall(pattern_x, cleaned)
    if matches_x:
        return int(matches_x[0])

    # Pattern 24 pz, 6 pezzi, 12pz
    pattern_pz = r"\b(\d+)\s*(?:pz|pezzi|pezzo)\b"
    matches_pz = re.findall(pattern_pz, cleaned)
    if matches_pz:
        return int(matches_pz[0])

    # Pattern cartone 24, conf 6, cassa 12
    pattern_box = r"\b(cartone|cartoni|ct|conf|confezione|confezioni|cassa|casse)\s*(\d+)\b"
    matches_box = re.findall(pattern_box, cleaned)
    if matches_box:
        return int(matches_box[0][1])

    # Pattern 24x33cl o similar (il moltiplicatore precede la x)
    pattern_mult = r"\b(\d+)\s*x\s*\d+"
    matches_mult = re.findall(pattern_mult, cleaned)
    if matches_mult:
        return int(matches_mult[0])

    return None


def extract_container_type(text: str) -> Optional[str]:
    """
    Rileva il tipo di contenitore.
    Riconosce: vetro, pet, lattina, fusto, bag in box.
    """
    cleaned = text.lower()
    if "bag in box" in cleaned or "bib" in cleaned:
        return "bag in box"
    elif "vetro" in cleaned:
        return "vetro"
    elif "pet" in cleaned:
        return "pet"
    elif "lattina" in cleaned or "latta" in cleaned:
        return "lattina"
    elif "fusto" in cleaned:
        return "fusto"
    return None


def extract_candidate_attributes(text: str) -> dict:
    """
    Raccoglie tutti gli attributi del candidato da una stringa.
    """
    normalized = normalize_text(text)

    # Riconosce i brand principali (può essere ampliato)
    brand = None
    for b in ["hendrick's", "beefeater", "jagermeister", "coca cola", "red bull", "keglevich"]:
        if b in normalized:
            brand = b
            break

    # Riconosce varianti / gusti
    variant = None
    for v in ["fragola", "pesca", "sugarfree", "zero", "classica"]:
        if v in normalized:
            variant = v
            break

    # Rileva la categoria
    category = None
    if any(x in normalized for x in ["acqua", "cola", "soda", "tonica", "aranciata", "succo", "gin", "vodka", "rum", "amaro", "birra", "vino"]):
        category = "beverage"

    return {
        "brand": brand,
        "category": category,
        "volume_ml": extract_volume_ml(text),
        "weight_g": extract_weight_g(text),
        "pack_qty": extract_pack_qty(text),
        "container_type": extract_container_type(text),
        "variant": variant,
    }
