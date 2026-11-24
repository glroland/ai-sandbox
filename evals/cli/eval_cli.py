#!/usr/bin/env python3
"""Command-line runner for the lm-evaluation-harness benchmarks (the CLI twin of the eval notebooks).

    python eval_cli.py install                 # pip-install requirements.txt (honours the proxy in .env)
    python eval_cli.py run mmlu --limit 10     # run one benchmark (quick smoke test)
    python eval_cli.py run all                 # run every benchmark
    python eval_cli.py scorecard               # print the latest score of each benchmark for the model

Benchmarks: ifeval, math, mmlu, truthfulqa, reasoning, multilingual.

Everything goes through `lm_eval` (EleutherAI lm-evaluation-harness), run with the Python interpreter
that runs this script. Settings come from a .env file (see dot_env.template), command-line flags
override it. Reports are written to <results-dir>/<model name>/<benchmark>.html.

This file needs only the standard library to start (so `install` works before anything is installed);
matplotlib is imported when a report is drawn.
"""
import argparse, base64, functools, html, io, json, os, re, shutil, statistics, subprocess, sys, time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, urlparse

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE / "lm_eval_tasks"          # custom lm-eval task definitions (truthfulqa, mgsm_chat, global_mmlu_lite)
WORK_DIR = HERE / ".eval-cli"               # raw lm-eval output + request cache, per model (git-ignored)
DEFAULT_RESULTS_DIR = HERE.parent / "reports"      # <results-dir>/<model name>/<benchmark>.html

LM_EVAL_VERSION = "0.4.12"                  # pinned in requirements.txt too, so results are repeatable
DEFAULT_CONCURRENT = 8                      # parallel requests to the model

# ---------------------------------------------------------------- benchmark definitions
# Each benchmark: the lm-eval run(s) it needs, the pass mark, and the report that draws its dashboard.
# `runs` entries: task, extra lm_eval flags. `max_gen_toks` is the default token budget per answer.
BENCHMARKS = {
    "ifeval": dict(
        title="IFEval - instruction following", threshold=0.6,
        runs=[dict(key="ifeval", task="ifeval")]),
    "math": dict(
        title="MATH Level 5 - hard competition maths", threshold=0.1,
        runs=[dict(key="math", task="leaderboard_math_hard", max_gen_toks=4096)]),
    "mmlu": dict(
        title="MMLU - broad knowledge (57 subjects)", threshold=0.6,
        runs=[dict(key="mmlu", task="mmlu_generative", num_fewshot=5,
                   system_instruction="Reply with only the letter of the correct answer (A, B, C, or D).")]),
    "truthfulqa": dict(
        title="TruthfulQA - resists falsehoods", threshold=0.5,
        runs=[dict(key="truthfulqa", task="truthfulqa_mc1_generative", include_tasks=True, max_gen_toks=64,
                   system_instruction="Reply with only the letter of the correct answer.")]),
    "reasoning": dict(
        title="Reasoning - GSM8K + Big-Bench Hard", threshold=0.6,
        runs=[dict(key="gsm8k", task="gsm8k_cot", max_gen_toks=2048),
              dict(key="bbh", task="bbh_cot_zeroshot", max_gen_toks=2048)]),
    "multilingual": dict(
        title="Multilingual - MGSM + Global-MMLU Lite", threshold=0.6,
        runs=[dict(key="mgsm", task="mgsm_chat", include_tasks=True, max_gen_toks=2048),
              dict(key="gmmlu", task="global_mmlu_lite_generative", include_tasks=True, num_fewshot=5, max_gen_toks=32,
                   system_instruction="Reply with only the letter of the correct answer (A, B, C, or D).")]),
}


# ---------------------------------------------------------------- .env and proxy
def load_env(path=None):
    """Read KEY=VALUE lines from a .env file into os.environ (the file wins over variables already set).

    Looks at `path` if given, else ./.env, then ../.env, then the same two next to this script
    (the shared .env lives in evals/, the parent of cli/). Returns the file used, or None."""
    candidates = [Path(path)] if path else [Path(".env"), Path("..") / ".env", HERE / ".env", HERE.parent / ".env"]
    p = next((c for c in candidates if c.is_file()), None)
    if p is None:
        if path:
            raise SystemExit(f"env file not found: {path}")
        return None
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")
    return p


def apply_proxy():
    """Export the proxy settings in the form every tool underneath reads them (pip, Hugging Face, the model calls).

    PROXY_URL is used for HTTP and HTTPS; NO_PROXY lists hosts that bypass it. PROXY_USERNAME / PROXY_PASSWORD
    add username/password (basic) authentication to PROXY_URL (percent-encoded, so special characters are safe).
    CA_BUNDLE is only for proxies that re-sign HTTPS traffic with a company CA."""
    url, no_proxy = os.environ.get("PROXY_URL", "").strip(), os.environ.get("NO_PROXY", "").strip()
    user, password = os.environ.get("PROXY_USERNAME", "").strip(), os.environ.get("PROXY_PASSWORD", "")
    if url and user and "@" not in url:
        scheme, sep, rest = url.partition("://")
        if not sep:
            scheme, rest = "http", url
        url = f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}@{rest}"
    if url:
        # The model endpoint is sent through the proxy too, unless its host is listed in NO_PROXY.
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[k] = url
        if no_proxy:
            for k in ("NO_PROXY", "no_proxy"):
                os.environ[k] = no_proxy
        print("Using proxy", url.split("@")[-1], "(NO_PROXY: " + (no_proxy or "none") + ")")
        # lm-eval 0.4.12 sends concurrent requests with aiohttp and never sets trust_env, so aiohttp would
        # ignore the variables above. This sitecustomize.py (loaded at start-up of the lm_eval process via
        # PYTHONPATH) makes every aiohttp.ClientSession trust them.
        patch_dir = WORK_DIR / "proxy-patch"
        patch_dir.mkdir(parents=True, exist_ok=True)
        (patch_dir / "sitecustomize.py").write_text(
            "try:\n"
            "    import aiohttp\n"
            "    _init = aiohttp.ClientSession.__init__\n"
            "    def __init__(self, *a, **kw):\n"
            "        kw.setdefault('trust_env', True)\n"
            "        _init(self, *a, **kw)\n"
            "    aiohttp.ClientSession.__init__ = __init__\n"
            "except ImportError:\n"
            "    pass\n")
        os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, [str(patch_dir), os.environ.get("PYTHONPATH")]))
    ca = os.environ.get("CA_BUNDLE", "").strip()
    if ca:
        ca = str(Path(ca).expanduser().resolve())
        for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "PIP_CERT"):
            os.environ[k] = ca
        print("Using CA bundle", ca)


def setup(args, need_model=True):
    """Load .env, apply flag overrides and the proxy; return (base_url, model, api_key)."""
    env_file = load_env(getattr(args, "env_file", None))
    print(f"Loaded settings from {env_file}" if env_file else "No .env file found (copy dot_env.template to .env)")
    for flag, var in (("base_url", "OPENAI_BASE_URL"), ("model", "OPENAI_MODEL"), ("api_key", "OPENAI_API_KEY")):
        if getattr(args, flag, None):
            os.environ[var] = getattr(args, flag)
    apply_proxy()
    if need_model:
        missing = [k for k in ("OPENAI_BASE_URL", "OPENAI_MODEL") if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Please set {', '.join(missing)} in .env or pass --base-url / --model (see dot_env.template)")
    return (os.environ.get("OPENAI_BASE_URL", "").rstrip("/"), os.environ.get("OPENAI_MODEL", ""),
            os.environ.get("OPENAI_API_KEY", ""))


def model_slug(model):
    """Folder name for a model: characters such as '/' become '_'."""
    return re.sub(r"[^\w.\-]+", "_", model).strip("._") or "unknown-model"


# ---------------------------------------------------------------- palette (light surface, validated set)
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#008300"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#ffffff"

RESULTS_DIR = DEFAULT_RESULTS_DIR   # set from --results-dir
MODEL = "unknown-model"             # set from the model being evaluated; names the report subfolder


def _plt():
    """Import matplotlib (headless backend) and apply the house style."""
    try:
        import matplotlib
        matplotlib.use("Agg")
    except ImportError:
        raise SystemExit("matplotlib is not installed - run `make install` (or `python eval_cli.py install`).")
    matplotlib.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2,
        "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "font.size": 10, "axes.titlesize": 11.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "figure.dpi": 110, "legend.frameon": False,
    })
    import matplotlib.pyplot as plt
    if not getattr(plt.show, "_records", False):
        plt.show = _recording_show()
    return plt


