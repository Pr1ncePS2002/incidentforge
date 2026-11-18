#!/bin/bash
# runs feature tests, then the repo suite without them; reward 1 only when both pass
set -u
mkdir -p /logs/verifier
cd /app/backend

mkdir -p "$(dirname tests/test_forge_scoped_names.py)" && cp /tests/feature/tests/test_forge_scoped_names.py tests/test_forge_scoped_names.py
run_tests -q -p no:cacheprovider tests/test_forge_scoped_names.py > /logs/verifier/feature_tests.log 2>&1
feature=$?

# the repo suite must pass on its own, so the feature tests are taken out again
rm -f tests/test_forge_scoped_names.py
bash -c 'run_tests -q tests/' > /logs/verifier/repo_suite.log 2>&1
suite=$?

f=$([ "$feature" -eq 0 ] && echo 1 || echo 0)
s=$([ "$suite" -eq 0 ] && echo 1 || echo 0)
r=$([ "$f" -eq 1 ] && [ "$s" -eq 1 ] && echo 1 || echo 0)
st() { [ "$1" -eq 1 ] && echo passed || echo failed; }
now=$(date +%s)000
cat > /logs/verifier/ctrf.json <<EOF
{"results": {"tool": {"name": "incidentforge"},
  "summary": {"tests": 2, "passed": $((f + s)), "failed": $((2 - f - s)), "pending": 0, "skipped": 0,
    "other": 0, "start": $now, "stop": $now},
  "tests": [
    {"name": "feature_tests", "status": "$(st $f)", "duration": 0},
    {"name": "repo_suite", "status": "$(st $s)", "duration": 0}]}}
EOF
echo "{\"reward\": $r, \"feature_tests\": $f, \"repo_suite\": $s}" > /logs/verifier/reward.json
echo "feature_tests=$f repo_suite=$s reward=$r"
