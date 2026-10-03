#!/bin/bash

usage() {
    echo "Usage: $0 [-k|--insecure] [-d|--debug] [-s|--stream] [-j|--jq] [-a|--api chat|responses|messages|embeddings] <BASE_URL> <MODEL> [ACCESS_TOKEN]" >&2
    exit 1
}

INSECURE=0
DEBUG=0
STREAM=0
JQ_FORMAT=0
API="chat"

while [ "$#" -gt 0 ]; do
    case "$1" in
        -k|--insecure)
            INSECURE=1
            shift
            ;;
        -d|--debug)
            DEBUG=1
            shift
            ;;
        -s|--stream)
            STREAM=1
            shift
            ;;
        -j|--jq)
            JQ_FORMAT=1
            shift
            ;;
        -a|--api)
            [ "$#" -ge 2 ] || usage
            API="$2"
            shift 2
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage
            ;;
        *)
            break
            ;;
    esac
done

case "$API" in
    chat|responses|messages|embeddings) ;;
    *)
        echo "Unknown API: $API (expected: chat, responses, messages, embeddings)" >&2
        usage
        ;;
esac

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    usage
fi

BASE_URL=${1%/}
MODEL=$2
ACCESS_TOKEN=${3:-nokeyneeded}

if [ "$JQ_FORMAT" -eq 1 ] && ! command -v jq >/dev/null 2>&1; then
    echo "Warning: jq not found on PATH, falling back to raw output" >&2
    JQ_FORMAT=0
fi

if [ "$API" = "embeddings" ] && [ "$STREAM" -eq 1 ]; then
    echo "Warning: embeddings do not support streaming, ignoring --stream" >&2
    STREAM=0
fi

STREAM_JSON="false"
[ "$STREAM" -eq 1 ] && STREAM_JSON="true"

case "$API" in
    chat)
        ENDPOINT="$BASE_URL/chat/completions"
        AUTH_HEADERS=(-H "Authorization: Bearer $ACCESS_TOKEN")
        REQUEST_BODY="{
      \"model\": \"$MODEL\",
      \"stream\": $STREAM_JSON,
      \"messages\": [{\"role\": \"user\", \"content\": \"Ping\"}]
    }"
        ;;
    responses)
        ENDPOINT="$BASE_URL/responses"
        AUTH_HEADERS=(-H "Authorization: Bearer $ACCESS_TOKEN")
        REQUEST_BODY="{
      \"model\": \"$MODEL\",
      \"stream\": $STREAM_JSON,
      \"input\": \"Ping\"
    }"
        ;;
    messages)
        ENDPOINT="$BASE_URL/messages"
        AUTH_HEADERS=(-H "x-api-key: $ACCESS_TOKEN" -H "anthropic-version: 2023-06-01")
        REQUEST_BODY="{
      \"model\": \"$MODEL\",
      \"stream\": $STREAM_JSON,
      \"max_tokens\": 1024,
      \"messages\": [{\"role\": \"user\", \"content\": \"Ping\"}]
    }"
        ;;
    embeddings)
        ENDPOINT="$BASE_URL/embeddings"
        AUTH_HEADERS=(-H "Authorization: Bearer $ACCESS_TOKEN")
        REQUEST_BODY="{
      \"model\": \"$MODEL\",
      \"input\": \"Ping\"
    }"
        ;;
esac

CURL_OPTS=(-sS)
[ "$DEBUG" -eq 1 ] && CURL_OPTS+=(-v)
[ "$INSECURE" -eq 1 ] && CURL_OPTS+=(-k)
[ "$STREAM" -eq 1 ] && CURL_OPTS+=(-N)

if [ "$STREAM" -eq 1 ]; then
    # SSE isn't a single JSON document, so each "data: {...}" line is
    # parsed on its own; anything that isn't a "data:" line (plain-text
    # error bodies, event: lines, [DONE]) is passed through untouched so
    # it never gets buried by a jq parse failure.
    curl "${CURL_OPTS[@]}" "$ENDPOINT" \
        -H "Content-Type: application/json" \
        "${AUTH_HEADERS[@]}" \
        -d "$REQUEST_BODY" | \
    if [ "$JQ_FORMAT" -eq 1 ]; then
        while IFS= read -r line; do
            case "$line" in
                "data: "*)
                    payload="${line#data: }"
                    if [ "$payload" = "[DONE]" ]; then
                        echo "[DONE]"
                    elif echo "$payload" | jq -e . >/dev/null 2>&1; then
                        echo "$payload" | jq -c .
                    else
                        echo "$line"
                    fi
                    ;;
                "")
                    ;;
                *)
                    echo "$line"
                    ;;
            esac
        done
    else
        cat
    fi
else
    # Append the HTTP status on its own line so it can be split from the
    # body without it ever flowing into jq.
    RESPONSE=$(curl "${CURL_OPTS[@]}" -w $'\n%{http_code}' "$ENDPOINT" \
        -H "Content-Type: application/json" \
        "${AUTH_HEADERS[@]}" \
        -d "$REQUEST_BODY")
    HTTP_CODE="${RESPONSE##*$'\n'}"
    BODY="${RESPONSE%$'\n'*}"

    if [ "$JQ_FORMAT" -eq 1 ]; then
        if echo "$BODY" | jq -e . >/dev/null 2>&1; then
            echo "$BODY" | jq .
        else
            echo "Warning: response body is not valid JSON (HTTP $HTTP_CODE)" >&2
            echo "$BODY"
        fi
    else
        echo "$BODY"
    fi
    echo "HTTP Status: $HTTP_CODE" >&2
fi
echo