# ---------------------------------------------------------------- shared helpers
def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes in n trials - sound even for small n or scores near 0/1."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return min(p, max(0.0, centre - half)), max(p, min(1.0, centre + half))


def pct(x):
    return f"{100 * x:.1f}%"


def _dur(seconds):
    seconds = int(float(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


def _short(text, n=150):
    text = re.sub(r"\s+", " ", str(text)).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _load_results(output):
    f = sorted(Path(output).rglob("results_*.json"))[-1]
    return json.loads(f.read_text())


def _load_samples(output):
    """{task name: [sample dicts]} from every samples_*.jsonl under `output`."""
    out = {}
    for f in sorted(Path(output).rglob("samples_*.jsonl")):
        task = re.match(r"samples_(.+?)_\d{4}-\d\d-\d\dT[\d\-.]+\.jsonl$", f.name).group(1)
        out[task] = [json.loads(line) for line in f.read_text(encoding="utf-8").split("\n") if line.strip()]
    return out


def _host(url):
    return urlparse(url or "").netloc or "-"


def _card(plt, title, subtitle, headline, passed, threshold, lo_hi, facts):
    """Banner figure: big headline score, PASS/FAIL against the threshold, and run facts."""
    fig = plt.figure(figsize=(11, 2.35))
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    colour = GREEN if passed else ORANGE
    ax.add_patch(plt.Rectangle((0, 0), 0.008, 1, color=colour, transform=ax.transAxes))
    ax.text(0.03, 0.80, title, fontsize=17, fontweight="bold", va="center")
    ax.text(0.03, 0.62, subtitle, fontsize=10, color=INK2, va="center")
    ax.text(0.03, 0.30, headline, fontsize=34, fontweight="bold", color=INK, va="center")
    ax.text(0.03, 0.08, f"95% CI {pct(lo_hi[0])} – {pct(lo_hi[1])}   ·   threshold {pct(threshold)}",
            fontsize=9.5, color=INK2, va="center")
    ax.text(0.30, 0.30, ("✔ PASS" if passed else "✘ FAIL"), fontsize=20, fontweight="bold", color=colour, va="center")
    for i, (k, v) in enumerate(facts):
        ax.text(0.57, 0.88 - i * 0.135, k, fontsize=9, color=MUTED, va="center")
        ax.text(0.76, 0.88 - i * 0.135, v, fontsize=9, color=INK, va="center")
    plt.show()


def _hbar(ax, labels, vals, los, his, ns=None, colours=None, ref=None, ref_label=None, xlim=(0, 1.0), fs=9):
    """Horizontal bars with 95% CI whiskers and a value label (and n) at the end."""
    y = list(range(len(labels)))
    ax.barh(y, vals, color=colours or BLUE, height=0.62)
    ax.errorbar(vals, y, xerr=[[v - l for v, l in zip(vals, los)], [h - v for v, h in zip(vals, his)]],
                fmt="none", ecolor=INK2, elinewidth=1, capsize=2.5)
    for yi, v, h, n in zip(y, vals, his, ns or [None] * len(vals)):
        ax.text(min(h, xlim[1]) + 0.012, yi, f"{100 * v:.0f}%" + (f"  n={n}" if n is not None else ""),
                va="center", fontsize=fs, color=INK2)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=fs); ax.invert_yaxis()
    ax.set_xlim(*xlim); ax.set_xticks([t / 5 for t in range(6)]); ax.xaxis.set_major_formatter(lambda x, _: f"{100 * x:.0f}%"); ax.grid(axis="y", visible=False)
    if ref is not None:
        ax.axvline(ref, color=MUTED, linestyle=(0, (4, 3)), linewidth=1)
        if ref_label:
            ax.text(ref, -0.9, ref_label, fontsize=8, color=MUTED, ha="center", va="bottom")



# ---------------------------------------------------------------- IFEval
def report_ifeval(output, threshold):
    plt = _plt()
    res = _load_results(output)
    samples = next(iter(_load_samples(output).values()))
    n = len(samples)
    secs = float(res.get("total_evaluation_time_seconds") or 0)

    # Per-instruction records
    recs = []  # (instruction id, strict, loose, prompt idx, n instructions in prompt)
    for i, s in enumerate(samples):
        ids = s["doc"]["instruction_id_list"]
        for iid, st, lo in zip(ids, s["inst_level_strict_acc"], s["inst_level_loose_acc"]):
            recs.append((iid, bool(st), bool(lo), i, len(ids)))
    n_inst = len(recs)
    inst_strict = sum(r[1] for r in recs); inst_loose = sum(r[2] for r in recs)
    pr_strict = sum(bool(s["prompt_level_strict_acc"]) for s in samples)
    pr_loose = sum(bool(s["prompt_level_loose_acc"]) for s in samples)
    score = inst_strict / n_inst

    mname = res.get("model_name", "?")
    words = [len(s["resps"][0][0].split()) for s in samples]
    _card(plt, "IFEval · instruction following", f"{mname} @ {_host(res['config']['model_args'].get('base_url'))}",
          pct(score), score >= threshold, threshold, wilson(inst_strict, n_inst),
          [("Prompts / instructions", f"{n} / {n_inst}"), ("Wall-clock time", _dur(secs)),
           ("Throughput", f"{n / secs:.2f} prompts/s" if secs else "-"),
           ("Median response", f"{statistics.median(words):.0f} words"),
           ("lm-eval", res.get("lm_eval_version", "?"))])

    # Fig: four metrics + difficulty by instructions-per-prompt
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.3), gridspec_kw={"width_ratios": [1.15, 1]})
    rows = [("Prompt-level, strict", pr_strict, n), ("Prompt-level, loose", pr_loose, n),
            ("Instruction-level, strict", inst_strict, n_inst), ("Instruction-level, loose", inst_loose, n_inst)]
    cis = [wilson(k, m) for _, k, m in rows]
    _hbar(a, [r[0] for r in rows], [k / m for _, k, m in rows], [c[0] for c in cis], [c[1] for c in cis],
          colours=[BLUE, "#7fb0ec", BLUE, "#7fb0ec"], ref=threshold, ref_label="threshold", xlim=(0, 1.12))
    a.set_title("Four ways to score the same answers")
    near = sum(1 for r in recs if r[2] and not r[1])
    a.text(0, 4.35, f"{near} instruction(s) failed strict but passed loose — right idea, small formatting slip.",
           fontsize=8.5, color=INK2, transform=a.transData)
    by_k = defaultdict(lambda: [0, 0])
    for s in samples:
        k = min(len(s["doc"]["instruction_id_list"]), 3)
        by_k[k][1] += 1; by_k[k][0] += bool(s["prompt_level_strict_acc"])
    ks = sorted(by_k)
    labels = [f"{k}{'+' if k == 3 else ''} instruction{'s' if k > 1 else ''}" for k in ks]
    vals = [by_k[k][0] / by_k[k][1] for k in ks]
    ci = [wilson(*by_k[k]) for k in ks]
    _hbar(b, labels, vals, [c[0] for c in ci], [c[1] for c in ci], ns=[by_k[k][1] for k in ks], xlim=(0, 1.2))
    b.set_title("Pass-rate by instructions per prompt")
    fig.tight_layout(); plt.show()

    # Fig: every instruction type
    per = defaultdict(lambda: [0, 0])
    for iid, st, *_ in recs:
        per[iid][1] += 1; per[iid][0] += st
    order = sorted(per, key=lambda k: per[k][0] / per[k][1])
    vals = [per[k][0] / per[k][1] for k in order]
    ci = [wilson(*per[k]) for k in order]
    fig, ax = plt.subplots(figsize=(11, 0.27 * len(order) + 1.2))
    _hbar(ax, [k.replace(":", " · ") for k in order], vals, [c[0] for c in ci], [c[1] for c in ci],
          ns=[per[k][1] for k in order], colours=[ORANGE if v < score - 0.05 else BLUE for v in vals],
          ref=score, ref_label=f"overall {pct(score)}", xlim=(0, 1.18), fs=8.5)
    ax.set_title("Accuracy by instruction type (strict) — orange: >5 points below overall")
    fig.tight_layout(); plt.show()

    # Failure gallery
    bad = [(sum(not x for x in s["inst_level_strict_acc"]), i) for i, s in enumerate(samples) if not s["prompt_level_strict_acc"]]
    bad.sort(reverse=True)
    print(f"Prompts with at least one missed instruction: {len(bad)} of {n}. The worst offenders:\n")
    for k, i in bad[:6]:
        s = samples[i]
        missed = [iid for iid, ok in zip(s["doc"]["instruction_id_list"], s["inst_level_strict_acc"]) if not ok]
        print(f"  ✘ missed {', '.join(missed)}")
        print(f"      prompt:   {_short(s['doc']['prompt'], 170)}")
        print(f"      response: {_short(s['resps'][0][0], 170)}\n")

    _save_scorecard("ifeval", {"title": "IFEval", "what": "instruction following", "score": score,
                               "ci": wilson(inst_strict, n_inst), "threshold": threshold, "n": n,
                               "model": mname, "seconds": secs})


