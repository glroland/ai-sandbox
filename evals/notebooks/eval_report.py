"""Result reports shared by the evaluation notebooks.

Each notebook calls one `report_*()` function after its benchmark has run. The function reads the
files the tool wrote (lm-evaluation-harness `results_*.json` / `samples_*.jsonl`, or the promptfoo
JSON) and draws charts that go well beyond a single PASS/FAIL number: confidence intervals,
per-category breakdowns, failure analysis and run statistics.

Only matplotlib is needed; it is installed on first use if missing.
"""
import json, re, statistics, subprocess, sys, time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------- palette (light surface, validated set)
BLUE, ORANGE, GREEN = "#2a78d6", "#eb6834", "#008300"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1", "#ffffff"
SCORECARD = Path(".eval-notebook-scorecard.json")


def _plt():
    """Import matplotlib (installing it into this kernel's Python if it is missing) and apply the house style."""
    try:
        import matplotlib
    except ImportError:
        print("Installing matplotlib (one-off) ...")
        cmds = ([sys.executable, "-m", "pip", "install", "-q", "matplotlib"],
                ["uv", "pip", "install", "-q", "--python", sys.executable, "matplotlib"])
        for cmd in cmds:
            try:
                if subprocess.run(cmd, capture_output=True).returncode == 0:
                    break
            except FileNotFoundError:
                pass
        import matplotlib  # raises a clear error if both installers failed
    matplotlib.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2,
        "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
        "font.size": 10, "axes.titlesize": 11.5, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "figure.dpi": 110, "legend.frameon": False,
    })
    import matplotlib.pyplot as plt
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


def _save_scorecard(key, entry):
    try:
        data = json.loads(SCORECARD.read_text()) if SCORECARD.exists() else {}
    except ValueError:
        data = {}
    data[key] = entry
    SCORECARD.write_text(json.dumps(data, indent=1))


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
    if unfinished:
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
        return p if p in letters else "?"
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


