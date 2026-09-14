from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import LotMatch


class MatchStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_matches (
                source_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                keyword TEXT NOT NULL,
                code TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'ICPortal',
                sent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        try:
            self.connection.execute("ALTER TABLE sent_matches ADD COLUMN source TEXT NOT NULL DEFAULT 'ICPortal'")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise
        self.connection.commit()

    def filter_new(self, matches: list[LotMatch]) -> list[LotMatch]:
        new_matches: list[LotMatch] = []
        for match in matches:
            exists = self.connection.execute(
                "SELECT 1 FROM sent_matches WHERE source_id = ?",
                (match.source_id,),
            ).fetchone()
            if exists is None:
                new_matches.append(match)
        return new_matches

    def mark_sent(self, matches: list[LotMatch]) -> None:
        self.connection.executemany(
            """
            INSERT OR IGNORE INTO sent_matches (source_id, title, url, keyword, code, source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(match.source_id, match.title, match.url, match.keyword, match.code, match.source) for match in matches],
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
