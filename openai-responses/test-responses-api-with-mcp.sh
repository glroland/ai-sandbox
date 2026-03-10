#!/bin/bash

export MODEL_URL=$(oc get routes openai-responses-api -o jsonpath='{.spec.host}' -n sandbox)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/responses" \
 -H 'X-LlamaStack-Provider-Data: {"vllm_api_token": "sha256~7ak50ZJscqJaL49G6ZLP2bugdcrgYjkU6I7CarmlZfE"}' \
 -H 'Content-Type: application/json' \
 -d '{
   "model": "vllm-inference/gpt-oss-20b",
   "input": "Write a birthday card for the person associated with the response from the tool tooltest1 with id pong",
   "tools": [
          {
            "type": "mcp",
            "server_label": "server1",
            "server_url": "http://rack:8000/mcp",
            "require_approval": "never"
          }
        ]
 }' | jq .
