import os

import pytest
from fastapi.testclient import TestClient

from libs.neural_flow.runtime_config import load_integration_config
from services.cortex.main import app

RUN_LIVE = os.getenv("RUN_LIVE_INTEGRATION", "0") == "1"
FALLBACK_IMAGE_PROMPT = (
    "Futuristic newsroom, AI data stream dashboard, cinematic lighting, "
    "high detail, clean composition"
)


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_INTEGRATION=1 to enable live API test")
def test_kimi_live_think() -> None:
    config = load_integration_config()
    if not config.kimi_api_key:
        pytest.skip("kimi_api_key is missing in config/feishu_config.json")

    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json().get("mode") == "kimi"

    resp = client.post(
        "/think",
        json={
            "title": "GLM-5 发布",
            "raw_text": "智谱发布了 GLM-5，强调 Coding 与 Agent 能力。",
            "history_context": "上周讨论过开源模型推理成本。",
            "platform_strategy": {"twitter": {"enabled": True, "style_prompt": "sharp_news"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["twitter_draft"]
    assert len(data["twitter_draft"]) <= 280
    assert data["article_markdown"]
    assert data["ai_summary"]
    assert data["image_prompt"]

    # ensure this test really hit live Kimi path, not local fallback template
    assert data["image_prompt"] != FALLBACK_IMAGE_PROMPT
