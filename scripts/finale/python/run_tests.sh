#!/usr/bin/env bash
# runs pytest from the repo root with any args; login shells reset PATH so the venv is pinned
set -e
export PATH="/app/.venv/bin:$PATH"
cd /app
exec python -m pytest "$@"
