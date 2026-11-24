# Install and run the lm-evaluation-harness benchmarks from the command line.
#
#   make install            create .venv and install requirements.txt (uses the proxy in .env)
#   make mmlu               run one benchmark:  ifeval math mmlu truthfulqa reasoning multilingual
#   make all                run every benchmark
#   make mmlu LIMIT=10      quick smoke test: 10 questions per task
#   make scorecard          latest score of each benchmark for the model in .env
#   make help               more options
#
# Settings (model URL, name, key, proxy) come from .env - see ../dot_env.template.

PYTHON ?= python3
VENV   ?= .venv
PY     := $(VENV)/bin/python
CLI    := $(PY) eval_cli.py
STAMP  := $(VENV)/.installed

# Optional knobs, passed straight to the CLI:
#   PYPI_INDEX=https://my.mirror/simple  (package index for `make install`; default https://pypi.org/simple)
#   LIMIT=10  THRESHOLD=0.7  CONCURRENT=16  MAX_GEN_TOKS=4096  RESULTS_DIR=/some/dir  ENV_FILE=other.env  STRICT=1
#   ARGS="--model foo --base-url https://host/v1"   (anything else the CLI accepts)
RUN_FLAGS = $(if $(LIMIT),--limit $(LIMIT)) $(if $(THRESHOLD),--threshold $(THRESHOLD)) \
            $(if $(CONCURRENT),--concurrent $(CONCURRENT)) $(if $(MAX_GEN_TOKS),--max-gen-toks $(MAX_GEN_TOKS)) $(if $(TEMPERATURE),--temperature $(TEMPERATURE)) \
            $(if $(STRICT),--strict) $(if $(RESULTS_DIR),--results-dir $(RESULTS_DIR)) \
            $(if $(ENV_FILE),--env-file $(ENV_FILE)) $(ARGS)

BENCHMARKS := ifeval math mmlu truthfulqa reasoning multilingual

.PHONY: help install all scorecard clean distclean $(BENCHMARKS)

help:
	@sed -n '3,9p' Makefile | sed 's/^# \{0,1\}//'
	@echo
	@echo "Options (VAR=value): PYPI_INDEX (install) LIMIT THRESHOLD CONCURRENT MAX_GEN_TOKS RESULTS_DIR ENV_FILE STRICT ARGS"
	@echo "Base interpreter for the venv: PYTHON=$(PYTHON)   venv folder: VENV=$(VENV)"

$(PY):
	$(PYTHON) -m venv $(VENV)

# Reinstalls whenever requirements.txt changes. Runs through eval_cli.py so .env proxy settings apply to pip.
$(STAMP): requirements.txt | $(PY)
	$(CLI) install $(if $(ENV_FILE),--env-file $(ENV_FILE)) $(if $(PYPI_INDEX),--index-url $(PYPI_INDEX))
	touch $(STAMP)

install: $(STAMP)

$(BENCHMARKS): $(STAMP)
	$(CLI) run $@ $(RUN_FLAGS)

all: $(STAMP)
	$(CLI) run all $(RUN_FLAGS)

scorecard: $(STAMP)
	$(CLI) scorecard $(if $(RESULTS_DIR),--results-dir $(RESULTS_DIR)) $(if $(ENV_FILE),--env-file $(ENV_FILE)) $(ARGS)

# Remove raw lm-eval output and request caches (reports are kept).
clean:
	rm -rf .eval-cli __pycache__

# Also remove the virtualenv.
distclean: clean
	rm -rf $(VENV)
