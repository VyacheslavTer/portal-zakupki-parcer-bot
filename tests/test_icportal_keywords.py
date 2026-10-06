from __future__ import annotations

import unittest

from icportal_bot.portal import _keyword_matches


class ICPortalKeywordMatchingTests(unittest.TestCase):
    def test_kib_does_not_match_ekibastuz(self) -> None:
        self.assertFalse(_keyword_matches("КИБ", "строительство, г.Екибастуз"))

    def test_kib_matches_standalone_abbreviation(self) -> None:
        self.assertTrue(_keyword_matches("КИБ", "Продление лицензии КИБ СёрчИнформ"))


if __name__ == "__main__":
    unittest.main()
