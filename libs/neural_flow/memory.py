from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

from .models import RememberRequest


class MemoryRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    url_hash TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    archive_url TEXT NOT NULL,
                    image_url TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_created_at ON memory_items(created_at)"
            )

    def is_duplicate(self, url_hash: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM memory_items WHERE url_hash = ? LIMIT 1", (url_hash,)
            ).fetchone()
        return row is not None

    def remember(self, req: RememberRequest) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO memory_items (
                        url_hash, source_id, title, url, summary,
                        keywords, raw_text, archive_url, image_url, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        req.url_hash,
                        req.source_id,
                        req.title,
                        req.url,
                        req.summary,
                        json.dumps(req.keywords, ensure_ascii=False),
                        req.raw_text,
                        req.archive_url,
                        req.image_url,
                        datetime.utcnow().isoformat(),
                    ),
                )

    def retrieve_context(self, keywords: List[str], limit: int = 3) -> Tuple[str, int]:
        if not keywords:
            return "", 0

        clauses = []
        params: List[str] = []
        for kw in keywords:
            clauses.append("keywords LIKE ?")
            params.append(f"%{kw}%")

        where_clause = " OR ".join(clauses)
        query = (
            f"SELECT title, summary, created_at FROM memory_items WHERE {where_clause} "
            "ORDER BY created_at DESC LIMIT ?"
        )

        with self._lock:
            rows = self._conn.execute(query, [*params, limit]).fetchall()

        if not rows:
            return "", 0

        lines = [f"- {row['title']} ({row['created_at']}): {row['summary']}" for row in rows]
        return "\n".join(lines), len(rows)

    def cleanup(self, retention_days: int) -> int:
        threshold = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "DELETE FROM memory_items WHERE created_at < ?", (threshold,)
                )
        return int(cursor.rowcount or 0)
