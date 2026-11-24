# EvalHub evaluations

Evaluations for EvalHub on OpenShift AI 3.5, run as managed jobs on the cluster, plus local runners that skip EvalHub. The "hello world" job (`job-basic.json`) sends the model one prompt,
*"What is the capital of France?"*, and passes only if the answer mentions **Paris**. `job-ifeval.json`, `job-mmlu.json` and `job-math.json` run standard lm-evaluation-harness benchmarks.

There's no custom code or image to build. It uses the community
[promptfoo adapter](https://github.com/eval-hub/eval-hub-contrib/tree/main/adapters/promptfoo)
(`quay.io/evalhub/community-promptfoo`), and the prompt and assertion are passed in the job request.

| File | Purpose |
|------|---------|
| `provider.json` | Registers the promptfoo provider and its `promptfoo-eval` benchmark (primary score `pass_rate`, threshold 1.0) |
| `provider-lm-eval.json` | Registers `lm-eval-standard`, a tenant copy of the built-in lm-evaluation-harness provider that adds the `mmlu_generative` benchmark (exact match, threshold 0.6) |
| `job-basic.json` | Hello-world job request: the model URL/name and the promptfoo prompts/test cases (threshold 1.0) |
| `job-ifeval.json` | Standard IFEval instruction-following benchmark, run by EvalHub's built-in LM Evaluation Harness provider (see [Instruction following (IFEval)](#instruction-following-ifeval)) |
| `job-mmlu.json` | MMLU (generative) via the `lm-eval-standard` provider registered by `install-evals.sh` (threshold 0.6) |
| `job-math.json` | MATH-hard (`leaderboard_math_hard`) via the built-in LM Evaluation Harness provider (threshold 0.1) |
| `optional/rbac.yaml` | Role and RoleBinding that give a single user EvalHub API access in one project (not needed when Contributor/Admin access from `prepare-namespace-for-evals.sh` is enough) |
| `prepare-namespace-for-evals.sh` | **Run as cluster admin**, once per namespace: labels/provisions it as an EvalHub tenant and gives project Contributors/Admins EvalHub API access |
| `install-evals.sh` | One-time setup as a project Contributor/Admin: checks the namespace was prepared, registers both providers (`provider.json`, `provider-lm-eval.json`), and stores the model's API key as a Secret |
| `run-remote.sh` | Submits the given job file (e.g. `job-basic.json`) to EvalHub, polls until it finishes, prints the result, and exits non-zero on failure |
| `run-ifeval-local.sh` | Runs IFEval locally with lm-evaluation-harness against the model's chat endpoint, with the chat template applied (see below) |
| `run-mmlu-local.sh` | Runs MMLU (generative, 5-shot, exact match) locally with lm-evaluation-harness against the model's chat endpoint, with the chat template applied. Takes a job file, e.g. `job-mmlu.json` |
| `run-promptfoo-local.sh` | Runs the job file's prompts/tests straight against the model with the local `promptfoo` CLI, no EvalHub or OpenShift |
| `load-env.sh` | Sourced by the scripts above: loads the shared `.env` and applies proxy settings (see [Settings](#settings-env)) |

The notebook versions of the local runners live in [`../notebooks`](../notebooks/README.md).

`prepare-namespace-for-evals.sh`, `install-evals.sh` and `run-remote.sh` take the tenant namespace as a required first argument. The EvalHub
host and the namespace EvalHub runs in are set at the top of each script (override by
exporting `EVALHUB_HOST`/`EVALHUB_NAMESPACE`, or setting them in `.env`). No local state is kept: `run-remote.sh` looks up
the registered promptfoo provider's id from EvalHub by name on each run. The model
URL/name/secret are hardcoded in each `job-*.json` — edit those files if the
model changes. (The local scripts can instead take the model from `.env`; see Settings.)

`install-evals.sh` fails up front, naming the exact `prepare-namespace-for-evals.sh`
command to hand a cluster admin, if the namespace hasn't been prepared or the current
user has no EvalHub API access there.

If the tenant namespace isn't the one EvalHub itself runs in,
`prepare-namespace-for-evals.sh` provisions it as a tenant directly (EvalHub has no
controller that does this from a namespace label alone — these are normally static,
hand-provisioned resources). A project admin can't do this: namespace labels and Roles
granting `trustyai.opendatahub.io` permissions both need cluster admin. It:
- labels it as an EvalHub tenant (`evalhub.trustyai.opendatahub.io/tenant=`)
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
- binds the job service account to `mlflow-operator-mlflow-integration` — without this,
  saving to MLflow fails with `PERMISSION_DENIED (HTTP 403)` even though the eval ran

It also creates the `evalhub-evaluator` ClusterRole, labeled to aggregate into the
built-in `edit` and `admin` ClusterRoles, which back the OpenShift AI dashboard's project
**Contributor** and **Admin** permissions. EvalHub authorizes every API call with a
SubjectAccessReview against `trustyai.opendatahub.io` resources (`providers`,
`evaluations`, `collections`), which `edit`/`admin` don't include by default — without
it, API calls fail with `403 Forbidden (user=..., verb=list, resource=providers)`. The
aggregation is cluster-wide (every project's Contributors/Admins get these permissions),
but EvalHub only runs evaluations in namespaces prepared as tenants.

## The test

The benchmark parameters in `job-basic.json` use promptfoo's own config format:

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
- `oc` (logged in to the target cluster), `jq`, `curl`
- A cluster admin to run `prepare-namespace-for-evals.sh` once per namespace
- Contributor or Admin on the project (granted from the OpenShift AI dashboard)

## Usage

```bash
# As cluster admin, once per namespace:
./prepare-namespace-for-evals.sh my-project

# As a project Contributor/Admin:
./install-evals.sh my-project   # once: registers the providers, prompts for the model's API key
./run-remote.sh my-project job-basic.json    # submits the job and prints pass/fail
```

To run against the model directly, without EvalHub or OpenShift at all (just `jq` and
`npx`/Node.js), use `run-promptfoo-local.sh` instead:

```bash
MODEL_API_KEY=... ./run-promptfoo-local.sh job-basic.json   # or omit MODEL_API_KEY and it'll prompt
```

It builds a `promptfoo` config from the job file's `prompts`/`tests`/`model.url`, runs
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

`run-remote.sh` prints the per-test breakdown (question, pass/fail, the model's actual
response, and the assertion failure reason when it fails) straight from the job
result's `results.benchmarks[].additional_info.promptfoo_eval_json` — this is the
same detail promptfoo itself produces, just surfaced directly instead of requiring
a trip through MLflow's or the OpenShift AI dashboard's UI (neither renders it as
more than a raw JSON artifact download).

### Instruction following (IFEval)

`job-ifeval.json` runs the standard [IFEval](https://arxiv.org/abs/2311.07911) benchmark
(541 prompts, 25 verifiable instruction types such as word counts, JSON output, required
or forbidden keywords, and casing). No custom tests are needed because it's already
registered in EvalHub as benchmark `ifeval` of the built-in `lm_evaluation_harness`
provider (Red Hat's `odh-ta-lmes-job` image). `install-evals.sh` doesn't register anything for it.

```bash
./run-remote.sh my-project job-ifeval.json
```

- The primary score is `inst_level_strict_acc`, which is the fraction of individual
  instructions followed exactly. The job also reports `prompt_level_strict_acc`, where
  every instruction in a prompt must be followed, and the `*_loose_acc` variants.
  The threshold is EvalHub's default for this benchmark: 0.6.
- The lm-eval adapter needs a Hugging Face tokenizer even when calling an
  OpenAI-compatible endpoint. `gemma-4` isn't a Hugging Face repo id, so `parameters.tokenizer`
  is set to `RedHatAI/gemma-4-E4B-it` (the model the service serves; not gated).
- The adapter appends `/completions` to `model.url` (or `/v1/completions` if the URL doesn't
  end in `/v1`), so either URL form works.
- **Caveat: the adapter always uses lm-eval's `local-completions` backend.** It sends raw
  text to `/v1/completions` without applying the model's chat template, and the job
  spec has no parameter to change that. Instruct/chat models like Gemma do much worse
  without their template, so scores here are lower than published IFEval numbers
  (which are measured with the chat template) and aren't comparable to them. They're
  still consistent run-to-run, so they work for regression tracking on the same model.
  The first concurrent batch of requests may also log `Internal Server Error`. lm-eval
  retries those automatically.

To get scores comparable to published IFEval numbers, run it locally through the chat
endpoint instead (needs `uv` and `jq`; no EvalHub or OpenShift):

```bash
MODEL_API_KEY=... ./run-ifeval-local.sh            # full 541 prompts
MODEL_API_KEY=... ./run-ifeval-local.sh --limit 10 # smoke test; extra args go to lm_eval
```

It reads the model URL/name, concurrency and threshold from `job-ifeval.json`, runs
lm-eval `0.4.13` (via `uvx`, so nothing gets installed globally) with the
`local-chat-completions` backend and `--apply_chat_template`, and reports pass/fail on
`inst_level_strict_acc`. Results and per-prompt samples are written to
`.eval-ifeval-local/` (gitignored). If a run dies partway through (e.g. `ServerDisconnectedError`
when the gateway drops a connection), run it again: completed requests are cached in
`.eval-ifeval-local-cache/` and only the remaining ones get sent. The cache is cleared
after a run that completes. On the same 10 prompts, gemma-4 scored 0.39 through
the EvalHub adapter and 0.94 locally.

Note that lm-eval logs the full request headers, including the `Authorization` bearer
token, when a request fails and is retried. Don't paste that output anywhere public.
- The job pod downloads the `google/IFEval` dataset and the tokenizer from Hugging Face
  at runtime. Disconnected clusters need them staged; see EvalHub's
  [disconnected cluster guide](https://eval-hub.github.io/guides/disconnected-cluster/).
- For a quick smoke test, add `"num_examples": 10` to the benchmark's `parameters`.
  That's useful for checking the setup, but the score isn't meaningful.
- `run-remote.sh` prints the metrics and pass/fail only. The per-prompt breakdown is
  promptfoo-specific.

### MMLU and MATH

```bash
./run-remote.sh my-project job-mmlu.json   # needs the lm-eval-standard provider from install-evals.sh
./run-remote.sh my-project job-math.json   # built-in provider, nothing to register
MODEL_API_KEY=... ./run-mmlu-local.sh job-mmlu.json --limit 10   # local, chat template applied
```

`job-mmlu.json` uses `mmlu_generative`, where the model generates the answer letter, so it works against
chat-completions endpoints. Like IFEval, the in-cluster adapter doesn't apply the chat template; the local script does
(5-shot, with a system instruction asking for just the letter) and writes to `.eval-mmlu-local/` (gitignored), with a
resumable request cache like the IFEval one.

### Model authentication

`install-evals.sh` prompts for the model's API key and stores it as a Secret
(`gemma-4-api-key`) in the tenant namespace; if `OPENAI_API_KEY` is set in `.env` it is used without prompting, referenced from the job files via
`model.auth.secret_ref`. Leave the prompt blank to skip creating/updating the secret.
The local scripts instead take the raw key from `OPENAI_API_KEY` in `.env`, `MODEL_API_KEY`, or a prompt,
since there's no cluster to hold a Secret for it.

### MLflow tracking

Add `"experiment": {"name": "hello-world"}` to a job file (`job-ifeval.json` and `job-math.json` already set one) to log the run (including
promptfoo's `eval.json`) to MLflow. This only takes effect if EvalHub is configured with
an MLflow tracking URI.

## Notes

- The promptfoo adapter is community-maintained, not Red Hat–supported.
- `provider.json` uses the `:latest` tag; `provider-lm-eval.json` pins the image by digest. To pin a specific digest for repeatable
  results, edit the `image` field directly and rerun `./install-evals.sh <namespace>`.
- Set `INSECURE=true` before running either script to skip TLS verification against
  a cluster with self-signed certs.
- `run-promptfoo-local.sh` pins the same promptfoo CLI version (`0.123.1`) the in-cluster adapter
  image currently uses, so local and EvalHub runs score identically.
- `job-basic.json`'s `model.url` uses the short `/sandbox/gemma-4` path rather than the
  KServe-native `/publishers/sandbox/models/gemma-4` one (both route to the same
  backend) — the MaaS gateway's authorization only recognizes the two-segment
  `<namespace>/<model>` path form, so the longer form gets rejected with a 403.

## Settings: `.env`

The local scripts and `install-evals.sh` read the shared `evals/.env` (template: `../dot_env.template`), looked up as `./.env` then `../.env`. `OPENAI_BASE_URL`, `OPENAI_MODEL` and `OPENAI_API_KEY` override the model in the job file (and replace the API key prompt); proxy settings and `EVALHUB_HOST` / `EVALHUB_NAMESPACE` / `EVALHUB_TOKEN` are also honoured.
