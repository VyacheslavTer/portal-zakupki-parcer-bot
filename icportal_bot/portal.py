from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import Config
from .models import LotMatch


DEFAULT_PARAMS = {
    "buyer": "",
    "type": "",
    "region": "",
    "format": "",
}

MIN_KEYWORD_LENGTH = 3
SHORT_KEYWORD_ALLOWLIST = {"1C", "1С", "MS"}


class ICPortalClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; ICPortalParser/0.1)",
            "Referer": config.portal.url,
        }

    def search_all_keywords(self) -> list[LotMatch]:
        matches: list[LotMatch] = []
        active_keywords = self._active_keywords()
        for keyword in active_keywords:
            matches.extend(self.search_keyword(keyword))
        if self.config.search.status == "open":
            matches.extend(self.scan_open_purchase_details(active_keywords))
        return _dedupe(matches)

    def search_keyword(self, keyword: str) -> list[LotMatch]:
        results: list[LotMatch] = []
        max_pages = self.config.search.max_pages_per_keyword
        max_results = self.config.search.max_results_per_keyword

        for page in range(1, max_pages + 1):
            payload = self._request_page(keyword, page, self.config.search.status)
            for item in payload.get("data", []):
                match = self._match_from_item(keyword, item)
                if match is None:
                    continue
                results.append(match)
                if len(results) >= max_results:
                    return results

            meta = payload.get("meta") or {}
            last_page = int(meta.get("last_page") or page)
            if page >= last_page:
                break

        return results

    def scan_open_purchase_details(self, keywords: list[str]) -> list[LotMatch]:
        results: list[LotMatch] = []
        for page in range(1, self.config.search.scan_open_pages + 1):
            payload = self._request_page("", page, "open")
            for item in payload.get("data", []):
                purchase_id = str(item.get("id") or "").strip()
                if not purchase_id:
                    continue
                detail = self._request_purchase_detail(purchase_id)
                match = self._match_from_detail(detail, keywords)
                if match is not None:
                    results.append(match)

            meta = payload.get("meta") or {}
            last_page = int(meta.get("last_page") or page)
            if page >= last_page:
                break
        return results

    def _active_keywords(self) -> list[str]:
        keywords: list[str] = []
        for keyword in self.config.search.keywords:
            normalized_keyword = keyword.strip()
            if len(normalized_keyword) < MIN_KEYWORD_LENGTH and normalized_keyword not in SHORT_KEYWORD_ALLOWLIST:
                print(f"Пропускаю слишком короткое ключевое слово: {keyword}")
                continue
            keywords.append(keyword)
        return keywords

    def _request_page(self, keyword: str, page: int, status: str | None) -> dict:
        params = {
            **DEFAULT_PARAMS,
            "page": page,
            "search": keyword,
            "status": status or "",
        }
        return self._get_json(f"{self.config.portal.api_url}?{urlencode(params)}")

    def _request_purchase_detail(self, purchase_id: str) -> dict:
        return self._get_json(f"{self.config.portal.api_url}/show/{purchase_id}")

    def _get_json(self, url: str) -> dict:
        request = Request(url, headers=self.headers, method="GET")
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _match_from_item(self, keyword: str, item: dict) -> LotMatch | None:
        purchase_id = str(item.get("id") or "").strip()
        title = " ".join(str(item.get("name") or "").split())
        if not purchase_id or not title:
            return None

        return LotMatch(
            keyword=keyword,
            title=title,
            url=f"{self.config.portal.url.rstrip('/')}/purchases/{purchase_id}",
            source_id=purchase_id,
            description=_purchase_description(item),
            code=str(item.get("code") or ""),
            source="ICPortal",
        )

    def _match_from_detail(self, detail: dict, keywords: list[str]) -> LotMatch | None:
        haystack_parts = [str(detail.get("name") or "")]
        lot_lines: list[str] = []
        for lot in detail.get("lots") or []:
            lot_text = " ".join(
                str(lot.get(field) or "")
                for field in ("name", "description", "code")
            ).strip()
            if lot_text:
                haystack_parts.append(lot_text)
                lot_lines.append(lot_text)

        haystack = "\n".join(haystack_parts).lower()
        matched_keyword = next((keyword for keyword in keywords if keyword.lower() in haystack), None)
        if matched_keyword is None:
            return None

        purchase_id = str(detail.get("id") or "").strip()
        title = " ".join(str(detail.get("name") or "").split())
        description = _purchase_description(detail)
        matching_lots = [line for line in lot_lines if matched_keyword.lower() in line.lower()]
        if matching_lots:
            description = f"Совпавшие лоты:\n" + "\n".join(f"- {line}" for line in matching_lots[:5]) + "\n" + description

        return LotMatch(
            keyword=matched_keyword,
            title=title,
            url=f"{self.config.portal.url.rstrip('/')}/purchases/{purchase_id}",
            source_id=purchase_id,
            description=description,
            code=str(detail.get("code") or ""),
            source="ICPortal",
        )


def search_portal(config: Config) -> list[LotMatch]:
    return ICPortalClient(config).search_all_keywords()


def _purchase_description(item: dict) -> str:
    status = item.get("status")
    if isinstance(status, dict):
        status = status.get("text") or status.get("index")
    description_parts = [
        _field("Статус", status),
        _field("Формат", item.get("format")),
        _field("Регион", ", ".join(item.get("regions") or [])),
        _field("Вид закупки", item.get("type")),
        _field("Период проведения", _date_range(item.get("startDate"), item.get("endDate"))),
        _field("Общая плановая сумма", item.get("lotsSum")),
        _field("Всего лотов", item.get("lotsCount") or len(item.get("lots") or [])),
        _field("Организатор закупки", item.get("organizer") or item.get("companyName")),
    ]
    return "\n".join(part for part in description_parts if part)


def _field(label: str, value: object) -> str:
    if value is None or value == "":
        return ""
    return f"{label}: {value}"


def _date_range(start: object, end: object) -> str:
    if start and end:
        return f"{start} - {end}"
    if start:
        return str(start)
    if end:
        return str(end)
    return ""


def _dedupe(matches: list[LotMatch]) -> list[LotMatch]:
    seen: set[str] = set()
    unique: list[LotMatch] = []
    for match in matches:
        key = match.source_id
        if key in seen:
            continue
        seen.add(key)
        unique.append(match)
    return unique
