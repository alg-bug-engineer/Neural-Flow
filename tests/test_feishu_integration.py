import os

import pytest
from fastapi.testclient import TestClient

from libs.neural_flow.runtime_config import load_integration_config
from services.archivist.main import app

RUN_FEISHU = os.getenv("RUN_FEISHU_INTEGRATION", "0") == "1"


@pytest.mark.skipif(not RUN_FEISHU, reason="set RUN_FEISHU_INTEGRATION=1 to enable feishu integration test")
def test_archivist_feishu_archive() -> None:
    config = load_integration_config()
    required = [
        config.app_id,
        config.app_secret,
        config.root_folder_token,
        config.receive_id,
        config.bitable_app_token,
        config.bitable_table_id,
    ]
    if not all(required):
        pytest.skip("feishu credentials incomplete in config/feishu_config.json")

    client = TestClient(app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json().get("mode") == "feishu+local"

    resp = client.post(
        "/archive",
        json={
            "content_pack": {
                "source_id": "integration_test",
                "url_hash": "feishu-test-hash",
                "title": "Neural-Flow 集成测试",
                "source_url": "https://example.com/source",
                "ai_summary": "这是飞书集成测试生成的数据。",
                "twitter_draft": "这是推文草稿。",
                "article_markdown": "# 集成测试\n\n飞书文档写入测试。",
                "image_prompt": "test prompt",
                "image_url": "https://example.com/image.jpg",
                "channels": ["twitter", "wechat_blog"],
                "status": "待审",
            }
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("archived_feishu", "archived_local")
    assert data["feishu_doc_url"]
