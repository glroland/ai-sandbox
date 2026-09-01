# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Black-box test suite for a deployed AI gateway. Tests call the gateway's live HTTP API (OpenAI-compatible endpoints) and assert on the response — there is no application code here, only test scripts and their shared config.

## Commands

Run the full suite:
```bash
./run-all.sh
```

Run a single test directly:
```bash
./test-openai-chat-completions.sh
```

There is no build step, package manager, or linter configured. Scripts are plain bash and must be executable (`chmod +x`).

## Configuration

- `env.example` is the source-controlled template of required config; copy it to `.env` for local/real values.
- `.env` is gitignored and holds the actual gateway endpoint, API key, model name, and timeout for the environment under test. It must exist for any test to run.
- Current variables: `GATEWAY_BASE_URL`, `GATEWAY_API_KEY`, `GATEWAY_MODEL`, `GATEWAY_TIMEOUT_SECONDS`.
- When a test needs a new config value, add it to both `env.example` (placeholder value) and `.env` (real value), never invent a second config file or hardcode values in a test script.

## Architecture / conventions

- **Test scripts**: every test file matches `test-*.sh`, is independently executable, and is self-contained — it sources `../.env` itself (via `set -a; source .env; set +a`) rather than relying on a shared harness. There is currently no shared helper library; keep it that way unless a second test reveals real duplication worth factoring out.
- **Exit codes**: a test must `exit 0` on pass and `exit 1` on any failure path (missing config, curl/network error, non-200 HTTP status, missing/malformed expected content in the response).
- **Output contract**: each test prints exactly one line to stdout, of the form `<PURPOSE>: PASS (...)` or `<PURPOSE>: FAIL (<reason>)`. `run-all.sh` and any human reading test output depends on this being a single line — always collapse multi-line error text (curl stderr, response bodies) with something like `tr '\n' ' '` before including it in the message.
- **Runner**: `run-all.sh` globs `test-*.sh` in its own directory (via `nullglob`), runs each as a subprocess, tallies pass/fail by exit code, prints a summary line, and exits non-zero overall if any test failed. Adding a new test requires no changes to `run-all.sh` — just drop a new `test-*.sh` file in the root that follows the conventions above.
