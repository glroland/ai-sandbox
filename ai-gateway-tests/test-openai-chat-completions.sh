#!/usr/bin/env bash
#
# Verifies the AI gateway's OpenAI-compatible /chat/completions endpoint
# returns a valid response from the self-hosted model.

set -uo pipefail

PURPOSE="OpenAI chat completions API against self-hosted model"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +a
else
  echo "${PURPOSE}: FAIL (missing .env config file)"
  exit 1
fi

: "${GATEWAY_BASE_URL:?}" "${GATEWAY_API_KEY:?}" "${GATEWAY_MODEL:?}"
TIMEOUT="${GATEWAY_TIMEOUT_SECONDS:-30}"

REQUEST_BODY=$(cat <<EOF
{
  "model": "${GATEWAY_MODEL}",
  "messages": [
    {"role": "user", "content": "Reply with exactly one word: pong"}
  ],
  "max_tokens": 10
}
EOF
)

CURL_ERR_FILE=$(mktemp)
RESPONSE=$(curl -sS --max-time "${TIMEOUT}" \
  -w '\n%{http_code}' \
  -X POST "${GATEWAY_BASE_URL}/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${GATEWAY_API_KEY}" \
  -d "${REQUEST_BODY}" 2>"${CURL_ERR_FILE}")
CURL_EXIT=$?
CURL_ERR=$(tr '\n' ' ' < "${CURL_ERR_FILE}")
rm -f "${CURL_ERR_FILE}"

if [[ ${CURL_EXIT} -ne 0 ]]; then
  echo "${PURPOSE}: FAIL (curl exit ${CURL_EXIT}: ${CURL_ERR})"
  exit 1
fi

HTTP_CODE=$(echo "${RESPONSE}" | tail -n1)
BODY=$(echo "${RESPONSE}" | sed '$d')

if [[ "${HTTP_CODE}" != "200" ]]; then
  echo "${PURPOSE}: FAIL (HTTP ${HTTP_CODE}: $(echo "${BODY}" | tr '\n' ' '))"
  exit 1
fi

CONTENT=$(echo "${BODY}" | grep -o '"content"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1)

if [[ -z "${CONTENT}" ]]; then
  echo "${PURPOSE}: FAIL (no message content in response: ${BODY})"
  exit 1
fi

echo "${PURPOSE}: PASS (HTTP 200, received: ${CONTENT})"
exit 0
