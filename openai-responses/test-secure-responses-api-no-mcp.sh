#!/bin/bash

#export MODEL_URL=$(oc get routes openai-responses-api-secure -o jsonpath='{.spec.host}' -n sandbox)
export MODEL_URL=$(oc get routes my-llama-stack -o jsonpath='{.spec.host}' -n my-llama-stack)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/responses" \
 -H 'X-LlamaStack-Provider-Data: {"vllm_api_token": "sha256~IqTPKaipuH9w6biYQJSd56K9yXFjJf2ANNg_n62jRF4"}' \
 -H 'Content-Type: application/json' \
 -d '{
   "model": "vllm-inference/gpt-oss-20b",
   "input": "What is the capital of Spain?"
 }' | jq .

