#!/usr/bin/env bash
# runs pytest from the repo root with any args; the repo's pyproject deselects stress tests and turns warnings into errors
set -e
# login shells reset PATH, so pin the venv explicitly
export PATH="/app/.venv/bin:$PATH"
cd /app
exec python -m pytest "$@"
