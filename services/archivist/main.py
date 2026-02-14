from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from libs.neural_flow.archive import ArchiveRepository
from libs.neural_flow.feishu import FeishuClient
from libs.neural_flow.http import post_json
from libs.neural_flow.models import ArchiveRequest, ArchiveResponse
from libs.neural_flow.observability import bind_log_context, configure_logging, get_logger, install_fastapi_observability
from libs.neural_flow.runtime_config import load_integration_config

configure_logging("archivist")

app = FastAPI(title="Neural-Flow Archivist", version="1.0.0")
install_fastapi_observability(app, "archivist")
logger = get_logger("archivist")

ARCHIVE_DIR = os.getenv("ARCHIVE_DIR", "./data/archive")
ARCHIVE_DB_PATH = os.getenv("ARCHIVE_DB_PATH", "./data/archive.db")
ARCHIVIST_PUBLIC_BASE_URL = os.getenv("ARCHIVIST_PUBLIC_BASE_URL", "http://localhost:8006").rstrip("/")
CORTEX_API = os.getenv("CORTEX_API", "http://cortex:8000")
IRIS_API = os.getenv("IRIS_API", "http://iris:8000")

repo = ArchiveRepository(db_path=ARCHIVE_DB_PATH, archive_dir=ARCHIVE_DIR)
feishu_client = FeishuClient(load_integration_config())


def _normalize_record_type(value: Any) -> str:
    raw = str(value or "").strip().lower()
    return "topic" if raw == "topic" else "draft"


def _normalize_channels(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [piece.strip() for piece in value.split(",") if piece.strip()]
    return ["twitter", "wechat_blog"]


def _normalize_platform(value: Any) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "twitter": "twitter",
        "x": "twitter",
        "推特": "twitter",
        "zhihu": "zhihu",
        "知乎": "zhihu",
        "juejin": "juejin",
        "掘金": "juejin",
        "wechat": "wechat_blog",
        "wechat_blog": "wechat_blog",
        "公众号": "wechat_blog",
        "weixin": "wechat_blog",
        "xiaohongshu": "xiaohongshu",
        "xhs": "xiaohongshu",
        "小红书": "xiaohongshu",
    }
    return mapping.get(raw, raw or "twitter")


