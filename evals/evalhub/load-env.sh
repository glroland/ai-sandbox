# Source this file to load the shared .env (see ../dot_env.template) into the environment.
# Searches ./.env then ../.env (relative to the current directory), then the same two places
# relative to this script. Set ENV_FILE=/path/to/file to use a specific file.
# Values in the file win over variables already set in the shell, as in cli/ and notebooks/.

_LE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
_LE_FILE=
for _c in "${ENV_FILE:-}" .env ../.env "$_LE_DIR/.env" "$_LE_DIR/../.env"; do
    [ -n "$_c" ] && [ -f "$_c" ] && { _LE_FILE=$_c; break; }
done
if [ -n "${ENV_FILE:-}" ] && [ "$_LE_FILE" != "$ENV_FILE" ]; then
    echo "env file not found: $ENV_FILE" >&2; return 1
fi

if [ -n "$_LE_FILE" ]; then
    echo "Loaded settings from $_LE_FILE"
    set -a
    # shellcheck disable=SC1090
    . "$_LE_FILE"
    set +a
fi

# Proxy: export in the forms uv, npm, Node and curl read.
if [ -n "${PROXY_URL:-}" ]; then
    _LE_PROXY=$PROXY_URL
    if [ -n "${PROXY_USERNAME:-}" ] && [[ "$_LE_PROXY" != *@* ]]; then
        _le_enc() { jq -rn --arg v "$1" '$v|@uri'; }
        _LE_SCHEME=http; _LE_REST=$_LE_PROXY
        [[ "$_LE_PROXY" == *://* ]] && { _LE_SCHEME=${_LE_PROXY%%://*}; _LE_REST=${_LE_PROXY#*://}; }
        _LE_PROXY="$_LE_SCHEME://$(_le_enc "$PROXY_USERNAME"):$(_le_enc "${PROXY_PASSWORD:-}")@$_LE_REST"
    fi
    export HTTP_PROXY=$_LE_PROXY HTTPS_PROXY=$_LE_PROXY http_proxy=$_LE_PROXY https_proxy=$_LE_PROXY \
           npm_config_proxy=$_LE_PROXY npm_config_https_proxy=$_LE_PROXY NODE_USE_ENV_PROXY=1
    if [ -n "${NO_PROXY:-}" ]; then
        export no_proxy=$NO_PROXY npm_config_noproxy=$NO_PROXY
    fi
    echo "Using proxy ${_LE_PROXY##*@} (NO_PROXY: ${NO_PROXY:-none})"
    # lm-eval's aiohttp ignores proxy variables unless trust_env is set; patch it at interpreter start-up.
    _LE_PATCH=$_LE_DIR/.eval-proxy-patch
    mkdir -p "$_LE_PATCH"
    cat > "$_LE_PATCH/sitecustomize.py" <<'PY'
try:
    import aiohttp
    _init = aiohttp.ClientSession.__init__
    def __init__(self, *a, **kw):
        kw.setdefault('trust_env', True)
        _init(self, *a, **kw)
    aiohttp.ClientSession.__init__ = __init__
except ImportError:
    pass
PY
    export PYTHONPATH="$_LE_PATCH${PYTHONPATH:+:$PYTHONPATH}"
fi
if [ -n "${CA_BUNDLE:-}" ]; then
    export SSL_CERT_FILE=$CA_BUNDLE REQUESTS_CA_BUNDLE=$CA_BUNDLE CURL_CA_BUNDLE=$CA_BUNDLE NODE_EXTRA_CA_CERTS=$CA_BUNDLE
    echo "Using CA bundle $CA_BUNDLE"
fi

# The local scripts read MODEL_API_KEY; OPENAI_API_KEY from .env is the shared name.
MODEL_API_KEY=${MODEL_API_KEY:-${OPENAI_API_KEY:-}}
unset _LE_DIR _LE_FILE _LE_PROXY _LE_SCHEME _LE_REST _LE_PATCH _c
