#!/bin/bash
# One-time setup, run as the user who'll submit evaluations: registers the promptfoo
# provider and stores the model's API key as a Secret in the given namespace. The
# namespace must first be prepared by a cluster admin with
# ./prepare-namespace-for-evals.sh. Re-run any time to update any of these.
#
# Usage: ./install-evals.sh <namespace>
set -eo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MODEL_SECRET=gemma-4-api-key

# EvalHub route host and the namespace evalhub-service runs in. Override via env.
EVALHUB_HOST=${EVALHUB_HOST:-evalhub-redhat-ods-applications.apps.ocp.home.glroland.com}
EVALHUB_NAMESPACE=${EVALHUB_NAMESPACE:-redhat-ods-applications}

[ -n "$1" ] || { echo "Usage: $0 <namespace>" >&2; exit 1; }
EVALHUB_TENANT=$1

command -v oc >/dev/null || { echo "oc is required and must be logged in (oc login ...)" >&2; exit 1; }
oc whoami >/dev/null 2>&1 || { echo "Not logged in to a cluster. Run 'oc login' first." >&2; exit 1; }
EVALHUB_USER=$(oc whoami)

echo "Using tenant namespace: $EVALHUB_TENANT"
echo "Using EvalHub host: $EVALHUB_HOST (namespace $EVALHUB_NAMESPACE)"

# Check that prepare-namespace-for-evals.sh has been run for this namespace (and this
# user) before doing anything.
NOT_READY=()
if [ "$EVALHUB_TENANT" != "$EVALHUB_NAMESPACE" ]; then
    NS_JSON=$(oc get namespace "$EVALHUB_TENANT" -o json)
    for LABEL in evalhub.trustyai.opendatahub.io/tenant= opendatahub.io/application-namespace=true; do
        jq -e --arg k "${LABEL%%=*}" --arg v "${LABEL#*=}" '.metadata.labels[$k] == $v' <<< "$NS_JSON" > /dev/null ||
            NOT_READY+=("namespace is missing label $LABEL")
    done
    oc get serviceaccount "evalhub-${EVALHUB_NAMESPACE}-job" -n "$EVALHUB_TENANT" > /dev/null 2>&1 ||
        NOT_READY+=("job service account evalhub-${EVALHUB_NAMESPACE}-job is missing")
    oc get configmap evalhub-service-ca -n "$EVALHUB_TENANT" > /dev/null 2>&1 ||
        NOT_READY+=("ConfigMap evalhub-service-ca is missing")
fi
# Ask with a SelfSubjectAccessReview, mirroring EvalHub's own check. "oc auth can-i"
# can't be used: providers isn't a real API resource (no CRD), so oc can't resolve its
# group and asks about the wrong resource, always answering "no".
oc create -o jsonpath='{.status.allowed}' -f - <<EOF 2> /dev/null | grep -qx true ||
apiVersion: authorization.k8s.io/v1
kind: SelfSubjectAccessReview
spec:
  resourceAttributes:
    namespace: $EVALHUB_TENANT
    verb: list
    group: trustyai.opendatahub.io
    resource: providers
EOF
    NOT_READY+=("user '$EVALHUB_USER' has no EvalHub API access (needs Contributor or Admin on the project, once it's prepared)")
if [ ${#NOT_READY[@]} -gt 0 ]; then
    echo "Namespace '$EVALHUB_TENANT' isn't prepared for evals:" >&2
    printf '  - %s\n' "${NOT_READY[@]}" >&2
    echo "Have a cluster admin run: ./prepare-namespace-for-evals.sh $EVALHUB_TENANT" >&2
    exit 1
fi

EVALHUB_URL="https://${EVALHUB_HOST}"
EVALHUB_TOKEN=${EVALHUB_TOKEN:-$(oc whoami -t)}

CURL_OPTS=(-s -f -S)
[ "$INSECURE" = "true" ] && CURL_OPTS+=(--insecure)

evalhub() {
    local method=$1 path=$2
    shift 2
    curl "${CURL_OPTS[@]}" -X "$method" "$EVALHUB_URL/api/v1/evaluations$path" \
        -H "Authorization: Bearer $EVALHUB_TOKEN" \
        -H "X-Tenant: $EVALHUB_TENANT" \
        -H "Content-Type: application/json" \
        "$@"
}

NAME=promptfoo
PROVIDER_ID=$(evalhub GET "/providers?name=$NAME&scope=tenant&benchmarks=false" | jq -r --arg n "$NAME" '[.items[]? | select(.name == $n)][0].resource.id // empty')

if [ -n "$PROVIDER_ID" ]; then
    echo "Updating provider '$NAME' ($PROVIDER_ID)"
    evalhub PUT "/providers/$PROVIDER_ID" -d @"$SCRIPT_DIR/provider.json" > /dev/null
else
    PROVIDER_ID=$(evalhub POST "/providers" -d @"$SCRIPT_DIR/provider.json" | jq -r .resource.id)
    echo "Created provider '$NAME' ($PROVIDER_ID)"
fi

read -r -s -p "Model API key for secret '$MODEL_SECRET' (leave blank to skip): " MODEL_API_KEY
echo
if [ -n "$MODEL_API_KEY" ]; then
    oc create secret generic "$MODEL_SECRET" -n "$EVALHUB_TENANT" \
        --from-literal=api-key="$MODEL_API_KEY" \
        --dry-run=client -o yaml | oc apply -f -
fi

echo "Install complete. Run ./run.sh $EVALHUB_TENANT job.json to evaluate."
