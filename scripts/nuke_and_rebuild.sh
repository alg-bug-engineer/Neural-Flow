#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[nuke-rebuild] removing containers and networks"
docker compose down --remove-orphans --volumes >/dev/null 2>&1 || true

echo "[nuke-rebuild] removing local service images"
for svc in pulse sentry hippocampus cortex iris archivist; do
  docker image rm -f "neural-flow-${svc}:latest" >/dev/null 2>&1 || true
done

echo "[nuke-rebuild] clearing records"
rm -f data/memory.db data/archive.db
rm -rf data/archive
mkdir -p data/archive

echo "[nuke-rebuild] rebuilding and starting"
docker compose up --build -d

echo "[nuke-rebuild] done"
