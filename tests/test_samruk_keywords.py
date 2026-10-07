from __future__ import annotations

import unittest

from icportal_bot.samruk import _is_missing_browser_error, _keyword_matches


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


if __name__ == "__main__":
    unittest.main()
