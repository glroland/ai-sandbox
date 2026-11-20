# Evaluation notebooks

Small, self-contained Jupyter notebooks that evaluate a model served on Red Hat OpenShift AI (RHAIE). Each notebook talks directly to your model's OpenAI-compatible endpoint, runs a benchmark, and prints a **PASS / FAIL** result against a threshold you can change.

| Notebook | What it tests | Tool used |
|---|---|---|
| `run-ifeval.ipynb` | **Instruction following** — 541 prompts such as "use no commas" or "write at least 300 words", checked by code | lm-evaluation-harness |
| `run-math.ipynb` | **Hard competition maths** (MATH Level 5, 1,324 problems) | lm-evaluation-harness |
| `run-promptfoo.ipynb` | **Your own prompt tests** — a handful of sample questions with simple pass/fail checks, meant to be copied and adapted | promptfoo |

Everything runs on your own machine. No OpenShift login and no EvalHub are needed — only network access to the model.

## 1. Prerequisites

- Python with Jupyter (JupyterLab, VS Code, or any notebook client)
- [`uv`](https://docs.astral.sh/uv/) — for the two lm-evaluation-harness notebooks (`ifeval`, `math`)
- [Node.js](https://nodejs.org/) — for the promptfoo notebook only
- An OpenAI-compatible model endpoint (for example a model served with vLLM on OpenShift AI)

The evaluation tools themselves are downloaded automatically the first time a notebook runs.

## 2. Point the notebooks at your model

```bash
cp .env.template .env
```

Edit `.env`:

| Variable | Meaning |
|---|---|
| `OPENAI_BASE_URL` | Base URL of the endpoint, usually ending in `/v1` |
| `OPENAI_API_KEY` | API key or token. Leave empty if the endpoint has none |
| `OPENAI_MODEL` | Model name exactly as the endpoint reports it |

`.env` is listed in `.gitignore`, so your key is never committed. If there is no `.env` file, each notebook asks for these three values when you run it.

> Tip: to find the model name, run `curl $OPENAI_BASE_URL/models` (add `-H "Authorization: Bearer $OPENAI_API_KEY"` if you use a key).

## 3. Run a notebook

Open a notebook and run the cells top to bottom. Each one follows the same steps:

1. **Configuration** — loads `.env` and sets the benchmark options.
2. **Run** — sends the questions to your model and streams progress.
3. **Score** — prints the score and **PASS** or **FAIL**.

Options you may want to change, all in the configuration cell:

- `THRESHOLD` — the minimum score that counts as a PASS
- `LIMIT` — set to e.g. `10` for a quick test run; `None` runs the full benchmark (`ifeval`, `math`)
- `NUM_CONCURRENT` / `CONCURRENCY` — how many requests are sent to the model at once
- `TESTS` — your own prompts and checks (`run-promptfoo.ipynb`)

Start with `LIMIT = 10` to confirm your connection works; the full benchmarks can take a long time.

## Output files

Runs write results to `.eval-notebook-*` files in this folder (git-ignored). For the lm-evaluation-harness notebooks, `samples_*.jsonl` shows each question and the model's answer, which is useful for seeing what it got wrong.

## Troubleshooting

- **`uvx` / `npx` not found** — install `uv` or Node.js (see prerequisites).
- **Connection or 401/403 errors** — check `OPENAI_BASE_URL` and `OPENAI_API_KEY` in `.env`; the URL must be reachable from your machine.
- **Model not found** — `OPENAI_MODEL` must match the name the endpoint serves.
- **Run interrupted** — re-run the "Run" cell; the lm-evaluation-harness notebooks resume from where they stopped.
