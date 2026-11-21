# Evaluation notebooks

Small, self-contained Jupyter notebooks that evaluate a model served on Red Hat OpenShift AI (RHAIE). Each notebook talks directly to your model's OpenAI-compatible endpoint, runs a benchmark, and prints a **PASS / FAIL** result against a threshold you can change.

| Notebook | What it tests | Tool used |
|---|---|---|
| `run-ifeval.ipynb` | **Instruction following** — 541 prompts such as "use no commas" or "write at least 300 words", checked by code | lm-evaluation-harness |
| `run-math.ipynb` | **Hard competition maths** (MATH Level 5, 1,324 problems) | lm-evaluation-harness |
| `run-promptfoo.ipynb` | **Your own prompt tests** — a handful of sample questions with simple pass/fail checks, meant to be copied and adapted | promptfoo |
| `run-scorecard.ipynb` | **One-page summary** of the latest run of every notebook above | — |

Everything runs on your own machine. No OpenShift login and no EvalHub are needed — only network access to the model.

## 1. Prerequisites

- Python with Jupyter (JupyterLab, VS Code, or any notebook client)
- [`uv`](https://docs.astral.sh/uv/) — for the two lm-evaluation-harness notebooks (`ifeval`, `math`)
- [Node.js](https://nodejs.org/) — for the promptfoo notebook only
- An OpenAI-compatible model endpoint (for example a model served with vLLM on OpenShift AI)

The evaluation tools themselves are downloaded automatically the first time a notebook runs.

## 2. Point the notebooks at your model

```bash
cp dot_env.template .env
```

Edit `.env`:

| Variable | Meaning |
|---|---|
| `OPENAI_BASE_URL` | Base URL of the endpoint, usually ending in `/v1` |
| `OPENAI_API_KEY` | API key or token. Leave empty if the endpoint has none |
| `OPENAI_MODEL` | Model name exactly as the endpoint reports it |

`.env` is listed in `.gitignore`, so your key is never committed. If there is no `.env` file, each notebook asks for these three values when you run it.

**Behind a proxy?** Optionally add these to `.env` (see `dot_env.template`); they are applied to `uv`, Python, Hugging Face dataset downloads, `npm`/`npx`, promptfoo and the model calls:

| Variable | Meaning |
|---|---|
| `PROXY_URL` | Proxy for HTTP and HTTPS traffic, e.g. `http://proxy.example.com:3128` (may include `user:pass@`) |
| `NO_PROXY` | Comma-separated hosts that bypass the proxy, e.g. an in-network model endpoint |
| `CA_BUNDLE` | PEM file with your company root CA, if the proxy re-signs HTTPS traffic |

lm-evaluation-harness 0.4.12 ignores proxy settings for its concurrent model requests, so the benchmark notebooks write a tiny `sitecustomize.py` into `.eval-notebook-proxy-patch/` (git-ignored) that makes it honor them. Nothing is patched when `PROXY_URL` is empty.

> Tip: to find the model name, run `curl $OPENAI_BASE_URL/models` (add `-H "Authorization: Bearer $OPENAI_API_KEY"` if you use a key).

## 3. Run a notebook

Open a notebook and run the cells top to bottom. Each one follows the same steps:

1. **Configuration** — loads `.env` and sets the benchmark options.
2. **Run** — sends the questions to your model and streams progress.
3. **Score** — prints the score and **PASS** or **FAIL**.
4. **Results dashboard** — charts and failure analysis built from the run's output files (see below).

## What the dashboards show

A single score hides most of what a run learned. Each notebook ends with a dashboard drawn by `eval_report.py` (it sits next to the notebooks and needs only matplotlib, which is installed automatically on first use). Every score carries a 95% confidence interval, so you can tell a real difference from noise.

| Notebook | Beyond the headline score |
|---|---|
| `run-ifeval` | Strict vs. loose scoring (formatting near-misses), pass-rate as prompts carry more instructions, accuracy for each of the instruction types, and the worst failed prompts |
| `run-math` | Accuracy by subject, solution length vs. outcome, and whether each miss was a **wrong answer** or a solution that **ran out of tokens** before finishing |
| `run-mmlu` | Subject areas, all 57 subjects ranked against the random-guess line, a confusion matrix of answer letters, position bias, replies that were not a clean letter, and example misses |
| `run-promptfoo` | Latency, token use and output speed per test, every assertion on every test, and finish reasons |
| `run-scorecard` | Each benchmark's latest score, confidence interval and pass mark side by side |

Each run also records its result in `.eval-notebook-scorecard.json`, which the scorecard notebook reads.

Options you may want to change, all in the configuration cell:

- `THRESHOLD` — the minimum score that counts as a PASS
- `LIMIT` — set to e.g. `10` for a quick test run; `None` runs the full benchmark (`ifeval`, `math`)
- `MAX_GEN_TOKS` — the most tokens the model may write per answer (`run-math` only, default `4096`). The benchmark's own default of 1024 cuts off many worked solutions before the final answer and scores them wrong; set `None` to restore it
- `NUM_CONCURRENT` / `CONCURRENCY` — how many requests are sent to the model at once
- `TESTS` — your own prompts and checks (`run-promptfoo.ipynb`)

Start with `LIMIT = 10` to confirm your connection works; the full benchmarks can take a long time.

## Output files

Runs write results to `.eval-notebook-*` files in this folder (git-ignored). For the lm-evaluation-harness notebooks, `samples_*.jsonl` shows each question and the model's answer, which is useful for seeing what it got wrong; the dashboards are built from these files.

## Troubleshooting

- **`uvx` / `npx` not found** — install `uv` or Node.js (see prerequisites).
- **Connection or 401/403 errors** — check `OPENAI_BASE_URL` and `OPENAI_API_KEY` in `.env`; the URL must be reachable from your machine.
- **Behind a proxy / downloads time out** — set `PROXY_URL` (and `NO_PROXY` for hosts that must be reached directly) in `.env`. `certificate verify failed` errors usually mean the proxy re-signs HTTPS; set `CA_BUNDLE`.
- **Model not found** — `OPENAI_MODEL` must match the name the endpoint serves.
- **Run interrupted** — re-run the "Run" cell; the lm-evaluation-harness notebooks resume from where they stopped.
