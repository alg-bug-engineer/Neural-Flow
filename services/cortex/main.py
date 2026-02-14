from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI

from libs.neural_flow.models import ThinkRequest, ThinkResponse
from libs.neural_flow.observability import configure_logging, get_logger, install_fastapi_observability
from libs.neural_flow.runtime_config import load_integration_config
from libs.neural_flow.textgen import fallback_think

configure_logging("cortex")
logger = get_logger("cortex")

app = FastAPI(title="Neural-Flow Cortex", version="1.0.0")
install_fastapi_observability(app, "cortex")

INTEGRATION_CONFIG = load_integration_config()
KIMI_API_KEY = os.getenv("KIMI_API_KEY", "") or INTEGRATION_CONFIG.kimi_api_key
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k2-turbo-preview")

KIMI_SYSTEM_PROMPT = """
你是资深科技内容主编，擅长把 AI/大模型/Agent 复杂信息写成高可读、高信息密度内容。
输出必须真实、具体、可执行，禁止空话套话。
你只返回严格 JSON，不要 markdown 代码块，不要额外解释。
""".strip()

BANNED_AI_PHRASES = [
    "值得注意的是",
    "让我们来看一下",
    "不可否认的是",
    "随着",
    "综上所述",
    "总而言之",
    "本文旨在",
]


def _strip_json_block(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    return text


def _safe_parse_json(text: str) -> Dict[str, Any]:
    raw = _strip_json_block(text)
    try:
        return json.loads(raw)
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        return json.loads(match.group())
    raise ValueError("model output is not valid json")


def _is_longform_strategy(req: ThinkRequest) -> bool:
    if not req.platform_strategy:
        return False

    for _, policy in req.platform_strategy.items():
        if not isinstance(policy, dict):
            continue
        style_prompt = str(policy.get("style_prompt", "")).strip().lower()
        content_format = str(policy.get("content_format", "")).strip().lower()
        if style_prompt == "longform_deep_analysis" or content_format == "longform":
            return True
    return False


def _is_casual_strategy(req: ThinkRequest) -> bool:
    if not req.platform_strategy:
        return False

    for _, policy in req.platform_strategy.items():
        if not isinstance(policy, dict):
            continue
        style_prompt = str(policy.get("style_prompt", "")).strip().lower()
        if style_prompt == "casual_log_style":
            return True
    return False


def _build_prompt(req: ThinkRequest) -> str:
    strategy_name = ", ".join(req.platform_strategy.keys()) if req.platform_strategy else "default"
    strategy_detail = json.dumps(req.platform_strategy, ensure_ascii=False)[:2200] if req.platform_strategy else "{}"

    longform = _is_longform_strategy(req)
    casual = _is_casual_strategy(req)

    style_directives = [
        "写作必须像真人表达，避免机械模板语。",
        "观点要明确，给出判断依据，不只复述事实。",
        "优先保留可核验事实：主体、动作、时间、影响、限制条件。",
        "禁用表达: " + "、".join(BANNED_AI_PHRASES),
    ]

    if longform:
        style_directives.extend(
            [
                "article_markdown 采用长文结构：开场钩子 -> 事实拆解 -> 技术原理 -> 影响评估 -> 可执行建议。",
                "至少使用 4 个二级标题，段落短小，手机阅读友好。",
                "在适合配图的段落插入 [配图: 描述]，数量 2-4 个，描述具体场景。",
            ]
        )

    if casual and not longform:
        style_directives.extend(
            [
                "article_markdown 采用日志感/口语化风格，可带第一人称观察。",
                "保持短句和节奏感，不要学术论文腔。",
            ]
        )

    image_directives = [
        "image_prompt 必须是英文单行，不超过 420 字符。",
        "image_prompt 结构必须包含: subject, scene, composition, lighting, color palette, style, quality tags。",
        "默认生成科技插画风格，强调 clean composition, high detail, cinematic lighting, professional editorial cover。",
        "如果是技术主题，加入 blueprint/data dashboard/futuristic UI 等可视元素。",
        "禁止在图中出现可读文字、logo、水印，禁止 lowres, blurry, distorted faces。",
    ]

    return (
        "请基于输入生成严格 JSON，键必须且只能是: twitter_draft, article_markdown, image_prompt, ai_summary。\n"
        "约束:\n"
        "- twitter_draft <= 280 字。\n"
        "- ai_summary <= 240 字。\n"
        "- article_markdown 需可直接发布，不要解释你在做什么。\n"
        "- image_prompt 仅英文。\n\n"
        "写作规则:\n- " + "\n- ".join(style_directives) + "\n\n"
        "生图规则:\n- " + "\n- ".join(image_directives) + "\n\n"
        f"标题: {req.title}\n"
        f"历史上下文: {req.history_context or '无'}\n"
        f"平台策略: {strategy_name}\n"
        f"平台策略详情(JSON): {strategy_detail}\n"
        f"正文: {req.raw_text[:9000]}"
    )


def _call_kimi(req: ThinkRequest) -> Optional[ThinkResponse]:
    if not KIMI_API_KEY:
        return None

    payload: Dict[str, Any] = {
        "model": KIMI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"{KIMI_SYSTEM_PROMPT} "
                    "Return strict JSON only with keys: twitter_draft, article_markdown, image_prompt, ai_summary."
                ),
            },
            {"role": "user", "content": _build_prompt(req)},
        ],
        "temperature": 0.5,
    }

    headers = {
        "Authorization": f"Bearer {KIMI_API_KEY}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{KIMI_BASE_URL}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        return None

    parsed = _safe_parse_json(content)
    return ThinkResponse(
        twitter_draft=str(parsed.get("twitter_draft", ""))[:280],
        article_markdown=str(parsed.get("article_markdown", "")),
        image_prompt=str(parsed.get("image_prompt", ""))[:500],
        ai_summary=str(parsed.get("ai_summary", ""))[:240],
    )


@app.get("/health")
def health() -> Dict[str, str]:
    mode = "kimi" if KIMI_API_KEY else "fallback"
    return {"status": "ok", "service": "cortex", "mode": mode}


@app.post("/think", response_model=ThinkResponse)
def think(req: ThinkRequest) -> ThinkResponse:
    try:
        result = _call_kimi(req)
        if result is not None:
            return result
    except Exception as exc:
        logger.warning("kimi_generation_failed", extra={"error": str(exc)[:200]})

    strategy_name = ", ".join(req.platform_strategy.keys()) if req.platform_strategy else "default"
    return fallback_think(req.title, req.raw_text, req.history_context, strategy_name=strategy_name)
