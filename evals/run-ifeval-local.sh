#!/bin/bash
# Run the IFEval instruction-following benchmark locally with lm-evaluation-harness,
# straight against the model's chat endpoint with its chat template applied.
# No EvalHub, no OpenShift — just the model/threshold from job-ifeval.json.
# Usage: ./run-ifeval-local.sh [lm_eval args...]   (e.g. --limit 10 for a smoke test)
set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
JOB_FILE=$SCRIPT_DIR/job-ifeval.json
LM_EVAL_VERSION=0.4.13

command -v uvx >/dev/null || { echo "uvx (uv) is required: https://docs.astral.sh/uv/" >&2; exit 1; }

MODEL_URL=$(jq -r '.model.url' "$JOB_FILE")
MODEL_NAME=$(jq -r '.model.name' "$JOB_FILE")
CONCURRENT=$(jq -r '.benchmarks[0].parameters.num_concurrent // 1' "$JOB_FILE")
THRESHOLD=$(jq -r '.pass_criteria.threshold' "$JOB_FILE")

if [ -z "$MODEL_API_KEY" ]; then
    read -r -s -p "Model API key for $MODEL_NAME (leave blank if none): " MODEL_API_KEY
    echo
fi

OUTPUT="$SCRIPT_DIR/.eval-ifeval-local"
rm -rf "$OUTPUT"

OPENAI_API_KEY=${MODEL_API_KEY:-not-required} uvx --python 3.12 --from "lm-eval[api,ifeval]==$LM_EVAL_VERSION" \
    lm_eval --model local-chat-completions \
    --model_args "model=$MODEL_NAME,base_url=${MODEL_URL%/}/chat/completions,num_concurrent=$CONCURRENT,max_retries=5,tokenized_requests=False" \
    --tasks ifeval --apply_chat_template --log_samples --output_path "$OUTPUT" "$@"

RESULTS=$(find "$OUTPUT" -name 'results_*.json' | head -1)
jq --argjson t "$THRESHOLD" '.results.ifeval | {
    inst_level_strict_acc: ."inst_level_strict_acc,none",
    prompt_level_strict_acc: ."prompt_level_strict_acc,none",
    inst_level_loose_acc: ."inst_level_loose_acc,none",
    prompt_level_loose_acc: ."prompt_level_loose_acc,none",
    threshold: $t}' "$RESULTS"

if [ "$(jq --argjson t "$THRESHOLD" '.results.ifeval."inst_level_strict_acc,none" >= $t' "$RESULTS")" = "true" ]; then
    echo "PASS: inst_level_strict_acc met the pass threshold"
else
    echo "FAIL: see $OUTPUT for per-prompt samples" >&2
    exit 1
fi
