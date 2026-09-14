from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LotMatch:
    keyword: str
    title: str
    url: str
    source_id: str
    description: str = ""
    code: str = ""
    source: str = "ICPortal"
