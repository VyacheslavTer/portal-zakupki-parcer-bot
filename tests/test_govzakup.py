from __future__ import annotations

import unittest

from icportal_bot.govzakup import _description


class GovZakupDescriptionTests(unittest.TestCase):
    def test_description_includes_announcement_and_enstru_short_description(self) -> None:
        row = {
            "announcement_name_ru": "Приобретение камеры для легкового автомобиля.",
            "enstrus": [
                {
                    "short_description_ru": "для легковых автомобилей, 6,50-16, резиновая",
                }
            ],
        }

        description = _description(row)

        self.assertIn("Объявление: Приобретение камеры для легкового автомобиля.", description)
        self.assertIn("Краткое описание: для легковых автомобилей, 6,50-16, резиновая", description)


if __name__ == "__main__":
    unittest.main()
