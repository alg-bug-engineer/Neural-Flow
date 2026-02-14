from __future__ import annotations

import os
from typing import Dict

from fastapi import FastAPI

from libs.neural_flow.memory import MemoryRepository
from libs.neural_flow.models import (
    DuplicateCheckRequest,
    DuplicateCheckResponse,
    RememberRequest,
    RetrieveContextRequest,
    RetrieveContextResponse,
)
from libs.neural_flow.observability import configure_logging, get_logger, install_fastapi_observability

configure_logging("hippocampus")
logger = get_logger("hippocampus")
app = FastAPI(title="Neural-Flow Hippocampus", version="1.0.0")
install_fastapi_observability(app, "hippocampus")

DB_PATH = os.getenv("MEMORY_DB_PATH", "./data/memory.db")
repository = MemoryRepository(DB_PATH)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok", "service": "hippocampus"}


@app.post("/check_duplicate", response_model=DuplicateCheckResponse)
def check_duplicate(req: DuplicateCheckRequest) -> DuplicateCheckResponse:
    return DuplicateCheckResponse(is_duplicate=repository.is_duplicate(req.url_hash))


@app.post("/retrieve_context", response_model=RetrieveContextResponse)
def retrieve_context(req: RetrieveContextRequest) -> RetrieveContextResponse:
    context, matched = repository.retrieve_context(req.keywords, limit=req.limit)
    return RetrieveContextResponse(context=context, matched_count=matched)


@app.post("/remember")
def remember(req: RememberRequest) -> Dict[str, str]:
    repository.remember(req)
    logger.info("remember_saved", extra={"source_id": req.source_id, "url_hash": req.url_hash[:16]})
    return {"status": "ok"}


@app.post("/cleanup")
def cleanup(retention_days: int = 30) -> Dict[str, int]:
    removed = repository.cleanup(retention_days)
    logger.info("cleanup_done", extra={"retention_days": retention_days, "removed": removed})
    return {"removed": removed}
