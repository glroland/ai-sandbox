"""Tool / function-calling test runner used by run-toolcalling.ipynb.

Sends each test case to the model's OpenAI-compatible /chat/completions endpoint together with tool
definitions, runs any tool calls the model makes against small mock functions (so multi-step tasks can be
followed through), and checks the result against what the case expects. Standard library only.
"""
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


class ToolsNotSupported(RuntimeError):
    pass


# ---------------------------------------------------------------- HTTP
def chat(base_url, api_key, model, messages, tools, max_tokens=1024, timeout=180):
    """One chat completion. Returns (response dict, latency in ms). Retries transient server errors."""
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if tools:
        body["tools"], body["tool_choice"] = tools, "auto"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", json.dumps(body).encode(), headers)
    last = None
    for attempt in range(4):
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r), (time.time() - t0) * 1000
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            if e.code < 500 and e.code != 429:
                raise RuntimeError(f"HTTP {e.code}: {detail}") from None
            last = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last)


# ---------------------------------------------------------------- schema + argument matching
_TYPES = {"string": str, "boolean": bool, "array": list, "object": dict}


def schema_errors(schema, value, path="args"):
    """Minimal JSON-Schema check: type, required, enum, items, nested properties."""
    errs, t = [], schema.get("type")
    if t == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif t == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif t in _TYPES:
        ok = isinstance(value, _TYPES[t])
    else:
        ok = True
    if not ok:
        return [f"{path}: expected {t}, got {type(value).__name__} ({json.dumps(value)[:40]})"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {json.dumps(value)} not one of {schema['enum']}")
    if t == "object":
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing required '{key}'")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errs += schema_errors(sub, value[key], f"{path}.{key}")
    if t == "array" and "items" in schema:
        for i, item in enumerate(value):
            errs += schema_errors(schema["items"], item, f"{path}[{i}]")
    return errs


def _lower(x):
    return x.strip().lower() if isinstance(x, str) else x


def value_matches(actual, exp):
    """Does an argument value meet the expectation?

    Expectations: a literal (strings compare case-insensitively), {"re": pattern}, {"contains": text},
    {"any": [options]}, a list (same items, any order), or a dict (every listed key must match).
    """
    if isinstance(exp, dict):
        if "re" in exp:
            return isinstance(actual, str) and re.search(exp["re"], actual, re.I) is not None
        if "contains" in exp:
            return isinstance(actual, str) and exp["contains"].lower() in actual.lower()
        if "any" in exp:
            return any(value_matches(actual, e) for e in exp["any"])
        return isinstance(actual, dict) and all(k in actual and value_matches(actual[k], v) for k, v in exp.items())
    if isinstance(exp, list):
        return (isinstance(actual, list) and len(actual) == len(exp)
                and sorted(map(str, map(_lower, actual))) == sorted(map(str, map(_lower, exp))))
    if isinstance(exp, bool):
        return actual is exp
    if isinstance(exp, (int, float)):
        return isinstance(actual, (int, float)) and not isinstance(actual, bool) and abs(actual - exp) < 1e-6
    return _lower(actual) == _lower(exp)


def args_mismatch(actual, expected):
    """Names of expected arguments the actual call got wrong or left out."""
    return [k for k, v in expected.items() if k not in actual or not value_matches(actual[k], v)]


# ---------------------------------------------------------------- running one case
def _message_text(msg):
    return (msg.get("content") or "").strip()


def run_case(case, tools, cfg):
    """Run one case. Returns a result dict (see keys at the bottom)."""
    defs = {t["function"]["name"]: t for t in tools.values()}
    offered = [tools[name] for name in case["tools"]]
    messages = [{"role": "system", "content": case.get("system", cfg["system"])}]
    messages += case["messages"] if "messages" in case else [{"role": "user", "content": case["prompt"]}]
    trace, final, latency, ptok, ctok, finishes, error = [], "", 0.0, 0, 0, [], None
    turns = 0
    try:
        for turns in range(1, cfg["max_turns"] + 1):
            data, ms = chat(cfg["base_url"], cfg["api_key"], cfg["model"], messages, offered)
            latency += ms
            usage = data.get("usage") or {}
            ptok += usage.get("prompt_tokens", 0); ctok += usage.get("completion_tokens", 0)
            choice = data["choices"][0]
            msg, finishes = choice["message"], finishes + [choice.get("finish_reason")]
            calls = msg.get("tool_calls") or []
            if not calls:
                final = _message_text(msg)
                break
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": calls})
            for call in calls:
                fn = call["function"]; name = fn["name"]; raw = fn.get("arguments") or "{}"
                entry = {"turn": turns, "name": name, "raw": raw, "args": None, "errors": []}
                try:
                    entry["args"] = json.loads(raw)
                    if not isinstance(entry["args"], dict):
                        raise ValueError("arguments are not a JSON object")
                except ValueError as e:
                    entry["errors"].append(f"arguments are not valid JSON ({e})")
                if name not in offered_names(offered):
                    entry["errors"].append(f"'{name}' is not one of the offered tools")
                elif entry["args"] is not None:
                    entry["errors"] += schema_errors(defs[name]["function"]["parameters"], entry["args"])
                trace.append(entry)
                mock = (case.get("mocks") or {}).get(name)
                if mock is None:
                    result = {"error": f"tool '{name}' is not available in this test"}
                else:
                    result = mock(entry["args"] or {})
                messages.append({"role": "tool", "tool_call_id": call.get("id", name),
                                 "content": result if isinstance(result, str) else json.dumps(result)})
            if not case.get("mocks"):  # single-turn case: judge the first reply only
                break
        else:
            error = "too_many_turns"
    except RuntimeError as e:
        error = f"api_error: {e}"
    passed, code, detail = evaluate(case, trace, final, error)
    return {"id": case["id"], "category": case["category"], "prompt": case.get("prompt") or messages[-1].get("content", ""),
            "passed": passed, "code": code, "detail": detail, "calls": trace, "final": final, "turns": turns,
            "latency_ms": latency, "prompt_tokens": ptok, "completion_tokens": ctok, "finish_reasons": finishes,
            "expect": _describe_expect(case["expect"])}


def offered_names(offered):
    return {t["function"]["name"] for t in offered}


# ---------------------------------------------------------------- judging
FAILURES = {  # code -> human label (also the order shown in the dashboard)
    "wrong_tool": "Chose the wrong tool",
    "wrong_args": "Right tool, wrong arguments",
    "missing_call": "Skipped a needed call",
    "extra_call": "Made extra calls",
    "wrong_order": "Calls in the wrong order",
    "invalid_args": "Arguments broke the schema",
    "unknown_tool": "Invented a tool",
    "called_when_not_needed": "Called a tool unnecessarily",
    "acted_without_info": "Guessed missing details",
    "did_not_ask": "Did not ask for the missing detail",
    "bad_final_answer": "Final answer ignored the tool result",
    "too_many_turns": "Never finished (loop)",
    "api_error": "Request failed",
}


def _describe_expect(exp):
    if exp.get("no_calls"):
        return "answer directly, no tool call"
    if exp.get("asks"):
        return "ask the user for the missing detail, no tool call"
    parts = ["%s(%s)" % (c["name"], ", ".join("%s=%s" % (k, json.dumps(v)) for k, v in c.get("args", {}).items()))
             for c in exp.get("calls", [])]
    out = (" → " if exp.get("ordered") else " + ").join(parts)
    if exp.get("final_contains"):
        out += "; answer mentions " + ", ".join("/".join(x) if isinstance(x, list) else x for x in exp["final_contains"])
    return out


def evaluate(case, trace, final, error):
    exp = case["expect"]
    if error and error.startswith("api_error"):
        return False, "api_error", error
    for c in trace:
        if any("not one of the offered" in e for e in c["errors"]):
            return False, "unknown_tool", c["errors"][0]
    for c in trace:
        if c["errors"]:
            return False, "invalid_args", f"{c['name']}: {c['errors'][0]}"
    if error == "too_many_turns":
        return False, "too_many_turns", "the model kept calling tools"

    if exp.get("no_calls"):
        if trace:
            return False, "called_when_not_needed", f"called {trace[0]['name']}({json.dumps(trace[0]['args'])})"
        return (True, None, "") if final else (False, "api_error", "empty reply")
    if exp.get("asks"):
        if trace:
            return False, "acted_without_info", f"called {trace[0]['name']}({json.dumps(trace[0]['args'])}) instead of asking"
        text = final.lower()
        if "?" in final or any(m in text for m in exp.get("mentions", [])):
            return True, None, ""
        return False, "did_not_ask", final[:120]

    wanted = exp.get("calls", [])
    names_got, names_want = [c["name"] for c in trace], [c["name"] for c in wanted]
    if sorted(names_got) != sorted(names_want):
        if len(names_got) < len(names_want) and set(names_got) <= set(names_want):
            return False, "missing_call", f"expected {names_want}, got {names_got}"
        if len(names_got) > len(names_want) and set(names_want) <= set(names_got):
            return False, "extra_call", f"expected {names_want}, got {names_got}"
        return False, "wrong_tool", f"expected {names_want}, got {names_got}"
    if exp.get("ordered") and names_got != names_want:
        return False, "wrong_order", f"expected {names_want}, got {names_got}"
    pool = list(trace)
    for w in wanted:  # match each expected call to a distinct actual call
        hit = next((c for c in pool if c["name"] == w["name"] and not args_mismatch(c["args"], w.get("args", {}))), None)
        if hit is None:
            cand = next(c for c in pool if c["name"] == w["name"])
            bad = args_mismatch(cand["args"], w.get("args", {}))
            got = ", ".join("%s=%s" % (k, json.dumps(cand["args"].get(k))) for k in bad)
            return False, "wrong_args", "%s: %s" % (w["name"], got)
        pool.remove(hit)
    for needle in exp.get("final_contains", []):
        options = needle if isinstance(needle, list) else [needle]
        if not any(o.lower() in final.lower() for o in options):
            return False, "bad_final_answer", f"reply lacks {'/'.join(options)}: {final[:100]}"
    return True, None, ""


# ---------------------------------------------------------------- whole suite
def run_cases(cases, tools, base_url, api_key, model, system, concurrency=4, max_turns=5):
    """Check the endpoint accepts tools, then run every case. Returns a list of result dicts."""
    cfg = {"base_url": base_url, "api_key": api_key, "model": model, "system": system, "max_turns": max_turns}
    try:  # fail early, and clearly, if the server does not do tool calling at all
        chat(base_url, api_key, model, [{"role": "user", "content": "What is the weather in Paris?"}],
             [tools["get_weather"]], max_tokens=64)
    except RuntimeError as e:
        if str(e).startswith("HTTP 4") or str(e).startswith("HTTP 501"):
            raise ToolsNotSupported(
                f"The endpoint rejected a request that includes tools ({e}). Tool calling must be enabled on the "
                "model server (for vLLM: --enable-auto-tool-choice and a --tool-call-parser for this model).") from None
        raise
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(run_case, c, tools, cfg) for c in cases]
        out = []
        for i, f in enumerate(futures, 1):
            out.append(f.result())
            print(f"\r{i}/{len(cases)} cases done", end="")
    print()
    return out
