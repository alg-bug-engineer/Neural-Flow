from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Dict, Optional, Tuple

from fastapi import FastAPI

from libs.neural_flow.models import PaintRequest, PaintResponse
from libs.neural_flow.observability import configure_logging, get_logger, install_fastapi_observability
from libs.neural_flow.runtime_config import load_integration_config

try:
    from volcengine.visual.VisualService import VisualService
except Exception:  # pragma: no cover - optional dependency
    VisualService = None  # type: ignore

app = FastAPI(title="Neural-Flow Iris", version="1.0.0")
configure_logging("iris")
install_fastapi_observability(app, "iris")
logger = get_logger("iris")

INTEGRATION_CONFIG = load_integration_config()
JIMENG_AK = os.getenv("JIMENG_AK", "") or INTEGRATION_CONFIG.jimeng_ak
JIMENG_SK = os.getenv("JIMENG_SK", "") or INTEGRATION_CONFIG.jimeng_sk
JIMENG_REQ_KEY = os.getenv("JIMENG_REQ_KEY", "jimeng_t2i_v40")

_PROMPT_KEYWORD_MAP = {
    "人工智能": "artificial intelligence",
    "大模型": "large language model",
    "模型": "model",
    "智能体": "agent",
    "工作流": "workflow",
    "数据": "data",
    "可视化": "data visualization",
    "架构": "architecture",
    "界面": "futuristic user interface",
    "代码": "code",
    "芯片": "chip",
    "云端": "cloud infrastructure",
    "科技感": "futuristic tech aesthetic",
    "插图": "illustration",
    "封面": "editorial cover art",
    "流程图": "process diagram",
}


def _size_from_ratio(ratio: str) -> Tuple[int, int]:
    if ratio == "3:4":
        return (768, 1024)
    return (1024, 576)


def _fallback_image(prompt: str, ratio: str) -> str:
    w, h = _size_from_ratio(ratio)
    seed = hashlib.sha256(f"{prompt}-{ratio}".encode("utf-8")).hexdigest()[:16]
    return f"https://picsum.photos/seed/{seed}/{w}/{h}"


def _build_visual_service() -> Optional["VisualService"]:
    if VisualService is None or not JIMENG_AK or not JIMENG_SK:
        return None

    service = VisualService()
    service.set_ak(JIMENG_AK)
    service.set_sk(JIMENG_SK)
    return service


def _contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _to_english_prompt(prompt: str) -> str:
    cleaned = (prompt or "").strip()
    if not cleaned:
        return "AI technology concept art"

    if not _contains_chinese(cleaned):
        return cleaned

    converted = cleaned
    for cn, en in sorted(_PROMPT_KEYWORD_MAP.items(), key=lambda x: -len(x[0])):
        converted = converted.replace(cn, f" {en} ")

    converted = re.sub(r"[\u4e00-\u9fff]+", " ", converted)
    converted = re.sub(r"\s+", " ", converted).strip(" ,.;")
    return converted or "AI technology concept art, modern digital illustration"


def _enhance_prompt(prompt: str) -> str:
    base = _to_english_prompt(prompt)
    lowered = base.lower()
    tech_markers = ("ai", "model", "agent", "data", "workflow", "architecture", "chip", "code")
    is_tech = any(marker in lowered for marker in tech_markers)

    common_tags = (
        "clean composition, cinematic lighting, high detail, editorial quality, "
        "4k, no text, no watermark, no logo"
    )
    if is_tech:
        return (
            f"Tech-style illustration, {base}, futuristic ui elements, blueprint layer, "
            f"blue-cyan palette, {common_tags}"
        )
    return f"Professional illustration, {base}, elegant color palette, {common_tags}"


def _call_jimeng(req: PaintRequest) -> Optional[str]:
    visual_service = _build_visual_service()
    if visual_service is None:
        return None

    submit_body = {
        "req_key": JIMENG_REQ_KEY,
        "prompt": f"{req.prompt}. composition ratio {req.ratio}",
        "scale": 0.5,
        "force_single": True,
    }

    submit_resp = visual_service.cv_sync2async_submit_task(submit_body)
    if int(submit_resp.get("code", -1)) != 10000:
        return None

    task_id = str(submit_resp.get("data", {}).get("task_id", ""))
    if not task_id:
        return None

    req_json_config = {
        "return_url": True,
        "logo_info": {"add_logo": False},
    }
    query_body = {
        "req_key": JIMENG_REQ_KEY,
        "task_id": task_id,
        "req_json": json.dumps(req_json_config),
    }

    for _ in range(45):
        query_resp = visual_service.cv_sync2async_get_result(query_body)
        if int(query_resp.get("code", -1)) != 10000:
            return None

        data = query_resp.get("data", {})
        status = str(data.get("status", ""))

        if status == "done":
            image_urls = data.get("image_urls", [])
            if image_urls:
                return str(image_urls[0])
            return None

        if status in ("in_queue", "generating"):
            time.sleep(2)
            continue

        return None

    return None


@app.get("/health")
def health() -> Dict[str, str]:
    mode = "jimeng" if VisualService is not None and JIMENG_AK and JIMENG_SK else "fallback"
    return {"status": "ok", "service": "iris", "mode": mode}


@app.post("/paint", response_model=PaintResponse)
def paint(req: PaintRequest) -> PaintResponse:
    enhanced_prompt = _enhance_prompt(req.prompt)
    request_payload = PaintRequest(prompt=enhanced_prompt, ratio=req.ratio)
    image_url = None
    try:
        image_url = _call_jimeng(request_payload)
    except Exception:
        image_url = None

    if not image_url:
        image_url = _fallback_image(enhanced_prompt, req.ratio)
        logger.info("paint_fallback", extra={"ratio": req.ratio, "enhanced_prompt": enhanced_prompt[:180]})
    else:
        logger.info("paint_jimeng_success", extra={"ratio": req.ratio, "enhanced_prompt": enhanced_prompt[:180]})

    return PaintResponse(image_url=image_url)
