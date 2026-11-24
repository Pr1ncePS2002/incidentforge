#!/usr/bin/env bash
# runs the guide's nop/oracle validation matrix on every task in a tasks dir and writes matrix.json + verifier logs
# usage: scripts/validation_matrix.sh <tasks_dir> <out_dir> [jobs_dir]
set -euo pipefail

tasks_dir=${1:?tasks dir, e.g. tasks/click}
out_dir=${2:?out dir, e.g. reports/validation/click}
jobs_dir=${3:-work/matrix}
harbor_cmd=${HARBOR:-harbor}

mkdir -p "$out_dir/matrix" "$jobs_dir"
rows=$(mktemp)
trap 'rm -f "$rows"' EXIT

for task in "$tasks_dir"/*/; do
  task=${task%/}
  [ -f "$task/task.toml" ] || continue
  id=$(basename "$task")
  for agent in nop oracle; do
    job="$jobs_dir/$id-$agent"
    # a fresh job dir per run so the newest trial is the only one we read
    rm -rf "$job"
    t0=$(date +%s)
    "$harbor_cmd" run -p "$task" -a "$agent" -k 1 -o "$job" --no-delete -y >"$jobs_dir/$id-$agent.log" 2>&1 || true
    secs=$(( $(date +%s) - t0 ))
    verifier=$(find "$job" -type d -name verifier -path "*${id}__*" | head -1)
    dest="$out_dir/matrix/$id/$agent"
    rm -rf "$dest"; mkdir -p "$dest"
    if [ -n "$verifier" ]; then
      cp "$verifier"/*.json "$verifier"/*.log "$verifier"/*.txt "$dest"/ 2>/dev/null || true
    fi
    reward=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("reward"))' "$dest/reward.json" 2>/dev/null || echo null)
    echo "$id $agent $reward $secs" | tee -a "$rows"
  done
done

python3 - "$rows" "$out_dir/matrix.json" "$("$harbor_cmd" --version 2>/dev/null | tail -1)" <<'PY'
import json, sys
rows, out, version = sys.argv[1], sys.argv[2], sys.argv[3]
tasks: dict[str, dict] = {}
for line in open(rows):
    tid, agent, reward, secs = line.split()
    r = None if reward in ("None", "null") else float(reward)
    tasks.setdefault(tid, {"id": tid})[agent] = {"reward": r, "duration_sec": int(secs)}
expected = {"nop": 0.0, "oracle": 1.0}
for t in tasks.values():
    t["ok"] = all(t.get(a, {}).get("reward") == v for a, v in expected.items())
summary = {
    "harbor_version": version,
    "expected": expected,
    "tasks": sorted(tasks.values(), key=lambda t: t["id"]),
    "all_ok": all(t["ok"] for t in tasks.values()),
}
json.dump(summary, open(out, "w"), indent=2)
print(f"{sum(t['ok'] for t in tasks.values())}/{len(tasks)} tasks match nop=0.0 oracle=1.0 -> {out}")
PY
