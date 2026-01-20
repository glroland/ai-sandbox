#!/bin/bash

export MODEL_URL=$(oc get routes granite4 -o jsonpath='{.spec.host}' -n sandbox)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/chat/completions" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
 -d '{
   "model": "granite4",
   "messages": [
       {
           "content": "what is the capital of Spain?",
           "role": "user"
       }
   ]}' | jq .
