from __future__ import annotations

import json
import os
import subprocess
import sys
from multiprocessing import Process, Queue
from queue import Empty
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Callable
from urllib.error import HTTPError, URLError

from .config import ROOT, load_config
from .govzakup import diagnose_govzakup_keyword, search_govzakup
from .mitwork import diagnose_mitwork_keyword, search_mitwork
from .models import LotMatch
from .mpkz import diagnose_mpkz_keyword, search_mpkz
from .notifier import format_matches, get_telegram_chat_ids, send_telegram, send_telegram_match, send_telegram_text
from .portal import search_portal
from .samruk import diagnose_samruk, diagnose_samruk_detail, diagnose_samruk_keyword, search_samruk
from .store import MatchStore

DEFAULT_SOURCE_TIMEOUT_SECONDS = 3600
SOURCE_TIMEOUT_SECONDS = {
    "Samruk": 1800,
}
SOURCE_NAMES = ("ICPortal", "Samruk", "ERG", "Mitwork", "MP.kz", "GovZakup")
RECOVERY_RUN_ENV = "ICPORTAL_RECOVERY_RUN"


@dataclass(frozen=True)
class SourceRun:
    source: str
    enabled: bool
    matches: list[LotMatch]
    error: str = ""


def run() -> None:
    config = load_config()
    store = MatchStore(ROOT / "data" / "sent.sqlite3")
    try:
        source_runs = _run_sources(config, lambda runs: _write_run_status(runs, [], [], complete=False))
        matches = [match for source_run in source_runs for match in source_run.matches]
        matches = _filter_excluded_phrases(matches, config.search.excluded_phrases)
        new_matches = store.filter_new(matches)
        _write_run_status(source_runs, matches, new_matches, complete=True)
        report = _run_report(config, source_runs, matches, new_matches)
        failure_alert = _source_failure_alert(source_runs)
        recovery_message = _source_failure_recovery_message(source_runs)
        if not new_matches:
            if config.telegram.enabled:
                if failure_alert:
                    send_telegram_text(config.telegram, failure_alert)
                if recovery_message:
                    send_telegram_text(config.telegram, recovery_message)
                send_telegram_text(config.telegram, report)
            print("Новых совпадений нет.")
            return

        if config.telegram.enabled:
            if failure_alert:
                send_telegram_text(config.telegram, failure_alert)
            if recovery_message:
                send_telegram_text(config.telegram, recovery_message)
            for index, match in enumerate(new_matches, start=1):
                send_telegram_match(config.telegram, match, index, len(new_matches))
                store.mark_sent([match])
            send_telegram_text(config.telegram, report)
        else:
            print(format_matches(new_matches, ascii_safe=True))
            print()
            print(report)
            store.mark_sent(new_matches)
        print(f"Новых совпадений: {len(new_matches)}")
    finally:
        store.close()


def _run_report(config, source_runs: list[SourceRun], filtered_matches: list[LotMatch], new_matches: list[LotMatch]) -> str:
    checked_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    filtered_counts = _count_by_source(filtered_matches)
    new_counts = _count_by_source(new_matches)
    lines = [
        "Проверка порталов закупок выполнена.",
        f"Время: {checked_at}",
    ]
    for source_run in source_runs:
        lines.append(_source_report_line(config, source_run, filtered_counts, new_counts))
    if new_matches:
        lines.append(f"Новых совпадений отправлено: {len(new_matches)}.")
    else:
        lines.append("Новых совпадений по ключевым словам не найдено.")
    return "\n".join(lines)


