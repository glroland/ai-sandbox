# Model evaluations

Tools for answering one question: **is this model, served on an OpenAI-compatible endpoint (for example vLLM on
OpenShift AI), good enough?** Each tool runs benchmarks against the endpoint and reports PASS / FAIL against a
threshold, with scores, confidence intervals and an HTML dashboard.

There are three ways to run evaluations. They share one configuration file and one reports folder.

## Start with `cli/`

**`cli/` is the newest and most complete option. Use it unless you have a reason not to.** It is a plain Python
command line (pip and `make`, no `uv`, no Jupyter) that runs the lm-evaluation-harness benchmarks (IFEval, MATH,
MMLU, TruthfulQA, reasoning, multilingual) with the same settings and pass marks as the notebooks. It also saves
the same HTML dashboards, and it is easy to script or run in CI.

```bash
cp dot_env.template .env      # set OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY
cd cli
make install
make mmlu LIMIT=10            # quick smoke test
make all                      # every benchmark
make scorecard                # latest score of each benchmark
```

See [`cli/README.md`](cli/README.md) for the details.

## The other two

| Folder | What it is | When to use it |
|---|---|---|
| [`cli/`](cli/README.md) | **Recommended.** Command-line runner for the lm-evaluation-harness benchmarks. | Repeatable runs, scripts, CI, headless machines. |
| [`notebooks/`](notebooks/README.md) | Jupyter notebooks, one per benchmark, with inline charts and a `run-all` notebook. It covers everything the CLI does, plus **tool calling** (41 cases) and **promptfoo** (your own prompt tests). | Exploring results interactively, or running tool calling and promptfoo, which the CLI doesn't have. |
| [`evalhub/`](evalhub/README.md) | Scripts and job files for **EvalHub on OpenShift AI**: they register providers, submit jobs to the cluster and wait for the result. There are also local `run-*-local.sh` scripts for IFEval, MMLU and promptfoo. | Running evaluations on the cluster through EvalHub, as a managed job. Needs `oc` access. |

## Shared setup

- **Configuration:** one `.env` in this folder, created from [`dot_env.template`](dot_env.template). It holds the
  model URL, name and API key, plus optional proxy, CA bundle and run settings. Every tool looks for `./.env`, then
  `../.env`, so it works from any of the three subfolders. `.env` is git-ignored, so your key is never committed.
  Precedence is command-line flags, then `.env`, then your shell environment.
- **Results:** `reports/<model name>/` is written by both `cli/` and `notebooks/`, so runs of different models and
  tools sit side by side. Typical contents are `<benchmark>.html` dashboards and a `scorecard.json`. `evalhub/` jobs
  report back through EvalHub itself.
