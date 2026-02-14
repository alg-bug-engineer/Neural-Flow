from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

TRACE_HEADER = "x-trace-id"
REQUEST_HEADER = "x-request-id"

_TRACE_ID: contextvars.ContextVar[str] = contextvars.ContextVar("neural_flow_trace_id", default="")
_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("neural_flow_request_id", default="")

_CONFIG_LOCK = threading.Lock()
_DEFAULT_LOG_DB = "./data/system_logs.db"
_MAX_LOG_QUERY_LIMIT = 1000

_RESERVED_LOG_RECORD_KEYS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "trace_id",
    "request_id",
    "service",
}


def _normalize_id(value: str, *, fallback: str = "") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "", str(value or ""))
    return cleaned[:64] or fallback


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def get_trace_id() -> str:
    return _TRACE_ID.get().strip()


def get_request_id() -> str:
    return _REQUEST_ID.get().strip()


@contextmanager
def bind_log_context(*, trace_id: Optional[str] = None, request_id: Optional[str] = None) -> Iterator[None]:
    token_trace = None
    token_request = None

    if trace_id is not None:
        token_trace = _TRACE_ID.set(_normalize_id(trace_id))
    if request_id is not None:
        token_request = _REQUEST_ID.set(_normalize_id(request_id))

    try:
        yield
    finally:
        if token_trace is not None:
            _TRACE_ID.reset(token_trace)
        if token_request is not None:
            _REQUEST_ID.reset(token_request)


def outbound_trace_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    trace_id = get_trace_id()
    request_id = get_request_id()
    if trace_id:
        headers[TRACE_HEADER] = trace_id
    if request_id:
        headers[REQUEST_HEADER] = request_id
    return headers


def _log_db_path() -> str:
    return os.getenv("LOG_DB_PATH", _DEFAULT_LOG_DB)


def _extract_extra(record: logging.LogRecord) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED_LOG_RECORD_KEYS:
            continue
        if key.startswith("_"):
            continue
        try:
            json.dumps(value, ensure_ascii=False)
            payload[key] = value
        except Exception:
            payload[key] = str(value)
    return payload


class _ContextFilter(logging.Filter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        record.request_id = get_request_id()
        record.service = self._service_name
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.utcfromtimestamp(record.created).isoformat(timespec="milliseconds") + "Z"
        payload: Dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "service": getattr(record, "service", ""),
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, "trace_id", ""),
            "request_id": getattr(record, "request_id", ""),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }
        extra = _extract_extra(record)
        if extra:
            payload["extra"] = extra

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


