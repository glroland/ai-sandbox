# Evaluation CLI

Command-line version of the evaluation notebooks, for the **lm-evaluation-harness** benchmarks only
(`ifeval`, `math`, `mmlu`, `truthfulqa`, `reasoning`, `multilingual`). It talks to your model's
OpenAI-compatible `/chat/completions` endpoint, runs the same tasks with the same settings and pass marks as the
notebooks, prints a PASS / FAIL, and saves the same HTML dashboards.

Pure `pip` and a Python interpreter: no `uv`, no Jupyter.

| File | Purpose |
|---|---|
| `eval_cli.py` | All the code: `.env` + proxy handling, the `lm_eval` runner, the report/dashboard code, the CLI |
| `requirements.txt` | `lm-eval[api,ifeval,math]==0.4.12` and `matplotlib` |
| `Makefile` | `make install`, `make <benchmark>`, `make all`, `make scorecard` |
| `../dot_env.template` | Shared template: copy to `../.env` |
| `lm_eval_tasks/` | Custom task definitions (TruthfulQA, MGSM, Global-MMLU Lite) passed to `lm_eval --include_path` |

## Quick start

```bash
cp ../dot_env.template ../.env   # then set OPENAI_BASE_URL, OPENAI_MODEL, OPENAI_API_KEY (and the proxy if you need one)
make install                  # creates .venv and installs requirements.txt
make mmlu LIMIT=10            # smoke test: 10 questions per task
make mmlu                     # the full benchmark
make all                      # every benchmark
make scorecard                # latest score of each benchmark for the model in .env
```

Targets: `ifeval`, `math`, `mmlu`, `truthfulqa`, `reasoning`, `multilingual`, `all`, `scorecard`, `install`,
`clean` (raw output and caches), `distclean` (also the venv). Any target installs first if the venv is missing, and
reinstalls when `requirements.txt` changes. Use `make a b c` to run several in a row.

lm-eval 0.4.12 is tested with Python 3.12 (`make install PYTHON=python3.12` to pick the interpreter).

## Options

Pass as `make mmlu LIMIT=10 CONCURRENT=16`, or to the script directly: `python eval_cli.py run mmlu --limit 10`.

| Make variable | CLI flag | Meaning |
|---|---|---|
| `PYPI_INDEX` | `install --index-url URL` | Package index for `make install` (default `https://pypi.org/simple`; also settable in `.env`; empty = pip's own config) |
| `LIMIT` | `--limit N` | Questions per task (per language/subtask where there are several). Default: everything |
| `THRESHOLD` | `--threshold X` | Pass mark for a single benchmark (defaults: ifeval 0.6, math 0.1, mmlu 0.6, truthfulqa 0.5, reasoning 0.6, multilingual 0.6) |
| `CONCURRENT` | `--concurrent N` | Parallel requests to the model (default 8, or `NUM_CONCURRENT` in `.env`) |
| `MAX_GEN_TOKS` | `--max-gen-toks N` | Most tokens per answer (defaults: math 4096, reasoning and MGSM 2048, truthfulqa 64, Global-MMLU 32). A model that "thinks" before answering needs far more on truthfulqa |
| `STRICT=1` | `--strict` | Exit status 1 if any benchmark FAILs (handy for CI) |
| `RESULTS_DIR` | `--results-dir D` | Where reports go (default `../reports/`, or `RESULTS_DIR` in `.env`) |
| `ENV_FILE` | `--env-file F` | Use another env file |
| `ARGS` | | Anything else, e.g. `ARGS="--model foo --base-url https://host/v1"` |

`python eval_cli.py --help` and `python eval_cli.py run --help` list everything.

## Settings: `.env`

Same variables as the notebooks (see `dot_env.template`). `.env` is read from the current directory, then its parent (the shared `evals/.env`), then from this
folder; it is git-ignored. Precedence: command-line flags > `.env` > variables already in your shell.

| Variable | Meaning |
|---|---|
| `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY` | The model endpoint (key may be empty) |
| `PROXY_URL`, `NO_PROXY` | Optional proxy for pip, Hugging Face datasets and the model calls; `NO_PROXY` hosts bypass it |
| `PROXY_USERNAME`, `PROXY_PASSWORD` | Optional proxy login. Added to `PROXY_URL` and URL-encoded for you, so special characters are safe |
| `CA_BUNDLE` | Optional PEM file, only if the proxy re-signs HTTPS traffic |
| `PYPI_INDEX` | Index for `make install` (default `https://pypi.org/simple`, as in the notebooks; empty = pip's own config) |
| `NUM_CONCURRENT`, `RESULTS_DIR` | Defaults for the options above |

`make install` goes through `eval_cli.py`, so the proxy settings apply to pip too. As in the notebooks, lm-eval's
concurrent requests would ignore the proxy variables, so a small `sitecustomize.py` (written to `.eval-cli/proxy-patch/`)
makes them honour it. Nothing is patched when `PROXY_URL` is empty.

## Output

- **Reports:** `../reports/<model name>/<benchmark>.html` (the shared `evals/reports/` folder) (characters such as `/` in the model name become `_`), plus
  `../reports/<model name>/scorecard.json`. Runs of different models sit side by side; a re-run replaces that
  benchmark's page.
- **Raw lm-eval output:** `.eval-cli/<model name>/<task>/` (`results_*.json`, `samples_*.jsonl`), git-ignored.
- **Resuming:** completed requests are cached, so if a run dies partway, re-run the same command to resume. The cache
  is deleted after a successful run so the next run gets fresh answers.