# ---------------------------------------------------------------- MATH
def report_math(output, threshold):
    plt = _plt()
    res = _load_results(output)
    tasks = _load_samples(output)
    samples = [s for t in tasks.values() for s in t]
    n = len(samples)
    secs = float(res.get("total_evaluation_time_seconds") or 0)
    ok = sum(bool(s["exact_match"]) for s in samples)
    score = ok / n
    cap = next(iter(res["configs"].values()))["generation_kwargs"].get("max_gen_toks")
    lens = [len(s["resps"][0][0]) for s in samples]
    mname = res.get("model_name", "?")
    _card(plt, "MATH Level 5 · competition mathematics", f"{mname} @ {_host(res['config']['model_args'].get('base_url'))}",
          pct(score), score >= threshold, threshold, wilson(ok, n),
          [("Problems", f"{n}"), ("Wall-clock time", _dur(secs)),
           ("Throughput", f"{n / secs:.2f} problems/s" if secs else "-"),
           ("Median solution", f"{statistics.median(lens):,.0f} characters"),
           ("Token budget per answer", f"{cap} tokens" if cap else "-")])

    subj = defaultdict(lambda: [0, 0, []])
    for s in samples:
        d = subj[s["doc"]["type"]]; d[1] += 1; d[0] += bool(s["exact_match"]); d[2].append(len(s["resps"][0][0]))
    order = sorted(subj, key=lambda k: -subj[k][0] / subj[k][1])
    vals = [subj[k][0] / subj[k][1] for k in order]; ci = [wilson(subj[k][0], subj[k][1]) for k in order]

    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.6), gridspec_kw={"width_ratios": [1.1, 1]})
    _hbar(a, order, vals, [c[0] for c in ci], [c[1] for c in ci], ns=[subj[k][1] for k in order],
          colours=[ORANGE if v < score - 0.1 else BLUE for v in vals], ref=score, ref_label=f"overall {pct(score)}", xlim=(0, 1.2))
    a.set_title("Accuracy by subject")

    # Solution length vs. outcome: a pile-up at the right edge means the token budget cut answers short.
    bins = 12; top = max(lens) or 1; width = top / bins
    good = [0] * bins; badc = [0] * bins
    for s, L in zip(samples, lens):
        idx = min(int(L / width), bins - 1)
        (good if s["exact_match"] else badc)[idx] += 1
    xs = [(i + 0.5) * width for i in range(bins)]
    b.bar(xs, good, width=width * 0.86, color=BLUE, label="correct")
    b.bar(xs, badc, width=width * 0.86, bottom=good, color=ORANGE, label="incorrect")
    b.set_title("Solution length vs. outcome"); b.set_xlabel("response length (characters)"); b.set_ylabel("problems")
    b.legend(loc="upper left"); b.grid(axis="x", visible=False)
    fig.tight_layout(); plt.show()

    # Accuracy by length quartile
    ranked = sorted(zip(lens, [bool(s["exact_match"]) for s in samples]))
    q = max(1, len(ranked) // 4)
    quarts = [ranked[i * q:(i + 1) * q if i < 3 else None] for i in range(4)]
    print("Accuracy by solution length (quartiles of response length):")
    for name, part in zip(("shortest 25%", "25–50%", "50–75%", "longest 25%"), quarts):
        k = sum(c for _, c in part)
        print(f"  {name:<13} {pct(k / len(part)):>6}   ({part[0][0]:,}–{part[-1][0]:,} chars)")
    print("  → long solutions are usually harder problems; if the longest bucket also sits at the "
          f"{cap}-token budget, raise it before blaming the model.\n" if cap else "")

    # Why did it miss? "No final answer" means the solution ran out of tokens mid-working.
    bad = [s for s in samples if not s["exact_match"]]
    unfinished = [s for s in bad if not re.search(r"final answer is", s["resps"][0][0], re.I)]
    wrong = [s for s in bad if s not in unfinished]
    answered = n - len(unfinished)
    print(f"{len(bad)} of {n} problems missed:")
    print(f"  • {len(wrong)} gave a final answer that was wrong")
    print(f"  • {len(unfinished)} never reached a final answer — the solution was still working when it stopped"
          + (f" (budget: {cap} tokens)" if cap else ""))
    if unfinished and answered:  # (answered is 0 when nothing finished)
        print(f"  When it did finish, accuracy was {pct((answered - len(wrong)) / answered)} "
              f"({answered - len(wrong)}/{answered}); a larger token budget could lift the headline toward that.\n")
    print("A sample of misses (expected answer vs. the end of the model's working):\n")
    for s in (wrong[:3] + unfinished[:2]):
        tag = "wrong answer" if s in wrong else "ran out of tokens"
        print(f"  ✘ [{s['doc']['type']} · {tag}] {_short(s['doc']['problem'], 150)}")
        print(f"      expected: {s['target']}")
        print(f"      model ended: …{_short(s['resps'][0][0][-140:], 140)}\n")

    _save_scorecard("math", {"title": "MATH Level 5", "what": "competition mathematics", "score": score,
                             "ci": wilson(ok, n), "threshold": threshold, "n": n, "model": mname, "seconds": secs})


# ---------------------------------------------------------------- MMLU
def report_mmlu(output, threshold):
    plt = _plt()
    res = _load_results(output)
    tasks = _load_samples(output)
    samples_all = [s for t in tasks.values() for s in t]
    n = len(samples_all)
    ok = sum(bool(s["exact_match"]) for s in samples_all)
    score = ok / n
    secs = float(res.get("total_evaluation_time_seconds") or 0)
    mname = res.get("model_name", "?")

    # subject -> category, via the group structure lm-eval recorded
    cat_of = {}
    for g, subs in res.get("group_subtasks", {}).items():
        if "::" in g:
            for t in subs:
                cat_of[t] = g.split("::")[1]
    letters = "ABCD"
    def pred(s):
        p = re.sub(r"[^A-Za-z]", "", s["resps"][0][0]).upper()
        return p if len(p) == 1 and p in letters else "?"  # len check: "" and "AB" are substrings of "ABCD"
    bare = sum(pred(s) != "?" for s in samples_all)

    _card(plt, "MMLU · knowledge across 57 subjects", f"{mname} @ {_host(res['config']['model_args'].get('base_url'))}",
          pct(score), score >= threshold, threshold, wilson(ok, n),
          [("Questions / subjects", f"{n:,} / {len(tasks)}"), ("Wall-clock time", _dur(secs)),
           ("Throughput", f"{n / secs:.1f} questions/s" if secs else "-"),
           ("Replied with a bare letter", pct(bare / n)),
           ("Few-shot examples", str(res["n-shot"].get(next(iter(tasks)), "?")))])

    # Categories + the full 57-subject ranking
    cat = defaultdict(lambda: [0, 0]); subj = {}
    for t, ss in tasks.items():
        k = sum(bool(s["exact_match"]) for s in ss); m = len(ss)
        name = t.replace("mmlu_", "").replace("_generative", "")
        subj[name] = (k, m)
        c = cat_of.get(t, "all"); cat[c][0] += k; cat[c][1] += m
    corder = sorted(cat, key=lambda c: -cat[c][0] / cat[c][1])
    fig, ax = plt.subplots(figsize=(11, 0.55 * len(corder) + 1.2))
    cv = [cat[c][0] / cat[c][1] for c in corder]; cc = [wilson(*cat[c]) for c in corder]
    _hbar(ax, [c.replace("other", "other (business, health, misc.)").replace("stem", "STEM") for c in corder], cv,
          [c[0] for c in cc], [c[1] for c in cc], ns=[cat[c][1] for c in corder], ref=0.25, ref_label="random guess 25%", xlim=(0, 1.2))
    ax.set_title("Accuracy by subject area"); fig.tight_layout(); plt.show()

    order = sorted(subj, key=lambda s: -subj[s][0] / subj[s][1])
    vals = [subj[s][0] / subj[s][1] for s in order]; ci = [wilson(*subj[s]) for s in order]
    fig, ax = plt.subplots(figsize=(11, 0.22 * len(order) + 1.2))
    _hbar(ax, [s.replace("_", " ") for s in order], vals, [c[0] for c in ci], [c[1] for c in ci],
          colours=[ORANGE if v < score - 0.15 else BLUE for v in vals], ref=0.25, ref_label="random guess 25%",
          xlim=(0, 1.1), fs=7.5)
    ax.axvline(score, color=INK2, linewidth=1)
    ax.set_title(f"All {len(order)} subjects, best to worst — orange: >15 points below overall ({pct(score)})")
    fig.tight_layout(); plt.show()

    # Answer-letter behaviour: confusion matrix + format compliance
    cols = list(letters) + ["?"]
    mat = [[0] * 5 for _ in range(4)]
    for s in samples_all:
        mat[letters.index(s["target"])][cols.index(pred(s))] += 1
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [1.1, 1]})
    row_tot = [sum(r) or 1 for r in mat]
    im = a.imshow([[v / t for v in r] for r, t in zip(mat, row_tot)], cmap="Blues", vmin=0, vmax=1)
    for i in range(4):
        for j in range(5):
            frac = mat[i][j] / row_tot[i]
            a.text(j, i, f"{mat[i][j]}\n{100 * frac:.0f}%", ha="center", va="center", fontsize=8.5,
                   color="white" if frac > 0.55 else INK)
    a.set_xticks(range(5)); a.set_xticklabels(["A", "B", "C", "D", "no letter"]); a.set_yticks(range(4)); a.set_yticklabels(list(letters))
    a.set_xlabel("model answered"); a.set_ylabel("correct answer"); a.grid(False)
    a.set_title("Confusion matrix (row = correct letter)")
    gold = Counter(s["target"] for s in samples_all); got = Counter(pred(s) for s in samples_all)
    x = range(4); w = 0.38
    b.bar([i - w / 2 for i in x], [gold[l] / n for l in letters], width=w, color=MUTED, label="correct answers")
    b.bar([i + w / 2 for i in x], [got[l] / n for l in letters], width=w, color=BLUE, label="model's answers")
    b.set_xticks(list(x)); b.set_xticklabels(list(letters)); b.yaxis.set_major_formatter(lambda v, _: f"{100 * v:.0f}%")
    b.set_title("Letter distribution — position bias?"); b.legend(); b.grid(axis="x", visible=False)
    fig.tight_layout(); plt.show()
    if got["?"]:
        print(f"⚠ {got['?']} of {n} replies ({pct(got['?'] / n)}) contained no clean A–D letter and were scored wrong — "
              "check the system instruction / few-shot setting if this is high.\n")

    bad = [s for s in samples_all if not s["exact_match"]]
    print(f"{len(bad)} questions missed. A sample:\n")
    for s in bad[:5]:
        d = s["doc"]
        print(f"  ✘ [{d['subject'].replace('_', ' ')}] {_short(d['question'], 150)}")
        print(f"      correct {s['target']}: {_short(d['choices'][letters.index(s['target'])], 70)}")
        p = pred(s)
        print(f"      model   {p}: {_short(d['choices'][letters.index(p)], 70) if p != '?' else _short(s['resps'][0][0], 70)}\n")

    _save_scorecard("mmlu", {"title": "MMLU", "what": "broad knowledge", "score": score, "ci": wilson(ok, n),
                             "threshold": threshold, "n": n, "model": mname, "seconds": secs})



