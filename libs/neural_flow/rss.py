from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from typing import List, Set

from bs4 import BeautifulSoup

from .models import NormalizedItem


_AD_WORDS = (
    "广告",
    "招聘",
    "欢迎关注",
    "点击原文",
    "推广",
    "商务合作",
)


def _clean_text(text: str) -> str:
    text = unescape(text or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"https?://\S+", text):
        return text
    if "<" not in text and ">" not in text:
        return text
    soup = BeautifulSoup(text, "html.parser")
    cleaned = soup.get_text("\n", strip=True)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def _extract_images(html_text: str) -> List[str]:
    if not html_text:
        return []
    soup = BeautifulSoup(html_text, "html.parser")
    result: List[str] = []
    for img in soup.find_all("img"):
        src = str(img.get("src") or "").strip()
        if src:
            result.append(src)
    return result


def _is_noise(title: str, cleaned_text: str) -> bool:
    plain = (cleaned_text or "").replace("\n", " ").strip()
    if not plain:
        return True

    if re.fullmatch(r"https?://\S+", plain):
        return True

    if re.fullmatch(r"https?://\S+", (title or "").strip()):
        return True

    lower_plain = plain.lower()
    for word in _AD_WORDS:
        if word in plain:
            return True
    if lower_plain.startswith("http://") or lower_plain.startswith("https://"):
        return True

    return False


def _extract_keywords(title: str, text: str, limit: int = 8) -> List[str]:
    corpus = f"{title} {text}"
    tokens = re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,}", corpus)
    seen: Set[str] = set()
    result: List[str] = []
    for token in tokens:
        token = token.strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= limit:
            break
    return result


def parse_rss_items(xml_text: str, source_id: str, max_items: int = 5) -> List[NormalizedItem]:
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    items: List[NormalizedItem] = []

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = item.findtext("description") or ""
        content_encoded = item.findtext("content:encoded", namespaces=ns) or ""
        pub_date = (item.findtext("pubDate") or "").strip() or None

        clean_description = _clean_text(description)
        clean_content = _clean_text(content_encoded)
        raw_text = clean_content or clean_description or title

        if _is_noise(title, raw_text):
            continue

        images = _extract_images(content_encoded) or _extract_images(description)
        summary = raw_text.split("\n")[0][:180]
        url_hash = hashlib.sha256(link.encode("utf-8")).hexdigest()
        keywords = _extract_keywords(title, raw_text)

        normalized = NormalizedItem(
            source_id=source_id,
            url_hash=url_hash,
            title=title[:300],
            url=link,
            summary=summary,
            raw_text=raw_text[:12000],
            published_at=pub_date,
            images=images[:6],
            keywords=keywords,
        )
        items.append(normalized)
        if len(items) >= max_items:
            break

    return items


def now_utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
