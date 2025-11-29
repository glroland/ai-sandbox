#!/bin/bash

export GUARDRAILS_URL=$(oc get routes guardrails -o jsonpath='{.spec.host}' -n sandbox)

curl -s -X 'POST' \
 "https://$GUARDRAILS_URL/api/v2/text/detection/content" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
  -d '{
    "content": "my amex 374245455400126",
    "detectors": {
        "regex": {"regex": ["ssn","email","credit-card","^hello$"]}
    }
  }' | jq

curl -s -X 'POST' \
 "https://$GUARDRAILS_URL/api/v2/text/detection/content" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
  -d '{
    "content": "hello", 
    "detectors": {
        "regex_language": {"regex": ["ssn","email","credit-card","^hello$"]}
    }
  }' | jq


curl -s -X 'POST' \
 "https://$GUARDRAILS_URL/api/v2/text/detection/content" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
  -d '{
    "content": "this is my email address email@domain.com", 
    "detectors": {
        "regex_language": {"regex_language": ["ssn","email","credit-card","^hello$"]}
    }
  }' | jq


curl -s -X 'POST' \
 "https://$GUARDRAILS_URL/api/v2/text/detection/content" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
  -d '{
    "content": "check out my social 123-45-6789", 
    "detectors": {
        "regex": {"regex": ["ssn","email","credit-card","^hello$"]}
    }
  }' | jq

curl -s -X 'POST' \
 "https://$GUARDRAILS_URL/api/v2/text/detection/content" \
 -H 'accept: application/json' \
 -H 'Content-Type: application/json' \
  -d '{
    "content": "this text should not pop up", 
    "detectors": {
        "regex": {"regex": ["ssn","email","credit-card","^hello$"]}
    }
  }' | jq
