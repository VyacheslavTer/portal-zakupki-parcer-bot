from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError

from .config import ROOT, load_config
from .govzakup import diagnose_govzakup_keyword, search_govzakup
from .models import LotMatch
from .notifier import format_matches, get_telegram_chat_ids, send_telegram, send_telegram_text
from .portal import search_portal
from .samruk import diagnose_samruk, diagnose_samruk_detail, diagnose_samruk_keyword, search_samruk
from .store import MatchStore


def run() -> None:
    config = load_config()
    store = MatchStore(ROOT / "data" / "sent.sqlite3")
    try:
        matches = search_portal(config)
        matches.extend(_safe_search_samruk(config))
        matches.extend(_safe_search_erg(config))
        matches.extend(_safe_search_govzakup(config))
        matches = _filter_excluded_phrases(matches, config.search.excluded_phrases)
        new_matches = store.filter_new(matches)
        if not new_matches:
            if config.telegram.enabled:
                send_telegram_text(config.telegram, _empty_report(config))
            print("Новых совпадений нет.")
            return

        if config.telegram.enabled:
            send_telegram(config.telegram, new_matches)
        else:
            print(format_matches(new_matches, ascii_safe=True))

        store.mark_sent(new_matches)
        print(f"Новых совпадений: {len(new_matches)}")
    finally:
        store.close()


def _empty_report(config) -> str:
    checked_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    icportal_status = _icportal_status_text(config)
    samruk_status = "действующие закупки с отметкой \"Осталось\"" if config.samruk.enabled else "выключен"
    erg_status = _erg_status_text(config) if config.erg.enabled else "выключен"
    govzakup_status = "актуальные опубликованные лоты" if config.govzakup.enabled else "выключен"
    return (
        "Проверка порталов закупок выполнена.\n"
        f"Время: {checked_at}\n"
        f"ICPortal: {icportal_status}\n"
        f"Samruk: {samruk_status}\n"
        f"ERG: {erg_status}\n"
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


def _safe_search_samruk(config) -> list[LotMatch]:
    if not config.samruk.enabled:
        return []
    try:
        return search_samruk(config)
    except HTTPError as error:
        print(f"Samruk: HTTP {error.code}, источник временно пропущен.", flush=True)
    except (URLError, TimeoutError) as error:
        print(f"Samruk: {error}, источник временно пропущен.", flush=True)
    except Exception as error:
        print(f"Samruk: {error}, источник временно пропущен.", flush=True)
    return []


def _safe_search_erg(config) -> list[LotMatch]:
    if not config.erg.enabled:
        return []
    try:
        from erg_parser.parser import ErgClient, load_config as load_erg_config

        erg_config_path = Path(config.erg.config_path)
        if not erg_config_path.is_absolute():
            erg_config_path = ROOT / erg_config_path
        erg_config = load_erg_config(erg_config_path)
        if config.erg.max_keyword_checks > 0:
            erg_config = erg_config.with_keywords(erg_config.keywords[: config.erg.max_keyword_checks])
        return [_erg_match_to_lot_match(match) for match in ErgClient(erg_config).search()]
    except Exception as error:
        print(f"ERG: {error}, источник временно пропущен.", flush=True)
        return []


def _safe_search_govzakup(config) -> list[LotMatch]:
    if not config.govzakup.enabled:
        return []
    try:
        return search_govzakup(config)
    except (HTTPError, URLError, TimeoutError) as error:
        print(f"GovZakup: {error}, источник временно пропущен.", flush=True)
    except Exception as error:
        print(f"GovZakup: {error}, источник временно пропущен.", flush=True)
    return []


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
