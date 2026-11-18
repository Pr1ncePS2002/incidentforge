#!/bin/bash
# applies the reference patch on the base commit
set -euo pipefail
cd /app
git apply --whitespace=nowarn /solution/reference.patch
