#!/bin/bash
# Prepares a namespace as an EvalHub tenant. Must be run by a cluster admin: it labels
# the namespace (project admins can't patch namespaces) and creates Roles granting
# trustyai.opendatahub.io permissions, which RBAC escalation prevention blocks anyone
# who doesn't already hold them from creating. Safe to re-run. Afterwards, anyone with
# Contributor or Admin on the project can run ./install-evals.sh and submit evaluations.
#
# Usage: ./prepare-namespace-for-evals.sh <namespace>
set -eo pipefail

# EvalHub route host's namespace, i.e. where evalhub-service runs. Override via env, or
# set to empty to auto-discover from the EvalHub route.
EVALHUB_NAMESPACE=${EVALHUB_NAMESPACE-redhat-ods-applications}

[ -n "$1" ] || { echo "Usage: $0 <namespace>" >&2; exit 1; }
EVALHUB_TENANT=$1

command -v oc >/dev/null || { echo "oc is required and must be logged in (oc login ...)" >&2; exit 1; }
oc whoami >/dev/null 2>&1 || { echo "Not logged in to a cluster. Run 'oc login' first." >&2; exit 1; }
oc get namespace "$EVALHUB_TENANT" >/dev/null || exit 1
[ "$(oc auth can-i patch namespace/"$EVALHUB_TENANT" 2> /dev/null)" = "yes" ] || {
    echo "User '$(oc whoami)' can't modify namespace '$EVALHUB_TENANT'. Run this as a cluster admin." >&2
    exit 1
}

if [ -z "$EVALHUB_NAMESPACE" ]; then
    ROUTE_JSON=$(oc get route -A -l app=eval-hub -o json)
    case "$(jq '.items | length' <<< "$ROUTE_JSON")" in
        1)
            EVALHUB_NAMESPACE=$(jq -r '.items[0].metadata.namespace' <<< "$ROUTE_JSON")
            ;;
        0)
            echo "No EvalHub route found (label app=eval-hub). Set EVALHUB_NAMESPACE and rerun." >&2
            exit 1
            ;;
        *)
            echo "Multiple EvalHub routes found; set EVALHUB_NAMESPACE and rerun:" >&2
            jq -r '.items[] | "  \(.metadata.namespace)/\(.metadata.name): \(.spec.host)"' <<< "$ROUTE_JSON" >&2
            exit 1
            ;;
    esac
fi
echo "Preparing namespace '$EVALHUB_TENANT' for EvalHub (evalhub-service in '$EVALHUB_NAMESPACE')"

# If the tenant isn't the namespace EvalHub itself runs in, it needs to be set up as
# an EvalHub tenant before anything will run there. EvalHub has no reconciler that does
# this from a namespace label alone (no operator/controller watches for it) — the
# per-tenant resources below are static and normally hand-provisioned once, per tenant
# (e.g. via GitOps), so create them directly instead of waiting for something to notice.
if [ "$EVALHUB_TENANT" != "$EVALHUB_NAMESPACE" ]; then
    # The tenant label marks the namespace as an EvalHub tenant. The
    # application-namespace label is needed because the NetworkPolicy guarding
    # $EVALHUB_NAMESPACE only allows ingress from namespaces labeled as an
    # OpenDataHub "application namespace" (the same label Data Science Projects get
    # from the dashboard). Without it, the job's status callbacks to evalhub silently
    # time out and the job stays "pending" forever even though it actually ran and
    # produced a result.
    oc label namespace "$EVALHUB_TENANT" evalhub.trustyai.opendatahub.io/tenant= --overwrite
    oc label namespace "$EVALHUB_TENANT" opendatahub.io/application-namespace=true --overwrite

    # 1. The service account evaluation Jobs run their pod as, plus the Role it needs
    #    to report status events back to EvalHub. Mirrors what already exists for
    #    other tenants (e.g. redhat-ods-applications, distribution-center).
    JOB_SA="evalhub-${EVALHUB_NAMESPACE}-job"
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

    # 4. The job SA also needs to create/update MLflow experiments and runs (used
    #    when job.json sets "experiment") — the MLflow server's RBAC-backed proxy
    #    authorizes those calls via a SubjectAccessReview against mlflow.kubeflow.org
    #    resources, so without this the job fails with "MLflow save failed:
    #    PERMISSION_DENIED (HTTP 403)" even though the eval itself ran fine.
    oc apply -n "$EVALHUB_TENANT" -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ${JOB_SA}-mlflow-rb
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: mlflow-operator-mlflow-integration
subjects:
  - kind: ServiceAccount
    name: $JOB_SA
    namespace: $EVALHUB_TENANT
EOF
fi

# 5. EvalHub authorizes API calls with a SubjectAccessReview against
#    trustyai.opendatahub.io resources in the tenant namespace, which the built-in
#    admin/edit roles don't include. Aggregate them into "edit" (and so "admin"), the
#    ClusterRoles behind the OpenShift AI dashboard's project Contributor and Admin
#    permissions, so anyone with either can use EvalHub in their projects. This is
#    cluster-wide and only needs applying once, but is idempotent.
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: evalhub-evaluator
  labels:
    rbac.authorization.k8s.io/aggregate-to-admin: "true"
    rbac.authorization.k8s.io/aggregate-to-edit: "true"
rules:
  - apiGroups: [trustyai.opendatahub.io]
    resources: [evaluations, collections, providers]
    verbs: [get, list, create, update, delete]
EOF

echo "Namespace '$EVALHUB_TENANT' is ready. Next: ./install-evals.sh $EVALHUB_TENANT"
