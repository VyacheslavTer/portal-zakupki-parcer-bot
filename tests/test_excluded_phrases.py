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

    def test_furniture_stem_filters_upholstery_service(self) -> None:
        matches = [
            LotMatch(
                keyword="Офис",
                title="Услуги по обтяжке мебели (обивка)",
                url="https://example.test/206244-1",
                source_id="mitwork:206244-1",
                code="206244-1",
                source="Mitwork",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["обтяж", "обивк"]))

    def test_car_parts_camera_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="камера",
                title="03060129-Запчасти автомашин легковых импортных",
                url="https://torgi.erg.kz/supplier/#/competitions/000000/competition-common-info",
                source_id="erg:000000",
                code="S/05299/21/09/26",
                source="ERG",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["запчасти автомашин"]))

    def test_office_cabinet_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="Офис",
                title="Шкаф офисный металлический (Жетысуская область)",
                url="https://eep.mitwork.kz/ru/publics/buy/206252",
                source_id="mitwork:206252-1",
                code="206252-1",
                source="Mitwork",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["шкаф офис"]))


if __name__ == "__main__":
    unittest.main()
