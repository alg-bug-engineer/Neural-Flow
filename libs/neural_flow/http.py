from __future__ import annotations

from typing import Any, Dict, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .observability import outbound_trace_headers


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
def post_json(
    url: str,
    payload: Dict[str, Any],
    timeout: float = 40.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    req_headers = outbound_trace_headers()
    if headers:
        req_headers.update({k: str(v) for k, v in headers.items()})

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, json=payload, headers=req_headers or None)
        response.raise_for_status()
        return response.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, min=0.5, max=4), reraise=True)
def get_json(
    url: str,
    timeout: float = 40.0,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    req_headers = outbound_trace_headers()
    if headers:
        req_headers.update({k: str(v) for k, v in headers.items()})

    with httpx.Client(timeout=timeout) as client:
        response = client.get(url, headers=req_headers or None)
        response.raise_for_status()
        return response.json()
