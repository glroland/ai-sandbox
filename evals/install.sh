#!/bin/bash
# One-time setup: discovers the EvalHub route from the connected oc session,
# registers the promptfoo provider, and stores the model's API key as a
# Secret. Re-run any time to update any of these. Writes the discovered
# host/tenant to .evalhub.env so run.sh doesn't have to rediscover them.
set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
MODEL_SECRET=gemma-4-api-key

command -v oc >/dev/null || { echo "oc is required and must be logged in (oc login ...)" >&2; exit 1; }
oc whoami >/dev/null 2>&1 || { echo "Not logged in to a cluster. Run 'oc login' first." >&2; exit 1; }

EVALHUB_TENANT=${EVALHUB_TENANT:-$(oc project -q)}
echo "Using tenant namespace: $EVALHUB_TENANT"

# Discover the EvalHub route and, from it, the namespace evalhub-service runs in
# (needed below to grant it read access to the model secret in the tenant namespace).
if [ -z "$EVALHUB_HOST" ] || [ -z "$EVALHUB_NAMESPACE" ]; then
    ROUTE_JSON=$(oc get route -A -l app=eval-hub -o json)
    ROUTE_COUNT=$(jq '.items | length' <<< "$ROUTE_JSON")
    case "$ROUTE_COUNT" in
        0)
            echo "No EvalHub route found (label app=eval-hub). Set EVALHUB_HOST and EVALHUB_NAMESPACE and rerun." >&2
            exit 1
            ;;
        1)
            EVALHUB_HOST=${EVALHUB_HOST:-$(jq -r '.items[0].spec.host' <<< "$ROUTE_JSON")}
            EVALHUB_NAMESPACE=${EVALHUB_NAMESPACE:-$(jq -r '.items[0].metadata.namespace' <<< "$ROUTE_JSON")}
            ;;
        *)
            if [ -z "$EVALHUB_HOST" ] || [ -z "$EVALHUB_NAMESPACE" ]; then
                echo "Multiple EvalHub routes found; set EVALHUB_HOST and EVALHUB_NAMESPACE and rerun:" >&2
                jq -r '.items[] | "  \(.metadata.namespace)/\(.metadata.name): \(.spec.host)"' <<< "$ROUTE_JSON" >&2
                exit 1
            fi
            ;;
    esac
fi
echo "Using EvalHub host: $EVALHUB_HOST (namespace $EVALHUB_NAMESPACE)"

# If the tenant isn't the namespace EvalHub itself runs in, it needs to be set up as
# an EvalHub tenant before anything will run there. EvalHub has no reconciler that does
# this from a namespace label alone (no operator/controller watches for it) — the
# per-tenant resources below are static and normally hand-provisioned once, per tenant
# (e.g. via GitOps), so create them directly instead of waiting for something to notice.
if [ "$EVALHUB_TENANT" != "$EVALHUB_NAMESPACE" ]; then
    echo "Labeling namespace '$EVALHUB_TENANT' as an EvalHub tenant"
    oc label namespace "$EVALHUB_TENANT" evalhub.trustyai.opendatahub.io/tenant= --overwrite

    # 0. The NetworkPolicy guarding $EVALHUB_NAMESPACE only allows ingress from
    #    namespaces labeled as an OpenDataHub "application namespace" (the same label
    #    Data Science Projects get from the dashboard). Without it, the job's status
    #    callbacks to evalhub silently time out and the job stays "pending" forever
    #    even though it actually ran and produced a result.
    oc label namespace "$EVALHUB_TENANT" opendatahub.io/application-namespace=true --overwrite

    # 1. The service account evaluation Jobs run their pod as, plus the Role it needs
    #    to report status events back to EvalHub. Mirrors what already exists for
    #    other tenants (e.g. redhat-ods-applications, distribution-center).
    JOB_SA="evalhub-${EVALHUB_NAMESPACE}-job"
    echo "Creating job service account '$JOB_SA' in '$EVALHUB_TENANT'"
    oc apply -n "$EVALHUB_TENANT" -f - <<EOF
apiVersion: v1
kind: ServiceAccount
metadata:
  name: $JOB_SA
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ${JOB_SA}-access-role
rules:
  - apiGroups: ["trustyai.opendatahub.io"]
    resources: ["status-events"]
    verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ${JOB_SA}-access-rb
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: ${JOB_SA}-access-role
subjects:
  - kind: ServiceAccount
    name: $JOB_SA
    namespace: $EVALHUB_TENANT
EOF

    # 2. The job pod mounts a CA bundle ConfigMap by this fixed name. An empty
    #    ConfigMap with this annotation gets auto-populated by OpenShift's cluster-wide
    #    service-ca controller (standard pattern, not EvalHub-specific).
    echo "Creating evalhub-service-ca ConfigMap in '$EVALHUB_TENANT'"
    oc apply -n "$EVALHUB_TENANT" -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: evalhub-service-ca
  annotations:
    service.beta.openshift.io/inject-cabundle: "true"
EOF

    # 3. The evalhub-service account manages job resources (secrets, configmaps,
    #    pods/jobs, ...) in the tenant namespace to run the benchmark. Bind it to the
    #    built-in "edit" ClusterRole, scoped to just this namespace via a RoleBinding.
    echo "Granting evalhub-service (ns $EVALHUB_NAMESPACE) edit access in $EVALHUB_TENANT"
    oc apply -n "$EVALHUB_TENANT" -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: evalhub-service-edit
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
subjects:
  - kind: ServiceAccount
    name: evalhub-service
    namespace: $EVALHUB_NAMESPACE
EOF
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

cat > "$SCRIPT_DIR/.evalhub.env" <<EOF
EVALHUB_HOST=$EVALHUB_HOST
EVALHUB_TENANT=$EVALHUB_TENANT
EVALHUB_PROVIDER_ID=$PROVIDER_ID
EOF

read -r -s -p "Model API key for secret '$MODEL_SECRET' (leave blank to skip): " MODEL_API_KEY
echo
if [ -n "$MODEL_API_KEY" ]; then
    oc create secret generic "$MODEL_SECRET" -n "$EVALHUB_TENANT" \
        --from-literal=api-key="$MODEL_API_KEY" \
        --dry-run=client -o yaml | oc apply -f -
fi

echo "Install complete. Run ./run.sh to evaluate."
