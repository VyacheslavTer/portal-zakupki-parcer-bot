from __future__ import annotations

import unittest
from unittest.mock import patch

from icportal_bot.commands import _search_with_retry
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


if __name__ == "__main__":
    unittest.main()
