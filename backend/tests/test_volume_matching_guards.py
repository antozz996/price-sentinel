"""Lettura del volume dal nome (extract_volume_ml) (volumi scritti in molti formati).

python -m unittest discover -s tests -p 'test_volume_matching_guards.py' -v   (da backend/, PYTHONPATH=.)
"""
import unittest
from types import SimpleNamespace

from app.services.normalization import extract_volume_ml


def catalog_product(product_id: int, name: str, **overrides):
    values = {
        "id": product_id, "sku_interno": f"SKU-{product_id}", "canonical_name": name,
        "volume_ml": None, "weight_g": None, "unit_count": 1, "brand": None, "category": None,
        "comparison_unit": "Pz", "container_type": None, "is_active": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class VolumeFromNameTest(unittest.TestCase):
    def test_previous_behaviour_is_kept(self):
        cases = {
            "GIN HENDRICK'S CL 100": 1000, "HENDRICKS GIN LT 1": 1000, "GIN HENDRIX 1000ML": 1000,
            "COCA COLA VETRO 33CL": 330, "ACQUA NATIA 0,50 X24": 500, "BICCH. CAFFE 80CC X100": 80,
            "VODKA GREY GOOSE CL70": 700, "RED BULL WATER MELON 24X250 ML": 250,
            "GRAN CREMA CAFFE' 2X2900ML": 2900, "OLIO EXTRA VERG.0,75LT DOP CILENTO": 750,
            "COPPETTA GOLD PLAST ONDA TRASP. CC95X25PZ": 95, "FUSTO COCA COLA 18 LT": 18000,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract_volume_ml(text), expected)

    def test_litres_written_with_cl_label(self):
        self.assertEqual(extract_volume_ml("BIRRA HEINEKEN 0.33 CL X 24 BT"), 330)
        self.assertEqual(extract_volume_ml("ACQUA LETE 1,50 CL X 6 BT"), 1500)
        self.assertEqual(extract_volume_ml("GRAPPA VIGNA ORO SCURA 40% CL 1,50"), 1500)
        self.assertEqual(extract_volume_ml("VODKA BELVEDERE CL 1.75"), 1750)
        self.assertEqual(extract_volume_ml("RUINART R 0.75 CL"), 750)
        self.assertEqual(extract_volume_ml("CAMPARI SODA VP 9,8 CL"), 98)

    def test_formats_not_read_before(self):
        self.assertEqual(extract_volume_ml("BITTER CAMPARI CL.100"), 1000)
        self.assertEqual(extract_volume_ml("LATTE P/S S/LATTOSIO ARBOREA LT.1"), 1000)
        self.assertEqual(extract_volume_ml("AMARO MONTENEGRO 1 LITRO"), 1000)
        self.assertEqual(extract_volume_ml("APEROL 1LITRO BT"), 1000)
        self.assertEqual(extract_volume_ml("VODKA KEGLEVICH 0.70 PESCA"), 700)
        self.assertEqual(extract_volume_ml("STACCAFACILE DUBOR SPRAY PR100 ML.600"), 600)

    def test_sizes_codes_and_weights_are_not_volumes(self):
        for text in (
            "Guanti in nitrile nero 3,5gr tg. L 100 pezzi",
            "GUANTI NITRILE NERO MIS. L 100PZ",
            "Coltello bianco monouso 100 pezzi CC100156",
            "Supra coltello spelucchino curvo lama 7cm manico nylon blu ST91A07L",
            "SALAME NOSTRANO ARCO 1,5 KG",
            "Rotolo alluminio 100 metri nudo P6505CC",
        ):
            with self.subTest(text=text):
                self.assertIsNone(extract_volume_ml(text))


if __name__ == "__main__":
    unittest.main()
