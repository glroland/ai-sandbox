#!/bin/bash
# Submit the hello world evaluation job and wait for the pass/fail result
set -e
source "$(dirname "$0")/common.sh"
: "${MODEL_URL:?MODEL_URL is required (see env.example)}"
: "${MODEL_NAME:?MODEL_NAME is required (see env.example)}"

PROVIDER_ID=${PROVIDER_ID:-$("$SCRIPT_DIR/register-provider.sh")}

JOB=$(jq --arg url "$MODEL_URL" --arg name "$MODEL_NAME" --arg pid "$PROVIDER_ID" --arg secret "$MODEL_SECRET" '
    .model.url = $url
    | .model.name = $name
    | .benchmarks[].provider_id = $pid
    | if $secret != "" then .model.auth.secret_ref = $secret else . end
    | if env.EXPERIMENT_NAME then .experiment.name = env.EXPERIMENT_NAME else . end' "$EVAL_DIR/job.json")

JOB_ID=$(evalhub POST "/jobs" -d "$JOB" | jq -r .resource.id)
echo "Submitted job $JOB_ID"

while true; do
    RESULT=$(evalhub GET "/jobs/$JOB_ID")
    STATE=$(jq -r .status.state <<< "$RESULT")
    echo "  state: $STATE"
    case "$STATE" in
        completed|failed|cancelled|partially_failed) break ;;
    esac
    sleep 5
done

jq '{state: .status.state, message: .status.message.message, test: .results.test, benchmarks: [.results.benchmarks[]? | {id, metrics, test}]}' <<< "$RESULT"

if [ "$(jq -r '.results.test.pass' <<< "$RESULT")" = "true" ]; then
    echo "PASS: all promptfoo assertions passed"
else
    echo "FAIL: see job $JOB_ID for details" >&2
    exit 1
fi
