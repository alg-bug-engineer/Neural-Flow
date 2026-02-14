from __future__ import annotations

import re

from .models import ThinkResponse


def _compact_text(text: str, limit: int = 500) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    return cleaned[:limit]


def fallback_think(title: str, raw_text: str, history_context: str, strategy_name: str = "default") -> ThinkResponse:
    body = _compact_text(raw_text, limit=1800)
    context = _compact_text(history_context, limit=300)
    summary = _compact_text(raw_text, limit=160)

    twitter_draft = (
        f"{title}\n"
        f"关键信息：{summary[:120]}\n"
        f"观点：结合过往讨论，重点看技术落地与成本。"
    )[:280]

    article_markdown = "\n".join(
        [
            f"# {title}",
            "",
            f"## 开场 ({strategy_name})",
            summary or "这是一个值得跟进的技术动态，先看结论再看细节。",
            "",
            "## 关键事实拆解",
            body or "暂无正文，建议补充官方信息、性能数据和限制条件。",
            "",
            "[配图: 未来感数据控制台与模型推理流程，可视化图层叠加]",
            "",
            "## 历史关联",
            context or "暂无历史上下文，可对比最近两周同类发布和成本变化。",
            "",
            "## 影响评估",
            "1. 对产品落地：看接入成本、迭代速度和稳定性。",
            "2. 对技术路线：关注模型能力边界和工程复杂度。",
            "3. 对团队协同：明确哪些环节可以自动化、哪些需要人工审核。",
            "",
            "[配图: 工程团队讨论架构方案，白板上有 Agent workflow 草图]",
            "",
            "## 可执行建议",
            "1. 跟踪官方文档和 benchmark 更新。",
            "2. 用小范围场景做 A/B 验证，再决定是否全量接入。",
            "3. 记录关键事实与结论，避免重复试错。",
        ]
    )

    image_prompt = (
        "Tech editorial illustration, AI model operations center, layered data dashboards, "
        "isometric composition, cinematic volumetric lighting, blue and cyan palette, "
        "clean modern design, ultra detailed, 4k, no text, no watermark"
    )

    return ThinkResponse(
        twitter_draft=twitter_draft,
        article_markdown=article_markdown,
        image_prompt=image_prompt,
        ai_summary=summary,
    )
