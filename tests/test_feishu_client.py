from libs.neural_flow.feishu import FeishuClient
from libs.neural_flow.runtime_config import IntegrationConfig


def _build_client() -> FeishuClient:
    cfg = IntegrationConfig(
        app_id="app_x",
        app_secret="secret_x",
        root_folder_token="root_123",
    )
    return FeishuClient(cfg)


def test_resolve_doc_folder_token_prefers_existing_folder() -> None:
    client = _build_client()
    calls = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path))
        if method == "GET":
            return {
                "code": 0,
                "data": {
                    "files": [{"type": "folder", "name": "2026-02-13", "token": "fld_existing"}],
                    "has_more": False,
                },
            }
        raise AssertionError("create_folder should not be called when existing folder is found")

    client._request = fake_request  # type: ignore[method-assign]

    token1 = client._resolve_doc_folder_token("2026-02-13")
    token2 = client._resolve_doc_folder_token("2026-02-13")

    assert token1 == "fld_existing"
    assert token2 == "fld_existing"
    assert calls == [("GET", "/open-apis/drive/v1/files?folder_token=root_123&page_size=200")]


def test_resolve_doc_folder_token_creates_folder_when_missing() -> None:
    client = _build_client()
    calls = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path))
        if method == "GET":
            return {"code": 0, "data": {"files": [], "has_more": False}}
        if method == "POST":
            assert path == "/open-apis/drive/v1/files/create_folder"
            assert kwargs["json_body"]["name"] == "2026-02-14"
            assert kwargs["json_body"]["folder_token"] == "root_123"
            return {"code": 0, "data": {"token": "fld_new"}}
        raise AssertionError("unexpected request")

    client._request = fake_request  # type: ignore[method-assign]

    token = client._resolve_doc_folder_token("2026-02-14")
    assert token == "fld_new"
    assert calls == [
        ("GET", "/open-apis/drive/v1/files?folder_token=root_123&page_size=200"),
        ("POST", "/open-apis/drive/v1/files/create_folder"),
    ]


def test_resolve_doc_folder_token_falls_back_to_root_folder() -> None:
    client = _build_client()
    calls = []

    def fake_request(method: str, path: str, **kwargs):
        calls.append((method, path))
        if method == "GET":
            return {"code": 0, "data": {"files": [], "has_more": False}}
        if method == "POST":
            raise RuntimeError("permission denied")
        raise AssertionError("unexpected request")

    client._request = fake_request  # type: ignore[method-assign]

    token = client._resolve_doc_folder_token("2026-02-15")
    assert token == "root_123"
    assert calls == [
        ("GET", "/open-apis/drive/v1/files?folder_token=root_123&page_size=200"),
        ("POST", "/open-apis/drive/v1/files/create_folder"),
        ("GET", "/open-apis/drive/v1/files?folder_token=root_123&page_size=200"),
    ]
