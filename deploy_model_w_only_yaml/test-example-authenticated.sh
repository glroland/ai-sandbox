#!/bin/bash

export MODEL_URL=$(oc get routes tinyllama -o jsonpath='{.spec.host}' -n sandbox)

export TOKEN=$(oc whoami -t)

curl -s -X 'POST' \
 "https://$MODEL_URL/v1/chat/completions" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
 -H "Authorization: Bearer $TOKEN" \
 -d '{
   "model": "tinyllama",
   "messages": [
       {
           "content": "what is the capital of Spain?",
           "role": "user"
       }
   ]}'

