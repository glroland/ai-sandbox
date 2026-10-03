#!/bin/bash

usage() {
    cat >&2 <<EOF
Usage: $0 [options] <BASE_URL> <MODEL> [ACCESS_TOKEN]

Repeatedly sends chat completion requests to <BASE_URL>/chat/completions.
Runs until either the total request count or the duration is reached.

Options:
  -n, --count N         Total number of requests to send (default: 10)
  -t, --duration SECS   Run for SECS seconds instead of a fixed count
  -c, --concurrency N   Number of workers sending requests in parallel (default: 1)
      --threads N       Alias for --concurrency
  -i, --interval SECS   Delay between requests per worker, fractions ok (default: 0)
  -p, --prompt TEXT     User message to send (default: "Ping")
  -m, --max-tokens N    max_tokens for each request (default: unset)
  -k, --insecure        Skip TLS verification
  -q, --quiet           Only print the final summary
EOF
    exit 1
}

COUNT=10
DURATION=0
CONCURRENCY=1
INTERVAL=0
PROMPT="Ping"
MAX_TOKENS=""
INSECURE=0
QUIET=0

is_uint() { [[ "$1" =~ ^[0-9]+$ ]]; }
is_number() { [[ "$1" =~ ^[0-9]+(\.[0-9]+)?$ ]]; }

# Wall-clock seconds with sub-second precision (macOS date has no %N).
now() {
    if [ -n "$EPOCHREALTIME" ]; then
        echo "$EPOCHREALTIME"
    else
        perl -MTime::HiRes=time -e 'printf "%.6f\n", time'
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -n|--count)
            [ "$#" -ge 2 ] && is_uint "$2" && [ "$2" -gt 0 ] || usage
            COUNT="$2"
            shift 2
            ;;
        -t|--duration)
            [ "$#" -ge 2 ] && is_uint "$2" && [ "$2" -gt 0 ] || usage
            DURATION="$2"
            shift 2
            ;;
        -c|--concurrency|--threads)
            [ "$#" -ge 2 ] && is_uint "$2" && [ "$2" -gt 0 ] || usage
            CONCURRENCY="$2"
            shift 2
            ;;
        -i|--interval)
            [ "$#" -ge 2 ] && is_number "$2" || usage
            INTERVAL="$2"
            shift 2
            ;;
        -p|--prompt)
            [ "$#" -ge 2 ] || usage
            PROMPT="$2"
            shift 2
            ;;
        -m|--max-tokens)
            [ "$#" -ge 2 ] && is_uint "$2" || usage
            MAX_TOKENS="$2"
            shift 2
            ;;
        -k|--insecure)
            INSECURE=1
            shift
            ;;
        -q|--quiet)
            QUIET=1
            shift
            ;;
        -h|--help)
            usage
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage
            ;;
        *)
            break
            ;;
    esac
done

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    usage
fi

BASE_URL=${1%/}
MODEL=$2
ACCESS_TOKEN=${3:-nokeyneeded}
ENDPOINT="$BASE_URL/chat/completions"

# Escape the prompt for embedding in a JSON string.
PROMPT_JSON=$(printf '%s' "$PROMPT" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' | awk 'NR>1{printf "\\n"} {printf "%s", $0}')

MAX_TOKENS_JSON=""
[ -n "$MAX_TOKENS" ] && MAX_TOKENS_JSON="\"max_tokens\": $MAX_TOKENS,"

REQUEST_BODY="{
  \"model\": \"$MODEL\",
  $MAX_TOKENS_JSON
  \"messages\": [{\"role\": \"user\", \"content\": \"$PROMPT_JSON\"}]
}"

CURL_OPTS=(-sS -o /dev/null -w '%{http_code} %{time_total}')
[ "$INSECURE" -eq 1 ] && CURL_OPTS+=(-k)

RESULTS_FILE=$(mktemp -t hammer_model_endpoint.XXXXXX)
WORKER_PIDS=()

