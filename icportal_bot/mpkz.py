from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .config import Config
from .models import LotMatch
from .portal import MIN_KEYWORD_LENGTH, SHORT_KEYWORD_ALLOWLIST


class MpKzClient:
    def __init__(self, config: Config) -> None:
        self.config = config.mpkz
        self.keywords = _active_keywords(config.search.keywords)
        self.headers = {
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 (compatible; MpKzParser/0.1)",
            "Referer": self.config.tenders_url,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }

    def search(self) -> list[LotMatch]:
        matches: list[LotMatch] = []
        for keyword in _limited_keywords(self.keywords, self.config.max_keyword_checks):
            matches.extend(self.search_keyword(keyword))
            time.sleep(self.config.delay_between_requests_seconds)
        return _dedupe(matches)

    def search_keyword(self, keyword: str) -> list[LotMatch]:
        matches: list[LotMatch] = []
        for page in range(1, self.config.max_pages + 1):
            text = self._get_text(_search_url(self.config.tenders_url, keyword, page))
            rows = _lot_rows_from_html(text)
            if not rows:
                break
            for row in rows:
                if not _is_open_actual(row):
                    continue
                match = _match_from_lot(keyword, row, self.config.url)
                if match is not None:
                    matches.append(match)
            if not _has_next_page(text, page):
                break
        return _dedupe(matches)

    def _get_text(self, url: str) -> str:
        request = Request(url, headers=self.headers, method="GET")
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")


def search_mpkz(config: Config) -> list[LotMatch]:
    if not config.mpkz.enabled:
        return []
    return MpKzClient(config).search()


def diagnose_mpkz_keyword(config: Config, keyword: str, limit: int = 10) -> list[LotMatch]:
    return MpKzClient(config).search_keyword(keyword)[:limit]


def _search_url(base_url: str, keyword: str, page: int) -> str:
    params = {
        "keyword": keyword,
        "sort": 1,
        "page": page,
    }
    return f"{base_url}?{urlencode(params)}"


def _lot_rows_from_html(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in re.finditer(r":lot='(\{.*?\})'", text, flags=re.DOTALL):
        raw = html.unescape(match.group(1))
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _is_open_actual(row: dict[str, Any]) -> bool:
    state = row.get("State")
    if not isinstance(state, dict) or state.get("constant") != "OPEN_FOR_BID":
        return False
    stop_date = _parse_datetime(row.get("dateStop"))
    return stop_date is not None and stop_date > datetime.now(timezone.utc)


def _match_from_lot(keyword: str, row: dict[str, Any], base_url: str) -> LotMatch | None:
    title = _text(row.get("name"))
    lot_id = _text(row.get("id"))
    if not title or not lot_id:
        return None
    haystack = _content_haystack(row)
    if not _keyword_matches(keyword, haystack):
        return None
    tender = row.get("Tender") if isinstance(row.get("Tender"), dict) else {}
    company = tender.get("InitiatorCompany") if isinstance(tender.get("InitiatorCompany"), dict) else {}
    state = row.get("State") if isinstance(row.get("State"), dict) else {}
    category = row.get("Category") if isinstance(row.get("Category"), dict) else {}
    lot_type = row.get("Type") if isinstance(row.get("Type"), dict) else {}
    code = f"Лот {lot_id}"
    tender_id = _text(tender.get("id"))
    if tender_id:
        code = f"{code} / Тендер {tender_id}"
    description = "\n".join(
        part
        for part in (
            _field("Портал", "MP.kz"),
            _field("Статус", state.get("name")),
            _field("Прием заявок до", _format_datetime(row.get("dateStop"))),
            _field("Заказчик", company.get("name")),
            _field("Категория", category.get("name")),
            _field("Тип", lot_type.get("name")),
            _field("Сумма", _format_amount(row.get("volume"), row.get("Currency"))),
        )
        if part
    )
    return LotMatch(
        keyword=keyword,
        title=title[:300],
        url=urljoin(base_url, str(row.get("tenderUrl") or "")),
        source_id=f"mpkz:{lot_id}",
        description=description,
        code=code,
        source="MP.kz",
    )


def _content_haystack(row: dict[str, Any]) -> str:
    tender = row.get("Tender") if isinstance(row.get("Tender"), dict) else {}
    company = tender.get("InitiatorCompany") if isinstance(tender.get("InitiatorCompany"), dict) else {}
    category = row.get("Category") if isinstance(row.get("Category"), dict) else {}
    lot_type = row.get("Type") if isinstance(row.get("Type"), dict) else {}
    return "\n".join(
        _text(part)
        for part in (
            row.get("name"),
            tender.get("name"),
            company.get("name"),
            category.get("name"),
            lot_type.get("name"),
        )
        if _text(part)
    )


def _keyword_matches(keyword: str, text: str) -> bool:
    clean = keyword.strip()
    lowered = text.casefold()
    lowered_keyword = clean.casefold()
    if _requires_token_match(clean):
        return re.search(rf"(?<![0-9A-Za-zА-Яа-яЁё]){re.escape(lowered_keyword)}(?![0-9A-Za-zА-Яа-яЁё])", lowered) is not None
    return lowered_keyword in lowered


def _requires_token_match(keyword: str) -> bool:
    return keyword.casefold() in {"1c", "1с", "ms", "итс", "project"}


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_datetime(value: object) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return _text(value)
    return parsed.astimezone().strftime("%d.%m.%Y %H:%M")


def _format_amount(value: object, currency: object) -> str:
    if value is None or value == "":
        return "закрытый торг"
    symbol = ""
    if isinstance(currency, dict):
        symbol = _text(currency.get("abbreviation") or currency.get("symbol"))
    try:
        amount = f"{float(value):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        amount = _text(value)
    return f"{amount} {symbol}".strip()


def _has_next_page(text: str, page: int) -> bool:
    return f"page={page + 1}" in text or f">{page + 1}<" in text


def _field(label: str, value: object) -> str:
    text = _text(value)
    return f"{label}: {text}" if text else ""


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _active_keywords(keywords: list[str]) -> list[str]:
    result: list[str] = []
    for keyword in keywords:
        clean = keyword.strip()
        if len(clean) < MIN_KEYWORD_LENGTH and clean not in SHORT_KEYWORD_ALLOWLIST:
            continue
        result.append(clean)
    return result


def _limited_keywords(keywords: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return keywords
    return keywords[:limit]


def _dedupe(matches: list[LotMatch]) -> list[LotMatch]:
    seen: set[str] = set()
    unique: list[LotMatch] = []
    for match in matches:
        if match.source_id in seen:
            continue
        seen.add(match.source_id)
        unique.append(match)
    return unique
