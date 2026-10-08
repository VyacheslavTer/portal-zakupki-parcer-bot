from __future__ import annotations

import html
import json
import unittest
from datetime import datetime, timedelta, timezone

from icportal_bot.mpkz import _is_open_actual, _lot_rows_from_html, _match_from_lot


class MpKzParserTests(unittest.TestCase):
    def test_extracts_lot_rows_from_html(self) -> None:
        row = {
            "id": 269397,
            "name": "Лицензии Microsoft SQL Server 2025 Standard Core",
            "State": {"constant": "OPEN_FOR_BID", "id": 2, "name": "Открытый"},
            "dateStop": "2026-10-14T16:30:00+05:00",
        }
        payload = html.escape(json.dumps(row, ensure_ascii=False), quote=True)
        text = f"<tender-lot-row :lot='{payload}'></tender-lot-row>"

        rows = _lot_rows_from_html(text)

        self.assertEqual(1, len(rows))
        self.assertEqual(269397, rows[0]["id"])
        self.assertEqual("OPEN_FOR_BID", rows[0]["State"]["constant"])

    def test_only_open_future_lots_are_actual(self) -> None:
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()

        self.assertTrue(_is_open_actual({"State": {"constant": "OPEN_FOR_BID"}, "dateStop": future}))
        self.assertFalse(_is_open_actual({"State": {"constant": "SUCCESSFUL"}, "dateStop": future}))
        self.assertFalse(_is_open_actual({"State": {"constant": "OPEN_FOR_BID"}, "dateStop": past}))

    def test_match_contains_mpkz_customer_status_and_amount(self) -> None:
        row = {
            "id": 269397,
            "name": "Лицензии Microsoft SQL Server 2025 Standard Core",
            "State": {"constant": "OPEN_FOR_BID", "id": 2, "name": "Открытый"},
            "Tender": {
                "id": 192323,
                "name": "Лицензии Microsoft SQL Server 2025 Standard Core",
                "InitiatorCompany": {"name": "Микрофинансовая организация Азиатский Кредитный Фонд"},
            },
            "Category": {"name": "Программное обеспечение, техническая поддержка и услуги интеграции"},
            "Type": {"name": "Классический торг"},
            "Currency": {"abbreviation": "тг"},
            "dateStop": "2026-10-14T16:30:00+05:00",
            "volume": 17049000,
            "tenderUrl": "/tenders/t192323-test/",
        }

        match = _match_from_lot("Microsoft", row, "https://mp.kz/")

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual("MP.kz", match.source)
        self.assertEqual("mpkz:269397", match.source_id)
        self.assertEqual("Лот 269397 / Тендер 192323", match.code)
        self.assertIn("Заказчик: Микрофинансовая организация Азиатский Кредитный Фонд", match.description)
        self.assertIn("Сумма: 17 049 000.00 тг", match.description)


if __name__ == "__main__":
    unittest.main()
