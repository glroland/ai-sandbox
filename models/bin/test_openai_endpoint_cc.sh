#!/bin/bash

usage() {
    echo "Usage: $0 [-s] [-l] <OPENAI_BASE_URL> <MODEL> [ACCESS_TOKEN] [TIMEOUT_SECONDS]" >&2
    echo "  -s  stream the response" >&2
    echo "  -l  use a long prompt (story) instead of \"Ping\"" >&2
    exit 1
}

STREAM=false
PROMPT="Ping"

while getopts ":sl" opt; do
    case $opt in
        s) STREAM=true ;;
        l) PROMPT="Tell me a long, detailed story about a lighthouse keeper who discovers a message in a bottle." ;;
        *) usage ;;
    esac
done
shift $((OPTIND - 1))

if [ "$#" -lt 2 ] || [ "$#" -gt 4 ]; then
    usage
fi

OPENAI_BASE_URL=${1%/}
MODEL=$2
ACCESS_TOKEN=${3:-nokeyneeded}
TIMEOUT_SECONDS=${4:-0}   # 0 = no timeout

curl -vsSN --max-time "$TIMEOUT_SECONDS" "$OPENAI_BASE_URL/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -d "{
      \"model\": \"$MODEL\",
      \"stream\": $STREAM,
      \"messages\": [{\"role\": \"user\", \"content\": \"$PROMPT\"}]
    }"
echo
