"""Persistent per-model rolling token reservations using standard-library SQLite."""

import sqlite3
import time
from contextlib import closing
from pathlib import Path

from agent_patterns.providers.base import ProviderQuotaError


class TokenQuota:
    def __init__(self, path: str, endpoint: str, model: str, minute: int, day: int) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path, self.endpoint, self.model = path, endpoint, model
        self.minute, self.day = minute, day
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations "
                "(id INTEGER PRIMARY KEY, endpoint TEXT, model TEXT, time REAL, tokens INTEGER)"
            )

    def reserve(self, tokens: int) -> tuple[int | None, float]:
        if not 0 < tokens <= self.minute:
            raise ProviderQuotaError("Request token reservation exceeds the per-minute quota")
        now = time.time()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT time, tokens FROM reservations WHERE endpoint=? AND model=? AND time>? "
                "ORDER BY time",
                (self.endpoint, self.model, now - 86400),
            ).fetchall()
            if sum(row[1] for row in rows) + tokens > self.day:
                raise ProviderQuotaError("Daily model token quota reached; rerun after reset")
            recent = [row for row in rows if row[0] > now - 60]
            if sum(row[1] for row in recent) + tokens > self.minute:
                return None, max(0.01, recent[0][0] + 60 - now)
            cursor = db.execute(
                "INSERT INTO reservations(endpoint,model,time,tokens) VALUES(?,?,?,?)",
                (self.endpoint, self.model, now, tokens),
            )
            return int(cursor.lastrowid or 0), 0

    def settle(self, reservation: int, tokens: int) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE reservations SET tokens=? WHERE id=?", (tokens, reservation))