def _normalize_platforms(value: Any) -> List[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = [part.strip() for part in re.split(r"[,，/\\|]", value) if part.strip()]
    elif isinstance(value, dict):
        raw_items = list(value.values())
    else:
        raw_items = []

    normalized: List[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            candidate = item.get("name") or item.get("text") or item.get("value") or ""
        else:
            candidate = item
        platform = _normalize_platform(candidate)
        if platform and platform not in normalized:
            normalized.append(platform)

    if not normalized:
        return ["twitter"]
    return normalized


def _extract_image_urls(content_pack: Dict[str, Any]) -> List[str]:
    image_urls = content_pack.get("image_urls")
    if isinstance(image_urls, list):
        return [str(v).strip() for v in image_urls if str(v).strip()]
    image_url = str(content_pack.get("image_url") or "").strip()
    return [image_url] if image_url else []


def _normalize_source_info(value: Any, source_id: str = "") -> str:
    text = str(value or "").strip()
    if text:
        return text
    sid = str(source_id or "").strip().lower()
    if sid:
        if sid.startswith("twitter_"):
            return f"twitter-{sid.split('twitter_', 1)[1].replace('_live', '')}"
        if sid.startswith("wechat_"):
            return f"wechat-{sid.split('wechat_', 1)[1].replace('_live', '')}"
        if sid.startswith("xhs_") or "xiaohongshu" in sid:
            return f"xiaohongshu-{sid.replace('_live', '')}"
        return sid
    return "unknown-unknown"


def _short_doc_title(title: str, limit: int = 48) -> str:
    compact = re.sub(r"\s+", " ", title).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _draft_style_policy(platform: str) -> Dict[str, str]:
    if platform in {"wechat_blog", "zhihu", "juejin"}:
        return {
            "style_prompt": "longform_deep_analysis",
            "tone": "技术解读、影响分析、科普解释，结构化长文",
            "format": "longform",
        }
    return {
        "style_prompt": "casual_log_style",
        "tone": "记录、日志、感慨、口语化交流",
        "format": "shortform",
    }


def _build_doc_markdown(content_pack: Dict[str, Any]) -> str:
    trace_id = str(content_pack.get("trace_id", ""))
    title = str(content_pack.get("title", "Untitled"))
    summary = str(content_pack.get("ai_summary", ""))
    topic_summary = str(content_pack.get("topic_summary", "")).strip()
    source_url = str(content_pack.get("source_url", ""))
    source_info = _normalize_source_info(content_pack.get("source_info"), str(content_pack.get("source_id", "")))
    record_type = _normalize_record_type(content_pack.get("record_type"))

    if record_type == "topic":
        channels = ", ".join(_normalize_channels(content_pack.get("channels")))
        return "\n".join(
            [
                f"# {title}",
                "",
                f"Trace ID: {trace_id}",
                "",
                "## 摘要",
                topic_summary or summary,
                "",
                f"来源: {source_info}",
                f"Source: {source_url}",
                f"Suggested Platforms: {channels}",
            ]
        )

    platform = str(content_pack.get("platform") or "general")
    twitter_draft = str(content_pack.get("twitter_draft", ""))
    article_markdown = str(content_pack.get("article_markdown", ""))
    image_urls = _extract_image_urls(content_pack)

    lines = [
        f"# {title}",
        "",
        f"Trace ID: {trace_id}",
        f"Platform: {platform}",
        f"来源: {source_info}",
        "",
        "## AI Summary",
        summary,
        "",
    ]
    if twitter_draft:
        lines.extend(["## Twitter Draft", twitter_draft, ""])

    lines.extend(["## Article", article_markdown, "", "## Images"])
    if image_urls:
        lines.extend([f"- {url}" for url in image_urls])
    else:
        lines.append("- (none)")
    lines.extend(["", f"Source: {source_url}"])
    return "\n".join(lines)


def _build_local_http_doc_url(local_file_uri: str) -> str:
    parsed = urlparse(local_file_uri)
    path = Path(parsed.path)
    archive_root = Path(ARCHIVE_DIR).resolve()
    try:
        rel = path.resolve().relative_to(archive_root)
    except Exception:
        return local_file_uri

    rel_path = str(rel).replace("\\", "/")
    return f"{ARCHIVIST_PUBLIC_BASE_URL}/local-archive/{rel_path}"


def _is_confirmed_status(value: Any) -> bool:
    status = str(value or "").strip().lower()
    return status in {
        "确认",
        "已确认",
        "通过",
        "approved",
        "confirmed",
        "ready",
        "ready_to_generate",
    }


def _field_by_aliases(fields: Dict[str, Any], aliases: List[str]) -> Any:
    for alias in aliases:
        if alias in fields:
            return fields.get(alias)
    return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_to_text(v) for v in value]
        return ", ".join([p for p in parts if p])
    if isinstance(value, dict):
        for key in ("text", "name", "value", "link", "url"):
            if key in value:
                text = _to_text(value.get(key))
                if text:
                    return text
        return ""
    return ""


def _image_count_for_platform(platform: str) -> int:
    if platform in {"twitter", "xiaohongshu"}:
        return 1
    return 3


def _folder_for_record(record_type: str) -> str:
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    bucket = "topic_pool" if record_type == "topic" else "draft_pool"
    return f"{date_prefix}/{bucket}"


def _title_for_cloud_doc(content_pack: Dict[str, Any], trace_id: str, record_type: str) -> str:
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    title = _short_doc_title(str(content_pack.get("title", "Neural-Flow")))
    source_info = _normalize_source_info(content_pack.get("source_info"), str(content_pack.get("source_id", "")))
    if record_type == "topic":
        return f"[{date_prefix}] 选题 | {source_info} | {title} [#{trace_id}]"
    platform = str(content_pack.get("platform") or "general")
    return f"[{date_prefix}] 草稿 | {platform} | {title} [#{trace_id}]"


def _archive_content_pack(content_pack: Dict[str, Any]) -> ArchiveResponse:
    record_type = _normalize_record_type(content_pack.get("record_type"))
    content_pack["record_type"] = record_type
    content_pack["source_info"] = _normalize_source_info(
        content_pack.get("source_info"),
        str(content_pack.get("source_id", "")),
    )

    url_hash = str(content_pack.get("url_hash") or "")
    topic_trace = str(content_pack.get("topic_trace_id") or "")
    platform = _normalize_platform(content_pack.get("platform"))

    if record_type == "draft":
        content_pack["platform"] = platform
        default_trace = f"{topic_trace or (url_hash[:8] if url_hash else datetime.now().strftime('%H%M%S'))}-{platform}"
    else:
        default_trace = topic_trace or (url_hash[:8] if url_hash else datetime.now().strftime("%H%M%S"))

    trace_id = str(content_pack.get("trace_id") or default_trace)
    content_pack["trace_id"] = trace_id

    local_doc_url = repo.write_markdown(content_pack)
    local_http_doc_url = _build_local_http_doc_url(local_doc_url)

    final_doc_url = local_http_doc_url
    drive_doc_url = ""
    status = "archived_local"
    doc_status = "local_only"

    if feishu_client.ready_for_doc:
        try:
            drive_doc_url = feishu_client.create_doc(
                title=_title_for_cloud_doc(content_pack, trace_id, record_type),
                markdown_text=_build_doc_markdown(content_pack),
                folder_name=_folder_for_record(record_type),
            )
        except Exception as exc:
            logger.warning("feishu create_doc failed: %s", exc)
            doc_status = str(exc)[:180]
            drive_doc_url = ""

        if drive_doc_url:
            final_doc_url = drive_doc_url
            status = "archived_feishu"
            doc_status = "ok"
    else:
        doc_status = "doc_not_configured"

    bitable_status = "not_sent"
    if feishu_client.ready_for_bitable:
        display_title = str(content_pack.get("title", ""))
        if record_type == "draft":
            display_title = f"[{platform}] {display_title}"
        summary_for_table = str(content_pack.get("ai_summary", "")).strip()
        if record_type == "topic":
            summary_for_table = str(content_pack.get("topic_summary", "")).strip()
        ok, msg = feishu_client.append_bitable_dashboard_record(
            title=display_title,
            ai_summary=summary_for_table,
            doc_url=drive_doc_url,
            status=str(content_pack.get("status", "待确认" if record_type == "topic" else "草稿完成")),
            channels=_normalize_channels(content_pack.get("channels")),
            source_info=str(content_pack.get("source_info", "")),
        )
        bitable_status = "ok" if ok else msg[:120]
        if not ok:
            logger.warning("feishu bitable write failed: %s", msg)

    notify_status = "not_sent"
    if record_type == "topic" and feishu_client.ready_for_notify:
        summary_for_notify = str(content_pack.get("topic_summary") or content_pack.get("ai_summary") or "")
        ok, msg = feishu_client.send_signal_message(
            title=str(content_pack.get("title", "")),
            summary=summary_for_notify,
            doc_url=drive_doc_url or final_doc_url,
            image_url=str(content_pack.get("image_url", "")),
            trace_id=trace_id,
        )
        notify_status = "ok" if ok else msg[:120]
        if not ok:
            logger.warning("feishu notify failed: %s", msg)

    content_pack["local_doc_url"] = local_doc_url
    content_pack["local_http_doc_url"] = local_http_doc_url
    content_pack["feishu_doc_status"] = doc_status
    content_pack["feishu_bitable_status"] = bitable_status
    content_pack["feishu_notify_status"] = notify_status
    content_pack["drive_doc_url"] = drive_doc_url
    repo.save_dashboard(content_pack, archive_url=final_doc_url)

    return ArchiveResponse(feishu_doc_url=final_doc_url, status=status)


def _extract_callback_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    candidate_paths = [
        event,
        event.get("record") if isinstance(event, dict) else None,
        event.get("data") if isinstance(event, dict) else None,
        (event.get("data") or {}).get("record") if isinstance(event, dict) else None,
        event.get("after") if isinstance(event, dict) else None,
        (event.get("after") or {}).get("record") if isinstance(event, dict) else None,
    ]
    for candidate in candidate_paths:
        if isinstance(candidate, dict) and isinstance(candidate.get("fields"), dict):
            return candidate.get("fields") or {}
    return {}


def _generate_platform_draft(
    *,
    title: str,
    summary: str,
    source_url: str,
    source_info: str,
    topic_trace_id: str,
    platform: str,
) -> ArchiveResponse:
    trace_id = f"{topic_trace_id}-{platform}" if topic_trace_id else platform
    with bind_log_context(trace_id=trace_id):
        anti_dup_context = repo.build_generation_context(title=title, platform=platform, limit=5)
        history_context = ""
        if anti_dup_context:
            history_context = "以下是历史草稿片段，请避免重复视角和重复句式：\n" + anti_dup_context
        style_policy = _draft_style_policy(platform)
        prompt_seed = (
            f"{summary or title}\n"
            f"写作要求：{style_policy['tone']}。"
            "必须基于事实，不要杜撰来源；结尾给出明确观点或行动建议。"
        )

        think_result = post_json(
            f"{CORTEX_API}/think",
            {
                "title": title,
                "raw_text": prompt_seed,
                "history_context": history_context,
                "platform_strategy": {
                    platform: {
                        "enabled": True,
                        "style_prompt": style_policy["style_prompt"],
                        "tone": style_policy["tone"],
                        "content_format": style_policy["format"],
                    }
                },
            },
        )

        image_count = _image_count_for_platform(platform)
        ratio = "16:9" if platform == "twitter" else "3:4"
        image_urls: List[str] = []
        base_prompt = str(think_result.get("image_prompt") or "")
        for idx in range(image_count):
            prompt = base_prompt if idx == 0 else f"{base_prompt}. variation {idx + 1}"
            paint_result = post_json(
                f"{IRIS_API}/paint",
                {
                    "prompt": prompt,
                    "ratio": ratio,
                },
            )
            image_url = str(paint_result.get("image_url") or "").strip()
            if image_url:
                image_urls.append(image_url)

        draft_pack = {
            "record_type": "draft",
            "topic_trace_id": topic_trace_id,
            "trace_id": trace_id if topic_trace_id else "",
            "source_id": "bitable_callback",
            "title": title,
            "source_info": source_info,
            "source_url": source_url,
            "ai_summary": str(think_result.get("ai_summary") or summary),
            "twitter_draft": str(think_result.get("twitter_draft") or ""),
            "article_markdown": str(think_result.get("article_markdown") or ""),
            "image_prompt": base_prompt,
            "image_urls": image_urls,
            "image_url": image_urls[0] if image_urls else "",
            "platform": platform,
            "channels": [platform],
            "status": "草稿完成",
        }
        return _archive_content_pack(draft_pack)


@app.get("/health")
def health() -> Dict[str, str]:
    mode = "feishu+local" if feishu_client.enabled else "local"
    return {"status": "ok", "service": "archivist", "mode": mode}


@app.get("/local-archive/{rel_path:path}")
def local_archive_file(rel_path: str) -> FileResponse:
    archive_root = Path(ARCHIVE_DIR).resolve()
    target = (archive_root / rel_path).resolve()
    if archive_root not in target.parents or not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="archive file not found")
    return FileResponse(str(target), media_type="text/markdown")


