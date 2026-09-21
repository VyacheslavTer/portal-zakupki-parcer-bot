from __future__ import annotations

import html
import re
import time
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from .config import Config
from .models import LotMatch
from .portal import MIN_KEYWORD_LENGTH, SHORT_KEYWORD_ALLOWLIST


class MitworkClient:
    def __init__(self, config: Config) -> None:
        self.config = config.mitwork
        self.keywords = _active_keywords(config.search.keywords)
        self.headers = {
            "Accept": "text/html",
            "User-Agent": "Mozilla/5.0 (compatible; MitworkParser/0.1)",
            "Referer": self.config.buys_url,
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }

    def search(self) -> list[LotMatch]:
        keywords = _limited_keywords(self.keywords, self.config.max_keyword_checks)
        matches: list[LotMatch] = []
        for buy_id, detail in self.iter_active_details():
            keyword = _find_keyword(keywords, _content_haystack(detail))
            if keyword is None:
                continue
            match = _match_from_detail(keyword, buy_id, detail, self.config.url)
            if match is not None:
                matches.append(match)
        return _dedupe(matches)

    def search_keyword(self, keyword: str) -> list[LotMatch]:
        matches: list[LotMatch] = []
        seen_buy_ids: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            text = self._get_text(_search_url(self.config.buys_url, keyword, page, self.config.page_size))
            buy_ids = _buy_ids_from_html(text)
            if not buy_ids:
                break
            for buy_id in buy_ids:
                if buy_id in seen_buy_ids:
                    continue
                seen_buy_ids.add(buy_id)
                detail = self.fetch_buy_detail(buy_id)
                if detail is None or not _is_actual_detail(detail):
                    continue
                match = _match_from_detail(keyword, buy_id, detail, self.config.url)
                if match is not None:
                    matches.append(match)
            if len(buy_ids) < self.config.page_size:
                break
        if matches:
            return matches
        for buy_id, detail in self.iter_active_details():
            if not _keyword_matches(keyword, _content_haystack(detail)):
                continue
            match = _match_from_detail(keyword, buy_id, detail, self.config.url)
            if match is not None:
                matches.append(match)
        return _dedupe(matches)

    def iter_active_details(self) -> list[tuple[str, str]]:
        details: list[tuple[str, str]] = []
        seen_buy_ids: set[str] = set()
        for page in range(1, self.config.max_pages + 1):
            text = self._get_text(_active_url(self.config.buys_url, page, self.config.page_size))
            buy_ids = _buy_ids_from_html(text)
            if not buy_ids:
                break
            for buy_id in buy_ids:
                if buy_id in seen_buy_ids:
                    continue
                seen_buy_ids.add(buy_id)
                detail = self.fetch_buy_detail(buy_id)
                if detail is not None and _is_actual_detail(detail):
                    details.append((buy_id, detail))
            if len(buy_ids) < self.config.page_size:
                break
            time.sleep(self.config.delay_between_requests_seconds)
        return details

    def fetch_buy_detail(self, buy_id: str) -> str | None:
        try:
            return self._get_text(urljoin(self.config.url, f"/ru/publics/buy/{buy_id}"))
        except Exception as error:
            print(f"Mitwork detail {buy_id}: {error}", flush=True)
            return None

    def _get_text(self, url: str) -> str:
        request = Request(url, headers=self.headers, method="GET")
        with urlopen(request, timeout=self.config.request_timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")


def search_mitwork(config: Config) -> list[LotMatch]:
    if not config.mitwork.enabled:
        return []
    return MitworkClient(config).search()


def diagnose_mitwork_keyword(config: Config, keyword: str, limit: int = 10) -> list[LotMatch]:
    return MitworkClient(config).search_keyword(keyword)[:limit]


def _search_url(base_url: str, keyword: str, page: int, page_size: int) -> str:
    params = {
        "filter[search]": keyword,
        "page": page,
        "per-page": page_size,
    }
    return f"{base_url}?{urlencode(params)}"


def _active_url(base_url: str, page: int, page_size: int) -> str:
    params = {
        "filter[top_filter_status]": "active",
        "page": page,
        "per-page": page_size,
    }
    return f"{base_url}?{urlencode(params)}"


def _buy_ids_from_html(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"/ru/publics/buy/(\d+)", text)))


def _is_actual_detail(text: str) -> bool:
    lines = _text_lines(text)
    if any(line.startswith("Объявление #") or "/ Обсуждение" in line for line in lines):
        return False
    title = _title_from_lines(lines)
    if "обсуждение" in title.casefold() or _announcement_number(lines, "").startswith("#"):
        return False
    status = _value_after(lines, "Статус")
    if status and "опублик" not in status.casefold():
        return False
    end_date = _parse_datetime(_value_after(lines, "Дата окончания приема заявок"))
    return end_date is None or end_date >= datetime.now()


