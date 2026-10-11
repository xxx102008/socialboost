#!/usr/bin/env bash
set -e
python -m playwright install chromium
python -m playwright install-deps chromium 2>/dev/null || true
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