# ---------------------------------------------------------------- shared by the newer reports
LANGUAGES = {"ar": "Arabic", "bn": "Bengali", "de": "German", "en": "English", "es": "Spanish", "fr": "French",
             "hi": "Hindi", "id": "Indonesian", "it": "Italian", "ja": "Japanese", "ko": "Korean",
             "pt": "Portuguese", "ru": "Russian", "sw": "Swahili", "te": "Telugu", "th": "Thai",
             "yo": "Yoruba", "zh": "Chinese"}


def _secs(res):
    return float(res.get("total_evaluation_time_seconds") or 0)


def _rows(samples, flt=None):
    """Sample rows, optionally only those scored by one named filter (lm-eval repeats rows per filter)."""
    return [x for x in samples if flt is None or x.get("filter") == flt]


def _acc(rows):
    k = sum(bool(x["exact_match"]) for x in rows)
    return k, len(rows)


def _cap(res):
    return next(iter(res["configs"].values()))["generation_kwargs"].get("max_gen_toks")


# ---------------------------------------------------------------- TruthfulQA
def report_truthfulqa(output, threshold):
    plt = _plt()
    res = _load_results(output)
    samples = next(iter(_load_samples(output).values()))
    n = len(samples); k = sum(bool(x["exact_match"]) for x in samples); score = k / n
    secs, mname = _secs(res), res.get("model_name", "?")
    chance = statistics.mean(1 / x["doc"]["n_options"] for x in samples)
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def pred(x):
        p = str(x["filtered_resps"][0]).strip()
        return p if len(p) == 1 and p in letters else "?"
    bare = sum(pred(x) != "?" for x in samples)

    _card(plt, "TruthfulQA · common falsehoods", f"{mname} @ {_host(res['config']['model_args'].get('base_url'))}",
          pct(score), score >= threshold, threshold, wilson(k, n),
          [("Questions", f"{n}"), ("Wall-clock time", _dur(secs)),
           ("Random guessing would score", pct(chance)), ("Replied with a clean letter", pct(bare / n)),
           ("lm-eval", res.get("lm_eval_version", "?"))])

    by_type = defaultdict(lambda: [0, 0])
    by_opts = defaultdict(lambda: [0, 0])
    by_cat = defaultdict(lambda: [0, 0])
    for x in samples:
        d = x["doc"]; ok = bool(x["exact_match"])
        for table, key in ((by_type, d.get("qtype", "Unknown")), (by_cat, d.get("category", "Unknown")),
                           (by_opts, "2–3 options" if d["n_options"] <= 3 else "4 options" if d["n_options"] == 4
                            else "5–6 options" if d["n_options"] <= 6 else "7+ options")):
            table[key][0] += ok; table[key][1] += 1

    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.2))
    rows = [("All questions", (k, n))] + [(f"{t} questions", tuple(v)) for t, v in sorted(by_type.items()) if t != "Unknown"]
    ci = [wilson(*v) for _, v in rows]
    _hbar(a, [r for r, _ in rows], [v[0] / v[1] for _, v in rows], [c[0] for c in ci], [c[1] for c in ci],
          ns=[v[1] for _, v in rows], colours=[BLUE] + [ORANGE if r.startswith("Adv") else "#7fb0ec" for r, _ in rows[1:]],
          ref=chance, ref_label="random guess", xlim=(0, 1.22))
    a.set_title("Adversarial = written to fool models")
    order = [o for o in ("2–3 options", "4 options", "5–6 options", "7+ options") if o in by_opts]
    ci = [wilson(*by_opts[o]) for o in order]
    _hbar(b, order, [by_opts[o][0] / by_opts[o][1] for o in order], [c[0] for c in ci], [c[1] for c in ci],
          ns=[by_opts[o][1] for o in order], xlim=(0, 1.22))
    b.set_title("Accuracy by number of options")
    fig.tight_layout(); plt.show()

    big = {c: v for c, v in by_cat.items() if v[1] >= 8}
    other = [0, 0]
    for c, v in by_cat.items():
        if c not in big:
            other[0] += v[0]; other[1] += v[1]
    if other[1]:
        big["Other (small categories)"] = other
    order = sorted(big, key=lambda c: -big[c][0] / big[c][1])
    ci = [wilson(*big[c]) for c in order]
    fig, ax = plt.subplots(figsize=(11, max(2.4, 0.28 * len(order) + 1.2)))
    _hbar(ax, order, [big[c][0] / big[c][1] for c in order], [c[0] for c in ci], [c[1] for c in ci], ns=[big[c][1] for c in order],
          colours=[ORANGE if big[c][0] / big[c][1] < score - 0.15 else BLUE for c in order], ref=score, ref_label=f"overall {pct(score)}",
          xlim=(0, 1.22), fs=8.5)
    ax.set_title("Accuracy by topic — orange: >15 points below overall")
    fig.tight_layout(); plt.show()

    wrong = [x for x in samples if not x["exact_match"] and pred(x) != "?"]
    wrong.sort(key=lambda x: x["doc"].get("qtype") != "Adversarial")
    print(f"{n - k} questions missed ({len(wrong)} picked a false statement, {n - k - len(wrong)} gave no clean letter). Examples:\n")
    for x in wrong[:6]:
        d = x["doc"]
        opt = {ln[0]: ln[3:] for ln in d["options"].split("\n")}
        print(f"  ✘ [{d.get('category', '?')}] {_short(d['question'], 150)}")
        print(f"      model chose  {pred(x)}: {_short(opt.get(pred(x), ''), 90)}")
        print(f"      true answer  {x['target']}: {_short(opt.get(x['target'], ''), 90)}\n")
    _save_scorecard("truthfulqa", {"title": "TruthfulQA", "what": "resists falsehoods", "score": score, "ci": wilson(k, n),
                                   "threshold": threshold, "n": n, "model": mname, "seconds": secs})


