#!/usr/bin/env bash
# scaffold a new target from a repo url + commit, prove its suite runs in docker, then forge tasks and time each step
# usage: scripts/finale_dry_run.sh <repo_url> <commit> <python|go> [name] [n]
set -euo pipefail

repo_url=${1:?repo url}
commit=${2:?commit sha}
lang=${3:?language: python or go}
name=${4:-$(basename "$repo_url" .git | tr '[:upper:]_' '[:lower:]-')}
n=${5:-3}
backend=${FORGE_BACKEND:-claude-code}

root=$(cd "$(dirname "$0")/.." && pwd)
targets="$root/src/incidentforge/targets"
env_dir="$targets/env/$name"
image="incidentforge/$name-env:dry"
log_dir="$root/work/finale/$name"
mkdir -p "$log_dir"
touch "$log_dir/.start"

case "$lang" in
  python) test_cmd="run_tests -q" ;;
  go) test_cmd="run_tests" ;;
  *) echo "language must be python or go" >&2; exit 2 ;;
esac

declare -a steps=()
start_all=$(date +%s)
first_accept=""
step() {
  # runs one named step, logs its output, records elapsed seconds; stops the run on failure
  local label=$1; shift
  local t0=$(date +%s)
  echo "==> $label"
  if "$@" >"$log_dir/$label.log" 2>&1; then
    steps+=("$label $(( $(date +%s) - t0 ))s ok")
  else
    steps+=("$label $(( $(date +%s) - t0 ))s FAILED (see $log_dir/$label.log)")
    summary; exit 1
  fi
}
summary() {
  echo; echo "dry run: $name ($lang) @ ${commit:0:12}"
  printf '  %s\n' "${steps[@]}"
  [ -n "$first_accept" ] && echo "  time to first accepted task: ${first_accept}s"
  echo "  total: $(( $(date +%s) - start_all ))s · logs: $log_dir"
}

scaffold() {
  # an existing env template is kept so hand fixes made during the event are not overwritten
  if [ ! -d "$env_dir" ]; then
    mkdir -p "$env_dir"
    cp "$root/scripts/finale/$lang/Dockerfile" "$root/scripts/finale/$lang/run_tests.sh" "$env_dir/"
  fi
  sed -i.bak -e "s|^ARG REPO_URL=.*|ARG REPO_URL=$repo_url|" -e "s|^ARG REPO_COMMIT=.*|ARG REPO_COMMIT=$commit|" \
    "$env_dir/Dockerfile" && rm -f "$env_dir/Dockerfile.bak"
  cat >"$targets/$name.yaml" <<EOF
name: $name
repo_url: $repo_url
commit: $commit
language: $lang
env_template: env/$name
test_command: $test_cmd
source_root: .
EOF
  cat "$targets/$name.yaml"
}

build() { docker build -t "$image" "$env_dir"; }
suite() { docker run --rm "$image" bash -lc "$test_cmd"; }

forge() {
  # watch the tasks dir so the first accepted task is timed separately from the whole run
  local t0=$(date +%s)
  (cd "$root" && uv run forge run --target "$name" --n "$n" --backend "$backend") &
  local pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if [ -z "$first_accept" ] && find "$root/reports/validation" -path "*$name*" -name '*.json' \
        -newer "$log_dir/.start" -exec grep -l '"accepted": *true' {} + 2>/dev/null | grep -q .; then
      first_accept=$(( $(date +%s) - start_all ))
      echo "first accepted task after ${first_accept}s (forge step $(( $(date +%s) - t0 ))s)"
    fi
    sleep 5
  done
  wait "$pid"
}

validate() { (cd "$root" && uv run forge validate "tasks/$name"); }

step scaffold scaffold
step build build
step repo-suite suite
step forge-run forge
step validate validate
summary
