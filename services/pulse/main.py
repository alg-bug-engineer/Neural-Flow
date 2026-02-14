from __future__ import annotations

import os
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException
from zoneinfo import ZoneInfo

from libs.neural_flow.config import interval_to_seconds, load_rules, rules_fingerprint
from libs.neural_flow.http import post_json
from libs.neural_flow.models import PulseRunResult, RulesConfig, SourceConfig
from libs.neural_flow.observability import bind_log_context, configure_logging, get_logger, install_fastapi_observability

configure_logging("pulse")
logger = get_logger("pulse")

app = FastAPI(title="Neural-Flow Pulse", version="1.0.0")
install_fastapi_observability(app, "pulse")

RULES_PATH = os.getenv("RULES_PATH", "./config/rules.yaml")
SENTRY_API = os.getenv("SENTRY_API", "http://sentry:8000")
HIPPOCAMPUS_API = os.getenv("HIPPOCAMPUS_API", "http://hippocampus:8000")
ARCHIVIST_API = os.getenv("ARCHIVIST_API", "http://archivist:8000")
HIGH_VALUE_HINTS = (
    "发布",
    "开源",
    "上线",
    "agent",
    "benchmark",
    "paper",
    "模型",
    "融资",
    "sota",
)


def _is_high_value_signal(item: Dict[str, Any]) -> bool:
    title = str(item.get("title") or "")
    raw_text = str(item.get("raw_text") or "")
    summary = str(item.get("summary") or "")
    merged = f"{title}\n{raw_text}\n{summary}".lower()

    score = 0
    if len(raw_text) >= 220:
        score += 1
    if len(item.get("images") or []) > 0:
        score += 1
    if any(hint in merged for hint in HIGH_VALUE_HINTS):
        score += 1
    return score >= 2


def _source_info_from_source_id(source_id: str) -> str:
    raw = source_id.strip().lower()
    if not raw:
        return "unknown-unknown"

    if raw.startswith("twitter_"):
        suffix = raw.split("twitter_", 1)[1].replace("_live", "")
        return f"twitter-{suffix}"
    if raw.startswith("wechat_"):
        suffix = raw.split("wechat_", 1)[1].replace("_live", "")
        return f"wechat-{suffix}"
    if raw.startswith("xhs_") or "xiaohongshu" in raw:
        suffix = raw.replace("_live", "")
        return f"xiaohongshu-{suffix}"
    return raw


