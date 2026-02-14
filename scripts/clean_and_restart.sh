#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[clean-restart] stopping services"
docker compose down --remove-orphans >/dev/null 2>&1 || true

echo "[clean-restart] clearing records and cache files"
rm -f data/memory.db data/archive.db
rm -rf data/archive
mkdir -p data/archive

echo "[clean-restart] starting services"
docker compose up -d

echo "[clean-restart] done"
