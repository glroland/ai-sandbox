#!/usr/bin/env bash
#
# Runs all test-*.sh scripts in this directory and tallies pass/fail counts.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS_COUNT=0
FAIL_COUNT=0

shopt -s nullglob
TEST_SCRIPTS=("${SCRIPT_DIR}"/test-*.sh)
shopt -u nullglob

if [[ ${#TEST_SCRIPTS[@]} -eq 0 ]]; then
  echo "No test-*.sh scripts found in ${SCRIPT_DIR}"
  exit 1
fi

for TEST_SCRIPT in "${TEST_SCRIPTS[@]}"; do
  bash "${TEST_SCRIPT}"
  if [[ $? -eq 0 ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
done

echo "----------------------------------------"
echo "Results: ${PASS_COUNT} passed, ${FAIL_COUNT} failed (of $((PASS_COUNT + FAIL_COUNT)) total)"

[[ ${FAIL_COUNT} -eq 0 ]]
