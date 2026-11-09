#!/bin/bash
# Submit an evaluation job (default: the hello world job.json) and wait for the pass/fail result.
# Usage: ./run.sh [job-file.json]
set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
JOB_FILE=${1:-$SCRIPT_DIR/job.json}

[ -f "$SCRIPT_DIR/.evalhub.env" ] || { echo "Run ./install.sh first." >&2; exit 1; }
source "$SCRIPT_DIR/.evalhub.env"

EVALHUB_URL="https://${EVALHUB_HOST}"
EVALHUB_TOKEN=${EVALHUB_TOKEN:-$(oc whoami -t)}
AUTH=(-H "Authorization: Bearer $EVALHUB_TOKEN" -H "X-Tenant: $EVALHUB_TENANT")
[ "$INSECURE" = "true" ] && AUTH+=(--insecure)

JOB=$(jq --arg pid "$EVALHUB_PROVIDER_ID" \
    '(.benchmarks[] | select(.provider_id == "REPLACED_BY_run.sh") | .provider_id) = $pid' "$JOB_FILE")
JOB_ID=$(curl -s -f -S "${AUTH[@]}" -H "Content-Type: application/json" \
    -d "$JOB" "$EVALHUB_URL/api/v1/evaluations/jobs" | jq -r .resource.id)
echo "Submitted job $JOB_ID"

while true; do
    RESULT=$(curl -s -f -S "${AUTH[@]}" "$EVALHUB_URL/api/v1/evaluations/jobs/$JOB_ID")
    STATE=$(jq -r .status.state <<< "$RESULT")
    echo "  state: $STATE"
    case "$STATE" in
        completed|failed|cancelled|partially_failed) break ;;
    esac
    sleep 5
done

jq '{state: .status.state, message: .status.message.message, test: .results.test, benchmarks: [.results.benchmarks[]? | {id, metrics, test}]}' <<< "$RESULT"

# Per-test breakdown (promptfoo jobs only)
if jq -e '[.results.benchmarks[]?.additional_info.promptfoo_eval_json] | any' <<< "$RESULT" >/dev/null; then
    echo
    echo "Test results:"
    jq -c '.results.benchmarks[]?.additional_info.promptfoo_eval_json.results.results[]? | {pass: .success, description: .testCase.description, question: .vars.question, response: .response.output, reason: .gradingResult.reason}' <<< "$RESULT" |
    while IFS= read -r TEST; do
        MARK=PASS; [ "$(jq -r .pass <<< "$TEST")" = "true" ] || MARK=FAIL
        echo
        echo "[$MARK] $(jq -r .description <<< "$TEST")"
        echo "  Q: $(jq -r .question <<< "$TEST")"
        echo "  A: $(jq -r .response <<< "$TEST")"
        if [ "$MARK" = FAIL ]; then echo "  Why: $(jq -r .reason <<< "$TEST")"; fi
    done
    echo
fi

if [ "$(jq -r '.results.test.pass' <<< "$RESULT")" = "true" ]; then
    echo "PASS: score met the pass threshold"
else
    echo "FAIL: see job $JOB_ID for details" >&2
    exit 1
fi
