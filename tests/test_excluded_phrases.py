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

    def test_known_erg_vision_part_is_always_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="Visio",
                title="03060123-Запчасти к технике импортной прочие",
                url="https://torgi.erg.kz/supplier/#/competitions/617046/competition-common-info",
                source_id="erg:617046",
                description="Позиции:\n- ЛАМПА; ОБОЗНАЧЕНИЕ: VISION W5W 12V 5W",
                code="T/39165/17/09/26",
                source="ERG",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["vision w5w"]))


if __name__ == "__main__":
    unittest.main()
