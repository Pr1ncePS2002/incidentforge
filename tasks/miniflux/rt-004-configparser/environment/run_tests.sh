#!/usr/bin/env bash
# runs go test from the repo root with any args; login shells reset PATH, so pin the toolchain
set -e
export PATH="/usr/local/go/bin:/go/bin:$PATH" GOTOOLCHAIN=local CGO_ENABLED=0 GOFLAGS=-mod=readonly GOPROXY=off
cd /app
exec go test -count=1 "$@"
