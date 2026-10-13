from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from icportal_bot.health import _run_status_problems


class HealthStatusTests(unittest.TestCase):
    def test_fresh_successful_status_has_no_problems(self) -> None:
        scheduled_at = datetime(2026, 10, 13, 10, 0)
        payload = {
            "checked_at": "2026-10-13T10:05:00",
            "sources": [
                {"source": "MP.kz", "enabled": True, "error": ""},
                {"source": "Samruk", "enabled": True, "error": ""},
            ],
        }

        path = self._write_status(payload, scheduled_at + timedelta(minutes=5))
        self.addCleanup(self._cleanup_status, path)

        self.assertEqual([], _run_status_problems(path, scheduled_at, ["MP.kz", "Samruk"]))

    def test_enabled_source_error_is_reported(self) -> None:
        scheduled_at = datetime(2026, 10, 13, 10, 0)
        payload = {
            "checked_at": "2026-10-13T10:05:00",
            "sources": [
                {"source": "MP.kz", "enabled": True, "error": ""},
                {"source": "GovZakup", "enabled": True, "error": "timeout"},
                {"source": "Samruk", "enabled": False, "error": "disabled"},
            ],
        }

        path = self._write_status(payload, scheduled_at + timedelta(minutes=5))
        self.addCleanup(self._cleanup_status, path)

        self.assertEqual(["GovZakup: ошибка проверки - timeout"], _run_status_problems(path, scheduled_at, ["MP.kz", "GovZakup"]))

    def test_stale_status_file_is_reported(self) -> None:
        scheduled_at = datetime(2026, 10, 13, 10, 0)
        payload = {
            "checked_at": "2026-10-13T09:59:00",
            "sources": [{"source": "MP.kz", "enabled": True, "error": ""}],
        }

        path = self._write_status(payload, scheduled_at - timedelta(minutes=1))
        self.addCleanup(self._cleanup_status, path)

        problems = _run_status_problems(path, scheduled_at)

        self.assertEqual(1, len(problems))
        self.assertIn("устарел", problems[0])

    def test_missing_expected_source_is_reported(self) -> None:
        scheduled_at = datetime(2026, 10, 13, 10, 0)
        payload = {
            "checked_at": "2026-10-13T10:05:00",
            "sources": [{"source": "MP.kz", "enabled": True, "error": ""}],
        }
        path = self._write_status(payload, scheduled_at + timedelta(minutes=5))
        self.addCleanup(self._cleanup_status, path)

        self.assertEqual(
            ["Samruk: нет результата проверки в последнем прогоне"],
            _run_status_problems(path, scheduled_at, ["MP.kz", "Samruk"]),
        )

    def test_incomplete_status_file_is_reported(self) -> None:
        scheduled_at = datetime(2026, 10, 13, 10, 0)
        payload = {
            "checked_at": "2026-10-13T10:05:00",
            "complete": False,
            "sources": [{"source": "MP.kz", "enabled": True, "error": ""}],
        }
        path = self._write_status(payload, scheduled_at + timedelta(minutes=5))
        self.addCleanup(self._cleanup_status, path)

        problems = _run_status_problems(path, scheduled_at, ["MP.kz"])

        self.assertIn("последний прогон еще не завершился полностью", problems)

    def _write_status(self, payload: dict[str, object], mtime: datetime) -> Path:
        path = Path("data") / f"test_health_{os.getpid()}_{id(payload)}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        timestamp = mtime.timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def _cleanup_status(self, path: Path) -> None:
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