# ---------------------------------------------------------------- reasoning (GSM8K + BBH)
def report_reasoning(gsm_output, bbh_output, threshold):
    plt = _plt()
    gres, bres = _load_results(gsm_output), _load_results(bbh_output)
    gs = [x for t in _load_samples(gsm_output).values() for x in t]
    bt = _load_samples(bbh_output)
    bs = [x for t in bt.values() for x in t]
    FLEX, STRICT = "flexible-extract", "strict-match"
    g_flex, g_strict = _acc(_rows(gs, FLEX)), _acc(_rows(gs, STRICT))
    b_flex = _acc(_rows(bs, FLEX))
    gsm, bbh = g_flex[0] / g_flex[1], b_flex[0] / b_flex[1]
    score = (gsm + bbh) / 2
    lo = (wilson(*g_flex)[0] + wilson(*b_flex)[0]) / 2; hi = (wilson(*g_flex)[1] + wilson(*b_flex)[1]) / 2
    secs = _secs(gres) + _secs(bres); mname = gres.get("model_name", "?")
    lens = [len(x["resps"][0][0]) for x in _rows(gs, FLEX) + _rows(bs, FLEX)]
    _card(plt, "Reasoning · GSM8K + Big-Bench Hard", f"{mname} @ {_host(gres['config']['model_args'].get('base_url'))}",
          pct(score), score >= threshold, threshold, (lo, hi),
          [("Problems", f"{g_flex[1]:,} GSM8K + {b_flex[1]:,} BBH"), ("Wall-clock time", _dur(secs)),
           ("Throughput", f"{(g_flex[1] + b_flex[1]) / secs:.2f} problems/s" if secs else "-"),
           ("Median working", f"{statistics.median(lens):,.0f} characters"),
           ("Token budget per answer", f"{_cap(bres)} tokens" if _cap(bres) else "-")])

    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 3.4), gridspec_kw={"width_ratios": [1.15, 1]})
    rows = [("GSM8K · lenient answer match", g_flex), ("GSM8K · strict 'The answer is…'", g_strict),
            ("BBH · lenient answer match", b_flex)]
    ci = [wilson(*v) for _, v in rows]
    _hbar(a, [r for r, _ in rows], [v[0] / v[1] for _, v in rows], [c[0] for c in ci], [c[1] for c in ci],
          colours=[BLUE, "#7fb0ec", BLUE], ref=threshold, ref_label="threshold", xlim=(0, 1.15), fs=8.5)
    a.set_title("Lenient vs. strict scoring")
    a.text(0, 3.4, "Strict scoring wants the exact phrase \"The answer is…\"; lenient reads the final answer.", fontsize=8.5, color=INK2)
    ranked = sorted(zip(lens, [bool(x["exact_match"]) for x in _rows(gs, FLEX) + _rows(bs, FLEX)]))
    q = max(1, len(ranked) // 4)
    parts = [ranked[i * q:(i + 1) * q if i < 3 else None] for i in range(4)]
    names = ["shortest 25%", "25–50%", "50–75%", "longest 25%"]
    vals = [sum(c for _, c in p) / len(p) for p in parts]; ci = [wilson(sum(c for _, c in p), len(p)) for p in parts]
    _hbar(b, names, vals, [c[0] for c in ci], [c[1] for c in ci], ns=[len(p) for p in parts], colours=BLUE, xlim=(0, 1.25))
    b.set_title("Accuracy by length of working")
    fig.tight_layout(); plt.show()

    sub = {t.replace("bbh_cot_zeroshot_", "").replace("_", " "): _acc(_rows(v, FLEX)) for t, v in bt.items()}
    order = sorted(sub, key=lambda t: -sub[t][0] / sub[t][1]); ci = [wilson(*sub[t]) for t in order]
    fig, ax = plt.subplots(figsize=(11, 0.27 * len(order) + 1.2))
    _hbar(ax, order, [sub[t][0] / sub[t][1] for t in order], [c[0] for c in ci], [c[1] for c in ci], ns=[sub[t][1] for t in order],
          colours=[ORANGE if sub[t][0] / sub[t][1] < bbh - 0.2 else BLUE for t in order], ref=bbh, ref_label=f"BBH overall {pct(bbh)}",
          xlim=(0, 1.2), fs=8.5)
    ax.set_title(f"All {len(order)} BBH tasks — orange: >20 points below the BBH average")
    fig.tight_layout(); plt.show()

    print(f"On GSM8K, strict scoring would have dropped {pct(g_flex[0] / g_flex[1] - g_strict[0] / g_strict[1])}: "
          "correct answers that were not phrased as \"The answer is …\". The headline uses lenient scoring.\n")
    miss = [x for x in _rows(bs, FLEX) if not x["exact_match"]]
    print(f"{len(miss)} of {b_flex[1]} BBH problems missed. A few:\n")
    for x in miss[:4]:
        print(f"  ✘ {_short(x['doc']['input'], 150)}")
        print(f"      expected: {_short(x['target'], 60)}    model: {_short(x['filtered_resps'][0], 60)}\n")
    _save_scorecard("reasoning", {"title": "Reasoning", "what": "GSM8K + BBH", "score": score, "ci": (lo, hi),
                                  "threshold": threshold, "n": g_flex[1] + b_flex[1], "model": mname, "seconds": secs})


# ---------------------------------------------------------------- multilingual (MGSM + Global-MMLU Lite)
def report_multilingual(mgsm_output, gmmlu_output, threshold):
    plt = _plt()
    mres, gres = _load_results(mgsm_output), _load_results(gmmlu_output)

    def by_lang(output):
        out = {}
        for t, rows in _load_samples(output).items():
            out[t.rsplit("_", 1)[1]] = rows
        return out
    mg, gm = by_lang(mgsm_output), by_lang(gmmlu_output)
    macc = {l: _acc(r) for l, r in mg.items()}; gacc = {l: _acc(r) for l, r in gm.items()}
    m_all = (sum(v[0] for v in macc.values()), sum(v[1] for v in macc.values()))
    g_all = (sum(v[0] for v in gacc.values()), sum(v[1] for v in gacc.values()))
    mscore, gscore = m_all[0] / m_all[1], g_all[0] / g_all[1]
    score = (mscore + gscore) / 2
    lo = (wilson(*m_all)[0] + wilson(*g_all)[0]) / 2; hi = (wilson(*m_all)[1] + wilson(*g_all)[1]) / 2
    secs = _secs(mres) + _secs(gres); mname = mres.get("model_name", "?")
    _card(plt, "Multilingual · many languages", f"{mname} @ {_host(mres['config']['model_args'].get('base_url'))}",
          pct(score), score >= threshold, threshold, (lo, hi),
          [("Languages", f"{len(macc)} (MGSM) · {len(gacc)} (Global-MMLU Lite)"), ("Questions", f"{m_all[1]:,} + {g_all[1]:,}"),
           ("Wall-clock time", _dur(secs)), ("MGSM (maths word problems)", pct(mscore)), ("Global-MMLU Lite (knowledge)", pct(gscore))])

    def lang_bars(ax, acc, title):
        order = sorted(acc, key=lambda l: -acc[l][0] / acc[l][1]); ci = [wilson(*acc[l]) for l in order]
        _hbar(ax, [LANGUAGES.get(l, l) for l in order], [acc[l][0] / acc[l][1] for l in order], [c[0] for c in ci], [c[1] for c in ci],
              ns=[acc[l][1] for l in order], colours=[GREEN if l == "en" else BLUE for l in order], xlim=(0, 1.25), fs=8.5)
        ax.set_title(title)
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 0.3 * max(len(macc), len(gacc)) + 1.4))
    lang_bars(a, macc, "Maths word problems (MGSM)"); lang_bars(b, gacc, "Knowledge (Global-MMLU Lite)")
    fig.suptitle("Accuracy by language — green: English", x=0.01, ha="left", fontsize=10, color=INK2)
    fig.tight_layout(); plt.show()

    # Gap to English: how much does each language lose?
    def gaps(acc):
        if "en" not in acc:
            return {}
        en = acc["en"][0] / acc["en"][1]
        return {l: 100 * (v[0] / v[1] - en) for l, v in acc.items() if l != "en"}
    mgap, ggap = gaps(macc), gaps(gacc)
    langs = sorted(set(mgap) | set(ggap), key=lambda l: statistics.mean([d[l] for d in (mgap, ggap) if l in d]))
    if langs:
        fig, ax = plt.subplots(figsize=(11, 0.34 * len(langs) + 1.4))
        y = range(len(langs)); h = 0.38
        ax.barh([i - h / 2 for i in y], [mgap.get(l, 0) for l in langs], height=h, color=BLUE, label="MGSM (maths)")
        ax.barh([i + h / 2 for i in y], [ggap.get(l, 0) for l in langs], height=h, color="#7fb0ec", label="Global-MMLU Lite (knowledge)")
        ax.set_yticks(list(y)); ax.set_yticklabels([LANGUAGES.get(l, l) for l in langs], fontsize=9); ax.invert_yaxis()
        for i, l in enumerate(langs):
            for off, d in ((-h / 2, mgap), (h / 2, ggap)):
                if l in d and abs(d[l]) >= 0.5:
                    ax.text(d[l] - 0.4, i + off, f"{d[l]:+.0f}", va="center", ha="right", fontsize=8, color=INK2)
        ax.axvline(0, color=INK2, linewidth=1); ax.grid(axis="y", visible=False)
        ax.xaxis.set_major_formatter(lambda v, _: f"{v:+.0f} pts"); ax.legend(loc="lower left")
        ax.set_title("Gap to English (percentage points) — how much each language loses")
        fig.tight_layout(); plt.show()

    # Culturally sensitive vs culturally agnostic questions
    cs = defaultdict(lambda: {"CS": [0, 0], "CA": [0, 0]})
    for l, rows in gm.items():
        for x in rows:
            lab = x["doc"].get("cultural_sensitivity_label")
            if lab in ("CS", "CA"):
                cs[l][lab][0] += bool(x["exact_match"]); cs[l][lab][1] += 1
    if cs:
        order = sorted(cs, key=lambda l: -(cs[l]["CA"][0] + cs[l]["CS"][0]) / max(1, cs[l]["CA"][1] + cs[l]["CS"][1]))
        fig, ax = plt.subplots(figsize=(11, 3.4))
        x = range(len(order)); w = 0.38
        ax.bar([i - w / 2 for i in x], [cs[l]["CA"][0] / max(1, cs[l]["CA"][1]) for l in order], width=w, color=BLUE, label="culturally agnostic")
        ax.bar([i + w / 2 for i in x], [cs[l]["CS"][0] / max(1, cs[l]["CS"][1]) for l in order], width=w, color=ORANGE, label="culturally sensitive")
        ax.set_xticks(list(x)); ax.set_xticklabels([LANGUAGES.get(l, l) for l in order], rotation=45, ha="right", fontsize=8.5)
        ax.yaxis.set_major_formatter(lambda v, _: f"{100 * v:.0f}%"); ax.set_ylim(0, 1.05); ax.grid(axis="x", visible=False); ax.legend(loc="lower left")
        ca = [sum(cs[l]["CA"][i] for l in cs) for i in (0, 1)]; cso = [sum(cs[l]["CS"][i] for l in cs) for i in (0, 1)]
        gap = ca[0] / ca[1] - cso[0] / cso[1]
        verdict = "culture-specific questions are harder" if gap > 0.02 else "no clear gap between the two kinds"
        ax.set_title(f"Culturally agnostic {pct(ca[0] / ca[1])} vs. sensitive {pct(cso[0] / cso[1])} — {verdict}")
        fig.tight_layout(); plt.show()

    # Format check: answers that could not be read (e.g. local-script digits)
    problems = []
    for name, tasks in (("MGSM", mg), ("Global-MMLU Lite", gm)):
        for l, rows in tasks.items():
            bad = sum(1 for x in rows if str(x["filtered_resps"][0]).strip() in ("[invalid]", ""))
            if bad / len(rows) > 0.02:
                problems.append((name, LANGUAGES.get(l, l), bad, len(rows)))
    if problems:
        print("⚠ Answers that could not be read (scored wrong) — worth a look, these may be formatting rather than ability:")
        for name, lang, bad, tot in sorted(problems, key=lambda p: -p[2] / p[3]):
            print(f"   {name:<17} {lang:<11} {bad}/{tot} ({pct(bad / tot)})")
    else:
        print("✔ Every language's answers could be read (under 2% unparseable).")
    worst = sorted(macc, key=lambda l: macc[l][0] / macc[l][1])[:2] + sorted(gacc, key=lambda l: gacc[l][0] / gacc[l][1])[:2]
    print("\nWeakest languages:", ", ".join(dict.fromkeys(LANGUAGES.get(l, l) for l in worst)))
    _save_scorecard("multilingual", {"title": "Multilingual", "what": "MGSM + Global-MMLU Lite", "score": score, "ci": (lo, hi),
                                     "threshold": threshold, "n": m_all[1] + g_all[1], "model": mname, "seconds": secs})





