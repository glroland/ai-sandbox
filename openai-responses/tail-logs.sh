#!/bin/bash

# Verify that an argument was provided
if [ -z "$1" ]; then
    echo "Error: No pod name prefix provided."
    echo "Usage: $0 <pod-name-prefix>"
    exit 1
fi

PREFIX=$1

# Find the first pod name that starts with the prefix
# --field-selector=status.phase=Running is optional but recommended
POD_NAME=$(oc get pods --no-headers -o custom-columns=":metadata.name" | grep "^${PREFIX}" | head -n 1)

# Check if a matching pod was found
if [ -z "$POD_NAME" ]; then
    echo "Error: No pod found starting with '$PREFIX'"
    exit 1
fi

echo "Fetching logs for pod: $POD_NAME"

# Stream the logs
oc logs -f "$POD_NAME"