@app.post("/archive", response_model=ArchiveResponse)
def archive(req: ArchiveRequest) -> ArchiveResponse:
    trace_seed = str(req.content_pack.get("trace_id") or req.content_pack.get("topic_trace_id") or req.content_pack.get("url_hash") or "")
    trace_id = trace_seed[:8] if trace_seed and len(trace_seed) > 8 else trace_seed
    with bind_log_context(trace_id=trace_id):
        return _archive_content_pack(req.content_pack)


@app.post("/feishu/callback")
def feishu_callback(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    fields = _extract_callback_fields(payload)
    if not fields:
        return {"status": "ignored", "reason": "fields_not_found"}

    status_val = _field_by_aliases(fields, ["状态", "🚦 状态", "Status"])
    if not _is_confirmed_status(_to_text(status_val)):
        return {"status": "ignored", "reason": "status_not_confirmed"}

    title = _to_text(_field_by_aliases(fields, ["原始标题", "📌 原始标题", "Title", "选题标题"]))
    if not title:
        return {"status": "ignored", "reason": "missing_title"}

    summary = _to_text(
        _field_by_aliases(
            fields,
            ["摘要", "Summary", "AI 摘要", "AI摘要", "🤖 AI 摘要", "AI Summary", "选题摘要"],
        )
    )
    source_url = _to_text(_field_by_aliases(fields, ["来源链接", "Source URL", "原文链接", "链接"]))
    source_info = _to_text(_field_by_aliases(fields, ["来源", "来源信息", "Source", "source_info"]))
    topic_trace_id = _to_text(_field_by_aliases(fields, ["Trace ID", "trace_id", "追踪ID", "追踪 Id"]))
    if not topic_trace_id:
        m = re.search(r"\[#([A-Za-z0-9_\-]+)\]", title)
        if m:
            topic_trace_id = m.group(1)
    if not topic_trace_id:
        topic_trace_id = datetime.now().strftime("%H%M%S")

    platform_field = _field_by_aliases(fields, ["发布平台", "发布渠道", "📢 发布渠道", "Channels", "平台"])
    platforms = _normalize_platforms(platform_field)

    results = []
    for platform in platforms:
        try:
            response = _generate_platform_draft(
                title=title,
                summary=summary,
                source_url=source_url,
                source_info=source_info,
                topic_trace_id=topic_trace_id,
                platform=platform,
            )
            results.append(
                {
                    "platform": platform,
                    "status": response.status,
                    "doc_url": response.feishu_doc_url,
                }
            )
        except Exception as exc:
            logger.exception("generate draft failed for platform=%s", platform)
            results.append(
                {
                    "platform": platform,
                    "status": "failed",
                    "error": str(exc)[:200],
                }
            )

    return {"status": "ok", "generated": len(results), "results": results}


@app.get("/dashboard")
def dashboard(limit: int = 20) -> Dict[str, Any]:
    rows = repo.list_dashboard(limit=limit)
    items = []
    for row in rows:
        payload = {}
        try:
            import json

            payload = json.loads(row.get("payload") or "{}")
        except Exception:
            payload = {}
        row.pop("payload", None)
        row["feishu_doc_status"] = payload.get("feishu_doc_status", "")
        row["feishu_bitable_status"] = payload.get("feishu_bitable_status", "")
        row["feishu_notify_status"] = payload.get("feishu_notify_status", "")
        row["trace_id"] = payload.get("trace_id", "")
        row["record_type"] = payload.get("record_type", "")
        row["platform"] = payload.get("platform", "")
        row["topic_summary"] = payload.get("topic_summary", "")
        row["source_info"] = payload.get("source_info", "")
        row["drive_doc_url"] = payload.get("drive_doc_url", "")
        row["local_http_doc_url"] = payload.get("local_http_doc_url", "")
        items.append(row)
    return {"items": items}