def _report_folder(model):
    return Path(RESULTS_DIR) / model_slug(model)


def _scorecard_file():
    return _report_folder(MODEL) / "scorecard.json"


def _save_scorecard(key, entry):
    f = _scorecard_file()
    try:
        data = json.loads(f.read_text()) if f.exists() else {}
    except ValueError:
        data = {}
    data[key] = entry
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=1))


def show_scorecard():
    """Print the latest score of every benchmark that has been run for the current model."""
    f = _scorecard_file()
    data = json.loads(f.read_text()) if f.exists() else {}
    if not data:
        print(f"No results yet for {MODEL} - run at least one benchmark first ({f.parent}).")
        return
    print(f"Scorecard - {MODEL}   (last run of each benchmark)")
    for d in sorted(data.values(), key=lambda d: -d["score"]):
        print(f"  {d['title']:<14} {pct(d['score']):>6}  {'PASS' if d['score'] >= d['threshold'] else 'FAIL'}  "
              f"(95% CI {pct(d['ci'][0])}-{pct(d['ci'][1])}, threshold {pct(d['threshold'])}, "
              f"n={d['n']:,}, took {_dur(d['seconds'])})")


# ---------------------------------------------------------------- saving each report to <model name>/
_PARTS = None  # while a report_*() runs: ordered ("text", str) / ("img", base64 png) pieces of what it showed


