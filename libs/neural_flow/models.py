from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SourceConfig(BaseModel):
    id: str
    type: str = "rss"
    url: str
    fetch_interval: str = "30m"
    weight: int = 1
    max_items: int = 5


class NormalizedItem(BaseModel):
    source_id: str
    url_hash: str
    title: str
    url: str
    summary: str = ""
    raw_text: str = ""
    published_at: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class ScanRequest(BaseModel):
    source_config: SourceConfig


class ScanResponse(BaseModel):
    source_id: str
    fetched_at: str
    item_count: int
    items: List[NormalizedItem]


class DuplicateCheckRequest(BaseModel):
    url_hash: str


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool


class RetrieveContextRequest(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    limit: int = 3


class RetrieveContextResponse(BaseModel):
    context: str
    matched_count: int


class RememberRequest(BaseModel):
    source_id: str
    url_hash: str
    title: str
    url: str
    summary: str
    keywords: List[str] = Field(default_factory=list)
    raw_text: str = ""
    archive_url: str = ""
    image_url: str = ""


class ThinkRequest(BaseModel):
    title: str
    raw_text: str
    history_context: str = ""
    platform_strategy: Dict[str, Any] = Field(default_factory=dict)


class ThinkResponse(BaseModel):
    twitter_draft: str
    article_markdown: str
    image_prompt: str
    ai_summary: str


class PaintRequest(BaseModel):
    prompt: str
    ratio: str = "16:9"


class PaintResponse(BaseModel):
    image_url: str
    base64_data: Optional[str] = None


class ArchiveRequest(BaseModel):
    content_pack: Dict[str, Any]


class ArchiveResponse(BaseModel):
    feishu_doc_url: str
    status: str


class PlatformPolicy(BaseModel):
    enabled: bool = True
    style_prompt: str = "default"
    schedule: Optional[str] = None
    max_posts_per_day: Optional[int] = None
    min_word_count: Optional[int] = None


class VisualConfig(BaseModel):
    default_style: str = "cyberpunk, data flow"
    default_ratio: str = "16:9"


class GlobalConfig(BaseModel):
    timezone: str = "Asia/Shanghai"
    memory_retention_days: int = 30


class RulesConfig(BaseModel):
    global_config: GlobalConfig = Field(default_factory=GlobalConfig, alias="global")
    sources: List[SourceConfig] = Field(default_factory=list)
    platforms: Dict[str, PlatformPolicy] = Field(default_factory=dict)
    visual: VisualConfig = Field(default_factory=VisualConfig)


class PulseRunResult(BaseModel):
    source_id: str
    scanned: int
    processed: int
    duplicated: int
    failed: int
    started_at: datetime
    ended_at: datetime
