from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .config import Config
from .models import LotMatch
from .portal import MIN_KEYWORD_LENGTH, SHORT_KEYWORD_ALLOWLIST


class GovZakupClient:
    def __init__(self, config: Config) -> None:
        self.config = config.govzakup
        self.keywords = _active_keywords(config.search.keywords)
        self.max_results_per_keyword = config.search.max_results_per_keyword
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; GovZakupParser/0.1)",
            "Referer": self.config.url,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }

    def search(self) -> list[LotMatch]:
        matches: list[LotMatch] = []
        for keyword in self.keywords[: self.config.max_keyword_checks]:
            matches.extend(self.search_keyword(keyword))
            time.sleep(self.config.delay_between_requests_seconds)
        return _dedupe(matches)

    def search_keyword(self, keyword: str) -> list[LotMatch]:
        matches: list[LotMatch] = []
        page = 0
        next_url: str | None = None
        while self.config.max_pages <= 0 or page < self.config.max_pages:
            try:
                payload = self.fetch_lot_page(keyword, page, next_url)
            except (HTTPError, URLError, TimeoutError) as error:
                print(f"GovZakup lots {keyword!r} page={page}: {error}", flush=True)
                break
            rows = payload.get("results") if isinstance(payload, dict) else None
            if not rows:
                break
            for row in rows:
                if _system_id(row) in self.config.excluded_system_ids:
                    continue
                if not _is_actual_lot(row):
                    continue
                match = _match_from_lot(keyword, row)
                if match is not None:
                    matches.append(match)
                if len(matches) >= self.max_results_per_keyword:
                    return matches
            next_url = payload.get("next") if isinstance(payload, dict) else None
            if not _is_safe_next_url(next_url):
                break
            page += 1
        return matches

    def fetch_lots(self, keyword: str, page: int = 0) -> list[dict[str, Any]]:
        payload = self.fetch_lot_page(keyword, page)
        rows = payload.get("results") if isinstance(payload, dict) else None
        return rows if isinstance(rows, list) else []

    def fetch_lot_page(self, keyword: str, page: int = 0, url: str | None = None) -> dict[str, Any]:
        if url is None:
            params = {
                "q": keyword,
                "limit": self.config.page_size,
                "offset": page * self.config.page_size,
                "offer_end_date__gte": datetime.now(timezone.utc).isoformat(),
            }
            url = f"{self.config.lots_api_url}?{urlencode(params)}"
        request = Request(url, headers=self.headers, method="GET")
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return payload if isinstance(payload, dict) else {}


def search_govzakup(config: Config) -> list[LotMatch]:
    if not config.govzakup.enabled:
        return []
    return GovZakupClient(config).search()


def diagnose_govzakup_keyword(config: Config, keyword: str, limit: int = 10) -> list[LotMatch]:
    return GovZakupClient(config).search_keyword(keyword)[:limit]


def _active_keywords(keywords: list[str]) -> list[str]:
    active: list[str] = []
    for keyword in keywords:
        normalized_keyword = keyword.strip()
        if len(normalized_keyword) < MIN_KEYWORD_LENGTH and normalized_keyword not in SHORT_KEYWORD_ALLOWLIST:
            continue
        active.append(normalized_keyword)
    return active


def _is_actual_lot(row: dict[str, Any]) -> bool:
    status = row.get("status")
    if isinstance(status, dict) and status.get("is_active") is False:
        return False
    if row.get("status_name") and str(row.get("status_name")).lower() not in {"опубликован", "опубликовано"}:
        return False
    end_date = _parse_datetime(row.get("offer_end_date"))
    return end_date is not None and end_date >= datetime.now(timezone.utc)


def _system_id(row: dict[str, Any]) -> int | None:
    system = row.get("system")
    value = system.get("id") if isinstance(system, dict) else row.get("system_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_safe_next_url(url: object) -> bool:
    if not url:
        return False
    parsed = urlparse(str(url))
    return parsed.scheme == "https" and parsed.netloc == "zakup.gov.kz"


def _match_from_lot(keyword: str, row: dict[str, Any]) -> LotMatch | None:
    lot_id = _text(row.get("id") or row.get("external_id"))
    lot_number = _text(row.get("lot_number") or row.get("lot_number_key"))
    announcement_id = _text(row.get("announcement_id"))
    title = _text(row.get("name_ru") or row.get("description_ru") or row.get("announcement_number"))
    if not lot_id or not title:
        return None

    return LotMatch(
        keyword=keyword,
        title=title,
        url=_lot_url(row),
        source_id=f"govzakup:{lot_id}",
        description=_description(row),
        code=lot_number,
        source="GovZakup",
    )


def _lot_url(row: dict[str, Any]) -> str:
    announcement_id = row.get("announcement_id")
    lot_id = row.get("id")
    if announcement_id and lot_id:
        return f"https://zakup.gov.kz/announcement/{announcement_id}#lot-{lot_id}"
    return "https://zakup.gov.kz/"


def _description(row: dict[str, Any]) -> str:
    system = row.get("system")
    system_name = system.get("name") if isinstance(system, dict) else row.get("system_id")
    parts = [
        _field("Площадка", system_name),
        _field("Объявление", row.get("announcement_number")),
        _field("Статус", row.get("status_name")),
        _field("Способ закупки", row.get("purchase_method_name")),
        _field("Публикация", _format_datetime(row.get("announcement_publish_date"))),
        _field("Прием заявок до", _format_datetime(row.get("offer_end_date"))),
        _field("Заказчик", row.get("organization_name")),
        _field("Сумма", _format_amount(row.get("total_price"))),
        _field("Описание", row.get("description_ru")),
    ]
    return "\n".join(part for part in parts if part)


def _field(label: str, value: object) -> str:
    if value is None or value == "":
        return ""
    return f"{label}: {value}"


def _format_amount(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):,.2f} тг".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _format_datetime(value: object) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return _text(value)
    return parsed.astimezone().strftime("%d.%m.%Y %H:%M")


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _dedupe(matches: list[LotMatch]) -> list[LotMatch]:
    seen: set[str] = set()
    unique: list[LotMatch] = []
    for match in matches:
        if match.source_id in seen:
            continue
        seen.add(match.source_id)
        unique.append(match)
    return unique