def _write_run_status(
    source_runs: list[SourceRun],
    filtered_matches: list[LotMatch],
    new_matches: list[LotMatch],
    complete: bool,
) -> None:
    now = datetime.now()
    filtered_counts = _count_by_source(filtered_matches)
    new_counts = _count_by_source(new_matches)
    payload = {
        "checked_at": now.isoformat(timespec="seconds"),
        "complete": complete,
        "sources": [
            {
                "source": source_run.source,
                "enabled": source_run.enabled,
                "error": source_run.error,
                "found": len(source_run.matches),
                "after_filters": filtered_counts.get(source_run.source, 0),
                "new": new_counts.get(source_run.source, 0),
            }
            for source_run in source_runs
        ],
    }
    path = ROOT / "data" / "run_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_failure_alert(source_runs: list[SourceRun]) -> str:
    failed_runs = [source_run for source_run in source_runs if source_run.enabled and source_run.error]
    if not failed_runs:
        return ""
    lines = ["ВНИМАНИЕ: не все порталы закупок ответили."]
    for source_run in failed_runs:
        lines.append(f"{source_run.source}: {_short_error(source_run.error)}")
    lines.append("Остальные порталы проверены; результаты ниже могут быть неполными.")
    return "\n".join(lines)


def _source_failure_recovery_message(source_runs: list[SourceRun]) -> str:
    failed_runs = [source_run for source_run in source_runs if source_run.enabled and source_run.error]
    if not failed_runs:
        return ""
    failed_sources = ", ".join(source_run.source for source_run in failed_runs)
    if os.getenv(RECOVERY_RUN_ENV) == "1":
        return (
            "Автовосстановление уже выполнялось в этом прогоне; повторный запуск не создаю, "
            f"чтобы не уйти в цикл. Источники с ошибками: {failed_sources}."
        )
    _start_recovery_run()
    return f"Запущен автоматический повторный прогон из-за ошибок источников: {failed_sources}."


