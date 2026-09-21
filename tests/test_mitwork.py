from __future__ import annotations

import unittest

from icportal_bot.mitwork import _content_haystack, _lot_descriptions, _lot_rows_from_html


MITWORK_LOTS_HTML = """
<table>
  <tbody>
    <tr data-key="688725">
      <td>631926-ОТ4</td>
      <td><a href="/ru/publics/lot/688725">Услуги по предоставлению лицензий</a></td>
      <td class="col-sm-3 hidden-xs">Лицензия интеллектуального голосового робота и чат-бота</td>
      <td>1.000</td>
    </tr>
  </tbody>
</table>
"""


class MitworkLotDescriptionTests(unittest.TestCase):
    def test_extracts_description_column_from_lot_table(self) -> None:
        lots = _lot_rows_from_html(MITWORK_LOTS_HTML)

        self.assertEqual(
            [("631926-ОТ4", "Услуги по предоставлению лицензий", "Лицензия интеллектуального голосового робота и чат-бота")],
            lots,
        )

    def test_formats_lot_description_for_notification(self) -> None:
        lots = _lot_rows_from_html(MITWORK_LOTS_HTML)

        self.assertEqual(
            "Описание лота: Лицензия интеллектуального голосового робота и чат-бота",
            _lot_descriptions(lots),
        )

    def test_search_haystack_contains_lot_description(self) -> None:
        self.assertIn("голосового робота", _content_haystack(MITWORK_LOTS_HTML))


if __name__ == "__main__":
    unittest.main()
