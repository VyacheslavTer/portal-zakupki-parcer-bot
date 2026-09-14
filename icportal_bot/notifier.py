from __future__ import annotations

import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import TelegramConfig
from .models import LotMatch


MAX_TELEGRAM_MESSAGE_LENGTH = 3500


def format_matches(matches: list[LotMatch], ascii_safe: bool = False) -> str:
    sources = sorted({match.source for match in matches})
    source_text = ", ".join(sources) if len(sources) <= 3 else "порталах закупок"
    lines = [f"Новые совпадения: {source_text}"]
    for match in matches:
        lines.append("")
        lines.append(f"Источник: {match.source}")
        lines.append(f"Ключевое слово: {match.keyword}")
        if match.code:
            lines.append(f"Код: {match.code}")
        lines.append(match.title)
        lines.append(match.url)
        if match.description:
            lines.append(match.description)
    text = "\n".join(lines)
    if ascii_safe:
        text = text.replace("₸", "тг")
    return text


def send_telegram(config: TelegramConfig, matches: list[LotMatch]) -> None:
    total = len(matches)
    for index, match in enumerate(matches, start=1):
        send_telegram_text(config, _format_match(match, index, total), disable_web_page_preview=True)


def send_telegram_text(config: TelegramConfig, text: str, disable_web_page_preview: bool = True) -> None:
    token = os.getenv(config.bot_token_env)
    chat_id = os.getenv(config.chat_id_env)
    if not token or not chat_id:
        raise RuntimeError("Telegram is enabled, but TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is empty.")

    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": disable_web_page_preview},
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


def _format_match(match: LotMatch, index: int, total: int) -> str:
    lines = [
        f"Новое совпадение {index}/{total}",
        f"Источник: {match.source}",
        f"Ключевое слово: {match.keyword}",
    ]
    if match.code:
        lines.append(f"Код: {match.code}")
    lines.extend([match.title, match.url])
    if match.description:
        lines.append(match.description)
    text = "\n".join(lines)
    if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return text
    reserved = "\n".join(lines[:-1]) if match.description else "\n".join(lines)
    max_description = max(0, MAX_TELEGRAM_MESSAGE_LENGTH - len(reserved) - 20)
    return reserved + "\n" + match.description[:max_description] + "\n..."


def _split_message(text: str) -> list[str]:
    if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return [text]

    chunks: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        separator = "\n\n" if current else ""
        if len(current) + len(separator) + len(block) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            current += separator + block
            continue
        if current:
            chunks.append(current)
        if len(block) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            current = block
            continue
        for start in range(0, len(block), MAX_TELEGRAM_MESSAGE_LENGTH):
            chunks.append(block[start : start + MAX_TELEGRAM_MESSAGE_LENGTH])
        current = ""
    if current:
        chunks.append(current)
    return chunks


def get_telegram_chat_ids(config: TelegramConfig) -> list[tuple[int, str]]:
    token = os.getenv(config.bot_token_env)
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty.")

    url = f"https://api.telegram.org/bot{token}/getUpdates?{urlencode({'limit': 20})}"
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    seen: set[int] = set()
    chats: list[tuple[int, str]] = []
    for update in payload.get("result", []):
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None or chat_id in seen:
            continue
        seen.add(chat_id)
        title = chat.get("title") or chat.get("username") or "private chat"
        chats.append((int(chat_id), str(title)))
    return chats