def _match_from_detail(keyword: str, buy_id: str, text: str, base_url: str) -> LotMatch | None:
    lines = _text_lines(text)
    title = _title_from_lines(lines)
    if not title:
        return None
    haystack = _content_haystack(text).casefold()
    if not _keyword_matches(keyword, haystack):
        return None
    lot_rows = _lot_rows_from_html(text)
    lot_numbers = [number for number, _, _ in lot_rows]
    docs = _document_names(text)
    lot_urls = [urljoin(base_url, f"/ru/publics/lot/{lot_id}") for lot_id in _lot_ids_from_html(text)]
    description = "\n".join(
        part
        for part in (
            _field("Портал", "MITWORK"),
            _field("Объявление", _announcement_number(lines, buy_id)),
            _field("Статус", _value_after(lines, "Статус")),
            _field("Начало приема", _value_after(lines, "Дата начала приема заявок")),
            _field("Прием заявок до", _value_after(lines, "Дата окончания приема заявок")),
            _field("Организатор", _value_after(lines, "Организатор")),
            _field("Сумма", _total_amount(text) or _value_after(lines, "Общая сумма, без НДС")),
            _field("Лоты", "; ".join(lot_numbers[:5])),
            _lot_descriptions(lot_rows[:5]),
            _field("Документы", "; ".join(docs[:8])),
            _field("Страницы лотов", "\n".join(lot_urls[:5])),
        )
        if part
    )
    return LotMatch(
        keyword=keyword,
        title=title[:300],
        url=urljoin(base_url, f"/ru/publics/buy/{buy_id}"),
        source_id=f"mitwork:{buy_id}",
        description=description,
        code=_announcement_number(lines, buy_id),
        source="Mitwork",
    )


def _find_keyword(keywords: list[str], text: str) -> str | None:
    return next((keyword for keyword in keywords if _keyword_matches(keyword, text)), None)


def _keyword_matches(keyword: str, text: str) -> bool:
    clean = keyword.strip()
    lowered = text.casefold()
    lowered_keyword = clean.casefold()
    if _requires_token_match(clean):
        return re.search(rf"(?<![0-9A-Za-zА-Яа-яЁё]){re.escape(lowered_keyword)}(?![0-9A-Za-zА-Яа-яЁё])", lowered) is not None
    return lowered_keyword in lowered


def _requires_token_match(keyword: str) -> bool:
    return keyword.casefold() in {"1c", "1с", "ms", "итс", "project"}


def _content_haystack(text: str) -> str:
    lines = _text_lines(text)
    parts = [_title_from_lines(lines)]
    for number, title, description in _lot_rows_from_html(text):
        parts.extend((number, title, description))
    return "\n".join(part for part in parts if part)


def _lot_rows_from_html(text: str) -> list[tuple[str, str, str]]:
    lots: list[tuple[str, str, str]] = []
    for row in re.findall(r"<tr[^>]+data-key=\"\d+\"[\s\S]*?</tr>", text, flags=re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, flags=re.IGNORECASE)
        if len(cells) < 3:
            continue
        cleaned_cells = [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", cell)).split()) for cell in cells]
        number_match = re.search(r"\d+-[А-ЯA-Z]+\d+", cleaned_cells[0])
        if number_match is None:
            continue
        lots.append((number_match.group(0), cleaned_cells[1], cleaned_cells[2]))
    return lots


def _lot_descriptions(lots: list[tuple[str, str, str]]) -> str:
    described = [(number, description) for number, _, description in lots if description]
    if not described:
        return ""
    if len(described) == 1:
        return _field("Описание лота", described[0][1])
    lines = ["Описания лотов:"]
    lines.extend(f"- {number}: {description}" for number, description in described)
    return "\n".join(lines)


def _title_from_lines(lines: list[str]) -> str:
    for line in lines:
        match = re.search(r"Объявление\s+\S+\s*:\s*(.+)", line)
        if match:
            return match.group(1).strip()
    return ""


def _announcement_number(lines: list[str], buy_id: str) -> str:
    for line in lines:
        match = re.search(r"Объявление\s+(\S+)", line)
        if match:
            return match.group(1)
    return buy_id


def _lot_ids_from_html(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"/ru/publics/lot/(\d+)", text)))


def _document_names(text: str) -> list[str]:
    clean = html.unescape(re.sub(r"<[^>]+>", "\n", text))
    return list(dict.fromkeys(re.findall(r"[\w.-]+\.(?:pdf|docx?|xlsx?|zip|rar|key)", clean, flags=re.IGNORECASE)))


def _total_amount(text: str) -> str:
    amounts = re.findall(r">\s*([\d\s]+,\d{2}\s*(?:KZT|₸))\s*<", text, flags=re.IGNORECASE)
    return " ".join(amounts[-1].split()) if amounts else ""


def _value_after(lines: list[str], label: str) -> str:
    for index, line in enumerate(lines):
        if line.casefold() == label.casefold() and index + 1 < len(lines):
            return lines[index + 1]
    return ""


def _text_lines(text: str) -> list[str]:
    cleaned = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"<style[\s\S]*?</style>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</(?:div|p|tr|td|th|li|h1|h2|h3|h4|span)>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = html.unescape(re.sub(r"<[^>]+>", " ", cleaned))
    return [" ".join(line.split()) for line in cleaned.splitlines() if line.strip()]


def _field(label: str, value: object) -> str:
    text = " ".join(str(value or "").split())
    return f"{label}: {text}" if text else ""


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


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    value = value.replace("г.", "").strip()
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _dedupe(matches: list[LotMatch]) -> list[LotMatch]:
    seen: set[str] = set()
    unique: list[LotMatch] = []
    for match in matches:
        if match.source_id in seen:
            continue
        seen.add(match.source_id)
        unique.append(match)
    return unique
