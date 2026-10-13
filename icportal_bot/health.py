from __future__ import annotations

import json
import subprocess
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from .config import ROOT, load_config
from .notifier import send_telegram_text

SCHEDULED_RUN_AT = time(10, 0)
GRACE_PERIOD = timedelta(minutes=30)


def run_health_check(now: datetime | None = None) -> None:
    checked_at = now or datetime.now()
    scheduled_at = datetime.combine(checked_at.date(), SCHEDULED_RUN_AT)
    if checked_at < scheduled_at + GRACE_PERIOD:
        print("ICPortal health: too early to check today's scheduled run.")
        return

    log_path = ROOT / "data" / "scheduler.log"
    if _is_fresh(log_path, scheduled_at):
        print("ICPortal health: scheduled run log is fresh.")
        return

    marker_path = ROOT / "data" / "health_alert.json"
    marker = _read_marker(marker_path)
    today = checked_at.date().isoformat()
    if marker.get("date") == today and marker.get("recovery_started"):
        print("ICPortal health: recovery was already started today.")
        return

    message = (
        "ВНИМАНИЕ: ежедневный парсер закупок не обновил лог после 10:00.\n"
        f"Последняя запись scheduler.log: {_mtime_text(log_path)}.\n"
        "Запускаю восстановительный прогон."
    )
    config = load_config()
    if config.telegram.enabled:
        send_telegram_text(config.telegram, message)
    print(message)
    _start_recovery_run()
    _write_marker(marker_path, {"date": today, "recovery_started": checked_at.isoformat(timespec="seconds")})


def _is_fresh(path: Path, scheduled_at: datetime) -> bool:
    return path.exists() and datetime.fromtimestamp(path.stat().st_mtime) >= scheduled_at


def _mtime_text(path: Path) -> str:
    if not path.exists():
        return "файл отсутствует"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S")


def _start_recovery_run() -> None:
    script = ROOT / "run_icportal_bot.bat"
    subprocess.Popen(
        f'"{script}"',
        cwd=str(ROOT),
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _read_marker(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_marker(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