def _recording_show():
    """Stand-in for plt.show(): keep each figure as a PNG for the HTML page, then close it."""
    def wrapper(*a, **kw):
        import matplotlib.pyplot as plt
        for num in plt.get_fignums():
            buf = io.BytesIO()
            plt.figure(num).savefig(buf, format="png", dpi=110, bbox_inches="tight")
            if _PARTS is not None:
                _PARTS.append(("img", base64.b64encode(buf.getvalue()).decode()))
        plt.close("all")
    wrapper._records = True
    return wrapper


class _Tee:
    """Passes writes through to stdout and keeps a copy in _PARTS."""
    def __init__(self, out):
        self.out = out

    def write(self, text):
        if text:
            if _PARTS and _PARTS[-1][0] == "text":
                _PARTS[-1] = ("text", _PARTS[-1][1] + text)
            else:
                _PARTS.append(("text", text))
        return self.out.write(text)

    def __getattr__(self, name):
        return getattr(self.out, name)


def _recorded(name):
    """Decorator: run a report_*() function, then write everything it showed to <model>/<name>.html."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            global _PARTS
            _PARTS, real_stdout = [], sys.stdout
            sys.stdout = _Tee(real_stdout)
            try:
                result = fn(*a, **kw)
            finally:
                sys.stdout, parts, _PARTS = real_stdout, _PARTS, None
            body = "".join(f"<pre>{html.escape(v)}</pre>" if k == "text" else f'<img src="data:image/png;base64,{v}">'
                           for k, v in parts)
            folder = _report_folder(MODEL)
            folder.mkdir(parents=True, exist_ok=True)
            out = folder / f"{name}.html"
            out.write_text(
                "<!doctype html><meta charset=utf-8>"
                f"<title>{html.escape(name)} - {html.escape(MODEL)}</title>"
                "<style>body{font:14px system-ui;max-width:1100px;margin:2em auto;padding:0 1em}"
                "pre{white-space:pre-wrap;font:12.5px ui-monospace,monospace}img{max-width:100%}</style>"
                f"<h1>{html.escape(name)}</h1><p>Model: <b>{html.escape(MODEL)}</b> &middot; "
                f"{time.strftime('%Y-%m-%d %H:%M:%S')}</p>{body}", encoding="utf-8")
            print(f"Report saved to {out}")
            return result
        return wrapper
    return deco


for _name in [n for n in list(globals()) if n.startswith("report_")]:
    globals()[_name] = _recorded(_name[len("report_"):])(globals()[_name])


# ---------------------------------------------------------------- running lm_eval
def run_lm_eval(run, base_url, model, api_key, work, concurrent, limit, max_gen_toks):
    """Run one lm-evaluation-harness task and return the folder holding its results and samples.

    Completed requests are cached, so if the run dies partway, re-running resumes where it stopped;
    the cache is deleted after a successful run so the next run gets fresh answers from the model."""
    task = run["task"]
    output = work / task
    cache = work / f"{task}-cache" / "requests"
    cache.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(output, ignore_errors=True)
    cmd = [sys.executable, "-m", "lm_eval", "--model", "local-chat-completions",
           "--model_args", f"model={model},base_url={base_url}/chat/completions,"
                           f"num_concurrent={concurrent},max_retries=5,tokenized_requests=False",
           "--tasks", task, "--apply_chat_template", "--log_samples",
           "--output_path", str(output), "--use_cache", str(cache)]
    if run.get("include_tasks"):
        cmd += ["--include_path", str(TASKS_DIR)]
    if run.get("num_fewshot") is not None:
        cmd += ["--num_fewshot", str(run["num_fewshot"])]
    if run.get("system_instruction"):
        cmd += ["--system_instruction", run["system_instruction"]]
    toks = max_gen_toks if max_gen_toks is not None else run.get("max_gen_toks")
    if toks:
        cmd += ["--gen_kwargs", f"max_gen_toks={toks}"]
    if limit:
        cmd += ["--limit", str(limit)]
    print(f"\n$ lm_eval --tasks {task}" + (f" --limit {limit}" if limit else ""), flush=True)
    log = work / f"{task}.log"
    rc, n_errors, first_error = _run_quiet(cmd, {**os.environ, "OPENAI_API_KEY": api_key or "not-required"}, log)
    if rc != 0:
        _explain_failure(task, rc, n_errors, first_error, log, cache, limit)
    shutil.rmtree(cache.parent, ignore_errors=True)
    return output


# Lines lm-eval prints for every failed request / retry; hundreds appear when the endpoint is down.
_NOISE = re.compile(r"Retry attempt|Exception:|API request failed|Session is closed|Traceback|^\s+(File |raise |await |async )|"
                    r"Error\b|ConnectionRefused|Cannot connect|Task exception was never retrieved", re.I)
_ERROR_LINE = re.compile(r"Exception:|API request failed|Status code|Cannot connect|\w+Error:", re.I)


def _run_quiet(cmd, env, log):
    """Run lm_eval, keeping the full output in `log`. The console gets a live progress line and the normal
    messages, but not the per-request error spam. Returns (exit code, error-line count, first error line)."""
    n_errors, first_error, shown_progress = 0, "", False
    with open(log, "wb") as f, subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
        buf = b""
        while True:
            chunk = os.read(proc.stdout.fileno(), 4096)
            if not chunk:
                break
            f.write(chunk)
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", "replace").rstrip()
                if not line:
                    continue
                m = _ERROR_LINE.search(line)
                if m:
                    n_errors += 1
                    if not first_error:
                        first_error = line[line.rfind("]", 0, m.start()) + 1:] if "it/s]" in line[:m.start()] else line
                    continue
                if "it/s]" in line or "s/it]" in line or "%|" in line:   # tqdm progress: redraw in place
                    print("\r" + line[:110].ljust(110), end="", flush=True)
                    shown_progress = True
                elif not _NOISE.search(line):
                    print(("\n" if shown_progress else "") + line, flush=True)
                    shown_progress = False
        if shown_progress:
            print(flush=True)
    return proc.returncode, n_errors, first_error


def _explain_failure(task, rc, n_errors, first_error, log, cache, limit):
    """Stop with one clear message instead of the raw error cascade."""
    done = 0
    try:
        import sqlite3  # lm-eval's cache is a sqlitedict file
        for db in cache.parent.glob("requests_rank*.db"):
            with sqlite3.connect(db) as c:
                done += c.execute("select count(*) from unnamed").fetchone()[0]
    except Exception:
        pass
    lines = [f"lm_eval exited with {rc} while running {task}."]
    if first_error:
        lines.append(f"First error ({n_errors} error lines in all): {first_error.strip()[:300]}")
    lines.append(f"Full log: {log}")
    lines.append(f"Answers saved so far: {done}" if done else "No answers were saved, so a re-run starts from the beginning.")
    lines.append("No report was written for this benchmark. Fix the cause and re-run the same command to resume"
                 + (" from the saved answers." if done else "."))
    raise SystemExit("\n" + "\n".join(lines))


def check_endpoint(base_url, model, api_key):
    """Send one tiny request before starting, so a dead endpoint fails in seconds with one clear line."""
    import urllib.request, urllib.error
    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps({"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}).encode(),
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})})
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode("utf-8", "replace")
        raise SystemExit(f"Model endpoint {base_url} answered HTTP {e.code} {e.reason}: {body}\nNothing was run.")
    except Exception as e:
        raise SystemExit(f"Model endpoint {base_url} is unreachable ({type(e).__name__}: {e}).\nNothing was run.")
    print("Endpoint check: OK", flush=True)


def _exact_match(output, task, key=None):
    scores = _load_results(output)["results"][task]
    return scores[key] if key else next(v for k, v in scores.items() if k.startswith("exact_match,"))


def run_benchmark(name, args, base_url, model, api_key):
    """Run every lm_eval task of one benchmark, print the score and PASS/FAIL, write the HTML report.

    Returns True if the benchmark passed."""
    spec = BENCHMARKS[name]
    threshold = args.threshold if args.threshold is not None else spec["threshold"]
    work = WORK_DIR / model_slug(model)
    print(f"\n=== {spec['title']} ===", flush=True)
    out = {r["key"]: run_lm_eval(r, base_url, model, api_key, work, args.concurrent, args.limit, args.max_gen_toks)
           for r in spec["runs"]}

    def report(fn, *a):
        try:
            fn(*a, threshold)
        except Exception as e:  # the raw results are kept, so a charting problem never costs a finished run
            print(f"WARNING: could not write the {name} report ({type(e).__name__}: {e}); raw results are in {work}")

    if name == "ifeval":
        scores = _load_results(out["ifeval"])["results"]["ifeval"]
        print(json.dumps({k.split(",")[0]: v for k, v in scores.items()
                          if k.endswith(",none") and not k.startswith("alias")}, indent=2))
        score, label = scores["inst_level_strict_acc,none"], "inst_level_strict_acc"
        report(report_ifeval, out["ifeval"])
    elif name == "math":
        score, label = _exact_match(out["math"], "leaderboard_math_hard"), "exact_match"
        print(f"exact_match: {score:.3f}")
        report(report_math, out["math"])
    elif name == "mmlu":
        score, label = _exact_match(out["mmlu"], "mmlu_generative"), "exact_match"
        print(f"exact_match: {score:.3f}")
        report(report_mmlu, out["mmlu"])
    elif name == "truthfulqa":
        score, label = _exact_match(out["truthfulqa"], "truthfulqa_mc1_generative"), "exact_match"
        print(f"exact_match: {score:.3f}")
        report(report_truthfulqa, out["truthfulqa"])
    elif name == "reasoning":
        gsm = _exact_match(out["gsm8k"], "gsm8k_cot", "exact_match,flexible-extract")
        bbh = _exact_match(out["bbh"], "bbh_cot_zeroshot", "exact_match,flexible-extract")
        score, label = (gsm + bbh) / 2, "average"
        print(f"GSM8K {gsm:.3f}   BBH {bbh:.3f}")
        report(report_reasoning, out["gsm8k"], out["bbh"])
    else:  # multilingual
        mgsm = _exact_match(out["mgsm"], "mgsm_chat")
        gmmlu = _exact_match(out["gmmlu"], "global_mmlu_lite_generative")
        score, label = (mgsm + gmmlu) / 2, "average"
        print(f"MGSM {mgsm:.3f}   Global-MMLU Lite {gmmlu:.3f}")
        report(report_multilingual, out["mgsm"], out["gmmlu"])

    passed = score >= threshold
    print("PASS" if passed else "FAIL", f"- {label} {score:.3f} vs threshold {threshold}", flush=True)
    return passed


# ---------------------------------------------------------------- command line
def cmd_install(args):
    setup(args, need_model=False)
    req = HERE / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
    # Like the notebooks, install from PyPI rather than whatever index pip is configured with (an internal mirror
    # may lack pinned versions). Set PYPI_INDEX / --index-url to another index URL, or to an empty value to use pip's own config.
    index = (args.index_url if args.index_url is not None else os.environ.get("PYPI_INDEX", "https://pypi.org/simple")).strip()
    env = dict(os.environ)
    if index:
        cmd += ["--index-url", index]
        env.pop("PIP_EXTRA_INDEX_URL", None)
    print(f"Installing {req} with {sys.executable}" + (f" from {index}" if index else "") + " ...", flush=True)
    sys.exit(subprocess.run(cmd, env=env).returncode)


def cmd_run(args):
    global RESULTS_DIR, MODEL
    names = list(BENCHMARKS) if "all" in args.benchmarks else list(dict.fromkeys(args.benchmarks))
    if args.threshold is not None and len(names) > 1:
        raise SystemExit("--threshold applies to a single benchmark; run them one at a time to set thresholds")
    base_url, MODEL, api_key = setup(args)
    RESULTS_DIR = Path(args.results_dir or os.environ.get("RESULTS_DIR") or DEFAULT_RESULTS_DIR).expanduser().resolve()
    print(f"Model: {MODEL} @ {urlparse(base_url).netloc or base_url}\nReports: {_report_folder(MODEL)}")
    check_endpoint(base_url, MODEL, api_key)
    results = {name: run_benchmark(name, args, base_url, MODEL, api_key) for name in names}
    print("\n=== Summary ===")
    for name, passed in results.items():
        print(f"  {name:<13} {'PASS' if passed else 'FAIL'}")
    show_scorecard()
    if args.strict and not all(results.values()):
        sys.exit(1)


def cmd_scorecard(args):
    global RESULTS_DIR, MODEL
    _, MODEL, _ = setup(args)
    RESULTS_DIR = Path(args.results_dir or os.environ.get("RESULTS_DIR") or DEFAULT_RESULTS_DIR).expanduser().resolve()
    show_scorecard()


def main(argv=None):
    p = argparse.ArgumentParser(description="Run lm-evaluation-harness benchmarks against an OpenAI-compatible chat endpoint.")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env-file", help="path to a .env file (default: ./.env, then ../.env)")
    common.add_argument("--base-url", help="model endpoint base URL, usually ending in /v1 (overrides OPENAI_BASE_URL)")
    common.add_argument("--model", help="model name as the endpoint reports it (overrides OPENAI_MODEL)")
    common.add_argument("--api-key", help="API key (overrides OPENAI_API_KEY; prefer .env so it stays out of shell history)")
    common.add_argument("--results-dir", help=f"where the <model name>/ report folders go (default: RESULTS_DIR or {DEFAULT_RESULTS_DIR})")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("install", parents=[common], help="pip-install requirements.txt (uses the proxy settings from .env)")
    sp.add_argument("--index-url", help="package index to install from (default: PYPI_INDEX or https://pypi.org/simple; "
                                        "an empty value uses pip's own configuration)")
    sp.set_defaults(func=cmd_install)

    sp = sub.add_parser("run", parents=[common], help="run one or more benchmarks")
    sp.add_argument("benchmarks", nargs="+", choices=[*BENCHMARKS, "all"], metavar="BENCHMARK",
                    help="one or more of: " + ", ".join(BENCHMARKS) + ", or 'all'")
    sp.add_argument("--limit", type=int, help="questions per task, for a quick smoke test (default: the full benchmark)")
    sp.add_argument("--threshold", type=float, help="pass mark for a single benchmark (default: the benchmark's own)")
    sp.add_argument("--concurrent", type=int, default=int(os.environ.get("NUM_CONCURRENT", DEFAULT_CONCURRENT)),
                    help=f"parallel requests to the model (default: NUM_CONCURRENT or {DEFAULT_CONCURRENT})")
    sp.add_argument("--max-gen-toks", type=int, help="most tokens the model may write per answer (default: per benchmark)")
    sp.add_argument("--strict", action="store_true", help="exit with status 1 if any benchmark FAILs its threshold")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("scorecard", parents=[common], help="print the latest result of each benchmark for the model")
    sp.set_defaults(func=cmd_scorecard)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
