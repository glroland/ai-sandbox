#!/bin/bash

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 <OPENAI_BASE_URL> <MODEL> [ACCESS_TOKEN]" >&2
    exit 1
fi

OPENAI_BASE_URL=${1%/}
MODEL=$2
ACCESS_TOKEN=${3:-nokeyneeded}

curl -vsS "$OPENAI_BASE_URL/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -d "{
      \"model\": \"$MODEL\",
      \"messages\": [{\"role\": \"user\", \"content\": \"Ping\"}]
    }"
echo
