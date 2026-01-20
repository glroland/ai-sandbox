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
           "content": "my name is john doe.  my amex 374245455400126. my email address email@domain.com.  my social 123-45-6789. create a text based ID card using this information.",
           "role": "user"
       }
   ]}' | jq .
