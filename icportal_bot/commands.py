from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError

from .config import ROOT, load_config
from .govzakup import diagnose_govzakup_keyword, search_govzakup
from .mitwork import diagnose_mitwork_keyword, search_mitwork
from .models import LotMatch
from .notifier import format_matches, get_telegram_chat_ids, send_telegram, send_telegram_text
from .portal import search_portal
from .samruk import diagnose_samruk, diagnose_samruk_detail, diagnose_samruk_keyword, search_samruk
from .store import MatchStore


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
        source_runs = [
            _safe_search_icportal(config),
            _safe_search_samruk(config),
            _safe_search_erg(config),
            _safe_search_mitwork(config),
            _safe_search_govzakup(config),
        ]
        matches = [match for source_run in source_runs for match in source_run.matches]
        matches = _filter_excluded_phrases(matches, config.search.excluded_phrases)
        new_matches = store.filter_new(matches)
        report = _run_report(config, source_runs, matches, new_matches)
        if not new_matches:
            if config.telegram.enabled:
                send_telegram_text(config.telegram, report)
            print("Новых совпадений нет.")
            return

        if config.telegram.enabled:
            send_telegram(config.telegram, new_matches)
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
    return (
        "Проверка порталов закупок выполнена.\n"
        f"Время: {checked_at}\n"
        f"ICPortal: {icportal_status}\n"
        f"Samruk: {samruk_status}\n"
        f"ERG: {erg_status}\n"
        f"Mitwork: {mitwork_status}\n"
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
    if not phrases:
        return matches
    result: list[LotMatch] = []
    for match in matches:
        haystack = _normalize_text("\n".join((match.title, match.description, match.code, match.keyword)))
        if any(phrase in haystack for phrase in phrases):
            print(f"Исключено по минус-фразе: {match.source} {match.code or match.source_id} {match.title}", flush=True)
            continue
        result.append(match)
    return result


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _safe_search_icportal(config) -> SourceRun:
    try:
        return SourceRun("ICPortal", True, search_portal(config))
    except Exception as error:
        print(f"ICPortal: {error}, источник временно пропущен.", flush=True)
        return SourceRun("ICPortal", True, [], str(error))


def _safe_search_samruk(config) -> SourceRun:
    if not config.samruk.enabled:
        return SourceRun("Samruk", False, [])
    try:
        return SourceRun("Samruk", True, search_samruk(config))
    except HTTPError as error:
        print(f"Samruk: HTTP {error.code}, источник временно пропущен.", flush=True)
        return SourceRun("Samruk", True, [], f"HTTP {error.code}")
    except (URLError, TimeoutError) as error:
        print(f"Samruk: {error}, источник временно пропущен.", flush=True)
        return SourceRun("Samruk", True, [], str(error))
    except Exception as error:
        print(f"Samruk: {error}, источник временно пропущен.", flush=True)
        return SourceRun("Samruk", True, [], str(error))


def _safe_search_erg(config) -> SourceRun:
    if not config.erg.enabled:
        return SourceRun("ERG", False, [])
    try:
        from erg_parser.parser import ErgClient, load_config as load_erg_config

        erg_config_path = Path(config.erg.config_path)
        if not erg_config_path.is_absolute():
            erg_config_path = ROOT / erg_config_path
        erg_config = load_erg_config(erg_config_path)
        if config.erg.max_keyword_checks > 0:
            erg_config = erg_config.with_keywords(erg_config.keywords[: config.erg.max_keyword_checks])
        return SourceRun("ERG", True, [_erg_match_to_lot_match(match) for match in ErgClient(erg_config).search()])
    except Exception as error:
        print(f"ERG: {error}, источник временно пропущен.", flush=True)
        return SourceRun("ERG", True, [], str(error))


def _safe_search_govzakup(config) -> SourceRun:
    if not config.govzakup.enabled:
        return SourceRun("GovZakup", False, [])
    try:
        return SourceRun("GovZakup", True, search_govzakup(config))
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"GovZakup: {error}, источник временно пропущен.", flush=True)
        return SourceRun("GovZakup", True, [], str(error))
    except Exception as error:
        print(f"GovZakup: {error}, источник временно пропущен.", flush=True)
        return SourceRun("GovZakup", True, [], str(error))


def _safe_search_mitwork(config) -> SourceRun:
    if not config.mitwork.enabled:
        return SourceRun("Mitwork", False, [])
    try:
        return SourceRun("Mitwork", True, search_mitwork(config))
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"Mitwork: {error}, источник временно пропущен.", flush=True)
        return SourceRun("Mitwork", True, [], str(error))
    except Exception as error:
        print(f"Mitwork: {error}, источник временно пропущен.", flush=True)
        return SourceRun("Mitwork", True, [], str(error))


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
