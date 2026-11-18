#!/usr/bin/env bash
# runs go test from the repo root; with no args the whole module is tested
set -e
export PATH="/usr/local/go/bin:/go/bin:$PATH"
cd /app
if [ "$#" -eq 0 ]; then set -- ./...; fi
exec go test -count=1 "$@"
