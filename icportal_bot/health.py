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

    config = load_config()
    status_path = ROOT / "data" / "run_status.json"
    problems = _run_status_problems(status_path, scheduled_at, _enabled_source_names(config))
    if not problems:
        print("ICPortal health: all enabled sources reported successfully.")
        return

    marker_path = ROOT / "data" / "health_alert.json"
    marker = _read_marker(marker_path)
    today = checked_at.date().isoformat()
    if marker.get("date") == today and marker.get("recovery_started"):
        print("ICPortal health: recovery was already started today.")
        return

    message = (
        "ВНИМАНИЕ: ежедневный парсер закупок не прошел полную проверку всех порталов.\n"
        + "\n".join(f"- {problem}" for problem in problems)
        + "\n"
        "Запускаю восстановительный прогон."
    )
    if config.telegram.enabled:
        send_telegram_text(config.telegram, message)
    print(message)
    _start_recovery_run()
    _write_marker(marker_path, {"date": today, "recovery_started": checked_at.isoformat(timespec="seconds")})


def _run_status_problems(path: Path, scheduled_at: datetime, expected_sources: list[str] | None = None) -> list[str]:
    if not path.exists():
        return ["нет data/run_status.json с результатами последнего полного прогона"]
    if datetime.fromtimestamp(path.stat().st_mtime) < scheduled_at:
        return [f"data/run_status.json устарел: {_mtime_text(path)}"]
    payload = _read_marker(path)
    checked_at = _parse_datetime(payload.get("checked_at"))
    if checked_at is None or checked_at < scheduled_at:
        return [f"последний полный прогон устарел: {payload.get('checked_at') or 'нет checked_at'}"]
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        return ["в run_status.json нет списка источников"]
    problems: list[str] = []
    seen_enabled: set[str] = set()
    for source in sources:
        if not isinstance(source, dict) or not source.get("enabled"):
            continue
        name = str(source.get("source") or "unknown")
        seen_enabled.add(name)
        error = str(source.get("error") or "").strip()
        if error:
            problems.append(f"{name}: ошибка проверки - {error[:180]}")
    for name in expected_sources or []:
        if name not in seen_enabled:
            problems.append(f"{name}: нет результата проверки в последнем прогоне")
    return problems


def _enabled_source_names(config) -> list[str]:
    names = ["ICPortal"]
    if config.samruk.enabled:
        names.append("Samruk")
    if config.erg.enabled:
        names.append("ERG")
    if config.mitwork.enabled:
        names.append("Mitwork")
    if config.mpkz.enabled:
        names.append("MP.kz")
    if config.govzakup.enabled:
        names.append("GovZakup")
    return names


def _mtime_text(path: Path) -> str:
    if not path.exists():
        return "файл отсутствует"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%d.%m.%Y %H:%M:%S")


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


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
