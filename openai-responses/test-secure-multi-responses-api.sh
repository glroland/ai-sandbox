#!/bin/bash

export NAMESPACE=sandbox
export RESPONSES_NAME=openai-responses-api-secure-multi
export MODEL_1_NAME=gemma-4-vllm-inference/gemma-4
export MODEL_2_NAME=tinyllama-vllm-inference/tinyllama

export RESPONSES_URL=$(oc get routes $RESPONSES_NAME -o jsonpath='{.spec.host}' -n $NAMESPACE)
echo Responses API URL: $RESPONSES_URL

export TOKEN=$(oc whoami -t)
echo Token: $TOKEN
echo

echo Model List
curl -s https://$RESPONSES_URL/v1/models \
   -H 'X-LlamaStack-Provider-Data: {"vllm_api_token": "sha256~PeSRbb12bmnTgFsJStcmlMbnVb-qW7xfAcLR78Hehqc"}' \
  | jq -r .data[].id
echo

echo Model 1 Test: $MODEL_1_NAME
curl -s -X 'POST' \
 "https://$RESPONSES_URL/v1/responses" \
 -H "X-LlamaStack-Provider-Data: {\"vllm_api_token\": \"$TOKEN\"}" \
 -H 'Content-Type: application/json' \
 -d "{
   \"model\": \"$MODEL_1_NAME\",
   \"input\": \"What is the capital of Spain?\"
 }" | jq -r .output[].content[].text
echo

echo Model 2 Test: $MODEL_2_NAME
curl -s -X 'POST' \
 "https://$RESPONSES_URL/v1/responses" \
 -H "X-LlamaStack-Provider-Data: {\"vllm_api_token\": \"$TOKEN\"}" \
 -H 'Content-Type: application/json' \
 -d "{
   \"model\": \"$MODEL_2_NAME\",
   \"input\": \"What is the capital of Spain?\"
 }" | jq -r .output[].content[].text
echo
