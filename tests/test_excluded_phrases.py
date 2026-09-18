from __future__ import annotations

import unittest

from icportal_bot.commands import _filter_excluded_phrases
from icportal_bot.models import LotMatch


class ExcludedPhraseTests(unittest.TestCase):
    def test_chair_stem_filters_inflected_titles(self) -> None:
        matches = [
            LotMatch(
                keyword="Офис",
                title="Офисные кресла для руководителя",
                url="https://example.test/205785-1",
                source_id="mitwork:205785-1",
                code="205785-1",
                source="Mitwork",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["кресл"]))


if __name__ == "__main__":
    unittest.main()