class _SqliteLogHandler(logging.Handler):
    def __init__(self, db_path: str) -> None:
        super().__init__()
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), timeout=8, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS service_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    service TEXT NOT NULL,
                    level TEXT NOT NULL,
                    logger TEXT NOT NULL,
                    message TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    module TEXT NOT NULL,
                    func_name TEXT NOT NULL,
                    line_no INTEGER NOT NULL,
                    extra_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_service_logs_created_at ON service_logs(created_at)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_service_logs_trace_id ON service_logs(trace_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_service_logs_service ON service_logs(service)")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = _extract_extra(record)
            if record.exc_info:
                try:
                    payload["exception"] = logging.Formatter().formatException(record.exc_info)
                except Exception:
                    payload["exception"] = "exception_format_failed"

            row = (
                datetime.utcfromtimestamp(record.created).isoformat(timespec="milliseconds") + "Z",
                str(getattr(record, "service", "")),
                str(record.levelname),
                str(record.name),
                str(record.getMessage()),
                str(getattr(record, "trace_id", "")),
                str(getattr(record, "request_id", "")),
                str(record.module),
                str(record.funcName),
                int(record.lineno),
                json.dumps(payload, ensure_ascii=False),
            )

            with self._lock:
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO service_logs (
                            created_at, service, level, logger, message,
                            trace_id, request_id, module, func_name, line_no, extra_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        row,
                    )
        except Exception:
            self.handleError(record)


def configure_logging(service_name: str) -> None:
    normalized_service = _normalize_id(service_name, fallback="service")
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    with _CONFIG_LOCK:
        root = logging.getLogger()
        current_service = getattr(root, "_neural_flow_service", "")
        if current_service == normalized_service and getattr(root, "_neural_flow_configured", False):
            return

        for handler in list(root.handlers):
            root.removeHandler(handler)

        context_filter = _ContextFilter(normalized_service)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        stream_handler.addFilter(context_filter)
        stream_handler.setFormatter(_JsonFormatter())

        sqlite_handler = _SqliteLogHandler(_log_db_path())
        sqlite_handler.setLevel(level)
        sqlite_handler.addFilter(context_filter)
        sqlite_handler.setFormatter(_JsonFormatter())

        root.setLevel(level)
        root.addHandler(stream_handler)
        root.addHandler(sqlite_handler)
        root._neural_flow_configured = True
        root._neural_flow_service = normalized_service

        # reduce noisy dependencies
        logging.getLogger("httpx").setLevel(max(level, logging.WARNING))
        logging.getLogger("httpcore").setLevel(max(level, logging.WARNING))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def query_logs(
    *,
    limit: int = 200,
    trace_id: str = "",
    service: str = "",
    level: str = "",
    keyword: str = "",
) -> List[Dict[str, Any]]:
    db_path = Path(_log_db_path())
    if not db_path.exists():
        return []

    safe_limit = max(1, min(int(limit or 200), _MAX_LOG_QUERY_LIMIT))

    clauses: List[str] = []
    params: List[Any] = []

    if trace_id.strip():
        clauses.append("trace_id = ?")
        params.append(_normalize_id(trace_id))
    if service.strip():
        clauses.append("service = ?")
        params.append(_normalize_id(service))
    if level.strip():
        clauses.append("level = ?")
        params.append(level.strip().upper())
    if keyword.strip():
        clauses.append("message LIKE ?")
        params.append(f"%{keyword.strip()}%")

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    query = (
        "SELECT id, created_at, service, level, logger, message, trace_id, request_id, "
        "module, func_name, line_no, extra_json "
        f"FROM service_logs {where} ORDER BY id DESC LIMIT ?"
    )
    params.append(safe_limit)

    conn = sqlite3.connect(str(db_path), timeout=8)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()

    items: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["extra"] = json.loads(item.pop("extra_json", "{}") or "{}")
        except Exception:
            item["extra"] = {}
            item.pop("extra_json", None)
        items.append(item)

    return items


def install_fastapi_observability(app: Any, service_name: str) -> None:
    if getattr(app.state, "_neural_flow_observability", False):
        return

    logger = get_logger(service_name)

    @app.middleware("http")
    async def _trace_middleware(request: Any, call_next: Any) -> Any:
        incoming_trace = request.headers.get(TRACE_HEADER) or request.query_params.get("trace_id", "")
        incoming_request = request.headers.get(REQUEST_HEADER)

        trace_id = _normalize_id(incoming_trace, fallback=_new_id())
        request_id = _normalize_id(incoming_request, fallback=_new_id())

        start = time.perf_counter()
        with bind_log_context(trace_id=trace_id, request_id=request_id):
            logger.info(
                "request_start",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "client": request.client.host if request.client else "",
                },
            )
            try:
                response = await call_next(request)
            except Exception:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                logger.exception(
                    "request_error",
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "latency_ms": elapsed_ms,
                    },
                )
                raise

            elapsed_ms = int((time.perf_counter() - start) * 1000)
            response.headers[TRACE_HEADER] = trace_id
            response.headers[REQUEST_HEADER] = request_id
            logger.info(
                "request_end",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": getattr(response, "status_code", 0),
                    "latency_ms": elapsed_ms,
                },
            )
            return response

    @app.get("/logs")
    def read_logs(
        limit: int = 200,
        trace_id: str = "",
        service: str = "",
        level: str = "",
        keyword: str = "",
    ) -> Dict[str, Any]:
        items = query_logs(
            limit=limit,
            trace_id=trace_id,
            service=service,
            level=level,
            keyword=keyword,
        )
        return {
            "items": items,
            "count": len(items),
            "filters": {
                "trace_id": trace_id,
                "service": service,
                "level": level,
                "keyword": keyword,
                "limit": max(1, min(int(limit or 200), _MAX_LOG_QUERY_LIMIT)),
            },
        }

    @app.get("/logs/trace/{trace_id}")
    def read_trace_logs(trace_id: str, limit: int = 200) -> Dict[str, Any]:
        items = query_logs(limit=limit, trace_id=trace_id)
        return {"trace_id": _normalize_id(trace_id), "count": len(items), "items": items}

    app.state._neural_flow_observability = True
