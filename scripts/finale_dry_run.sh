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
# overridable so tests can run the script without docker or a generator backend
docker_cmd=${FINALE_DOCKER:-docker}
forge_cmd=${FINALE_FORGE:-uv run forge}
poll=${FINALE_POLL_SEC:-5}

root=$(cd "$(dirname "$0")/.." && pwd)
targets="$root/src/incidentforge/targets"
target_yaml="$targets/$name.yaml"
env_dir="$targets/env/$name"
image="incidentforge/$name-env:dry"
log_dir="$root/work/finale/$name"
mkdir -p "$log_dir"
touch "$log_dir/.start"

case "$lang" in
  python) default_test_cmd="run_tests -q" ;;
  go) default_test_cmd="run_tests" ;;
  *) echo "language must be python or go" >&2; exit 2 ;;
esac

declare -a steps=()
start_all=$(date +%s)
first_accept=""
step() {
  # runs one named step, logs its output, records elapsed seconds; stops the run on failure
  local label=$1; shift
  local t0
  t0=$(date +%s)
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
  if [ -n "$first_accept" ]; then echo "  time to first accepted task: ${first_accept}s"; fi
  echo "  total: $(( $(date +%s) - start_all ))s · logs: $log_dir"
}

scaffold() {
  # existing env dir and target yaml are kept so hand fixes made on the day survive a re-run
  if [ ! -d "$env_dir" ]; then
    mkdir -p "$env_dir"
    cp "$root/scripts/finale/$lang/Dockerfile" "$root/scripts/finale/$lang/run_tests.sh" "$env_dir/"
  fi
  sed -i.bak -e "s|^ARG REPO_URL=.*|ARG REPO_URL=$repo_url|" -e "s|^ARG REPO_COMMIT=.*|ARG REPO_COMMIT=$commit|" \
    "$env_dir/Dockerfile" && rm -f "$env_dir/Dockerfile.bak"
  if [ -f "$target_yaml" ]; then
    sed -i.bak -e "s|^repo_url:.*|repo_url: $repo_url|" -e "s|^commit:.*|commit: $commit|" "$target_yaml" \
      && rm -f "$target_yaml.bak"
  else
    cat >"$target_yaml" <<EOF
name: $name
repo_url: $repo_url
commit: $commit
language: $lang
env_template: env/$name
test_command: $default_test_cmd
source_root: .
EOF
  fi
  cat "$target_yaml"
}

test_cmd() {
  # the suite step uses whatever test_command the yaml holds now, including hand edits
  local cmd
  cmd=$(sed -n 's/^test_command: *//p' "$target_yaml" | head -n 1)
  cmd=${cmd%\"}; cmd=${cmd#\"}; cmd=${cmd%\'}; cmd=${cmd#\'}
  echo "${cmd:-$default_test_cmd}"
}

build() { $docker_cmd build -t "$image" "$env_dir"; }
suite() { $docker_cmd run --rm "$image" bash -lc "$(test_cmd)"; }

check_accept() {
  if [ -z "$first_accept" ] && [ -d "$root/reports/validation" ] \
    && find "$root/reports/validation" -path "*$name*" -name '*.json' -newer "$log_dir/.start" \
      -exec grep -l '"accepted": *true' {} + 2>/dev/null | grep -q .; then
    first_accept=$(( $(date +%s) - start_all ))
    echo "first accepted task after ${first_accept}s"
  fi
}

forge() {
  # watch reports while forge runs so the first accepted task is timed apart from the whole run
  (cd "$root" && $forge_cmd run --target "$name" --n "$n" --backend "$backend") &
  local pid=$! rc=0
  while kill -0 "$pid" 2>/dev/null; do
    check_accept
    sleep "$poll"
  done
  wait "$pid" || rc=$?
  # a report written just before exit lands between polls, so look once more
  check_accept
  return "$rc"
}

validate() { (cd "$root" && $forge_cmd validate "tasks/$name"); }

step scaffold scaffold
step build build
step repo-suite suite
step forge-run forge
step validate validate
summary
