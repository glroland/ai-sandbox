#!/bin/bash

export MODEL_URL=$(oc get routes openai-responses-api-secure -o jsonpath='{.spec.host}' -n sandbox)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/responses" \
 -H 'X-LlamaStack-Provider-Data: {"vllm_api_token": "place_token_here"}' \
 -H 'Content-Type: application/json' \
 -d '{
   "model": "vllm-inference/gpt-oss-20b",
   "input": "What is the capital of Spain?"
 }' | jq .

