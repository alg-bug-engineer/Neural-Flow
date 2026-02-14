from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from pydantic import BaseModel


class IntegrationConfig(BaseModel):
    app_id: str = ""
    app_secret: str = ""
    bitable_app_token: str = ""
    bitable_table_id: str = ""
    root_folder_token: str = ""
    receive_id: str = ""
    kimi_api_key: str = ""
    jimeng_ak: str = ""
    jimeng_sk: str = ""


def _read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_integration_config() -> IntegrationConfig:
    config_path = Path(os.getenv("FEISHU_CONFIG_PATH", "./config/feishu_config.json"))
    base = _read_json_file(config_path)

    env_overrides = {
        "app_id": os.getenv("FEISHU_APP_ID"),
        "app_secret": os.getenv("FEISHU_APP_SECRET"),
        "bitable_app_token": os.getenv("FEISHU_BITABLE_APP_TOKEN"),
        "bitable_table_id": os.getenv("FEISHU_BITABLE_TABLE_ID"),
        "root_folder_token": os.getenv("FEISHU_ROOT_FOLDER_TOKEN"),
        "receive_id": os.getenv("FEISHU_RECEIVE_ID"),
        "kimi_api_key": os.getenv("KIMI_API_KEY"),
        "jimeng_ak": os.getenv("JIMENG_AK"),
        "jimeng_sk": os.getenv("JIMENG_SK"),
    }

    merged: Dict[str, Any] = dict(base)
    for key, value in env_overrides.items():
        if value:
            merged[key] = value

    return IntegrationConfig.model_validate(merged)
