#!/usr/bin/env sh
set -eu

python - <<'PY'
import os

from core.migrations import run_upgrade

shared = os.environ.get("DATABASE_URL_SHARED")
per_env = os.environ.get("DATABASE_URL_PER_ENV")

if shared:
    run_upgrade("shared", shared)

if per_env:
    run_upgrade("per_env", per_env)
PY

exec uvicorn core.api.main:app --host 0.0.0.0 --port 8080
