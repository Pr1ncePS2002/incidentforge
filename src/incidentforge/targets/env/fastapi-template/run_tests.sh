#!/usr/bin/env bash
# starts postgres if needed, migrates, then runs pytest from the backend dir with any args
set -e
pg_ctlcluster "$(ls /etc/postgresql)" main start 2>/dev/null || true
for i in $(seq 1 30); do runuser -u postgres -- pg_isready -q && break; sleep 1; done
cd /app/backend
alembic upgrade head >/dev/null
python app/initial_data.py >/dev/null
exec python -m pytest "$@"
