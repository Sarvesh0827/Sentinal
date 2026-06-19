#!/bin/bash
set -e
cd "$(dirname "$0")/.."   # always run from sentinel/ directory
export PYTHONPATH="$(pwd):$PYTHONPATH"
echo "Starting Sentinel (in-memory mode, no Docker)..."
uvicorn src.app:app --host 0.0.0.0 --port "${API_PORT:-8000}" --reload "$@"
