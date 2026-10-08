from __future__ import annotations

import unittest

from icportal_bot.models import LotMatch
from icportal_bot.samruk import _browser_detail_customer, _is_missing_browser_error, _keyword_matches, _with_browser_detail_fields


class SamrukKeywordMatchingTests(unittest.TestCase):
    def test_kib_does_not_match_ekibastuz(self) -> None:
        self.assertFalse(_keyword_matches("КИБ", "ремонт тракторов в г.Экибастуз"))

    def test_kib_matches_standalone_abbreviation(self) -> None:
        self.assertTrue(_keyword_matches("КИБ", "Продление лицензии КИБ СёрчИнформ"))

    def test_dlp_does_not_match_inside_word(self) -> None:
        self.assertFalse(_keyword_matches("DLP", "ADLP-service"))

    def test_dlp_matches_standalone_abbreviation(self) -> None:
        self.assertTrue(_keyword_matches("DLP", "Система DLP для предотвращения утечек"))

    def test_detects_missing_playwright_browser_error(self) -> None:
        error = Exception("Executable doesn't exist at C:\\Users\\test\\chromium.exe. Please run: playwright install")

        self.assertTrue(_is_missing_browser_error(error))

    def test_extracts_browser_detail_customer_from_organizer_line(self) -> None:
        text = "\n".join(
            [
                "Объявление № 1258707",
                "Услуга по продлению лицензий",
                "Организатор: 110740001729 ТОО \"KMG PetroChem\"",
            ]
        )

        self.assertEqual('110740001729 ТОО "KMG PetroChem"', _browser_detail_customer(text))

    def test_browser_match_description_includes_customer(self) -> None:
        match = LotMatch(
            keyword="Acrobat",
            title="Услуга по продлению лицензий Acrobat pro",
            url="https://zakup.sk.kz/#/ext(popup:item/1258707/advert)",
            source_id="samruk:1258707",
            description="Портал: Samruk-Kazyna\nНомер: 1258707\nСумма: 900 000 ₸",
            code="1258707",
            source="Samruk",
        )

        updated = _with_browser_detail_fields(match, "Организатор\nАО \"Самрук-Казына\"")

        self.assertIn("Заказчик: АО \"Самрук-Казына\"", updated.description)


if __name__ == "__main__":
    unittest.main()
