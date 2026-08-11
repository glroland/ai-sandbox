#!/bin/bash

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "Usage: $0 <MCP_URL> [ACCESS_TOKEN]" >&2
    exit 1
fi

MCP_URL=$1
ACCESS_TOKEN=${2:-nokeyneeded}

if [ -z "$MCP_URL" ]; then
    echo "Error: MCP_URL is required" >&2
    exit 1
fi

INIT_HEADERS=$(mktemp)
INIT_BODY=$(mktemp)

HTTP_CODE=$(curl -s -L -D "$INIT_HEADERS" -o "$INIT_BODY" -w '%{http_code}' -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -d '{
      "jsonrpc": "2.0",
      "id": 1,
      "method": "initialize",
      "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": { "name": "curl-client", "version": "1.0.0" }
      }
    }')

if [ "$HTTP_CODE" -lt 200 ] || [ "$HTTP_CODE" -ge 300 ]; then
    echo "Error: initialize request failed with HTTP $HTTP_CODE" >&2
    cat "$INIT_BODY" >&2
    rm -f "$INIT_HEADERS" "$INIT_BODY"
    exit 1
fi

# Mcp-Session-Id is optional per the MCP spec: stateful servers assign one and expect
# it echoed back on every subsequent request; stateless servers omit it entirely, which
# is not an error, so we only attach the header when one was actually returned.
MCP_SESSION_ID=$(grep -i '^mcp-session-id:' "$INIT_HEADERS" | sed 's/^[^:]*: *//' | tr -d '\r')
rm -f "$INIT_HEADERS" "$INIT_BODY"

SESSION_HEADER=()
if [ -n "$MCP_SESSION_ID" ]; then
    SESSION_HEADER=(-H "Mcp-Session-Id: $MCP_SESSION_ID")
fi

# Required handshake step before any other method call is valid in-session
curl -s -L -o /dev/null -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "${SESSION_HEADER[@]}" \
    -d '{
      "jsonrpc": "2.0",
      "method": "notifications/initialized"
    }'

RESPONSE=$(curl -s -L -X POST "$MCP_URL" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    "${SESSION_HEADER[@]}" \
    -d '{
      "jsonrpc": "2.0",
      "id": 2,
      "method": "tools/list",
      "params": {}
    }')

# Servers may reply with a plain JSON body or an SSE stream ("data: {...}") depending on transport config
if echo "$RESPONSE" | head -c1 | grep -q '{'; then
    JSON="$RESPONSE"
else
    JSON=$(echo "$RESPONSE" | grep '^data: ' | sed 's/^data: //')
fi

echo "$JSON" | jq '.result.tools[] | {name, description}'
