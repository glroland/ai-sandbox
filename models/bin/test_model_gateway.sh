#!/bin/bash
#
# Usage: test_model_gateway.sh [-v|-vv|-vvv] [-p] [-u gateway_url] [-a api_format] [model_name[,model_name...]]
#   -v/-vv/-vvv     increasing verbosity (see -h for details)
#   -p              pause between each test
#   -u gateway_url  gateway base URL (default: https://maas.apps.ocp.home.glroland.com)
#   -a api_format   which API request shape to use: auto (default), chat,
#                   responses, or messages
#   model_name      only test the given model(s); comma-delimited list matched
#                   against the model id or the name portion of its
#                   "owned_by" field

set -uo pipefail

GATEWAY_BASE="https://maas.apps.ocp.home.glroland.com"

VERBOSE=0
PAUSE=0
MODEL_FILTER=""
API_FORMAT="auto"

usage() {
    echo "Usage: $0 [-v|-vv|-vvv] [-p] [-u gateway_url] [-a auto|chat|responses|messages] [-h] [model_name[,model_name...]]" >&2
    exit 1
}

print_help() {
    cat <<EOF
Test each model exposed by the MaaS model gateway.

Usage: $0 [-v|-vv|-vvv] [-p] [-u gateway_url] [-a auto|chat|responses|messages] [-h] [model_name[,model_name...]]

Fetches the model list from the gateway's /v1/models endpoint, then sends
a "Ping" request to each model, reporting pass/fail.

Options:
  -v              List the model ids found by the gateway, and show each
                  model's response output alongside its test result.
  -vv             -v, plus the full raw model list response and internal
                  debug info (bearer key, fetched model list, per-test
                  request URL).
  -vvv            -vv, but with the full curl -v trace (headers, TLS,
                  timing) for both the model list request and each
                  per-model test, instead of just the response body.
                  The most detail available; -v may be stacked
                  (e.g. "-v -v -v") instead of combined.
  -p              Pause and wait for a keypress between each test.
  -u gateway_url  Gateway base URL to test against.
                  (default: $GATEWAY_BASE)
  -a api_format   Which API request shape to send to every tested model:
                     auto       (default) inspect each model's
                                modelDetails.description and use
                                "responses" for any model described as
                                using the Responses API, "chat" otherwise.
                     chat       Force OpenAI Chat Completions:
                                POST .../v1/chat/completions with a
                                "messages" array.
                     responses  Force the OpenAI Responses API:
                                POST .../v1/responses with an "input"
                                string.
                     messages   Force the Anthropic Messages API:
                                POST .../v1/messages with a "messages"
                                array and "max_tokens".
  -h, --help      Show this help message and exit.

Arguments:
  model_name      Only test the given model(s) instead of every model
                  in the gateway's list. Accepts a comma-delimited list
                  (e.g. "gpt-4o,claude-sonnet-5"). Matched against a
                  model's id or the name portion of its "owned_by" field.

Environment:
  MAAS_KEY        Required. Bearer token used to authenticate against
                  the gateway.

Examples:
  $0
  $0 -v gpt-4o
  $0 -vvv -p
  $0 "gpt-4o,claude-sonnet-5"
  $0 -u https://other-gateway.example.com
  $0 -a responses gpt-4o-responses
EOF
    exit 0
}

trim() {
    local s="$1"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

if [ -t 1 ]; then
    COLOR_RED=$'\033[31m'
    COLOR_RESET=$'\033[0m'
else
    COLOR_RED=""
    COLOR_RESET=""
fi

while [ "$#" -gt 0 ]; do
    case "$1" in
        -v|-vv|-vvv)
            VERBOSE=$((VERBOSE + ${#1} - 1))
            shift
            ;;
        -p)
            PAUSE=1
            shift
            ;;
        -u)
            if [ "$#" -lt 2 ]; then
                echo "-u requires a URL argument." >&2
                usage
            fi
            GATEWAY_BASE="${2%/}"
            shift 2
            ;;
        -a)
            if [ "$#" -lt 2 ]; then
                echo "-a requires an api_format argument." >&2
                usage
            fi
            case "$2" in
                auto|chat|responses|messages)
                    API_FORMAT="$2"
                    ;;
                *)
                    echo "Invalid -a value: '$2' (must be auto, chat, responses, or messages)." >&2
                    usage
                    ;;
            esac
            shift 2
            ;;
        -h|--help)
            print_help
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage
            ;;
        *)
            if [ -n "$MODEL_FILTER" ]; then
                echo "Only one model_name argument may be specified (use a comma-delimited list for multiple models)." >&2
                usage
            fi
            MODEL_FILTER="$1"
            shift
            ;;
    esac
