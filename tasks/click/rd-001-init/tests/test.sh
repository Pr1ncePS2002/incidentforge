#!/bin/bash
# runs the feature tests, then the repo suite without them.
# reward: 0 if the repo suite or a guard fails, else the share of tests/fail_to_pass.json that pass.
# guards are feature tests that already pass on base; they sit in tests/pass_to_pass.json
set -u
mkdir -p /logs/verifier
cd /app

TESTS=(tests/test_formatter_width_limits.py::test_explicit_width_used_verbatim tests/test_formatter_width_limits.py::test_fault_hardcoded_size_floor_follows_min_width tests/test_formatter_width_limits.py::test_fault_hardcoded_size_floor_raised tests/test_formatter_width_limits.py::test_fault_unset_limit_uses_default_max tests/test_formatter_width_limits.py::test_fault_unset_limit_small_terminal tests/test_formatter_width_limits.py::test_fault_zero_or_negative tests/test_formatter_width_limits.py::test_fault_zero_or_negative_context_setting tests/test_formatter_width_limits.py::test_fault_min_over_max_explicit tests/test_formatter_width_limits.py::test_fault_min_over_max_default_max tests/test_formatter_width_limits.py::test_min_equal_to_max_allowed)
GUARDS=(tests/test_formatter_width_limits.py::test_default_width_clamped_to_80 tests/test_formatter_width_limits.py::test_default_floor_is_50 tests/test_formatter_width_limits.py::test_small_max_width_without_min_keeps_old_floor tests/test_formatter_width_limits.py::test_help_still_renders)
mkdir -p "$(dirname tests/test_formatter_width_limits.py)" && cp /tests/feature/tests/test_formatter_width_limits.py tests/test_formatter_width_limits.py
feature=0
run_tests -q -p no:cacheprovider -rA tests/test_formatter_width_limits.py > /logs/verifier/feature_tests.log 2>&1 || feature=1

# the repo suite must pass on its own, so the feature tests are taken out again
rm -f tests/test_formatter_width_limits.py
bash -c 'run_tests -q' > /logs/verifier/repo_suite.log 2>&1
suite=$?

status() { awk -v id="$1" '($1=="PASSED"||$1=="FAILED"||$1=="ERROR") { n=$2; sub(/\[.*$/, "", n); if (n==id) { if ($1=="PASSED") p=1; else f=1 } } END { print (p && !f) ? "passed" : "failed" }' /logs/verifier/feature_tests.log; }
passed=0
results=()
for t in ${TESTS[@]+"${TESTS[@]}"}; do
  r=$(status "$t")
  results+=("$r")
  [ "$r" = passed ] && passed=$((passed + 1))
done
guards_ok=1
guard_results=()
for t in ${GUARDS[@]+"${GUARDS[@]}"}; do
  g=$(status "$t")
  guard_results+=("$g")
  [ "$g" = passed ] || guards_ok=0
done
total=${#TESTS[@]}
# no test ids could be read from the feature files: fall back to the run's exit code
if [ "$total" -eq 0 ] && [ ${#GUARDS[@]} -eq 0 ]; then total=1; passed=$([ "$feature" -eq 0 ] && echo 1 || echo 0); fi
if [ "$total" -eq 0 ]; then total=1; fi
s=$([ "$suite" -eq 0 ] && [ "$guards_ok" -eq 1 ] && echo 1 || echo 0)
f=$(awk -v p="$passed" -v t="$total" 'BEGIN { printf "%.4g", p / t }')
r=$([ "$s" -eq 1 ] && echo "$f" || echo 0)
st() { [ "$1" = 1 ] && echo passed || echo failed; }
fs=$([ "$passed" -eq "$total" ] && echo passed || echo failed)
g_ok=0
for g in ${guard_results[@]+"${guard_results[@]}"}; do [ "$g" = passed ] && g_ok=$((g_ok + 1)); done
ok=$(( passed + g_ok + s + ($passed == $total ? 1 : 0) ))
n=$(( ${#results[@]} + ${#guard_results[@]} + 2 ))
now=$(date +%s)000
{
  printf '{"results": {"tool": {"name": "incidentforge"},\n'
  printf '  "summary": {"tests": %d, "passed": %d, "failed": %d, "pending": 0, "skipped": 0, ' "$n" "$ok" "$((n - ok))"
  printf '"other": 0, "start": %s, "stop": %s},\n  "tests": [\n' "$now" "$now"
  printf '    {"name": "feature_tests", "status": "%s", "duration": 0},\n' "$fs"
  printf '    {"name": "repo_suite", "status": "%s", "duration": 0}' "$(st "$s")"
  i=0
  for t in ${TESTS[@]+"${TESTS[@]}"}; do
    printf ',\n    {"name": "%s", "status": "%s", "duration": 0}' "$t" "${results[$i]}"
    i=$((i + 1))
  done
  i=0
  for t in ${GUARDS[@]+"${GUARDS[@]}"}; do
    printf ',\n    {"name": "%s", "status": "%s", "duration": 0}' "$t" "${guard_results[$i]}"
    i=$((i + 1))
  done
  printf ']}}\n'
} > /logs/verifier/ctrf.json
echo "{\"reward\": $r, \"feature_tests\": $f, \"repo_suite\": $s}" > /logs/verifier/reward.json
echo "feature_tests=$passed/$total repo_suite=$s reward=$r"
