from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_URL = "https://torgi.erg.kz/api/SupplierAuctionService/GetAuctions"
PAGE_URL = "https://torgi.erg.kz/supplier/#/competitions"


@dataclass(frozen=True)
class Probe:
    name: str
    params: dict[str, Any]


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Probe public ERG competition API behavior.")
    parser.add_argument("keywords", nargs="*", help="Extra EstmcPosName values to test.")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=3, help="How many sample rows to print.")
    args = parser.parse_args()

    probes = [
        Probe("empty", {}),
        Probe("status_4", {"AuStatus": 4}),
        Probe("status_64", {"AuStatus": 64}),
        Probe("keyword_adobe", {"EstmcPosName": "Adobe"}),
        Probe("keyword_ms", {"EstmcPosName": "MS"}),
        Probe("keyword_shield_ru", {"EstmcPosName": "щит"}),
    ]
    probes.extend(Probe(f"keyword_{keyword}", {"EstmcPosName": keyword}) for keyword in args.keywords)

    for probe in probes:
        run_probe(probe, timeout=args.timeout, limit=args.limit)


def run_probe(probe: Probe, timeout: float, limit: int) -> None:
    started = time.monotonic()
    url = f"{API_URL}?{urlencode(probe.params)}" if probe.params else API_URL
    print(f"\n=== {probe.name} ===")
    print(url)
    try:
        payload = get_json(url, timeout=timeout)
    except HTTPError as error:
        elapsed = time.monotonic() - started
        body = error.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR http={error.code} elapsed={elapsed:.2f}s body={body!r}")
        return
    except (URLError, TimeoutError) as error:
        elapsed = time.monotonic() - started
        print(f"ERROR elapsed={elapsed:.2f}s {error}")
        return

    elapsed = time.monotonic() - started
    rows = payload.get("GetAuctionsResult")
    if not isinstance(rows, list):
        print(f"HTTP 200 elapsed={elapsed:.2f}s unexpected keys={list(payload)[:20]}")
        return

    print(f"HTTP 200 elapsed={elapsed:.2f}s rows={len(rows)}")
    if rows:
        print(f"keys={', '.join(rows[0].keys())}")
    for row in rows[:limit]:
        print(
            json.dumps(
                {
                    "ID": row.get("ID"),
                    "NUM": row.get("NUM"),
                    "STATUS": row.get("STATUS"),
                    "STATUSES": row.get("STATUSES"),
                    "PURCHASE_MANNER": row.get("PURCHASE_MANNER"),
                    "PUBLISH_DATE_1": row.get("PUBLISH_DATE_1"),
                    "CO_TAKING_END_DATE_1": row.get("CO_TAKING_END_DATE_1"),
                    "MAIN_CATEGORY_TITLE": row.get("MAIN_CATEGORY_TITLE"),
                    "MAIN_CATEGORY_TRU_TITLE": row.get("MAIN_CATEGORY_TRU_TITLE"),
                    "DETAILED_NAME_PURCHASE_SUBJECT": row.get("DETAILED_NAME_PURCHASE_SUBJECT"),
                    "Customers": row.get("Customers"),
                },
                ensure_ascii=False,
            )
        )


def get_json(url: str, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; ErgParserProbe/0.1)",
            "Referer": PAGE_URL,
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8-sig"))


if __name__ == "__main__":
    main()
