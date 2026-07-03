"""
Unit Tests per la normalizzazione di testo e attributi (Fase 2 / Fase 8).
"""

from app.services.normalization import (
    normalize_text,
    extract_volume_ml,
    extract_weight_g,
    extract_pack_qty,
    extract_container_type,
    extract_candidate_attributes,
)


def run_tests():
    print("🧪 Avvio test unitari per normalizzazione...")

    # Test Case 1: "GIN HENDRICK'S CL 100"
    t1 = "GIN HENDRICK'S CL 100"
    attrs1 = extract_candidate_attributes(t1)
    assert attrs1["brand"] == "hendrick's", f"Brand errato: {attrs1['brand']}"
    assert attrs1["volume_ml"] == 1000, f"Volume errato: {attrs1['volume_ml']}"
    print(f"  ✅ Test 1 Superato: '{t1}' -> brand={attrs1['brand']}, vol={attrs1['volume_ml']}ml")

    # Test Case 2: "HENDRICKS GIN LT 1"
    t2 = "HENDRICKS GIN LT 1"
    attrs2 = extract_candidate_attributes(t2)
    assert attrs2["brand"] == "hendrick's", f"Brand errato: {attrs2['brand']}"
    assert attrs2["volume_ml"] == 1000, f"Volume errato: {attrs2['volume_ml']}"
    print(f"  ✅ Test 2 Superato: '{t2}' -> brand={attrs2['brand']}, vol={attrs2['volume_ml']}ml")

    # Test Case 3: "GIN HENDRIX 1000ML"
    t3 = "GIN HENDRIX 1000ML"
    attrs3 = extract_candidate_attributes(t3)
    assert attrs3["brand"] == "hendrick's", f"Brand errato: {attrs3['brand']}"
    assert attrs3["volume_ml"] == 1000, f"Volume errato: {attrs3['volume_ml']}"
    print(f"  ✅ Test 3 Superato: '{t3}' -> brand={attrs3['brand']}, vol={attrs3['volume_ml']}ml")

    # Test Case 4: "KEGLEVICH FRAGOLA LT 1"
    t4 = "KEGLEVICH FRAGOLA LT 1"
    attrs4 = extract_candidate_attributes(t4)
    assert attrs4["brand"] == "keglevich", f"Brand errato: {attrs4['brand']}"
    assert attrs4["variant"] == "fragola", f"Variante errata: {attrs4['variant']}"
    assert attrs4["volume_ml"] == 1000, f"Volume errato: {attrs4['volume_ml']}"
    print(f"  ✅ Test 4 Superato: '{t4}' -> brand={attrs4['brand']}, var={attrs4['variant']}, vol={attrs4['volume_ml']}ml")

    # Test Case 5: "COCA COLA VETRO 33CL"
    t5 = "COCA COLA VETRO 33CL"
    attrs5 = extract_candidate_attributes(t5)
    assert attrs5["brand"] == "coca cola", f"Brand errato: {attrs5['brand']}"
    assert attrs5["container_type"] == "vetro", f"Contenitore errato: {attrs5['container_type']}"
    assert attrs5["volume_ml"] == 330, f"Volume errato: {attrs5['volume_ml']}"
    print(f"  ✅ Test 5 Superato: '{t5}' -> brand={attrs5['brand']}, cont={attrs5['container_type']}, vol={attrs5['volume_ml']}ml")

    # Test Case 6: "ACQUA NATIA 0,50 X24"
    t6 = "ACQUA NATIA 0,50 X24"
    attrs6 = extract_candidate_attributes(t6)
    assert attrs6["volume_ml"] == 500, f"Volume errato: {attrs6['volume_ml']}"
    assert attrs6["pack_qty"] == 24, f"Pack errato: {attrs6['pack_qty']}"
    print(f"  ✅ Test 6 Superato: '{t6}' -> vol={attrs6['volume_ml']}ml, pack={attrs6['pack_qty']}")

    # Test Case 7: Brand Corrections
    t7_jeg = "JEGERMEISTER"
    norm7_jeg = normalize_text(t7_jeg)
    assert "jagermeister" in norm7_jeg, f"Jegermeister non normalizzato correttamente: {norm7_jeg}"
    print(f"  ✅ Test 7 Superato: '{t7_jeg}' -> '{norm7_jeg}'")

    print("🎉 Tutti i test unitari di normalizzazione superati con successo!")


if __name__ == "__main__":
    run_tests()
