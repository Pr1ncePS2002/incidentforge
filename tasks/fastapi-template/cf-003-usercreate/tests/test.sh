#!/bin/bash
# runs the feature tests, then the repo suite without them.
# reward: 0 if the repo suite or a guard fails, else the share of tests/fail_to_pass.json that pass.
# guards are feature tests that already pass on base; they sit in tests/pass_to_pass.json
set -u
mkdir -p /logs/verifier
cd /app/backend

TESTS=(tests/test_forge_usercreate_identity_password.py::test_fault_dependent_bound_email_local_part tests/test_forge_usercreate_identity_password.py::test_fault_dependent_bound_full_name tests/test_forge_usercreate_identity_password.py::test_fault_dependent_bound_both_reported_in_one_error tests/test_forge_usercreate_identity_password.py::test_fault_dependent_bound_signup_payload_conversion tests/test_forge_usercreate_identity_password.py::test_fault_boundary_equal_password_equals_local_part tests/test_forge_usercreate_identity_password.py::test_fault_boundary_equal_password_equals_full_name tests/test_forge_usercreate_identity_password.py::test_fault_boundary_equal_three_char_local_part_is_checked)
GUARDS=(tests/test_forge_usercreate_identity_password.py::test_valid_user_still_validates tests/test_forge_usercreate_identity_password.py::test_valid_user_without_full_name tests/test_forge_usercreate_identity_password.py::test_superuser_payload_still_valid tests/test_forge_usercreate_identity_password.py::test_two_char_local_part_is_not_checked tests/test_forge_usercreate_identity_password.py::test_two_char_full_name_is_not_checked tests/test_forge_usercreate_identity_password.py::test_password_length_limit_unchanged)
mkdir -p "$(dirname tests/test_forge_usercreate_identity_password.py)" && cp /tests/feature/tests/test_forge_usercreate_identity_password.py tests/test_forge_usercreate_identity_password.py
feature=0
run_tests -q -p no:cacheprovider -rA tests/test_forge_usercreate_identity_password.py > /logs/verifier/feature_tests.log 2>&1 || feature=1

# the repo suite must pass on its own, so the feature tests are taken out again
rm -f tests/test_forge_usercreate_identity_password.py
bash -c 'run_tests -q tests/' > /logs/verifier/repo_suite.log 2>&1
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
