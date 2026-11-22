"""Shared setup for the evaluation notebooks: model endpoint settings and proxy configuration.

Notebooks call `setup()`, which returns (model_url, model_name, api_key) and exports the proxy
settings every tool underneath needs. Settings come from a .env file (see dot_env.template) or,
when there is none, from prompts.
"""
import os
from getpass import getpass
from pathlib import Path

__all__ = ["setup", "load_env", "apply_proxy"]


def load_env():
    """Read KEY=VALUE lines from a .env file into os.environ. Returns False if there is no file.

    Looks in the kernel's working directory, then ./notebooks (some Jupyter servers start the
    kernel in the repo's parent folder rather than next to the notebook)."""
    p = next((c for c in (Path(".env"), Path("notebooks/.env")) if c.is_file()), None)
    if p is None:
        return False
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip("\"'")
    return True


def apply_proxy():
    """Export the proxy settings in the form each tool underneath reads them.

    uv, Python (requests / huggingface_hub / aiohttp) and npm read HTTP(S)_PROXY and NO_PROXY
    (upper or lower case); Node's built-in fetch needs NODE_USE_ENV_PROXY; npm also has its own
    npm_config_* names. CA_BUNDLE is for proxies that re-sign HTTPS traffic with a company CA."""
    url, no_proxy = os.environ.get("PROXY_URL", "").strip(), os.environ.get("NO_PROXY", "").strip()
    if url:
        # The model endpoint is sent through the proxy too, unless its host is listed in NO_PROXY.
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "npm_config_proxy", "npm_config_https_proxy"):
            os.environ[k] = url
        os.environ["NODE_USE_ENV_PROXY"] = "1"
        if no_proxy:
            for k in ("NO_PROXY", "no_proxy", "npm_config_noproxy"):
                os.environ[k] = no_proxy
        print("Using proxy", url.split("@")[-1], "(NO_PROXY: " + (no_proxy or "none") + ")")
        # lm-eval 0.4.12 sends concurrent requests with aiohttp and never sets trust_env, so aiohttp
        # would ignore the variables above. This sitecustomize.py (loaded at start-up of the lm_eval
        # process via PYTHONPATH) makes every aiohttp.ClientSession trust them.
        patch_dir = Path(".eval-notebook-proxy-patch").resolve()
        patch_dir.mkdir(exist_ok=True)
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
        for k in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"):
            os.environ[k] = ca
        print("Using CA bundle", ca)


def setup():
    """Load the model endpoint settings, apply the proxy settings, return (url, model, api_key).

    If EVAL_OVERRIDE_URL / EVAL_OVERRIDE_MODEL / EVAL_OVERRIDE_API_KEY are set (run-all.ipynb does
    this), they win over the .env file and nothing is prompted for."""
    override = {k: os.environ[f"EVAL_OVERRIDE_{v}"] for k, v in
                (("OPENAI_BASE_URL", "URL"), ("OPENAI_MODEL", "MODEL"), ("OPENAI_API_KEY", "API_KEY"))
                if f"EVAL_OVERRIDE_{v}" in os.environ}
    loaded = load_env()
    if override:
        os.environ.update(override)
        print("Using model settings from run-all.ipynb (overriding .env)")
    if loaded:
        if not override:
            print("Loaded settings from .env")
        missing = [k for k in ("OPENAI_BASE_URL", "OPENAI_MODEL") if not os.environ.get(k)]
        if missing:
            raise SystemExit(f"Please set {', '.join(missing)} in .env (see dot_env.template)")
    elif not override:
        print("No .env file found (copy dot_env.template to .env to skip these prompts)")
        os.environ["OPENAI_BASE_URL"] = input("Model base URL (e.g. https://host/v1): ").strip()
        os.environ["OPENAI_MODEL"] = input("Model name: ").strip()
        os.environ["OPENAI_API_KEY"] = getpass("API key (leave blank if none): ")
    apply_proxy()
    return os.environ["OPENAI_BASE_URL"].rstrip("/"), os.environ["OPENAI_MODEL"], os.environ.get("OPENAI_API_KEY", "")
