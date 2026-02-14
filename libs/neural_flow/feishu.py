from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import httpx

from .runtime_config import IntegrationConfig


class FeishuClient:
    def __init__(self, config: IntegrationConfig, base_url: str = "https://open.feishu.cn") -> None:
        self.config = config
        self.base_url = base_url.rstrip("/")
        self._tenant_token = ""
        self._token_expire_at = 0.0
        self._folder_cache: Dict[str, str] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.config.app_id and self.config.app_secret)

    @property
    def ready_for_bitable(self) -> bool:
        return bool(self.enabled and self.config.bitable_app_token and self.config.bitable_table_id)

    @property
    def ready_for_doc(self) -> bool:
        return bool(self.enabled)

    @property
    def ready_for_notify(self) -> bool:
        return bool(self.enabled and self.config.receive_id)

    def _request(self, method: str, path: str, *, auth: bool = False, json_body: Optional[Dict[str, Any]] = None, timeout: float = 20.0) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self._get_tenant_access_token()}"

        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, json=json_body, headers=headers)
            response.raise_for_status()
            data = response.json()

        if isinstance(data, dict) and int(data.get("code", 0)) != 0:
            raise RuntimeError(f"feishu api error {data.get('code')}: {data.get('msg')}")
        return data if isinstance(data, dict) else {}

    def _get_tenant_access_token(self) -> str:
        now = time.time()
        if self._tenant_token and now < self._token_expire_at:
            return self._tenant_token

        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }
        data = self._request(
            "POST",
            "/open-apis/auth/v3/tenant_access_token/internal",
            auth=False,
            json_body=payload,
            timeout=15.0,
        )

        token = str(data.get("tenant_access_token", ""))
        expire = int(data.get("expire", 7200))
        if not token:
            raise RuntimeError("feishu tenant token empty")

        self._tenant_token = token
        self._token_expire_at = now + max(60, expire - 60)
        return token

    def create_doc(self, title: str, markdown_text: str = "", folder_name: str = "") -> str:
        if not self.ready_for_doc:
            return ""

        payload = {"title": title[:180] or "Neural-Flow"}
        folder_token = self._resolve_doc_folder_token(folder_name.strip())
        if folder_token:
            payload["folder_token"] = folder_token

        try:
            data = self._request(
                "POST",
                "/open-apis/docx/v1/documents",
                auth=True,
                json_body=payload,
            )
        except Exception as exc:
            # If folder permission is missing, fallback to app default space.
            if folder_token and "1770040" in str(exc):
                data = self._request(
                    "POST",
                    "/open-apis/docx/v1/documents",
                    auth=True,
                    json_body={"title": title[:180] or "Neural-Flow"},
                )
            else:
                raise

        doc_id = str(data.get("data", {}).get("document", {}).get("document_id", ""))
        if not doc_id:
            return ""

        if markdown_text.strip():
            self._append_doc_plain_lines(doc_id, markdown_text)

        return f"https://feishu.cn/docx/{doc_id}"

    def _resolve_doc_folder_token(self, folder_name: str) -> str:
        root_folder_token = str(self.config.root_folder_token or "").strip()
        if not root_folder_token:
            return ""
        if not folder_name:
            return root_folder_token

        segments = [seg.strip() for seg in folder_name.replace("\\", "/").split("/") if seg.strip()]
        if not segments:
            return root_folder_token

        current_parent = root_folder_token
        path_so_far = ""
        for segment in segments:
            path_so_far = f"{path_so_far}/{segment}" if path_so_far else segment
            cache_key = f"{current_parent}:{path_so_far}"
            cached = self._folder_cache.get(cache_key)
            if cached:
                current_parent = cached
                continue

            existing = self._find_child_folder_token(current_parent, segment)
            if existing:
                self._folder_cache[cache_key] = existing
                current_parent = existing
                continue

            try:
                data = self._request(
                    "POST",
                    "/open-apis/drive/v1/files/create_folder",
                    auth=True,
                    json_body={"name": segment[:180], "folder_token": current_parent},
                )
                token = str(data.get("data", {}).get("token", "")).strip()
                if token:
                    self._folder_cache[cache_key] = token
                    current_parent = token
                    continue
            except Exception:
                pass

            # folder create can fail if same-name folder exists; try lookup one more time.
            existing = self._find_child_folder_token(current_parent, segment)
            if existing:
                self._folder_cache[cache_key] = existing
                current_parent = existing
                continue
            return root_folder_token

        return current_parent

    def _find_child_folder_token(self, parent_token: str, folder_name: str) -> str:
        page_token = ""
        safe_parent = quote(parent_token, safe="")
        while True:
            path = f"/open-apis/drive/v1/files?folder_token={safe_parent}&page_size=200"
            if page_token:
                path += f"&page_token={quote(page_token, safe='')}"
            try:
                data = self._request("GET", path, auth=True)
            except Exception:
                return ""

            data_obj = data.get("data", {}) if isinstance(data, dict) else {}
            files = data_obj.get("files", []) or []
            for item in files:
                if str(item.get("type", "")).lower() != "folder":
                    continue
                if str(item.get("name", "")).strip() != folder_name:
                    continue
                token = str(item.get("token", "")).strip()
                if token:
                    return token

            if not bool(data_obj.get("has_more", False)):
                return ""
            page_token = str(data_obj.get("next_page_token", "")).strip()
            if not page_token:
                return ""

    def _append_doc_plain_lines(self, doc_id: str, markdown_text: str) -> None:
        lines = [line.strip() for line in markdown_text.splitlines() if line.strip()]
        if not lines:
            return

        # Append each line as a text block under the root page block.
        for line in lines[:40]:
            payload = {
                "index": -1,
                "children": [
                    {
                        "block_type": 2,
                        "text": {
                            "elements": [
                                {
                                    "text_run": {
                                        "content": line[:900],
                                    }
                                }
                            ]
                        },
                    }
                ]
            }
            self._request(
                "POST",
                f"/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children?document_revision_id=-1",
                auth=True,
                json_body=payload,
            )

    def append_bitable_dashboard_record(
        self,
        *,
        title: str,
        ai_summary: str,
        doc_url: str,
        status: str,
        channels: List[str],
        source_info: str = "",
    ) -> Tuple[bool, str]:
        if not self.ready_for_bitable:
            return False, "bitable_not_configured"

        try:
            field_items = self._request(
                "GET",
                f"/open-apis/bitable/v1/apps/{self.config.bitable_app_token}/tables/{self.config.bitable_table_id}/fields?page_size=200",
                auth=True,
            ).get("data", {}).get("items", [])
        except Exception as exc:
            return False, f"field_meta_error: {exc}"

        if not field_items:
            return False, "field_meta_empty"

        title_field = self._find_field(field_items, ["原始标题", "📌 原始标题", "Title"])
        summary_field = self._find_field(field_items, ["AI 摘要", "AI摘要", "🤖 AI 摘要", "AI Summary"])
        status_field = self._find_field(field_items, ["状态", "🚦 状态", "Status"])
        doc_field = self._find_field(field_items, ["文档链接", "飞书文档", "🔗 飞书文档", "Doc URL"])
        channels_field = self._find_field(field_items, ["发布平台", "发布渠道", "📢 发布渠道", "Channels"])
        date_field = self._find_field(field_items, ["归档日期", "日期", "📅 日期", "Date"])
        source_field = self._find_field(field_items, ["来源", "来源信息", "Source", "Source Info"])

        if not title_field or not summary_field:
            return False, "missing_required_fields"

        fields_payload: Dict[str, Any] = {
            title_field["field_name"]: title,
            summary_field["field_name"]: ai_summary,
        }

        if status_field:
            fields_payload[status_field["field_name"]] = self._format_single_select(status_field, status)
        if doc_field:
            fields_payload[doc_field["field_name"]] = self._format_link(doc_field, doc_url)
        if channels_field:
            fields_payload[channels_field["field_name"]] = self._format_multi_select(channels_field, channels)
        if date_field:
            fields_payload[date_field["field_name"]] = self._format_date(date_field)
        if source_field:
            fields_payload[source_field["field_name"]] = source_info

        try:
            self._request(
                "POST",
                f"/open-apis/bitable/v1/apps/{self.config.bitable_app_token}/tables/{self.config.bitable_table_id}/records",
                auth=True,
                json_body={"fields": fields_payload},
            )
            return True, "ok"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _find_field(items: List[Dict[str, Any]], aliases: List[str]) -> Optional[Dict[str, Any]]:
        alias_set = set(aliases)
        for item in items:
            name = str(item.get("field_name", ""))
            if name in alias_set:
                return item
        return None

    @staticmethod
    def _format_single_select(field: Dict[str, Any], value: str) -> Any:
        if int(field.get("type", 0)) != 3:
            return value

        options = field.get("property", {}).get("options", []) or []
        valid_names = [str(opt.get("name", "")) for opt in options]
        if value in valid_names:
            return value
        if valid_names:
            return valid_names[0]
        return value

    @staticmethod
    def _format_multi_select(field: Dict[str, Any], channels: List[str]) -> Any:
        if int(field.get("type", 0)) != 4:
            return ", ".join(channels) if channels else ""

        options = field.get("property", {}).get("options", []) or []
        valid_names = [str(opt.get("name", "")) for opt in options]
        mapping = {
            "twitter": "Twitter",
            "wechat_blog": "公众号",
            "wechat": "公众号",
            "juejin": "掘金",
            "zhihu": "知乎",
            "xiaohongshu": "小红书",
            "xhs": "小红书",
        }

        selected: List[str] = []
        for raw in channels:
            mapped = mapping.get(str(raw).strip().lower(), str(raw))
            if mapped in valid_names and mapped not in selected:
                selected.append(mapped)

        if selected:
            return selected
        if valid_names:
            return [valid_names[0]]
        return channels

    @staticmethod
    def _format_date(field: Dict[str, Any]) -> Any:
        if int(field.get("type", 0)) == 5:
            return int(time.time() * 1000)
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _format_link(field: Dict[str, Any], url: str) -> Any:
        if int(field.get("type", 0)) == 15:
            return {"text": "打开文档", "link": url}
        return url

    def send_signal_message(
        self,
        *,
        title: str,
        summary: str,
        doc_url: str,
        image_url: str,
        trace_id: str = "",
    ) -> Tuple[bool, str]:
        if not self.ready_for_notify:
            return False, "receiver_not_configured"

        receive_id_type = "chat_id" if self.config.receive_id.startswith("oc_") else "open_id"
        text = (
            "⚡ 脉搏：发现高价值信号\n"
            f"TraceID: {trace_id}\n"
            f"Title: {title}\n"
            f"Summary: {summary}\n"
            f"Image: {image_url}\n"
            f"Doc: {doc_url}"
        )

        payload = {
            "receive_id": self.config.receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }

        try:
            self._request(
                "POST",
                f"/open-apis/im/v1/messages?receive_id_type={receive_id_type}",
                auth=True,
                json_body=payload,
            )
            return True, "ok"
        except Exception as exc:
            return False, str(exc)
