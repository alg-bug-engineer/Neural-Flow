# Neural-Flow

Neural-Flow is a 6-service microservice system based on the PRD in `docs/prd.md`.

Services:
- `pulse`: central scheduler and workflow orchestrator
- `sentry`: RSS scanner and cleaner
- `hippocampus`: SQLite memory and deduplication
- `cortex`: content generation (fallback + Kimi API)
- `iris`: image prompt rendering (fallback + Jimeng API)
- `archivist`: Markdown archive + Feishu Doc/Bitable/Group message integration

## Quick Start

1. Prepare local credentials and environment files:

```bash
cp config/feishu_config.example.json config/feishu_config.json
cp .env.example .env
```

2. Fill your own keys in `config/feishu_config.json` and/or `.env`.

3. Start all services:

```bash
docker compose up --build -d
```

4. Check health:

```bash
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health
curl http://localhost:8005/health
curl http://localhost:8006/health
```

5. Trigger one full heartbeat manually:

```bash
curl -X POST "http://localhost:8001/run_once"
```

6. Inspect dashboard data:

```bash
curl "http://localhost:8006/dashboard?limit=10"
```

## Rules Configuration

- Runtime rules live in `config/rules.yaml`.
- `pulse` watches this file and auto-reloads jobs after changes.
- Default setup uses local sample XML files in `data/` for offline testing.

## Production Credentials

- Default credential file: `config/feishu_config.json`
- Template file: `config/feishu_config.example.json`
- Override path with env: `FEISHU_CONFIG_PATH`
- Supported fields:
  - `app_id`, `app_secret`
  - `bitable_app_token`, `bitable_table_id`
  - `root_folder_token`, `receive_id`
  - `kimi_api_key`
  - `jimeng_ak`, `jimeng_sk`

## Data Output

- Memory DB: `data/memory.db`
- Archive DB: `data/archive.db`
- Markdown docs: `data/archive/YYYY-MM-DD/*.md`
- Unified logs DB: `data/system_logs.db`

## Unified Logging / Trace

- Every service now writes structured logs into one SQLite DB (`LOG_DB_PATH`).
- Trace propagation uses headers: `x-trace-id`, `x-request-id`.
- Query logs from any service:

```bash
curl "http://localhost:8006/logs?limit=100"
curl "http://localhost:8006/logs/trace/topic1234-twitter?limit=200"
curl "http://localhost:8006/logs?service=cortex&level=ERROR&limit=50"
```

## Local Test

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Live Integration Test

Run live Kimi + Jimeng tests:

```bash
RUN_LIVE_INTEGRATION=1 pytest -q tests/test_kimi_api.py tests/test_jimeng_api.py
```

Run Feishu integration test (will create online artifacts):

```bash
RUN_FEISHU_INTEGRATION=1 pytest -q tests/test_feishu_integration.py
```