# Each worker appends "<http_code> <seconds>" per request to RESULTS_FILE.
# Short single-line appends are atomic, so workers can share the file.
worker() {
    local id=$1 quota=$2 end_time=$3 sent=0 result
    while :; do
        if [ "$end_time" -gt 0 ]; then
            [ "$(date +%s)" -lt "$end_time" ] || break
        else
            [ "$sent" -lt "$quota" ] || break
        fi

        result=$(curl "${CURL_OPTS[@]}" "$ENDPOINT" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $ACCESS_TOKEN" \
            -d "$REQUEST_BODY" 2>/dev/null)
        # curl reports 000 on connection failures / timeouts.
        [ -n "$result" ] || result="000 0"
        echo "$result" >> "$RESULTS_FILE"
        sent=$((sent + 1))

        if [ "$QUIET" -eq 0 ]; then
            printf '[%s] worker %d #%d -> HTTP %s in %ss\n' \
                "$(date +%H:%M:%S)" "$id" "$sent" "${result% *}" "${result#* }"
        fi

        [ "$INTERVAL" != "0" ] && sleep "$INTERVAL"
    done
}

summarize() {
    local elapsed
    elapsed=$(awk -v s="$START_TIME" -v e="$(now)" 'BEGIN { printf "%.3f", e - s }')

    echo
    echo "==== Summary ===="
    echo "Endpoint:     $ENDPOINT"
    echo "Model:        $MODEL"
    echo "Workers:      $CONCURRENCY in parallel"
    echo "Elapsed:      ${elapsed}s"

    if [ ! -s "$RESULTS_FILE" ]; then
        echo "No requests completed."
        return
    fi

    awk -v elapsed="$elapsed" '
        {
            total++
            codes[$1]++
            if ($1 ~ /^2/) ok++
            lat[total] = $2
            sum += $2
        }
        END {
            printf "Requests:     %d (%.2f req/s)\n", total, (elapsed > 0 ? total / elapsed : 0)
            printf "Succeeded:    %d\n", ok
            printf "Failed:       %d\n", total - ok
            printf "Status codes:"
            for (c in codes) printf " %s=%d", c, codes[c]
            printf "\n"
        }' "$RESULTS_FILE"

    # Latency percentiles over every request (including failures).
    awk '{print $2}' "$RESULTS_FILE" | sort -n | awk '
        { v[NR] = $1; sum += $1 }
        END {
            p50 = v[int((NR - 1) * 0.50) + 1]
            p95 = v[int((NR - 1) * 0.95) + 1]
            p99 = v[int((NR - 1) * 0.99) + 1]
            printf "Latency (s):  min=%.3f avg=%.3f p50=%.3f p95=%.3f p99=%.3f max=%.3f\n", \
                v[1], sum / NR, p50, p95, p99, v[NR]
        }'
}

cleanup() {
    trap - INT TERM
    # Reap workers with stderr silenced so bash's "Terminated" job
    # notices don't land in the middle of the summary.
    {
        for pid in "${WORKER_PIDS[@]}"; do
            kill "$pid"
            wait "$pid"
        done
    } 2>/dev/null
    summarize
    rm -f "$RESULTS_FILE"
    exit 130
}
trap cleanup INT TERM

START_TIME=$(now)
START_SECS=${START_TIME%.*}
END_TIME=0
if [ "$DURATION" -gt 0 ]; then
    END_TIME=$((START_SECS + DURATION))
    echo "Hammering $ENDPOINT ($MODEL) for ${DURATION}s with $CONCURRENCY parallel worker(s)..."
else
    echo "Hammering $ENDPOINT ($MODEL) with $COUNT request(s) across $CONCURRENCY parallel worker(s)..."
fi

# Spread the total count evenly; the first COUNT % CONCURRENCY workers get one extra.
for ((w = 1; w <= CONCURRENCY; w++)); do
    quota=$((COUNT / CONCURRENCY))
    [ "$w" -le $((COUNT % CONCURRENCY)) ] && quota=$((quota + 1))
    if [ "$END_TIME" -eq 0 ] && [ "$quota" -eq 0 ]; then
        continue
    fi
    worker "$w" "$quota" "$END_TIME" &
    WORKER_PIDS+=($!)
done

wait
trap - INT TERM
summarize
rm -f "$RESULTS_FILE"
