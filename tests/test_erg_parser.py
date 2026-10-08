from __future__ import annotations

import unittest

from erg_parser.parser import competition_url, keyword_matches, meaningful_haystack


class ErgKeywordMatchingTests(unittest.TestCase):
    def test_visio_does_not_match_vision(self) -> None:
        self.assertFalse(keyword_matches("Visio", "VISION W5W 12V 5W"))

    def test_visio_matches_standalone_product_name(self) -> None:
        self.assertTrue(keyword_matches("Visio", "Лицензия Microsoft Visio Professional"))

    def test_meaningful_haystack_ignores_document_names(self) -> None:
        detail = {
            "Positions": [{"TruFullName": "Серверное оборудование"}],
            "DocTenderList": [{"NAME": "Project договор.docx"}],
        }
        haystack = meaningful_haystack({}, detail)

        self.assertIn("Серверное оборудование", haystack)
        self.assertNotIn("Project договор.docx", haystack)

    def test_competition_url_uses_new_public_interface(self) -> None:
        self.assertEqual(
            "https://torgi.erg.kz/contests/618907/offer-positions",
            competition_url("https://torgi.erg.kz/supplier/#/competitions", "618907"),
        )


if __name__ == "__main__":
    unittest.main()
