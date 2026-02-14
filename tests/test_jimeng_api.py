import os

import pytest
from fastapi.testclient import TestClient

from libs.neural_flow.runtime_config import load_integration_config
from services.iris.main import app

RUN_LIVE = os.getenv("RUN_LIVE_INTEGRATION", "0") == "1"


@pytest.mark.skipif(not RUN_LIVE, reason="set RUN_LIVE_INTEGRATION=1 to enable live API test")
def test_jimeng_live_paint() -> None:
    config = load_integration_config()
    if not config.jimeng_ak or not config.jimeng_sk:
        pytest.skip("jimeng ak/sk missing in config/feishu_config.json")

    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    if health.json().get("mode") != "jimeng":
        pytest.skip("volcengine sdk unavailable or jimeng config not loaded")

    resp = client.post(
        "/paint",
        json={
            "prompt": "Cyberpunk city skyline, data stream, cinematic lighting",
            "ratio": "16:9",
        },
    )
    assert resp.status_code == 200

    data = resp.json()
    image_url = data.get("image_url", "")
    assert image_url.startswith("http")

    # ensure this test really hit live Jimeng path, not fallback picsum
    assert "picsum.photos" not in image_url
