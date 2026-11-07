#!/bin/bash
# Run the hello world evaluation locally with promptfoo, straight against the model.
# No EvalHub, no OpenShift — just the same prompts/tests/model from job.json.
set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROMPTFOO_VERSION=0.123.1

command -v npx >/dev/null || { echo "npx (Node.js) is required." >&2; exit 1; }

MODEL_URL=$(jq -r '.model.url' "$SCRIPT_DIR/job.json")
MODEL_NAME=$(jq -r '.model.name' "$SCRIPT_DIR/job.json")
THRESHOLD=$(jq -r '.pass_criteria.threshold' "$SCRIPT_DIR/job.json")

if [ -z "$MODEL_API_KEY" ]; then
    read -r -s -p "Model API key for $MODEL_NAME (leave blank if none): " MODEL_API_KEY
    echo
fi

WORKDIR=$(mktemp -d)
CONFIG="$WORKDIR/config.json"
OUTPUT="$SCRIPT_DIR/.eval-local.json"
trap 'rm -rf "$WORKDIR"' EXIT

jq --arg url "$MODEL_URL/v1" --arg name "$MODEL_NAME" --arg key "${MODEL_API_KEY:-not-required}" \
    '.benchmarks[0].parameters + {providers: [{id: ("openai:chat:" + $name), config: {apiBaseUrl: $url, apiKey: $key}}]}' \
    "$SCRIPT_DIR/job.json" > "$CONFIG"

npx --yes "promptfoo@$PROMPTFOO_VERSION" eval -c "$CONFIG" -o "$OUTPUT" --no-cache --no-progress-bar -j 4

SUCCESSES=$(jq '.results.stats.successes' "$OUTPUT")
FAILURES=$(jq '.results.stats.failures' "$OUTPUT")
ERRORS=$(jq '.results.stats.errors' "$OUTPUT")
PASS_RATE=$(jq -n --argjson s "$SUCCESSES" --argjson f "$FAILURES" --argjson e "$ERRORS" '$s / ($s + $f + $e)')

echo "{\"pass_rate\": $PASS_RATE, \"threshold\": $THRESHOLD, \"n_passed\": $SUCCESSES, \"n_failed\": $FAILURES, \"n_errors\": $ERRORS}"

if [ "$(jq -n --argjson p "$PASS_RATE" --argjson t "$THRESHOLD" '$p >= $t')" = "true" ]; then
    echo "PASS: all promptfoo assertions passed"
else
    echo "FAIL: see $OUTPUT for details" >&2
    exit 1
fi
