from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_DB = ROOT / "data" / "erg_sent.sqlite3"
MIN_KEYWORD_LENGTH = 3
SHORT_KEYWORD_ALLOWLIST = {"1C", "1С", "MS"}


@dataclass(frozen=True)
class Config:
    api_url: str
    detail_api_url: str
    page_url: str
    statuses: list[int]
    search_mode: str
    publish_date_days: int
    keywords: list[str]
    excluded_phrases: list[str]
    request_timeout_seconds: float
    detail_timeout_seconds: float
    delay_between_requests_seconds: float
    fetch_details_for_all_active: bool
    max_details: int
    telegram_enabled: bool
    telegram_bot_token_env: str
    telegram_chat_id_env: str

    def with_keywords(self, keywords: list[str]) -> Config:
        return Config(
            api_url=self.api_url,
            detail_api_url=self.detail_api_url,
            page_url=self.page_url,
            statuses=self.statuses,
            search_mode=self.search_mode,
            publish_date_days=self.publish_date_days,
            keywords=keywords,
            excluded_phrases=self.excluded_phrases,
            request_timeout_seconds=self.request_timeout_seconds,
            detail_timeout_seconds=self.detail_timeout_seconds,
            delay_between_requests_seconds=self.delay_between_requests_seconds,
            fetch_details_for_all_active=self.fetch_details_for_all_active,
            max_details=self.max_details,
            telegram_enabled=self.telegram_enabled,
            telegram_bot_token_env=self.telegram_bot_token_env,
            telegram_chat_id_env=self.telegram_chat_id_env,
        )


@dataclass(frozen=True)
class Match:
    source_id: str
    keyword: str
    number: str
    title: str
    url: str
    description: str


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Monitor ERG competitions separately from ICPortal.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--keyword", action="append", help="Override config keywords; can be passed more than once.")
    parser.add_argument("--max-keywords", type=int, help="Only process this many keywords from the selected list.")
    parser.add_argument("--start-at", type=int, default=0, help="Skip this many keywords before processing.")
    parser.add_argument("--dry-run", action="store_true", help="Do not mark matches as sent.")
    parser.add_argument("--show-all", action="store_true", help="Print all matches, including already sent.")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.keyword:
        config = config.with_keywords(args.keyword)
    elif args.start_at or args.max_keywords is not None:
        keywords = config.keywords[args.start_at :]
        if args.max_keywords is not None:
            keywords = keywords[: args.max_keywords]
        config = config.with_keywords(keywords)
    client = ErgClient(config)
    store = MatchStore(args.db)
    try:
        matches = client.search()
        output_matches = matches if args.show_all else store.filter_new(matches)
        if output_matches:
            text = format_matches(output_matches)
            print(text, flush=True)
            if config.telegram_enabled and not args.dry_run:
                send_telegram(config, text)
            if not args.dry_run and not args.show_all:
                store.mark_sent(output_matches)
        else:
            print("ERG: новых совпадений нет.", flush=True)
    finally:
        store.close()


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Copy erg_parser/config.example.json to erg_parser/config.json.")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    return Config(
        api_url=raw["api_url"],
        detail_api_url=raw["detail_api_url"],
        page_url=raw["page_url"],
        statuses=[int(status) for status in raw.get("statuses", [4])],
        search_mode=raw.get("search_mode", "server_keywords"),
        publish_date_days=int(raw.get("publish_date_days", 31)),
        keywords=[str(keyword) for keyword in raw["keywords"]],
        excluded_phrases=[str(phrase) for phrase in raw.get("excluded_phrases", [])],
        request_timeout_seconds=float(raw.get("request_timeout_seconds", 30)),
        detail_timeout_seconds=float(raw.get("detail_timeout_seconds", 15)),
        delay_between_requests_seconds=float(raw.get("delay_between_requests_seconds", 0.5)),
        fetch_details_for_all_active=bool(raw.get("fetch_details_for_all_active", False)),
        max_details=int(raw.get("max_details", 50)),
        telegram_enabled=bool(raw.get("telegram_enabled", False)),
        telegram_bot_token_env=raw.get("telegram_bot_token_env", "TELEGRAM_BOT_TOKEN"),
        telegram_chat_id_env=raw.get("telegram_chat_id_env", "TELEGRAM_CHAT_ID"),
    )


class ErgClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.keywords = active_keywords(config.keywords)

    def search(self) -> list[Match]:
        if self.config.search_mode == "server_keywords":
            return filter_excluded_phrases(self.search_server_keywords(), self.config.excluded_phrases)
        if self.config.search_mode != "active_local":
            raise ValueError("search_mode must be server_keywords or active_local")
        return filter_excluded_phrases(self.search_active_local(), self.config.excluded_phrases)

    def search_server_keywords(self) -> list[Match]:
        matches: list[Match] = []
        start_date = date.today() - timedelta(days=self.config.publish_date_days)
        end_date = date.today()
        for keyword in self.keywords:
            params: dict[str, Any] = {
                "EstmcPosName": keyword,
                "AuStatus": ",".join(str(status) for status in self.config.statuses),
                "PublishDateFrom": start_date.isoformat(),
                "PublishDateTo": end_date.isoformat(),
            }
            rows = self.safe_get_auctions(params)
            for row in dedupe_rows(rows):
                if not is_active_row(row, self.config):
                    continue
                match = match_from_row(keyword, row, self.config.page_url)
                detail = self.get_detail(row)
                if detail:
                    match = match_from_detail(keyword, row, detail, self.config.page_url)
                matches.append(match)
            time.sleep(self.config.delay_between_requests_seconds)
        return dedupe_matches(matches)

    def search_active_local(self) -> list[Match]:
        rows: list[dict[str, Any]] = []
        for status in self.config.statuses:
            rows.extend(self.get_auctions({"AuStatus": status}))

        matches: list[Match] = []
        detail_candidates: list[dict[str, Any]] = []
        for row in dedupe_rows(rows):
            if not is_active_row(row, self.config):
                continue
            keyword = find_keyword(self.keywords, row_haystack(row))
            if keyword:
                matches.append(match_from_row(keyword, row, self.config.page_url))
            elif self.config.fetch_details_for_all_active and len(detail_candidates) < self.config.max_details:
                detail_candidates.append(row)

        for row in detail_candidates:
            detail = self.get_detail(row)
            if not detail:
                continue
            keyword = find_keyword(self.keywords, detail_haystack(detail))
            if keyword:
                matches.append(match_from_detail(keyword, row, detail, self.config.page_url))

        return dedupe_matches(matches)

    def safe_get_auctions(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            return self.get_auctions(params)
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:300]
            print(f"ERG list {params}: HTTP {error.code} {body}", flush=True)
            return []
        except (URLError, TimeoutError) as error:
            print(f"ERG list {params}: {error}", flush=True)
            return []

    def get_auctions(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        started = time.monotonic()
        url = f"{self.config.api_url}?{urlencode(params)}" if params else self.config.api_url
        payload = self.get_json(url, self.config.request_timeout_seconds)
        rows = payload.get("GetAuctionsResult") or []
        elapsed = time.monotonic() - started
        print(f"ERG list {params}: rows={len(rows)} elapsed={elapsed:.2f}s", flush=True)
        return rows if isinstance(rows, list) else []

    def get_detail(self, row: dict[str, Any]) -> dict[str, Any] | None:
        auction_id = row.get("ID")
        if not auction_id:
            return None
        url = f"{self.config.detail_api_url}?{urlencode({'auctionId': auction_id})}"
        try:
            payload = self.get_json(url, self.config.detail_timeout_seconds)
        except (HTTPError, URLError, TimeoutError) as error:
            print(f"ERG detail {auction_id}: {error}", flush=True)
            return None
        detail = payload.get("GetCommercialOfferViewModelResult")
        return detail if isinstance(detail, dict) else None

    def get_json(self, url: str, timeout: float) -> dict[str, Any]:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (compatible; ErgParser/0.1)",
                "Referer": self.config.page_url,
            },
            method="GET",
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8-sig"))


class MatchStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_matches (
                source_id TEXT PRIMARY KEY,
                number TEXT NOT NULL,
                title TEXT NOT NULL,
                keyword TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def filter_new(self, matches: list[Match]) -> list[Match]:
        fresh: list[Match] = []
        for match in matches:
            exists = self.connection.execute(
                "SELECT 1 FROM sent_matches WHERE source_id = ?",
                (match.source_id,),
            ).fetchone()
            if exists is None:
                fresh.append(match)
        return fresh

    def mark_sent(self, matches: list[Match]) -> None:
        self.connection.executemany(
            """
            INSERT OR IGNORE INTO sent_matches (source_id, number, title, keyword)
            VALUES (?, ?, ?, ?)
            """,
            [(match.source_id, match.number, match.title, match.keyword) for match in matches],
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def active_keywords(keywords: list[str]) -> list[str]:
    result: list[str] = []
    for keyword in keywords:
        clean = keyword.strip()
        if len(clean) < MIN_KEYWORD_LENGTH and clean not in SHORT_KEYWORD_ALLOWLIST:
            print(f"ERG: пропускаю слишком короткое ключевое слово: {keyword}", flush=True)
            continue
        result.append(clean)
    return result


def row_haystack(row: dict[str, Any]) -> str:
    fields = [
        "NUM",
        "MAIN_CATEGORY_TITLE",
        "MAIN_CATEGORY_TRU_TITLE",
        "DETAILED_NAME_PURCHASE_SUBJECT",
        "Customers",
        "InnerCustomers",
        "CustomerShortName",
        "ETP_TENDER_NUMBER",
    ]
    return "\n".join(clean_text(row.get(field)) for field in fields)


def detail_haystack(detail: dict[str, Any]) -> str:
    values: list[str] = []
    auction = detail.get("AuctionsDetails") or {}
    if isinstance(auction, dict):
        values.extend(clean_text(value) for value in auction.values() if isinstance(value, (str, int, float)))
    for position in detail.get("Positions") or []:
        if isinstance(position, dict):
            values.extend(clean_text(value) for value in position.values() if isinstance(value, (str, int, float)))
    for docs_key in ("DocSpecificationList", "DocTenderList", "DocProjectContractsList"):
        for doc in detail.get(docs_key) or []:
            if isinstance(doc, dict):
                values.append(clean_text(doc.get("NAME")))
                values.append(clean_text(doc.get("DOC_COMMENT")))
    return "\n".join(value for value in values if value)


def find_keyword(keywords: list[str], text: str) -> str | None:
    lowered = text.lower()
    return next((keyword for keyword in keywords if keyword.lower() in lowered), None)


def filter_excluded_phrases(matches: list[Match], excluded_phrases: list[str]) -> list[Match]:
    phrases = [normalize_text(phrase) for phrase in excluded_phrases if phrase.strip()]
    if not phrases:
        return matches
    result: list[Match] = []
    for match in matches:
        haystack = normalize_text("\n".join((match.title, match.description, match.number, match.keyword)))
        if any(phrase in haystack for phrase in phrases):
            print(f"ERG: исключено по минус-фразе: {match.number} {match.title}", flush=True)
            continue
        result.append(match)
    return result


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def is_active_row(row: dict[str, Any], config: Config) -> bool:
    try:
        status = int(row.get("STATUS"))
    except (TypeError, ValueError):
        return False
    if status not in config.statuses:
        return False
    end_date = parse_date(row.get("CO_TAKING_END_DATE_1") or row.get("CO_TACKING_END_DATE_2"))
    return end_date is None or end_date >= date.today()


def match_from_row(keyword: str, row: dict[str, Any], page_url: str) -> Match:
    auction_id = clean_text(row.get("ID"))
    number = clean_text(row.get("NUM"))
    title = first_text(
        row.get("DETAILED_NAME_PURCHASE_SUBJECT"),
        row.get("MAIN_CATEGORY_TRU_TITLE"),
        row.get("MAIN_CATEGORY_TITLE"),
        number,
    )
    return Match(
        source_id=f"erg:{auction_id}",
        keyword=keyword,
        number=number,
        title=title,
        url=competition_url(page_url, auction_id),
        description=format_row_description(row),
    )


def match_from_detail(keyword: str, row: dict[str, Any], detail: dict[str, Any], page_url: str) -> Match:
    match = match_from_row(keyword, row, page_url)
    positions = detail.get("Positions") or []
    lines: list[str] = []
    for position in positions:
        if isinstance(position, dict):
            text = first_text(position.get("TruFullName"), position.get("TruName"), position.get("Comment"))
            if keyword.lower() in text.lower():
                lines.append(text)
    if not lines:
        for position in positions[:5]:
            if isinstance(position, dict):
                lines.append(first_text(position.get("TruFullName"), position.get("TruName"), position.get("Comment")))
    if lines:
        title = first_text(match.title, lines[0])
        description = match.description + "\nПозиции:\n" + "\n".join(f"- {line}" for line in lines if line)
    else:
        title = match.title
        description = match.description
    return Match(match.source_id, match.keyword, match.number, title, match.url, description)


def format_row_description(row: dict[str, Any]) -> str:
    parts = [
        field("Портал", "ERG"),
        field("Номер", row.get("NUM")),
        field("Статус", row.get("STATUS")),
        field("Способ закупки", row.get("PURCHASE_MANNER")),
        field("Публикация", date_only(row.get("PUBLISH_DATE_1"))),
        field("Окончание приема КП", date_only(row.get("CO_TAKING_END_DATE_1"))),
        field("Заказчик", row.get("Customers")),
        field("Категория", row.get("MAIN_CATEGORY_TITLE")),
        field("Категория ТРУ", row.get("MAIN_CATEGORY_TRU_TITLE")),
        field("Позиций", row.get("PositionCount")),
        field("Контакт", row.get("ContactFullName") or row.get("ContactName")),
        field("Email", row.get("CONTACT_EMAIL")),
        field("Телефон", row.get("CONTACT_PHONE")),
    ]
    return "\n".join(part for part in parts if part)


def format_matches(matches: list[Match]) -> str:
    lines = ["Новые совпадения на ERG:"]
    for match in matches:
        lines.append("")
        lines.append(f"Ключевое слово: {match.keyword}")
        if match.number:
            lines.append(f"Номер: {match.number}")
        lines.append(match.title)
        lines.append(match.url)
        lines.append(match.description)
    return "\n".join(lines)


def competition_url(page_url: str, auction_id: str) -> str:
    if not auction_id:
        return page_url
    return f"{page_url.rstrip('/')}/{auction_id}/competition-common-info"


def send_telegram(config: Config, text: str) -> None:
    token = os.getenv(config.telegram_bot_token_env)
    chat_id = os.getenv(config.telegram_chat_id_env)
    if not token or not chat_id:
        raise RuntimeError("ERG Telegram is enabled, but token or chat id env is empty.")

    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        if response.status >= 400:
            raise RuntimeError(f"Telegram returned HTTP {response.status}")


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = clean_text(row.get("ID"))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def dedupe_matches(matches: list[Match]) -> list[Match]:
    seen: set[str] = set()
    unique: list[Match] = []
    for match in matches:
        if match.source_id in seen:
            continue
        seen.add(match.source_id)
        unique.append(match)
    return unique


def field(label: str, value: Any) -> str:
    text = clean_text(value)
    return f"{label}: {text}" if text else ""


def first_text(*values: Any) -> str:
    return next((text for text in (clean_text(value) for value in values) if text), "")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def date_only(value: Any) -> str:
    return clean_text(value).split("T", 1)[0]


def parse_date(value: Any) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


if __name__ == "__main__":
    main()
