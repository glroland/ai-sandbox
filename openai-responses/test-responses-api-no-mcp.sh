#!/bin/bash

export MODEL_URL=$(oc get routes openai-responses-api -o jsonpath='{.spec.host}' -n sandbox)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/responses" \
 -H 'Authorization: Bearer $OPENAI_API_KEY' \
 -H 'Content-Type: application/json' \
 -d '{
   "model": "vllm-inference/gpt-oss-20b-essential",
   "input": "What is the capital of Spain?"
 }' | jq .

