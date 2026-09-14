from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PortalConfig:
    url: str
    api_url: str


@dataclass(frozen=True)
class SamrukConfig:
    enabled: bool
    mode: str
    url: str
    search_url: str
    detail_api_url: str
    max_pages: int
    max_details: int
    max_keyword_checks: int
    request_timeout_seconds: float
    delay_between_requests_seconds: float


@dataclass(frozen=True)
class ErgBridgeConfig:
    enabled: bool
    config_path: str
    max_keyword_checks: int


@dataclass(frozen=True)
class SearchConfig:
    keywords: list[str]
    max_results_per_keyword: int
    max_pages_per_keyword: int
    scan_open_pages: int
    status: str | None


@dataclass(frozen=True)
class TelegramConfig:
    enabled: bool
    bot_token_env: str
    chat_id_env: str


@dataclass(frozen=True)
class Config:
    portal: PortalConfig
    samruk: SamrukConfig
    erg: ErgBridgeConfig
    search: SearchConfig
    telegram: TelegramConfig


def load_config(path: Path | None = None) -> Config:
    _load_dotenv(ROOT / ".env")
    config_path = path or ROOT / "config.json"
    if not config_path.exists():
        raise FileNotFoundError("config.json not found. Copy config.example.json to config.json first.")

    raw = json.loads(config_path.read_text(encoding="utf-8-sig"))
    portal = raw["portal"]
    samruk = raw.get("samruk", {})
    erg = raw.get("erg", {})
    search = raw["search"]
    notifications = raw["notifications"]

    return Config(
        portal=PortalConfig(
            url=portal["url"],
            api_url=portal["api_url"],
        ),
        samruk=SamrukConfig(
            enabled=bool(samruk.get("enabled", False)),
            mode=samruk.get("mode", "http"),
            url=samruk.get("url", "https://zakup.sk.kz/"),
            search_url=samruk.get("search_url", "https://zakup.sk.kz/ru/search?status=опубликовано&sort=date_desc"),
            detail_api_url=samruk.get("detail_api_url", "https://zakup.sk.kz/eprocsearch/api/external/4dv3rts"),
            max_pages=int(samruk.get("max_pages", 3)),
            max_details=int(samruk.get("max_details", 50)),
            max_keyword_checks=int(samruk.get("max_keyword_checks", 25)),
            request_timeout_seconds=float(samruk.get("request_timeout_seconds", 30)),
            delay_between_requests_seconds=float(samruk.get("delay_between_requests_seconds", 0.5)),
        ),
        erg=ErgBridgeConfig(
            enabled=bool(erg.get("enabled", False)),
            config_path=erg.get("config_path", "erg_parser/config.json"),
            max_keyword_checks=int(erg.get("max_keyword_checks", 25)),
        ),
        search=SearchConfig(
            keywords=[str(keyword) for keyword in search["keywords"]],
            max_results_per_keyword=int(search.get("max_results_per_keyword", 20)),
            max_pages_per_keyword=int(search.get("max_pages_per_keyword", 5)),
            scan_open_pages=int(search.get("scan_open_pages", 5)),
            status=search.get("status"),
        ),
        telegram=TelegramConfig(
            enabled=bool(notifications.get("telegram_enabled", False)),
            bot_token_env=notifications.get("telegram_bot_token_env", "TELEGRAM_BOT_TOKEN"),
            chat_id_env=notifications.get("telegram_chat_id_env", "TELEGRAM_CHAT_ID"),
        ),
    )


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
