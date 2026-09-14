from __future__ import annotations

import json
import re
import time
from typing import Any
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from .config import Config, SamrukConfig
from .models import LotMatch
from .portal import MIN_KEYWORD_LENGTH, SHORT_KEYWORD_ALLOWLIST


class SamrukClient:
    def __init__(self, config: Config) -> None:
        self.config = config.samruk
        self.keywords = _active_keywords(config.search.keywords)
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self._warmed_up = False
        self.headers = {
            "Accept": "text/html,application/json",
            "User-Agent": "Mozilla/5.0 (compatible; SamrukParser/0.1)",
            "Referer": self.config.url,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }

    def search(self) -> list[LotMatch]:
        if self.config.mode == "browser":
            return self.search_browser()
        if self.config.mode != "http":
            raise ValueError("samruk.mode must be http or browser")
        adverts = self.fetch_recent_adverts()
        matches: list[LotMatch] = []
        detail_count = 0
        for advert in adverts:
            keyword = _find_keyword(self.keywords, _advert_haystack(advert))
            detail = None
            if keyword is None and detail_count < self.config.max_details:
                detail = self.fetch_detail(_advert_id(advert))
                detail_count += 1
                keyword = _find_keyword(self.keywords, _detail_haystack(detail or {}))
                time.sleep(self.config.delay_between_requests_seconds)
            if keyword is None:
                continue
            if detail is None:
                detail = self.fetch_detail(_advert_id(advert))
                time.sleep(self.config.delay_between_requests_seconds)
            matches.append(_match_from_advert(keyword, advert, detail or {}, self.config))
        return _dedupe(matches)

    def search_browser(self) -> list[LotMatch]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Samruk browser mode requires Playwright. Install it with: "
                "py -m pip install playwright && py -m playwright install chromium"
            ) from error

        matches: list[LotMatch] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="ru-RU")
            try:
                for keyword in _limited_keywords(self.keywords, self.config.max_keyword_checks):
                    matches.extend(self._search_browser_keyword_on_page(page, keyword, self.config.max_details))
                    if len(matches) >= self.config.max_details:
                        break
                    time.sleep(self.config.delay_between_requests_seconds)
            finally:
                browser.close()
        return _dedupe(matches)

    def search_browser_keyword(self, keyword: str, limit: int = 10) -> list[LotMatch]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "Samruk browser mode requires Playwright. Install it with: "
                "py -m pip install playwright && py -m playwright install chromium"
            ) from error

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(locale="ru-RU")
            try:
                return self._search_browser_keyword_on_page(page, keyword, limit)
            finally:
                browser.close()

    def _search_browser_keyword_on_page(self, page: Any, keyword: str, limit: int) -> list[LotMatch]:
        page.goto(_search_url(self.config.url, keyword), wait_until="domcontentloaded", timeout=60000)
        page.locator('select[name="advertStatusName"]').select_option(index=0, timeout=10000)
        page.locator('input[name="keywordName"]').fill(keyword, timeout=10000)
        page.locator("button.button--primary.button--bold").last.click(timeout=10000)
        page.wait_for_timeout(4000)
        matches = _matches_from_browser_text(keyword, page.locator("body").inner_text(timeout=10000), self.config)
        return self._filter_browser_actual_matches(page, matches, limit)

    def _filter_browser_actual_matches(self, page: Any, matches: list[LotMatch], limit: int) -> list[LotMatch]:
        actual: list[LotMatch] = []
        for match in matches:
            page.goto(match.url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            text = page.locator("body").inner_text(timeout=10000)
            if not _is_actual_browser_detail(text, match.code):
                continue
            actual.append(match)
            if len(actual) >= limit:
                break
        return actual

    def fetch_recent_adverts(self) -> list[dict[str, Any]]:
        adverts: list[dict[str, Any]] = []
        for page in range(self.config.max_pages):
            payload = {"advertStatus": "ALL", "lotStatus": "PUBLISHED", "tenderSubjectTypes": []}
            page_adverts = self.fetch_advert_page(payload, page)
            adverts.extend(page_adverts)
            if len(page_adverts) == 0:
                break
            time.sleep(self.config.delay_between_requests_seconds)
        return _dedupe_adverts(adverts)

    def search_keyword_page(self, keyword: str, page: int = 0) -> list[dict[str, Any]]:
        payload = {"query": keyword, "advertStatus": "ALL", "lotStatus": "PUBLISHED", "tenderSubjectTypes": []}
        return self.fetch_advert_page(payload, page)

    def fetch_advert_page(self, payload: dict[str, Any], page: int) -> list[dict[str, Any]]:
        self.warm_up()
        params = {"size": 10, "page": page, "sort": "lastModifiedDate,desc"}
        url = f"{self.config.detail_api_url.rstrip('/')}/filter?{urlencode(params)}"
        response = self._post_json(url, payload)
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            for key in ("content", "data", "items", "result"):
                value = response.get(key)
                if isinstance(value, list):
                    return value
        return []

    def warm_up(self) -> None:
        if self._warmed_up:
            return
        try:
            self._get_text(self.config.url)
            self._get_json(f"{self.config.url.rstrip('/')}/eprocsearch/api/external/time?clientTime={int(time.time() * 1000)}")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"Samruk warm-up: {error}", flush=True)
        self._warmed_up = True

    def fetch_detail(self, advert_id: str) -> dict[str, Any] | None:
        if not advert_id:
            return None
        url = f"{self.config.detail_api_url.rstrip('/')}/{advert_id}"
        try:
            return self._get_json(url)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            print(f"Samruk detail {advert_id}: {error}", flush=True)
            return None

    def diagnose(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.fetch_recent_adverts()[:limit]

    def diagnose_keyword(self, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        if self.config.mode == "browser":
            return [_match_to_row(match) for match in self.search_browser_keyword(keyword, limit)]
        return self.search_keyword_page(keyword)[:limit]

    def _get_text(self, url: str) -> str:
        request = Request(_safe_url(url), headers=self.headers, method="GET")
        with self.opener.open(request, timeout=self.config.request_timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(_safe_url(url), headers={**self.headers, "Accept": "application/json"}, method="GET")
        with self.opener.open(request, timeout=self.config.request_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    def _post_json(self, url: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            _safe_url(url),
            data=body,
            headers={
                **self.headers,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": self.config.url.rstrip("/"),
                "X-Request-No-Transparent": "true",
            },
            method="POST",
        )
        with self.opener.open(request, timeout=self.config.request_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))


def search_samruk(config: Config) -> list[LotMatch]:
    if not config.samruk.enabled:
        return []
    return SamrukClient(config).search()


def diagnose_samruk(config: Config, limit: int = 10) -> list[dict[str, Any]]:
    return SamrukClient(config).diagnose(limit)


def diagnose_samruk_keyword(config: Config, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    return SamrukClient(config).diagnose_keyword(keyword, limit)


def diagnose_samruk_detail(config: Config, advert_id: str) -> dict[str, Any] | None:
    return SamrukClient(config).fetch_detail(advert_id)


def _match_to_row(match: LotMatch) -> dict[str, Any]:
    return {
        "id": match.code,
        "number": match.code,
        "name": match.title,
        "text": match.description,
    }


def _safe_url(url: str) -> str:
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%")
    query = quote(parts.query, safe="=&?/%:+")
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def _search_url(base_url: str, keyword: str) -> str:
    params = urlencode({"tabs": "advert", "q": keyword, "adst": "ALL", "lst": "PUBLISHED", "page": 1})
    return f"{base_url.rstrip('/')}/#/ext?{params}"


def _advert_search_url(base_url: str, advert_id: str) -> str:
    params = urlencode({"tabs": "advert", "q": advert_id, "adst": "ALL", "lst": "PUBLISHED", "page": 1})
    return f"{base_url.rstrip('/')}/#/ext(popup:item/{advert_id}/advert)?{params}"


def _matches_from_browser_text(keyword: str, text: str, config: SamrukConfig) -> list[LotMatch]:
    matches: list[LotMatch] = []
    pattern = re.compile(
        r"№\s*(?P<number>\d+)\s+(?P<title>.*?)(?=\n(?:Из одного источника|Запрос ценовых предложений|Открытый тендер|Двухэтапный тендер|Тендер путем)|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(text):
        number = match.group("number").strip()
        title = " ".join(match.group("title").split())
        if not number or not title:
            continue
        block_start = match.start()
        block_end = text.find("\n№ ", match.end())
        block = text[block_start:] if block_end == -1 else text[block_start:block_end]
        if not _is_open_browser_advert(block):
            continue
        matches.append(
            LotMatch(
                keyword=keyword,
                title=title[:300],
                url=_advert_search_url(config.url, number),
                source_id=f"samruk:{number}",
                description=_browser_description(number, block),
                code=number,
                source="Samruk",
            )
        )
    return matches


def _browser_description(number: str, block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    method = next((line for line in lines if line not in {f"№ {number}"} and not line.startswith("Стоимость:")), "")
    amount = next((line.removeprefix("Стоимость:").strip() for line in lines if line.startswith("Стоимость:")), "")
    parts = [_field("Портал", "Samruk-Kazyna"), _field("Номер", number), _field("Способ закупки", method), _field("Сумма", amount)]
    return "\n".join(part for part in parts if part)


def _is_open_browser_advert(block: str) -> bool:
    lowered = block.lower()
    return "осталось:" in lowered and not _has_inactive_status(lowered)


def _is_actual_browser_detail(text: str, advert_id: str) -> bool:
    status = _browser_detail_status(text, advert_id)
    if not status:
        return False
    lowered = status.lower()
    return "опублик" in lowered and not _has_inactive_status(lowered)


def _browser_detail_status(text: str, advert_id: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    marker = f"№ {advert_id}"
    indexes = [index for index, line in enumerate(lines) if line == marker]
    if not indexes:
        return ""
    index = indexes[-1]
    if index + 2 >= len(lines):
        return ""
    return lines[index + 2]


def _has_inactive_status(text: str) -> bool:
    inactive_statuses = (
        "отменен",
        "отменён",
        "отменена",
        "отменено",
        "завершен",
        "завершён",
        "завершена",
        "завершено",
        "итоги",
        "договор заключен",
        "договор заключён",
    )
    return any(status in text for status in inactive_statuses)


def _active_keywords(keywords: list[str]) -> list[str]:
    result: list[str] = []
    for keyword in keywords:
        clean = keyword.strip()
        if len(clean) < MIN_KEYWORD_LENGTH and clean not in SHORT_KEYWORD_ALLOWLIST:
            print(f"Samruk: пропускаю слишком короткое ключевое слово: {keyword}", flush=True)
            continue
        result.append(clean)
    return result


def _limited_keywords(keywords: list[str], limit: int) -> list[str]:
    if limit <= 0:
        return keywords
    return keywords[:limit]


def _advert_id(advert: dict[str, Any]) -> str:
    return _first_text(advert.get("id"), advert.get("number"), advert.get("advertId"), advert.get("tender_id"))


def _advert_haystack(advert: dict[str, Any]) -> str:
    return "\n".join(_clean_text(value) for value in advert.values())


def _detail_haystack(detail: dict[str, Any]) -> str:
    values: list[str] = []
    _collect_text_values(detail, values)
    return "\n".join(values)


def _collect_text_values(value: Any, values: list[str]) -> None:
    if isinstance(value, dict):
        for nested in value.values():
            _collect_text_values(nested, values)
    elif isinstance(value, list):
        for nested in value:
            _collect_text_values(nested, values)
    elif isinstance(value, (str, int, float)):
        text = _clean_text(value)
        if text:
            values.append(text)


def _find_keyword(keywords: list[str], text: str) -> str | None:
    lowered = text.lower()
    return next((keyword for keyword in keywords if keyword.lower() in lowered), None)


def _match_from_advert(keyword: str, advert: dict[str, Any], detail: dict[str, Any], config: SamrukConfig) -> LotMatch:
    advert_id = _advert_id(advert)
    title = _first_text(
        detail.get("nameRu"),
        detail.get("name"),
        detail.get("titleRu"),
        detail.get("title"),
        advert.get("title"),
        advert.get("text"),
        advert_id,
    )
    return LotMatch(
        keyword=keyword,
        title=title[:300],
        url=_advert_search_url(config.url, advert_id),
        source_id=f"samruk:{advert_id}",
        description=_description(advert, detail),
        code=advert_id,
        source="Samruk",
    )


def _description(advert: dict[str, Any], detail: dict[str, Any]) -> str:
    parts = [
        _field("Портал", "Samruk-Kazyna"),
        _field("Номер", _advert_id(advert)),
        _field("Статус", _first_text(detail.get("status"), detail.get("statusRu"), advert.get("status"))),
        _field("Способ закупки", _first_text(detail.get("tenderType"), detail.get("type"), advert.get("type"))),
        _field("Заказчик", _first_text(detail.get("customerNameRu"), detail.get("customerName"), advert.get("customer"))),
        _field("Сумма", _first_text(detail.get("sum"), detail.get("amount"), advert.get("amount"))),
    ]
    return "\n".join(part for part in parts if part)


def _field(label: str, value: Any) -> str:
    text = _clean_text(value)
    return f"{label}: {text}" if text else ""


def _first_text(*values: Any) -> str:
    return next((text for text in (_clean_text(value) for value in values) if text), "")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return _first_text(value.get("ru"), value.get("kk"), value.get("en"), value.get("nameRu"), value.get("name"))
    return " ".join(str(value).split())


def _dedupe_adverts(adverts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for advert in adverts:
        advert_id = _advert_id(advert)
        if not advert_id or advert_id in seen:
            continue
        seen.add(advert_id)
        unique.append(advert)
    return unique


def _dedupe(matches: list[LotMatch]) -> list[LotMatch]:
    seen: set[str] = set()
    unique: list[LotMatch] = []
    for match in matches:
        if match.source_id in seen:
            continue
        seen.add(match.source_id)
        unique.append(match)
    return unique
