# EvalHub Hello World

A minimal evaluation for EvalHub on OpenShift AI 3.5. It sends the model one prompt,
*"What is the capital of France?"*, and passes only if the answer mentions **Paris**.

There's no custom code or image to build. It uses the community
[promptfoo adapter](https://github.com/eval-hub/eval-hub-contrib/tree/main/adapters/promptfoo)
(`quay.io/evalhub/community-promptfoo`), and the prompt and assertion are passed in the job request.

| File | Purpose |
|------|---------|
| `provider.json` | Registers the promptfoo provider and its `promptfoo-eval` benchmark (primary score `pass_rate`, threshold 1.0) |
| `job.json` | Evaluation job request containing the promptfoo prompt and test case. `bin/run-eval.sh` fills in the model and provider id |
| `optional/rbac.yaml` | Role and RoleBinding that let a non-admin user run evaluations in a project |
| `bin/register-provider.sh` | Creates or updates the provider via the EvalHub API and prints its id |
| `bin/run-eval.sh` | Registers the provider if needed, submits the job, polls until it finishes, prints the result, and exits non-zero on failure |

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
- `oc`, `jq`, `curl`
- A model served with an OpenAI-compatible API (e.g. vLLM via KServe)
- To run in your own project instead of `redhat-ods-applications`: label it as an EvalHub
  tenant and, for non-admin users, apply `optional/rbac.yaml`

```bash
oc label namespace my-project evalhub.trustyai.opendatahub.io/tenant=
oc apply -f optional/rbac.yaml   # after editing the namespace and user
```

## Usage

```bash
cp bin/env.example bin/.env     # then set MODEL_URL and MODEL_NAME (and EVALHUB_TENANT if needed)
./bin/run-eval.sh
```

Example output:

```
Creating provider 'promptfoo'
Submitted job 6f1c...
  state: pending
  state: running
  state: completed
{
  "state": "completed",
  "test": { "score": 1, "threshold": 1, "pass": true },
  "benchmarks": [ { "id": "promptfoo-eval", "metrics": { "pass_rate": 1, "n_passed": 1, ... } } ]
}
PASS: all promptfoo assertions passed
```

### Model authentication

If the model endpoint requires a token, create a Secret with an `api-key` key in the
tenant namespace and set `MODEL_SECRET` in `bin/.env`:

```bash
oc create secret generic my-model-api-key -n redhat-ods-applications --from-literal=api-key="$TOKEN"
```

Without a secret, the promptfoo adapter sends a placeholder key (`not-required`), so this
only works for models that don't require auth. Because the header isn't empty, the sidecar
won't swap in the job's service account token either. Use a secret for any protected endpoint.

### MLflow tracking

Set `EXPERIMENT_NAME=hello-world` before running `bin/run-eval.sh` to log the run (including
promptfoo's `eval.json`) to MLflow. This only takes effect if EvalHub is configured with
an MLflow tracking URI.

## Notes

- The promptfoo adapter is community-maintained, not Red Hat–supported.
- `provider.json` uses the `:latest` tag. To keep results repeatable, set `PROMPTFOO_IMAGE`
  in `bin/.env` to a digest (`bin/env.example` has the one current as of 2026-11-06) and rerun
  `bin/register-provider.sh`.
