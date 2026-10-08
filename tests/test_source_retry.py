from __future__ import annotations

import unittest
from unittest.mock import patch

from icportal_bot.commands import SourceRun, _source_failure_alert, _search_with_retry
from icportal_bot.models import LotMatch


class SourceRetryTests(unittest.TestCase):
    def test_source_is_retried_after_first_failure(self) -> None:
        calls = 0
        match = LotMatch(
            keyword="Acrobat",
            title="Acrobat Pro",
            url="https://example.test",
            source_id="samruk:1",
            source="Samruk",
        )

        def search() -> list[LotMatch]:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise TimeoutError("temporary timeout")
            return [match]

        with patch("icportal_bot.commands.sleep"):
            result = _search_with_retry("Samruk", True, search)

        self.assertEqual([match], result.matches)
        self.assertEqual("", result.error)
        self.assertEqual(2, calls)

    def test_source_reports_error_only_after_retry_fails(self) -> None:
        calls = 0

        def search() -> list[LotMatch]:
            nonlocal calls
            calls += 1
            raise RuntimeError("still broken")

        with patch("icportal_bot.commands.sleep"):
            result = _search_with_retry("GovZakup", True, search)

        self.assertEqual([], result.matches)
        self.assertIn("still broken", result.error)
        self.assertEqual(2, calls)

    def test_source_failure_alert_lists_failed_enabled_sources(self) -> None:
        alert = _source_failure_alert(
            [
                SourceRun("ICPortal", True, []),
                SourceRun("MP.kz", True, [], "connection refused"),
                SourceRun("Samruk", False, [], "disabled error is ignored"),
            ]
        )

        self.assertIn("ВНИМАНИЕ", alert)
        self.assertIn("MP.kz: connection refused", alert)
        self.assertNotIn("Samruk", alert)

    def test_source_failure_alert_is_empty_when_all_enabled_sources_answered(self) -> None:
        self.assertEqual("", _source_failure_alert([SourceRun("MP.kz", True, [])]))


if __name__ == "__main__":
    unittest.main()
