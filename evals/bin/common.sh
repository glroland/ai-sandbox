#!/bin/bash
# Shared settings for the EvalHub hello world scripts. Values come from .env or the environment.

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
EVAL_DIR=$(dirname "$SCRIPT_DIR")
[ -f "$SCRIPT_DIR/.env" ] && source "$SCRIPT_DIR/.env"

: "${EVALHUB_HOST:?EVALHUB_HOST is required (see env.example)}"
: "${EVALHUB_TENANT:?EVALHUB_TENANT is required (see env.example)}"
EVALHUB_TOKEN=${EVALHUB_TOKEN:-$(oc whoami -t)}
EVALHUB_URL="https://${EVALHUB_HOST#https://}"

# Set INSECURE=true to skip TLS verification for clusters with self-signed certs
CURL_OPTS=(-s -f -S)
[ "$INSECURE" = "true" ] && CURL_OPTS+=(--insecure)

evalhub() {
    local method=$1 path=$2
    shift 2
    curl "${CURL_OPTS[@]}" -X "$method" "$EVALHUB_URL/api/v1/evaluations$path" \
        -H "Authorization: Bearer $EVALHUB_TOKEN" \
        -H "X-Tenant: $EVALHUB_TENANT" \
        -H "Content-Type: application/json" \
        "$@"
}
