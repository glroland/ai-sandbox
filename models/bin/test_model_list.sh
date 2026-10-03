#!/bin/bash

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: $0 <OPENAI_BASE_URL> [ACCESS_TOKEN]" >&2
    exit 1
fi

OPENAI_BASE_URL=${1%/}
ACCESS_TOKEN=${2:-nokeyneeded}

curl -sS "$OPENAI_BASE_URL/models" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ACCESS_TOKEN"
echo