done

if [ "$VERBOSE" -gt 3 ]; then
    VERBOSE=3
fi

MODEL_FILTERS=()
MODEL_FILTERS_MATCHED=()
if [ -n "$MODEL_FILTER" ]; then
    IFS=',' read -ra MODEL_FILTERS <<< "$MODEL_FILTER"
    for i in "${!MODEL_FILTERS[@]}"; do
        MODEL_FILTERS[$i]="$(trim "${MODEL_FILTERS[$i]}")"
        MODEL_FILTERS_MATCHED[$i]=0
    done
fi

debug() {
    if [ "$VERBOSE" -ge 2 ]; then
        echo "$@"
    fi
}

export OPENAI_KEY="${MAAS_KEY:-}"
if [ -z "$OPENAI_KEY" ]; then
    echo "Error: MAAS_KEY is not set." >&2
    exit 1
fi

debug "Key = $OPENAI_KEY"
debug "  URL = $GATEWAY_BASE/v1/models"
debug

echo "Gathering models..."

TRACE_FILE=""
if [ "$VERBOSE" -ge 3 ]; then
    TRACE_FILE=$(mktemp)
    trap 'rm -f "$TRACE_FILE"' EXIT
    RESPONSE=$(curl -sS -v --max-time 15 -w $'\n%{http_code}' "$GATEWAY_BASE/v1/models" \
        -H "Authorization: Bearer $OPENAI_KEY" 2>"$TRACE_FILE")
else
    RESPONSE=$(curl -sS --max-time 15 -w $'\n%{http_code}' "$GATEWAY_BASE/v1/models" \
        -H "Authorization: Bearer $OPENAI_KEY")
fi
CURL_STATUS=$?

if [ "$CURL_STATUS" -ne 0 ]; then
    echo "Error: could not reach $GATEWAY_BASE/v1/models (curl exit code $CURL_STATUS)." >&2
    exit 1
fi

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
    echo "Error: model list request returned HTTP $HTTP_CODE:" >&2
    echo "$BODY" >&2
    exit 1
fi

if ! echo "$BODY" | jq -e '.data' >/dev/null 2>&1; then
    echo "Error: model list response was not valid JSON with a .data array:" >&2
    echo "$BODY" >&2
    exit 1
fi

MODEL_COUNT=$(echo "$BODY" | jq '.data | length')
echo "Gathered $MODEL_COUNT model(s)."

if [ "$VERBOSE" -ge 1 ]; then
    echo "Models found:"
    echo "$BODY" | jq -r '.data[].id'
fi

if [ "$VERBOSE" -ge 2 ]; then
    echo "Model list response:"
    echo "$BODY" | jq .
fi

if [ "$VERBOSE" -ge 3 ]; then
    echo "Model list curl trace:"
    cat "$TRACE_FILE"
fi

echo

FOUND=0
PASS=0
FAIL=0

