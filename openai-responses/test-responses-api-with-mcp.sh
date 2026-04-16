#!/bin/bash

export MODEL_URL=$(oc get routes my-llama-stack -o jsonpath='{.spec.host}' -n my-llama-stack)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/responses" \
 -H 'X-LlamaStack-Provider-Data: {"vllm_api_token": "sha256~7ak50ZJscqJaL49G6ZLP2bugdcrgYjkU6I7CarmlZfE"}' \
 -H 'Content-Type: application/json' \
 -d '{
   "model": "together/openai/gpt-oss-20b",
   "input": "What is the current temperature in atlanta today?",
   "tools": [
          {
            "type": "mcp",
            "server_label": "server1",
            "server_url": "https://baseball-chatbot-agent-utilities-baseball-chatbot.apps.ocp.home.glroland.com/mcp",
            "require_approval": "never"
          }
        ]
 }' | jq .
