from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Sequence


class ArchiveRepository:
    def __init__(self, db_path: str, archive_dir: str) -> None:
        self.db_path = Path(db_path)
        self.archive_dir = Path(archive_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    ai_summary TEXT NOT NULL,
                    archive_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    channels TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_dashboard_created_at ON dashboard_entries(created_at)"
            )

    def write_markdown(self, content_pack: Dict[str, Any]) -> str:
        now = datetime.now()
        day_label = now.strftime("%Y-%m-%d")
        record_type = _normalize_record_type(content_pack.get("record_type"))
        bucket = "topic_pool" if record_type == "topic" else "draft_pool"
        day_folder = self.archive_dir / day_label / bucket
        day_folder.mkdir(parents=True, exist_ok=True)

        safe_hash = str(content_pack.get("url_hash") or now.strftime("%H%M%S"))
        trace_id = str(content_pack.get("trace_id") or safe_hash[:8] or now.strftime("%H%M%S"))
        platform = _safe_file_part(str(content_pack.get("platform") or "general"), max_len=24)
        safe_title = _safe_file_part(str(content_pack.get("title") or "untitled"), max_len=42)
        if record_type == "topic":
            filename = f"{day_label}-{trace_id}-{safe_title}.md"
        else:
            filename = f"{day_label}-{trace_id}-{platform}-{safe_title}.md"
        target = day_folder / filename

        body = self._build_markdown_body(content_pack, now=now, trace_id=trace_id, record_type=record_type)

        target.write_text("\n".join(body), encoding="utf-8")
        return target.resolve().as_uri()

    def _build_markdown_body(
        self,
        content_pack: Dict[str, Any],
        *,
        now: datetime,
        trace_id: str,
        record_type: str,
    ) -> List[str]:
        title = str(content_pack.get("title") or "Untitled")
        summary = str(content_pack.get("ai_summary") or "")
        topic_summary = str(content_pack.get("topic_summary") or "")
        source_url = str(content_pack.get("source_url") or "")
        channels = _normalize_channels(content_pack.get("channels"))
        image_urls = _normalize_images(content_pack)

        if record_type == "topic":
            return [
                f"# {title}",
                "",
                f"- Archived At: {now.isoformat()}",
                f"- Trace ID: {trace_id}",
                f"- Source URL: {source_url}",
                f"- Suggested Platforms: {', '.join(channels)}",
                "",
                "## 摘要",
                topic_summary or summary,
                "",
            ]

        platform = str(content_pack.get("platform") or "general")
        article_markdown = str(content_pack.get("article_markdown") or "")
        twitter_draft = str(content_pack.get("twitter_draft") or "")
        image_lines = image_urls or [str(content_pack.get("image_url") or "")]
        image_lines = [line for line in image_lines if line]

        body = [
            f"# {title}",
            "",
            f"- Archived At: {now.isoformat()}",
            f"- Trace ID: {trace_id}",
            f"- Platform: {platform}",
            f"- Source URL: {source_url}",
            "",
            "## AI Summary",
            summary,
            "",
        ]
        if twitter_draft:
            body.extend(
                [
                    "## Twitter Draft",
                    twitter_draft,
                    "",
                ]
            )
        body.extend(
            [
                "## Article",
                article_markdown,
                "",
                "## Images",
            ]
        )
        if image_lines:
            body.extend([f"- {img}" for img in image_lines])
        else:
            body.append("- (none)")
        body.append("")
        return body

    def save_dashboard(self, content_pack: Dict[str, Any], archive_url: str) -> None:
        channels = content_pack.get("channels") or ["twitter", "wechat_blog"]
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO dashboard_entries (
                        created_at, source_id, title, ai_summary, archive_url,
                        status, channels, payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        datetime.utcnow().isoformat(),
                        content_pack.get("source_id", "unknown"),
                        content_pack.get("title", "Untitled"),
                        content_pack.get("ai_summary", "") or content_pack.get("topic_summary", ""),
                        archive_url,
                        content_pack.get("status", "待审"),
                        ", ".join(channels),
                        json.dumps(content_pack, ensure_ascii=False),
                    ),
                )

    def build_generation_context(self, title: str, platform: str, limit: int = 5) -> str:
        title_tokens = _extract_tokens(title)
        if not title_tokens:
            return ""

        snippets: List[str] = []
        draft_files = sorted(
            self.archive_dir.glob("*/draft_pool/*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        platform_key = platform.strip().lower()
        for path in draft_files:
            if len(snippets) >= limit:
                break
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue

            head = text.splitlines()[0].strip() if text else ""
            text_lower = text.lower()
            score = 0
            for token in title_tokens:
                if token in text_lower:
                    score += 1

            path_lower = path.name.lower()
            if platform_key and f"-{platform_key}-" in path_lower:
                score += 2
            if score <= 0:
                continue

            one_liner = _safe_one_line(text, limit=220)
            snippets.append(f"- {head}: {one_liner}")

        return "\n".join(snippets)

    def list_dashboard(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT created_at, source_id, title, ai_summary, archive_url, status, channels, payload
                FROM dashboard_entries
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(row) for row in rows]


def _safe_file_part(value: str, max_len: int = 32) -> str:
    value = value.strip().replace(" ", "_")
    value = re.sub(r"[^A-Za-z0-9_\-]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    if not value:
        return "item"
    return value[:max_len]


def _normalize_record_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "topic":
        return "topic"
    return "draft"


def _normalize_channels(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        single = value.strip()
        return [single] if single else []
    return []


def _normalize_images(content_pack: Dict[str, Any]) -> List[str]:
    images = content_pack.get("image_urls")
    if isinstance(images, Sequence) and not isinstance(images, (str, bytes)):
        return [str(v).strip() for v in images if str(v).strip()]
    image_url = str(content_pack.get("image_url") or "").strip()
    return [image_url] if image_url else []


def _safe_one_line(text: str, limit: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def _extract_tokens(text: str) -> List[str]:
    raw_tokens = re.findall(r"[a-zA-Z0-9]{3,}|[\u4e00-\u9fff]{2,}", text.lower())
    result: List[str] = []
    seen = set()
    for token in raw_tokens:
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result[:10]
