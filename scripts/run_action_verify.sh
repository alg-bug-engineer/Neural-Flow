#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PULSE_API="${PULSE_API:-http://localhost:8001}"
SENTRY_API="${SENTRY_API:-http://localhost:8002}"
HIPPO_API="${HIPPO_API:-http://localhost:8003}"
CORTEX_API="${CORTEX_API:-http://localhost:8004}"
IRIS_API="${IRIS_API:-http://localhost:8005}"
ARCHIVIST_API="${ARCHIVIST_API:-http://localhost:8006}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-180}"
RUN_ACTION_BUILD="${RUN_ACTION_BUILD:-0}"

log() {
  printf '[run-action] %s\n' "$*"
}

wait_health() {
  local url="$1"
  local name="$2"
  local max_try=$((HEALTH_TIMEOUT_SECONDS / 2))
  local i

  for ((i=1; i<=max_try; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "health ok: ${name} (${url})"
      return 0
    fi
    sleep 2
  done

  log "health timeout: ${name} (${url})"
  return 1
}

log "resetting compose stack"
docker compose down --remove-orphans >/dev/null 2>&1 || true

if [[ "${RUN_ACTION_BUILD}" == "1" ]]; then
  log "building docker images"
  export DOCKER_BUILDKIT=0
  export COMPOSE_DOCKER_CLI_BUILD=0
  docker compose build
fi

log "starting docker services"
if [[ "${RUN_ACTION_BUILD}" == "1" ]]; then
  docker compose up -d --no-build
else
  docker compose up -d
fi

wait_health "${PULSE_API}/health" "pulse"
wait_health "${SENTRY_API}/health" "sentry"
wait_health "${HIPPO_API}/health" "hippocampus"
wait_health "${CORTEX_API}/health" "cortex"
wait_health "${IRIS_API}/health" "iris"
wait_health "${ARCHIVIST_API}/health" "archivist"

log "clearing memory duplicates for reproducible validation"
curl -fsS -X POST "${HIPPO_API}/cleanup?retention_days=0" -H "Content-Type: application/json" -d '{}' >/dev/null

log "triggering pulse run_once"
RUN_ONCE_RESP="$(curl -fsS -X POST "${PULSE_API}/run_once")"
export RUN_ONCE_RESP
python - <<'PY'
import json
import os

raw = os.environ.get("RUN_ONCE_RESP", "{}")
resp = json.loads(raw)
results = resp.get("results", [])
scanned = sum(int(item.get("scanned", 0)) for item in results)
processed = sum(int(item.get("processed", 0)) for item in results)
failed = sum(int(item.get("failed", 0)) for item in results)
print(f"[run-action] run_once summary: sources={len(results)} scanned={scanned} processed={processed} failed={failed}")
PY

fetch_dashboard() {
  curl -fsS "${ARCHIVIST_API}/dashboard?limit=100"
}

log "loading dashboard after run_once"
DASH_JSON="$(fetch_dashboard)"
export DASH_JSON

TOPIC_LINE="$(python - <<'PY'
import json
import os

items = json.loads(os.environ.get("DASH_JSON", "{}")).get("items", [])
for it in items:
    if str(it.get("record_type", "")).strip() == "topic":
        title = str(it.get("title", "")).strip()
        summary = str(it.get("ai_summary") or it.get("topic_summary") or "").strip()[:180]
        source_info = str(it.get("source_info", "")).strip()
        trace = str(it.get("trace_id", "")).strip()
        print("\t".join([title, summary, trace, source_info]))
        break
PY
)"

if [[ -z "${TOPIC_LINE}" ]]; then
  TRACE_ID="manual-$(date +%s)"
  TOPIC_TITLE="Run Action 验证选题 ${TRACE_ID}"
  TOPIC_SUMMARY="用于验证飞书回调触发分平台草稿与本地/飞书层级一致性。"
  TOPIC_SOURCE="run-action-manual"
  log "no topic found from run_once, creating one manually"
  curl -fsS -X POST "${ARCHIVIST_API}/archive" \
    -H "Content-Type: application/json" \
    -d "{\"content_pack\":{\"record_type\":\"topic\",\"source_id\":\"run_action\",\"source_info\":\"${TOPIC_SOURCE}\",\"url_hash\":\"${TRACE_ID}\",\"trace_id\":\"${TRACE_ID}\",\"title\":\"${TOPIC_TITLE}\",\"source_url\":\"https://example.com/run-action\",\"topic_summary\":\"${TOPIC_SUMMARY}\",\"channels\":[\"twitter\",\"zhihu\"],\"status\":\"待确认\"}}" >/dev/null
else
  IFS=$'\t' read -r TOPIC_TITLE TOPIC_SUMMARY TRACE_ID TOPIC_SOURCE <<<"${TOPIC_LINE}"
  if [[ -z "${TRACE_ID}" ]]; then
    TRACE_ID="manual-$(date +%s)"
  fi
  if [[ -z "${TOPIC_SOURCE:-}" ]]; then
    TOPIC_SOURCE="run-action-topic"
  fi
fi

log "using topic trace_id=${TRACE_ID}"

CALLBACK_PAYLOAD="$(cat <<JSON
{
  "event": {
    "record": {
      "fields": {
        "原始标题": "${TOPIC_TITLE}",
        "摘要": "${TOPIC_SUMMARY}",
        "来源": "${TOPIC_SOURCE}",
        "状态": "已确认",
        "发布平台": ["Twitter", "知乎"],
        "Trace ID": "${TRACE_ID}",
        "来源链接": "https://example.com/run-action"
      }
    }
  }
}
JSON
)"