# ---------------------------------------------------------------- promptfoo
def report_promptfoo(output, threshold):
    plt = _plt()
    data = json.loads(Path(output).read_text())
    rows = data["results"]["results"]; stats = data["results"]["stats"]
    n = len(rows); ok = sum(bool(r["success"]) for r in rows)
    score = ok / n if n else 0
    lat = [r.get("latencyMs") or (r.get("response") or {}).get("latencyMs") or 0 for r in rows]
    tok = [(r.get("response") or {}).get("tokenUsage") or r.get("tokenUsage") or {} for r in rows]
    comp = [t.get("completion", 0) for t in tok]; prom = [t.get("prompt", 0) for t in tok]
    tps = [c / (l / 1000) if l else 0 for c, l in zip(comp, lat)]
    names = [_short((r["testCase"].get("description") or r["vars"].get("question") or f"test {i}"), 34) for i, r in enumerate(rows)]
    cost = sum(r.get("cost") or 0 for r in rows)
    mname = rows[0]["provider"]["id"].split(":")[-1] if rows else "?"
    p95 = sorted(lat)[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else 0
    _card(plt, "promptfoo · your own prompt tests", mname, f"{ok} / {n} passed", score >= threshold, threshold,
          wilson(ok, n), [("Median latency", f"{statistics.median(lat):.0f} ms"), ("Slowest (p95)", f"{p95:.0f} ms"),
                          ("Tokens in / out", f"{sum(prom)} / {sum(comp)}"),
                          ("Generation speed", f"{statistics.median(tps):.0f} tokens/s (median)"),
                          ("Estimated cost", f"${cost:.4f}" if cost else "not reported")])

    fig, axs = plt.subplots(1, 3, figsize=(11, 0.5 * n + 2.4), sharey=True)
    y = list(range(n))
    axs[0].barh(y, lat, color=[BLUE if r["success"] else ORANGE for r in rows], height=0.6)
    axs[0].set_title("Latency (ms)")
    axs[1].barh(y, prom, color=MUTED, height=0.6, label="prompt"); axs[1].barh(y, comp, left=prom, color=BLUE, height=0.6, label="completion")
    axs[1].set_title("Tokens"); axs[1].legend(fontsize=8, loc="lower right")
    axs[2].barh(y, tps, color=BLUE, height=0.6); axs[2].set_title("Output tokens ÷ latency (tok/s)")
    axs[0].set_yticks(y); axs[0].set_yticklabels(names, fontsize=8.5); axs[0].invert_yaxis()
    for a in axs:
        a.grid(axis="y", visible=False)
    fig.tight_layout(); plt.show()

    # Assertion matrix: every check on every test
    comps = [(r.get("gradingResult") or {}).get("componentResults") or [] for r in rows]
    width = max([len(c) for c in comps] + [1])
    fig, ax = plt.subplots(figsize=(11, 0.42 * n + 1.3))
    for i, cs in enumerate(comps):
        for j, c in enumerate(cs):
            a = c.get("assertion") or {}
            ax.add_patch(plt.Rectangle((j, i), 0.94, 0.8, color=BLUE if c.get("pass") else ORANGE))
            ax.text(j + 0.47, i + 0.4, f"{'✔' if c.get('pass') else '✘'} {a.get('type', '?')}: {_short(a.get('value', ''), 22)}",
                    ha="center", va="center", color="white", fontsize=8)
    ax.set_xlim(0, width); ax.set_ylim(n, 0); ax.set_yticks([i + 0.4 for i in range(n)]); ax.set_yticklabels(names, fontsize=8.5)
    ax.set_xticks([]); ax.grid(False); [s.set_visible(False) for s in ax.spines.values()]
    ax.set_title("Every assertion on every test")
    fig.tight_layout(); plt.show()

    reasons = Counter((r.get("response") or {}).get("finishReason", "?") for r in rows)
    print("Finish reasons:", ", ".join(f"{k} ×{v}" for k, v in reasons.items()),
          "(anything other than 'stop' — e.g. 'length' — means the answer was cut off)")

    _save_scorecard("promptfoo", {"title": "promptfoo", "what": "your own prompt tests", "score": score,
                                  "ci": wilson(ok, n), "threshold": threshold, "n": n, "model": mname,
                                  "seconds": (stats.get("durationMs") or 0) / 1000})


# ---------------------------------------------------------------- scorecard across notebooks
def show_scorecard():
    plt = _plt()
    data = json.loads(SCORECARD.read_text()) if SCORECARD.exists() else {}
    if not data:
        print("No results yet — run at least one of the evaluation notebooks first.")
        return
    items = sorted(data.values(), key=lambda d: -d["score"])
    fig, ax = plt.subplots(figsize=(11, 0.75 * len(items) + 1.5))
    vals = [d["score"] for d in items]; ci = [d["ci"] for d in items]
    _hbar(ax, [f"{d['title']}\n{d['what']}" for d in items], vals, [c[0] for c in ci], [c[1] for c in ci],
          ns=[d["n"] for d in items], colours=[GREEN if d["score"] >= d["threshold"] else ORANGE for d in items], xlim=(0, 1.2))
    for yi, d in enumerate(items):  # each benchmark's own pass mark
        ax.plot([d["threshold"]] * 2, [yi - 0.4, yi + 0.4], color=INK, linewidth=2)
    models = sorted({d["model"] for d in items})
    ax.set_title(f"Scorecard — {', '.join(models)}   (green: passed · orange: failed · black tick: threshold)")
    fig.tight_layout(); plt.show()
    print("Last run of each benchmark:")
    for d in items:
        print(f"  {d['title']:<14} {pct(d['score']):>6}  "
              f"{'PASS' if d['score'] >= d['threshold'] else 'FAIL'}  (n={d['n']:,}, took {_dur(d['seconds'])})")
