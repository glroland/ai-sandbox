#!/bin/bash

export MODEL_NAME=nomic-gpu

export MODEL_HOST=$(oc get routes $MODEL_NAME -o jsonpath='{.spec.host}' -n sandbox)

export MODEL_URL=https://$MODEL_HOST/v1/embeddings
echo URL: $MODEL_URL

curl $MODEL_URL \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{
      "input": "Your text string goes here",
      "model": "'"$MODEL_NAME"'"
    }'
