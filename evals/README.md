# EvalHub Hello World

A minimal evaluation for EvalHub on OpenShift AI 3.5. It sends the model one prompt,
*"What is the capital of France?"*, and passes only if the answer mentions **Paris**.

There's no custom code or image to build. It uses the community
[promptfoo adapter](https://github.com/eval-hub/eval-hub-contrib/tree/main/adapters/promptfoo)
(`quay.io/evalhub/community-promptfoo`), and the prompt and assertion are passed in the job request.

| File | Purpose |
|------|---------|
| `provider.json` | Registers the promptfoo provider and its `promptfoo-eval` benchmark (primary score `pass_rate`, threshold 1.0) |
| `job.json` | Evaluation job request, including the model URL/name and the promptfoo prompt/test case |
| `optional/rbac.yaml` | Role and RoleBinding that let a non-admin *user* run evaluations in a project (only needed for non-admin users; see Prerequisites) |
| `install.sh` | One-time setup: discovers EvalHub, labels/provisions the tenant namespace if needed, registers the provider, and stores the model's API key as a Secret |
| `run.sh` | Submits the job to EvalHub, polls until it finishes, prints the result, and exits non-zero on failure |
| `run-local.sh` | Runs the same prompt/test straight against the model with the local `promptfoo` CLI — no EvalHub, no OpenShift |

`install.sh` discovers `EVALHUB_HOST` from the EvalHub route (`oc get route -A -l
app=eval-hub`) and `EVALHUB_TENANT` from your current `oc project`, then writes them
(plus the registered provider id) to `.evalhub.env` (gitignored) for `run.sh` to read.
Override the discovered host/tenant by exporting `EVALHUB_HOST`/`EVALHUB_TENANT` before
running `install.sh`. The model URL/name/secret are hardcoded directly in `job.json` —
edit that file in place if the model changes.

If the tenant namespace isn't the one EvalHub itself runs in, `install.sh` also
provisions it as a tenant directly (EvalHub has no controller that does this from a
namespace label alone — these are normally static, hand-provisioned resources):
- labels it as an EvalHub tenant (`evalhub.trustyai.opendatahub.io/tenant=`)
- labels it `opendatahub.io/application-namespace=true` — the NetworkPolicy guarding
  EvalHub's namespace only allows ingress from namespaces carrying this label (the same
  one Data Science Projects get from the dashboard). Without it, the job's status
  callbacks to EvalHub silently time out and the job stays reported as `pending`
  forever even though it actually ran and produced a result
- creates the `evalhub-<namespace>-job` service account evaluation Jobs run their pod
  as, plus the Role it needs to report status events back to EvalHub — without this,
  jobs sit stuck because the Job can't even create its pod
  (`FailedCreate: serviceaccount ... not found`)
- creates the `evalhub-service-ca` ConfigMap the job pod mounts for CA trust (an empty,
  annotated ConfigMap that OpenShift's service-ca controller auto-populates) — without
  this, the pod sits stuck at `Init:0/1` (`FailedMount: configmap ... not found`)
- binds the `evalhub-service` service account to the built-in `edit` ClusterRole there,
  since it needs to manage secrets/configmaps/pods in the tenant namespace to run the
  benchmark — without this, the job fails with a `... is forbidden` RBAC error

## The test

The benchmark parameters in `job.json` use promptfoo's own config format:

```json
"prompts": ["{{question}}"],
"tests": [
  {
    "description": "Capital of France",
    "vars": { "question": "What is the capital of France?" },
    "assert": [{ "type": "icontains", "value": "paris" }]
  }
]
```

`icontains` is a case-insensitive substring check. To add more checks, add entries to
`tests`. Any [promptfoo assertion type](https://www.promptfoo.dev/docs/configuration/expected-outputs/)
works (e.g. `regex`, `contains-any`, `javascript`). `pass_rate` is the fraction of test
cases that pass, and the 1.0 threshold means every one must pass.

## Prerequisites

- EvalHub enabled in OpenShift AI (an `EvalHub` CR, `trustyai.opendatahub.io/v1alpha1`)
- `oc` (logged in to the target cluster, with the desired project set as current), `jq`, `curl`
- Cluster-admin rights the first time you run `./install.sh` against a new tenant
  namespace (it labels the namespace and grants RBAC there — see above)
- For non-admin users: apply `optional/rbac.yaml` (after editing the namespace and user)

```bash
oc project my-project   # or redhat-ods-applications
oc apply -f optional/rbac.yaml
```

## Usage

```bash
./install.sh   # once: discovers EvalHub, registers the provider, prompts for the model's API key
./run.sh        # submits the job and prints pass/fail
```

To run against the model directly, without EvalHub or OpenShift at all (just `jq` and
`npx`/Node.js), use `run-local.sh` instead:

```bash
MODEL_API_KEY=... ./run-local.sh   # or omit MODEL_API_KEY and it'll prompt
```

It builds a `promptfoo` config from `job.json`'s `prompts`/`tests`/`model.url`, runs
`promptfoo eval` locally, and reports the same pass/fail using the configured threshold.
Raw results are written to `.eval-local.json` (gitignored).

Example output:

```
Submitted job 6f1c...
  state: pending
  state: running
  state: completed
{
  "state": "completed",
  "test": { "score": 1, "threshold": 1, "pass": true },
  "benchmarks": [ { "id": "promptfoo-eval", "metrics": { "pass_rate": 1, "n_passed": 1, ... } } ]
}

Test results:

[PASS] Capital of France
  Q: What is the capital of France?
  A: The capital of France is **Paris**.

PASS: all promptfoo assertions passed
```

`run.sh` prints the per-test breakdown (question, pass/fail, the model's actual
response, and the assertion failure reason when it fails) straight from the job
result's `results.benchmarks[].additional_info.promptfoo_eval_json` — this is the
same detail promptfoo itself produces, just surfaced directly instead of requiring
a trip through MLflow's or the OpenShift AI dashboard's UI (neither renders it as
more than a raw JSON artifact download).

### Model authentication

`install.sh` prompts for the model's API key and stores it as a Secret
(`gemma-4-api-key`) in the tenant namespace, referenced from `job.json` via
`model.auth.secret_ref`. Leave the prompt blank to skip creating/updating the secret.
`run-local.sh` instead takes the raw key directly via `MODEL_API_KEY` (or a prompt),
since there's no cluster to hold a Secret for it.

### MLflow tracking

Add `"experiment": {"name": "hello-world"}` to `job.json` to log the run (including
promptfoo's `eval.json`) to MLflow. This only takes effect if EvalHub is configured with
an MLflow tracking URI.

## Notes

- The promptfoo adapter is community-maintained, not Red Hat–supported.
- `provider.json` uses the `:latest` tag. To pin a specific digest for repeatable
  results, edit the `image` field directly and rerun `./install.sh`.
- Set `INSECURE=true` before running either script to skip TLS verification against
  a cluster with self-signed certs.
- `run-local.sh` pins the same promptfoo CLI version (`0.123.1`) the in-cluster adapter
  image currently uses, so local and EvalHub runs score identically.
- `job.json`'s `model.url` uses the short `/sandbox/gemma-4` path rather than the
  KServe-native `/publishers/sandbox/models/gemma-4` one (both route to the same
  backend) — the MaaS gateway's authorization only recognizes the two-segment
  `<namespace>/<model>` path form, so the longer form gets rejected with a 403.