class PulseEngine:
    def __init__(self) -> None:
        self.rules: Optional[RulesConfig] = None
        self.fingerprint: str = ""
        self.last_runs: Dict[str, Dict[str, Any]] = {}
        self._run_lock = threading.Lock()
        self.scheduler = BackgroundScheduler()

    def start(self) -> None:
        self._load_and_schedule(force=True)
        self.scheduler.add_job(
            self._watch_rules,
            trigger=IntervalTrigger(seconds=60),
            id="config_watcher",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Pulse scheduler started")

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)

    def _watch_rules(self) -> None:
        try:
            current = rules_fingerprint(RULES_PATH)
            if current != self.fingerprint:
                logger.info("Detected rules.yaml change, reloading jobs")
                self._load_and_schedule(force=True)
        except Exception as exc:
            logger.error("Failed to watch rules file: %s", exc)

    def _load_and_schedule(self, force: bool = False) -> None:
        new_fingerprint = rules_fingerprint(RULES_PATH)
        if not force and new_fingerprint == self.fingerprint:
            return

        rules = load_rules(RULES_PATH)
        timezone = ZoneInfo(rules.global_config.timezone)

        self._clear_runtime_jobs()

        for source in sorted(rules.sources, key=lambda s: s.weight, reverse=True):
            seconds = interval_to_seconds(source.fetch_interval)
            self.scheduler.add_job(
                self.run_source,
                trigger=IntervalTrigger(seconds=seconds, timezone=timezone),
                args=[source],
                id=f"source::{source.id}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        for name, policy in rules.platforms.items():
            if not policy.enabled or not policy.schedule:
                continue
            hour, minute = self._parse_schedule_hhmm(policy.schedule)
            self.scheduler.add_job(
                self.run_all_sources,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
                kwargs={"platform": name},
                id=f"platform::{name}",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        self.scheduler.add_job(
            self.cleanup_memory,
            trigger=CronTrigger(hour=3, minute=30, timezone=timezone),
            id="maintenance::cleanup",
            replace_existing=True,
            max_instances=1,
        )

        self.rules = rules
        self.fingerprint = new_fingerprint
        logger.info("Loaded %s source jobs", len(rules.sources))

    def _clear_runtime_jobs(self) -> None:
        for job in self.scheduler.get_jobs():
            if job.id == "config_watcher":
                continue
            self.scheduler.remove_job(job.id)

    @staticmethod
    def _parse_schedule_hhmm(raw: str) -> Tuple[int, int]:
        parts = raw.strip().split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid HH:MM schedule: {raw}")
        return int(parts[0]), int(parts[1])

    def status(self) -> Dict[str, Any]:
        jobs = [
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in self.scheduler.get_jobs()
        ]
        return {
            "rules_path": RULES_PATH,
            "rules_fingerprint": self.fingerprint,
            "jobs": jobs,
            "last_runs": self.last_runs,
        }

    def run_all_sources(self, platform: str = "manual") -> Dict[str, Any]:
        if not self.rules:
            raise RuntimeError("rules not loaded")

        logger.info("Running all sources for platform schedule: %s", platform)
        results = []
        for source in sorted(self.rules.sources, key=lambda s: s.weight, reverse=True):
            results.append(self.run_source(source))
        return {"platform": platform, "results": results}

    def cleanup_memory(self) -> Dict[str, Any]:
        if not self.rules:
            return {"removed": 0}

        days = self.rules.global_config.memory_retention_days
        try:
            result = post_json(
                f"{HIPPOCAMPUS_API}/cleanup?retention_days={days}",
                {},
                timeout=30,
            )
            logger.info("cleanup done (retention=%sd): %s", days, result)
            return result
        except Exception as exc:
            logger.error("cleanup failed: %s", exc)
            return {"removed": 0, "error": str(exc)}

    def run_source(self, source: SourceConfig) -> Dict[str, Any]:
        started = datetime.utcnow()
        counters = {
            "source_id": source.id,
            "scanned": 0,
            "processed": 0,
            "duplicated": 0,
            "filtered": 0,
            "failed": 0,
            "started_at": started.isoformat(),
        }

        logger.info("Heartbeat start source=%s", source.id)

        with self._run_lock:
            try:
                scan_response = post_json(
                    f"{SENTRY_API}/scan",
                    {"source_config": source.model_dump()},
                )
                items = scan_response.get("items", [])
                counters["scanned"] = len(items)

                for item in items:
                    try:
                        trace_seed = str(item.get("url_hash") or "")
                        trace_id = trace_seed[:8] if trace_seed else source.id
                        with bind_log_context(trace_id=trace_id):
                            duplicate = post_json(
                                f"{HIPPOCAMPUS_API}/check_duplicate",
                                {"url_hash": item["url_hash"]},
                            )
                            if duplicate.get("is_duplicate", False):
                                counters["duplicated"] += 1
                                continue

                            platform_strategy = {}
                            if self.rules:
                                platform_strategy = {
                                    name: policy.model_dump()
                                    for name, policy in self.rules.platforms.items()
                                    if policy.enabled
                                }

                            if not _is_high_value_signal(item):
                                counters["filtered"] += 1
                                continue

                            source_summary = str(item.get("summary") or item.get("raw_text") or "")[:240]
                            content_pack = {
                                "record_type": "topic",
                                "source_id": source.id,
                                "source_info": _source_info_from_source_id(source.id),
                                "url_hash": item.get("url_hash", ""),
                                "title": item.get("title", ""),
                                "source_url": item.get("url", ""),
                                "topic_summary": source_summary,
                                "ai_summary": "",
                                "image_url": (item.get("images") or [""])[0],
                                "image_urls": item.get("images", [])[:3],
                                "channels": list(platform_strategy.keys()) or ["twitter", "wechat_blog"],
                                "status": "待确认",
                                "trace_id": trace_id,
                            }

                            archive_result = post_json(
                                f"{ARCHIVIST_API}/archive",
                                {"content_pack": content_pack},
                            )

                            post_json(
                                f"{HIPPOCAMPUS_API}/remember",
                                {
                                    "source_id": source.id,
                                    "url_hash": item.get("url_hash", ""),
                                    "title": item.get("title", ""),
                                    "url": item.get("url", ""),
                                    "summary": source_summary,
                                    "keywords": item.get("keywords", []),
                                    "raw_text": item.get("raw_text", ""),
                                    "archive_url": archive_result.get("feishu_doc_url", ""),
                                    "image_url": (item.get("images") or [""])[0],
                                },
                            )

                            counters["processed"] += 1
                    except Exception as item_exc:
                        counters["failed"] += 1
                        logger.error("Item processing failed source=%s err=%s", source.id, item_exc)
            except Exception as exc:
                counters["failed"] += 1
                logger.error("Source run failed source=%s err=%s", source.id, exc)

        ended = datetime.utcnow()
        result = PulseRunResult(
            source_id=source.id,
            scanned=counters["scanned"],
            processed=counters["processed"],
            duplicated=counters["duplicated"],
            failed=counters["failed"],
            started_at=started,
            ended_at=ended,
        )

        serialized = result.model_dump(mode="json")
        self.last_runs[source.id] = serialized

        logger.info(
            "Heartbeat done source=%s scanned=%s processed=%s dup=%s filtered=%s failed=%s",
            source.id,
            counters["scanned"],
            counters["processed"],
            counters["duplicated"],
            counters["filtered"],
            counters["failed"],
        )
        return serialized


engine = PulseEngine()


@app.on_event("startup")
def on_startup() -> None:
    engine.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    engine.stop()


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "service": "pulse", "jobs": len(engine.scheduler.get_jobs())}


@app.get("/status")
def status() -> Dict[str, Any]:
    return engine.status()


@app.post("/reload")
def reload_rules() -> Dict[str, Any]:
    try:
        engine._load_and_schedule(force=True)
        return {"status": "reloaded", "fingerprint": engine.fingerprint}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/run_once")
def run_once(source_id: Optional[str] = None) -> Dict[str, Any]:
    if not engine.rules:
        raise HTTPException(status_code=500, detail="rules not loaded")

    sources = engine.rules.sources
    if source_id:
        sources = [s for s in sources if s.id == source_id]
        if not sources:
            raise HTTPException(status_code=404, detail=f"source {source_id} not found")

    results = [engine.run_source(source) for source in sources]
    return {"results": results}
