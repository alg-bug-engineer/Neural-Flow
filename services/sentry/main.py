from __future__ import annotations

from pathlib import Path
from typing import Dict

import httpx
from fastapi import FastAPI, HTTPException

from libs.neural_flow.models import ScanRequest, ScanResponse
from libs.neural_flow.observability import configure_logging, get_logger, install_fastapi_observability
from libs.neural_flow.rss import now_utc_iso, parse_rss_items

configure_logging("sentry")
logger = get_logger("sentry")

app = FastAPI(title="Neural-Flow Sentry", version="1.0.0")
install_fastapi_observability(app, "sentry")


def _fetch_rss_text(url: str) -> str:
    if url.startswith("file://"):
        path = Path(url[7:])
        if not path.exists():
            raise FileNotFoundError(f"RSS file not found: {path}")
        return path.read_text(encoding="utf-8")

    with httpx.Client(timeout=25.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "sentry"}


@app.post("/scan", response_model=ScanResponse)
def scan(req: ScanRequest) -> ScanResponse:
    source = req.source_config
    try:
        xml_text = _fetch_rss_text(source.url)
        items = parse_rss_items(xml_text=xml_text, source_id=source.id, max_items=source.max_items)
        logger.info("scan_success", extra={"source_id": source.id, "item_count": len(items)})
        return ScanResponse(
            source_id=source.id,
            fetched_at=now_utc_iso(),
            item_count=len(items),
            items=items,
        )
    except Exception as exc:
        logger.warning("scan_failed", extra={"source_id": source.id, "error": str(exc)[:200]})
        raise HTTPException(status_code=502, detail=f"scan failed: {exc}") from exc
