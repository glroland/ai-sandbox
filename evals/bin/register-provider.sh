#!/bin/bash
# Create (or update) the community promptfoo provider in EvalHub and print its provider id
set -e
source "$(dirname "$0")/common.sh"

PROVIDER=$(jq --arg image "${PROMPTFOO_IMAGE:-quay.io/evalhub/community-promptfoo:latest}" \
    '.runtime.k8s.image = $image' "$EVAL_DIR/provider.json")
NAME=$(jq -r .name <<< "$PROVIDER")

PROVIDER_ID=$(evalhub GET "/providers?name=$NAME&scope=tenant&benchmarks=false" | jq -r --arg n "$NAME" '[.items[]? | select(.name == $n)][0].resource.id // empty')

if [ -n "$PROVIDER_ID" ]; then
    echo "Updating provider '$NAME' ($PROVIDER_ID)" >&2
    evalhub PUT "/providers/$PROVIDER_ID" -d "$PROVIDER" > /dev/null
else
    echo "Creating provider '$NAME'" >&2
    PROVIDER_ID=$(evalhub POST "/providers" -d "$PROVIDER" | jq -r .resource.id)
fi

echo "$PROVIDER_ID"