while IFS=$'\t' read -r MODEL_ID OWNED_BY DESCRIPTION; do
    [ -z "$MODEL_ID" ] && continue

    NAMESPACE="${OWNED_BY%%/*}"
    MODEL_NAME="${OWNED_BY#*/}"

    if [ "${#MODEL_FILTERS[@]}" -gt 0 ]; then
        MATCHED=0
        for i in "${!MODEL_FILTERS[@]}"; do
            if [ "${MODEL_FILTERS[$i]}" = "$MODEL_ID" ] || [ "${MODEL_FILTERS[$i]}" = "$MODEL_NAME" ]; then
                MATCHED=1
                MODEL_FILTERS_MATCHED[$i]=1
            fi
        done
        [ "$MATCHED" -eq 0 ] && continue
    fi
    FOUND=1

    CHAT_MODEL_NAME="$MODEL_NAME"

    if [ "$API_FORMAT" = "auto" ]; then
        if echo "$DESCRIPTION" | grep -qi "Responses API"; then
            API_KIND="responses"
        else
            API_KIND="chat"
        fi
    else
        API_KIND="$API_FORMAT"
    fi

    EXTRA_HEADER=()
    case "$API_KIND" in
        responses)
            OPENAI_URL="$GATEWAY_BASE/$NAMESPACE/$MODEL_NAME/v1/responses"
            REQUEST_BODY="{\"model\": \"$CHAT_MODEL_NAME\", \"input\": \"Ping\"}"
            ;;
        messages)
            OPENAI_URL="$GATEWAY_BASE/$NAMESPACE/$MODEL_NAME/v1/messages"
            REQUEST_BODY="{\"model\": \"$CHAT_MODEL_NAME\", \"max_tokens\": 1024, \"messages\": [{\"role\": \"user\", \"content\": \"Ping\"}]}"
            EXTRA_HEADER=(-H "anthropic-version: 2023-06-01")
            ;;
        *)
            OPENAI_URL="$GATEWAY_BASE/$NAMESPACE/$MODEL_NAME/v1/chat/completions"
            REQUEST_BODY="{\"model\": \"$CHAT_MODEL_NAME\", \"messages\": [{\"role\": \"user\", \"content\": \"Ping\"}]}"
            ;;
    esac

    echo "Testing $MODEL_ID ($NAMESPACE/$MODEL_NAME)"
    debug "  URL = $OPENAI_URL"
    debug "  API = $API_KIND"

    if [ "$VERBOSE" -ge 3 ]; then
        CHAT_RESPONSE=$(curl -sS -v -L --max-time 30 -w $'\n%{http_code}' "$OPENAI_URL" \
            -H 'Content-Type: application/json' \
            -H "Authorization: Bearer $OPENAI_KEY" \
            "${EXTRA_HEADER[@]+"${EXTRA_HEADER[@]}"}" \
            -d "$REQUEST_BODY" 2>&1)
    else
        CHAT_RESPONSE=$(curl -sS -L --max-time 30 -w $'\n%{http_code}' "$OPENAI_URL" \
            -H 'Content-Type: application/json' \
            -H "Authorization: Bearer $OPENAI_KEY" \
            "${EXTRA_HEADER[@]+"${EXTRA_HEADER[@]}"}" \
            -d "$REQUEST_BODY")
    fi
    CHAT_STATUS=$?
    CHAT_CODE=$(echo "$CHAT_RESPONSE" | tail -n1)
    CHAT_BODY=$(echo "$CHAT_RESPONSE" | sed '$d')

    if [ "$VERBOSE" -ge 1 ]; then
        [ -n "$CHAT_BODY" ] && echo "$CHAT_BODY"
    elif [ "$CHAT_STATUS" -ne 0 ] || [ "$CHAT_CODE" -lt 200 ] || [ "$CHAT_CODE" -ge 300 ]; then
        [ -n "$CHAT_BODY" ] && echo "  $CHAT_BODY"
    fi

    if [ "$CHAT_STATUS" -ne 0 ]; then
        echo "FAILED (curl exit code $CHAT_STATUS)"
        FAIL=$((FAIL + 1))
    elif [ "$CHAT_CODE" -lt 200 ] || [ "$CHAT_CODE" -ge 300 ]; then
        echo "FAILED (HTTP $CHAT_CODE)"
        FAIL=$((FAIL + 1))
    else
        echo "OK (HTTP $CHAT_CODE)"
        PASS=$((PASS + 1))
    fi
    echo

    if [ "$PAUSE" -eq 1 ]; then
        read -rsn1 -p "Press any key to continue..."
        echo
        echo
    fi
done < <(echo "$BODY" | jq -r '.data[] | select(.owned_by != null) | "\(.id)\t\(.owned_by)\t\(.modelDetails.description // "")"')

for i in "${!MODEL_FILTERS[@]}"; do
    if [ "${MODEL_FILTERS_MATCHED[$i]}" -eq 0 ]; then
        echo "Warning: model '${MODEL_FILTERS[$i]}' not found in gateway model list." >&2
    fi
done

if [ "$FOUND" -eq 0 ]; then
    if [ "${#MODEL_FILTERS[@]}" -gt 0 ]; then
        echo "Error: none of the requested models ($MODEL_FILTER) were found in gateway model list." >&2
    else
        echo "Error: no models found in gateway response." >&2
    fi
    exit 1
fi

echo "Results: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
