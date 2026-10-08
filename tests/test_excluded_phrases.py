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

    def test_furniture_purchase_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="Офис",
                title="приобретение мебели",
                url="https://zakup.gov.kz/announcement/example#lot-43460784",
                source_id="govzakup:43460784",
                code="43460784-ОЛ-ОИ2",
                source="GovZakup",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["мебел"]))

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

    def test_car_tire_camera_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="камера",
                title="Камера",
                url="https://zakup.gov.kz/announcement/40743326#lot-61177450",
                source_id="govzakup:61177450",
                description=(
                    "Объявление: Приобретение камеры для легкового автомобиля.\n"
                    "Краткое описание: для легковых автомобилей, 6,50-16, резиновая"
                ),
                code="88157981-ЗЦП1",
                source="GovZakup",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["для легкового автомобиля"]))

    def test_wheel_disk_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="диск",
                title="Диск колеса",
                url="https://zakup.gov.kz/announcement/example#lot-88122548",
                source_id="govzakup:88122548",
                code="88122548-ЗЦП2",
                source="GovZakup",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["диск колеса"]))

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

    def test_office_pedestal_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="Офис",
                title="Тумба офисная (Восточно-Казахстанская область)",
                url="https://eep.mitwork.kz/ru/publics/buy/206467",
                source_id="mitwork:206467-1",
                code="206467-1",
                source="Mitwork",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["тумба офис"]))

    def test_recruiting_site_access_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="подписка",
                title="Предоставление информации/ доступа на сайт по подбору персонала&#x20;",
                url="https://eep.mitwork.kz/ru/publics/buy/207710",
                source_id="mitwork:207710-1",
                code="207710-1",
                source="Mitwork",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["подбору персонала"]))

    def test_event_conference_service_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="конференц",
                title=(
                    "Услуги по организации/проведению конференций/семинаров/форумов/"
                    "конкурсов/корпоративных/спортивных/культурных/праздничных "
                    "и аналогичных мероприятий"
                ),
                url="https://eep.mitwork.kz/ru/publics/buy/207648",
                source_id="mitwork:207648-2",
                code="207648-2",
                source="Mitwork",
            )
        ]

        self.assertEqual(
            [],
            _filter_excluded_phrases(matches, ["проведению конференций", "аналогичных мероприятий"]),
        )

    def test_food_products_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="смета",
                title="Продукты питания",
                url="https://zakup.gov.kz/announcement/example#lot-43426668",
                source_id="govzakup:43426668",
                code="43426668-ОЛ-ЗЦП2",
                source="GovZakup",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["продукты питания"]))

    def test_sour_cream_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="смета",
                title="Сметана",
                url="https://zakup.gov.kz/announcement/example#lot-88147712",
                source_id="govzakup:88147712",
                code="88147712-ГЗПОП1",
                source="GovZakup",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["сметана"]))

    def test_projector_dlp_false_positive_is_filtered(self) -> None:
        matches = [
            LotMatch(
                keyword="DLP",
                title="Проектор",
                url="https://zakup.sk.kz/#/ext(popup:item/1255995/advert)",
                source_id="samruk:1255995",
                code="1255995",
                source="Samruk",
            )
        ]

        self.assertEqual([], _filter_excluded_phrases(matches, ["проектор"]))


if __name__ == "__main__":
    unittest.main()
