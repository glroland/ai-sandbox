#!/bin/bash
# Run the MMLU benchmark locally with lm-evaluation-harness, straight against the
# model's chat endpoint with its chat template applied (generative, exact match).
# No EvalHub, no OpenShift — just the model/threshold from the job file.
# Usage: ./run-mmlu-local.sh <job-file.json> [lm_eval args...]   (e.g. job-mmlu.json --limit 10 for a smoke test)
set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
LM_EVAL_VERSION=0.4.13

[ -n "$1" ] || { echo "Usage: $0 <job-file.json> [lm_eval args...]" >&2; exit 1; }
JOB_FILE=$1
shift
[ -f "$JOB_FILE" ] || { echo "Job file '$JOB_FILE' not found." >&2; exit 1; }

command -v uvx >/dev/null || { echo "uvx (uv) is required: https://docs.astral.sh/uv/" >&2; exit 1; }

MODEL_URL=$(jq -r '.model.url' "$JOB_FILE")
MODEL_NAME=$(jq -r '.model.name' "$JOB_FILE")
TASK=$(jq -r '.benchmarks[0].id' "$JOB_FILE")
CONCURRENT=$(jq -r '.benchmarks[0].parameters.num_concurrent // 1' "$JOB_FILE")
THRESHOLD=$(jq -r '.pass_criteria.threshold' "$JOB_FILE")

if [ -z "$MODEL_API_KEY" ]; then
    read -r -s -p "Model API key for $MODEL_NAME (leave blank if none): " MODEL_API_KEY
    echo
fi

# Completed requests are cached, so if a run dies (e.g. the gateway drops a connection,
# which lm-eval doesn't retry) rerunning resumes where it left off. The cache is cleared
# after a successful run so the next run always gets fresh answers from the model.
OUTPUT="$SCRIPT_DIR/.eval-mmlu-local"
CACHE="$SCRIPT_DIR/.eval-mmlu-local-cache/requests"
mkdir -p "$(dirname "$CACHE")"
rm -rf "$OUTPUT"

OPENAI_API_KEY=${MODEL_API_KEY:-not-required} uvx --python 3.12 --from "lm-eval[api]==$LM_EVAL_VERSION" \
    lm_eval --model local-chat-completions \
    --model_args "model=$MODEL_NAME,base_url=${MODEL_URL%/}/chat/completions,num_concurrent=$CONCURRENT,max_retries=5,tokenized_requests=False" \
    --tasks "$TASK" --apply_chat_template --log_samples --output_path "$OUTPUT" \
    --use_cache "$CACHE" "$@"
rm -rf "$(dirname "$CACHE")"

# The group-level exact_match is the overall score across all subjects.
RESULTS=$(find "$OUTPUT" -name 'results_*.json' | head -1)
SCORE=$(jq --arg t "$TASK" '.results[$t] | to_entries | map(select(.key | startswith("exact_match,")))[0].value' "$RESULTS")
jq -n --argjson s "$SCORE" --argjson t "$THRESHOLD" '{exact_match: $s, threshold: $t}'

if [ "$(jq -n --argjson s "$SCORE" --argjson t "$THRESHOLD" '$s >= $t')" = "true" ]; then
    echo "PASS: exact_match met the pass threshold"
else
    echo "FAIL: see $OUTPUT for per-prompt samples" >&2
    exit 1
fi