log "triggering feishu callback for platform drafts"
CALLBACK_RESP="$(curl -fsS -X POST "${ARCHIVIST_API}/feishu/callback" -H "Content-Type: application/json" -d "${CALLBACK_PAYLOAD}")"
export CALLBACK_RESP
python - <<'PY'
import json
import os

resp = json.loads(os.environ.get("CALLBACK_RESP", "{}"))
print(f"[run-action] callback result: status={resp.get('status')} generated={resp.get('generated')}")
for item in resp.get("results", []):
    print(f"[run-action] draft: platform={item.get('platform')} status={item.get('status')} url={item.get('doc_url', '')}")
PY

log "validating dashboard records and archive directory"
POST_DASH_JSON="$(fetch_dashboard)"
export POST_DASH_JSON TRACE_ID ROOT_DIR
python - <<'PY'
import json
import os
from datetime import datetime
from pathlib import Path

trace_id = os.environ["TRACE_ID"]
items = json.loads(os.environ.get("POST_DASH_JSON", "{}")).get("items", [])

topic_ok = False
draft_count = 0
drive_urls = []
for it in items:
    tid = str(it.get("trace_id", ""))
    rtype = str(it.get("record_type", ""))
    if tid == trace_id and rtype == "topic":
        topic_ok = True
        drive_urls.append(str(it.get("drive_doc_url", "")))
    if tid.startswith(trace_id + "-") and rtype == "draft":
        draft_count += 1
        drive_urls.append(str(it.get("drive_doc_url", "")))

if not topic_ok:
    raise SystemExit("[run-action] validation failed: topic record not found")
if draft_count < 2:
    raise SystemExit(f"[run-action] validation failed: expected >=2 drafts, got {draft_count}")

root = Path(os.environ["ROOT_DIR"]) / "data" / "archive" / datetime.now().strftime("%Y-%m-%d")
topic_dir = root / "topic_pool"
draft_dir = root / "draft_pool"
if not topic_dir.exists():
    raise SystemExit(f"[run-action] validation failed: missing {topic_dir}")
if not draft_dir.exists():
    raise SystemExit(f"[run-action] validation failed: missing {draft_dir}")
if not any(topic_dir.glob("*.md")):
    raise SystemExit(f"[run-action] validation failed: no topic markdown in {topic_dir}")
if not any(draft_dir.glob("*.md")):
    raise SystemExit(f"[run-action] validation failed: no draft markdown in {draft_dir}")

non_empty_drive = [u for u in drive_urls if u]
if non_empty_drive:
    if not all(u.startswith("https://feishu.cn/docx/") for u in non_empty_drive):
        raise SystemExit("[run-action] validation failed: found non-drive doc url in drive_doc_url field")
    print(f"[run-action] drive url check: ok ({len(non_empty_drive)} records)")
else:
    print("[run-action] drive url check: skipped (feishu doc not configured or unavailable)")

print(f"[run-action] validation passed: trace_id={trace_id}, drafts={draft_count}")
PY

log "run action completed successfully"