def _start_recovery_run() -> None:
    script = ROOT / "run_icportal_bot.bat"
    env = os.environ.copy()
    env[RECOVERY_RUN_ENV] = "1"
    subprocess.Popen(
        f'"{script}"',
        cwd=str(ROOT),
        env=env,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _source_report_line(config, source_run: SourceRun, filtered_counts: dict[str, int], new_counts: dict[str, int]) -> str:
    if not source_run.enabled:
        return f"{source_run.source}: выключен"
    if source_run.error:
        return f"{source_run.source}: ошибка проверки - {_short_error(source_run.error)}"
    found = len(source_run.matches)
    after_filters = filtered_counts.get(source_run.source, 0)
    new = new_counts.get(source_run.source, 0)
    status = _source_status_text(config, source_run.source)
    if found == 0:
        return f"{source_run.source}: ничего не найдено ({status})"
    if after_filters == 0:
        return f"{source_run.source}: найдено {found}, после минус-фраз ничего не осталось ({status})"
    if new == 0:
        return f"{source_run.source}: найдено {after_filters}, новых нет ({status})"
    return f"{source_run.source}: найдено {after_filters}, новых {new} ({status})"


def _source_status_text(config, source: str) -> str:
    if source == "ICPortal":
        return _icportal_status_text(config)
    if source == "Samruk":
        return "действующие закупки с отметкой \"Осталось\""
    if source == "ERG":
        return _erg_status_text(config)
    if source == "Mitwork":
        return "родные активные объявления MITWORK"
    if source == "MP.kz":
        return "открытые тендеры MP.kz (OPEN_FOR_BID, срок не истек)"
    if source == "GovZakup":
        return "актуальные опубликованные лоты"
    return "включен"


def _count_by_source(matches: list[LotMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.source] = counts.get(match.source, 0) + 1
    return counts


def _short_error(error: str) -> str:
    return " ".join(error.split())[:240]


def _empty_report(config) -> str:
    checked_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    icportal_status = _icportal_status_text(config)
    samruk_status = "действующие закупки с отметкой \"Осталось\"" if config.samruk.enabled else "выключен"
    erg_status = _erg_status_text(config) if config.erg.enabled else "выключен"
    govzakup_status = "актуальные опубликованные лоты" if config.govzakup.enabled else "выключен"
    mitwork_status = "родные активные объявления MITWORK" if config.mitwork.enabled else "выключен"
    mpkz_status = "открытые тендеры MP.kz" if config.mpkz.enabled else "выключен"
    return (
        "Проверка порталов закупок выполнена.\n"
        f"Время: {checked_at}\n"
        f"ICPortal: {icportal_status}\n"
        f"Samruk: {samruk_status}\n"
        f"ERG: {erg_status}\n"
        f"Mitwork: {mitwork_status}\n"
        f"MP.kz: {mpkz_status}\n"
        f"GovZakup: {govzakup_status}\n"
        "Новых совпадений по ключевым словам не найдено."
    )


def _icportal_status_text(config) -> str:
    if config.search.status == "open":
        return "открытые закупки (status=open)"
    return f"статус {config.search.status}" if config.search.status else "все статусы"


def _erg_status_text(config) -> str:
    try:
        from erg_parser.parser import load_config as load_erg_config

        erg_config_path = Path(config.erg.config_path)
        if not erg_config_path.is_absolute():
            erg_config_path = ROOT / erg_config_path
        erg_config = load_erg_config(erg_config_path)
    except Exception:
        return "активные конкурсы по ERG API"
    if erg_config.search_mode == "active_local":
        return f"активные конкурсы (API-фильтр AuStatus={_format_statuses(erg_config.statuses)})"
    return f"поиск по ключевым словам за последние {erg_config.publish_date_days} дн."


def _format_statuses(statuses: list[int]) -> str:
    return ",".join(str(status) for status in statuses)


def _filter_excluded_phrases(matches: list[LotMatch], excluded_phrases: list[str]) -> list[LotMatch]:
    phrases = [_normalize_text(phrase) for phrase in excluded_phrases if phrase.strip()]
    result: list[LotMatch] = []
    for match in matches:
        haystack = _normalize_text("\n".join((match.title, match.description, match.code, match.keyword)))
        if _is_builtin_excluded_match(haystack) or any(phrase in haystack for phrase in phrases):
            _safe_print(f"Исключено по минус-фразе: {match.source} {match.code or match.source_id} {match.title}")
            continue
        result.append(match)
    return result


def _is_builtin_excluded_match(haystack: str) -> bool:
    is_property_rent = ("аренд" in haystack or "эксплуатац" in haystack) and (
        "недвижим" in haystack or "нежил" in haystack
    )
    is_office_rent = "аренд" in haystack and "офис" in haystack and (
        "помещ" in haystack or "недвижим" in haystack or "нежил" in haystack
    )
    is_generic_office_goods = "офис" in haystack and (
        "товары для офис" in haystack or "товар для офис" in haystack
    )
    is_stationery_goods = "канцеляр" in haystack
    is_office_construction = "офис" in haystack and (
        "строитель" in haystack
        or "проклад" in haystack
        or "модернизац" in haystack
    ) and (
        "линии связи" in haystack
        or "линия связи" in haystack
        or "информационнокоммуникационной инфраструктур" in haystack
        or "информационно коммуникационной инфраструктур" in haystack
        or "инфраструктур" in haystack
    )
    is_cutting_tool_disk = "диск" in haystack and (
        "отрезн" in haystack
        or "болгарк" in haystack
        or "ушм" in haystack
        or "угловой шлифов" in haystack
        or "циркулярн" in haystack
        or "пил" in haystack
        or "абразив" in haystack
        or "круг" in haystack
        or "колес" in haystack
        or "колёс" in haystack
        or "сцеплен" in haystack
        or "тормозн" in haystack
        or "уничтожител" in haystack
        or "антибиотик" in haystack
        or "щеточн" in haystack
    )
    return (
        is_property_rent
        or is_office_rent
        or is_generic_office_goods
        or is_stationery_goods
        or is_office_construction
        or is_cutting_tool_disk
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _safe_search_icportal(config) -> SourceRun:
    return _search_with_retry("ICPortal", True, lambda: search_portal(config))


def _safe_search_samruk(config) -> SourceRun:
    if not config.samruk.enabled:
        return SourceRun("Samruk", False, [])
    return _search_with_retry("Samruk", True, lambda: search_samruk(config))


def _safe_search_erg(config) -> SourceRun:
    if not config.erg.enabled:
        return SourceRun("ERG", False, [])
    def search() -> list[LotMatch]:
        from erg_parser.parser import ErgClient, load_config as load_erg_config

        erg_config_path = Path(config.erg.config_path)
        if not erg_config_path.is_absolute():
            erg_config_path = ROOT / erg_config_path
        erg_config = load_erg_config(erg_config_path)
        if config.erg.max_keyword_checks > 0:
            erg_config = erg_config.with_keywords(erg_config.keywords[: config.erg.max_keyword_checks])
        return [_erg_match_to_lot_match(match) for match in ErgClient(erg_config).search()]

    return _search_with_retry("ERG", True, search)


def _safe_search_govzakup(config) -> SourceRun:
    if not config.govzakup.enabled:
        return SourceRun("GovZakup", False, [])
    return _search_with_retry("GovZakup", True, lambda: search_govzakup(config))


def _safe_search_mitwork(config) -> SourceRun:
    if not config.mitwork.enabled:
        return SourceRun("Mitwork", False, [])
    return _search_with_retry("Mitwork", True, lambda: search_mitwork(config))


def _safe_search_mpkz(config) -> SourceRun:
    if not config.mpkz.enabled:
        return SourceRun("MP.kz", False, [])
    return _search_with_retry("MP.kz", True, lambda: search_mpkz(config))


def _run_sources(config, status_callback: Callable[[list[SourceRun]], None]) -> list[SourceRun]:
    processes: dict[str, tuple[Process, Queue, float]] = {}
    completed: dict[str, SourceRun] = {}
    for source in SOURCE_NAMES:
        queue: Queue = Queue(maxsize=1)
        process = Process(target=_search_source_worker, args=(source, config, queue), daemon=True)
        process.start()
        processes[source] = (process, queue, monotonic())

    while len(completed) < len(SOURCE_NAMES):
        changed = False
        for source in SOURCE_NAMES:
            if source in completed:
                continue
            process, queue, started_at = processes[source]
            result = _try_source_run_from_queue(source, queue)
            if result is not None:
                process.join(10)
                if process.is_alive():
                    process.terminate()
                    process.join(5)
                completed[source] = result
                changed = True
                continue
            timeout_seconds = _source_timeout_seconds(source)
            if process.is_alive() and monotonic() - started_at > timeout_seconds:
                completed[source] = _timeout_source_run(source, process)
                changed = True
                continue
            if process.is_alive():
                continue
            completed[source] = _source_run_from_queue(source, queue)
            changed = True
        if changed:
            status_callback(_ordered_source_runs(completed))
            continue
        sleep(1)
    return _ordered_source_runs(completed)


def _timeout_source_run(source: str, process: Process) -> SourceRun:
    timeout_seconds = _source_timeout_seconds(source)
    process.terminate()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join(5)
    return SourceRun(source, True, [], f"timeout after {timeout_seconds} seconds")


def _source_timeout_seconds(source: str) -> int:
    return SOURCE_TIMEOUT_SECONDS.get(source, DEFAULT_SOURCE_TIMEOUT_SECONDS)


def _source_run_from_queue(source: str, queue: Queue) -> SourceRun:
    try:
        result = queue.get(timeout=2)
    except Empty:
        return SourceRun(source, True, [], "search process finished without result")
    return _coerce_source_run(source, result)


def _try_source_run_from_queue(source: str, queue: Queue) -> SourceRun | None:
    try:
        result = queue.get_nowait()
    except Empty:
        return None
    return _coerce_source_run(source, result)


def _coerce_source_run(source: str, result) -> SourceRun:
    if isinstance(result, SourceRun):
        return result
    return SourceRun(source, True, [], str(result))


def _ordered_source_runs(source_runs: dict[str, SourceRun]) -> list[SourceRun]:
    return [source_runs[source] for source in SOURCE_NAMES if source in source_runs]


def _search_source_worker(source: str, config, queue: Queue) -> None:
    try:
        queue.put(_safe_search_source(source, config))
    except Exception as error:
        queue.put(SourceRun(source, True, [], _error_text(error)))


def _safe_search_source(source: str, config) -> SourceRun:
    if source == "ICPortal":
        return _safe_search_icportal(config)
    if source == "Samruk":
        return _safe_search_samruk(config)
    if source == "ERG":
        return _safe_search_erg(config)
    if source == "Mitwork":
        return _safe_search_mitwork(config)
    if source == "MP.kz":
        return _safe_search_mpkz(config)
    if source == "GovZakup":
        return _safe_search_govzakup(config)
    return SourceRun(source, False, [], "unknown source")


def _search_with_retry(source: str, enabled: bool, search: Callable[[], list[LotMatch]], attempts: int = 2) -> SourceRun:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return SourceRun(source, enabled, search())
        except Exception as error:
            last_error = error
            if attempt < attempts:
                _safe_print(f"{source}: {_error_text(error)}, пробую восстановить проверку и повторить.")
                sleep(5)
                continue
            _safe_print(f"{source}: {_error_text(error)}, источник временно пропущен после повтора.")
    return SourceRun(source, enabled, [], _error_text(last_error) if last_error else "unknown error")


def _safe_print(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_message = message.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_message, flush=True)


def _error_text(error: Exception | None) -> str:
    if error is None:
        return "unknown error"
    if isinstance(error, HTTPError):
        return f"HTTP {error.code}"
    if isinstance(error, URLError):
        return str(error.reason)
    return str(error)


def _erg_match_to_lot_match(match) -> LotMatch:
    return LotMatch(
        keyword=match.keyword,
        title=match.title,
        url=match.url,
        source_id=match.source_id,
        description=match.description,
        code=match.number,
        source="ERG",
    )


def samruk_diagnose(advert_id: str | None = None, keyword: str | None = None) -> None:
    config = load_config()
    if advert_id:
        detail = diagnose_samruk_detail(config, advert_id)
        if detail is None:
            print(f"Samruk: детали закупки {advert_id} не получены.")
            return
        print(detail)
        return
    if keyword:
        rows = diagnose_samruk_keyword(config, keyword)
        _print_samruk_rows(rows)
        return
    rows = diagnose_samruk(config)
    _print_samruk_rows(rows)


def govzakup_diagnose(keyword: str) -> None:
    config = load_config()
    matches = diagnose_govzakup_keyword(config, keyword)
    if not matches:
        print("GovZakup: актуальные лоты не найдены.")
        return
    print(format_matches(matches, ascii_safe=True))


def mitwork_diagnose(keyword: str) -> None:
    config = load_config()
    matches = diagnose_mitwork_keyword(config, keyword)
    if not matches:
        print("Mitwork: актуальные объявления не найдены.")
        return
    print(format_matches(matches, ascii_safe=True))


def mpkz_diagnose(keyword: str) -> None:
    config = load_config()
    matches = diagnose_mpkz_keyword(config, keyword)
    if not matches:
        print("MP.kz: открытые тендеры не найдены.")
        return
    print(format_matches(matches, ascii_safe=True))


def _print_samruk_rows(rows: list[dict]) -> None:
    if not rows:
        print("Samruk: в публичном поиске не удалось разобрать закупки.")
        return
    for index, row in enumerate(rows, start=1):
        print(f"{index}. {row.get('number') or row.get('id') or row.get('advertNumber')}")
        print(row.get("nameRu") or row.get("name") or row.get("titleRu") or row.get("text") or row)
        print()


def telegram_chat_id() -> None:
    config = load_config()
    chat_ids = get_telegram_chat_ids(config.telegram)
    if not chat_ids:
        print("Сообщений боту пока нет. Напишите вашему Telegram-боту /start и запустите команду еще раз.")
        return
    for chat_id, title in chat_ids:
        print(f"{chat_id} - {title}")


def telegram_test() -> None:
    config = load_config()
    send_telegram(
        config.telegram,
        [
            LotMatch(
                keyword="test",
                title="Тестовое уведомление ICPortal работает.",
                url=config.portal.url,
                source_id="telegram-test",
                source="Test",
            )
        ],
    )
    print("Тестовое сообщение отправлено.")
