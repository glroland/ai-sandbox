#!/bin/bash

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
    echo "Usage: $0 <OPENAI_BASE_URL> <MODEL> [ACCESS_TOKEN] [TIMEOUT_SECONDS]" >&2
    exit 1
fi

OPENAI_BASE_URL=${1%/}
MODEL=$2
ACCESS_TOKEN=${3:-nokeyneeded}
TIMEOUT_SECONDS=${4:-0}   # 0 = no timeout

curl -vsS --max-time "$TIMEOUT_SECONDS" "$OPENAI_BASE_URL/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -d "{
      \"model\": \"$MODEL\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Ping\"}]
    }"
echo
