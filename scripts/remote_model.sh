#!/usr/bin/env bash
# Point every vendor SDK at one base_url and see which pull it off.
#
# The base_url comes from a file (default `tunnel-url.txt`, the artifact the
# `local-model-tunnel` workflow writes) or from the first argument. The idea: instead of
# trusting that "our client speaks OpenAI", let `openai`, `anthropic`, `google-genai` and
# `mistralai` each try the same endpoint, and record exactly what happened.
#
#   ./scripts/remote_model.sh                       # read ./tunnel-url.txt
#   ./scripts/remote_model.sh https://x.trycloudflare.com
#   ./scripts/remote_model.sh URL --sdk openai --sdk mistral
#
# Exit codes: 0 if at least one SDK completed a chat turn, 3 if none did (a real answer, not
# a crash), 2 for a usage error.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# The venv is how this is run locally; a CI runner installs into its own interpreter, so fall
# back to whatever `python3` and `archx-agent` resolve to before giving up.
if [ -x "$HERE/.venv/bin/python" ]; then
  PY="$HERE/.venv/bin/python"
else
  PY="$(command -v python3 || command -v python || echo python3)"
fi
if [ -x "$HERE/.venv/bin/archx-agent" ]; then
  CLI="$HERE/.venv/bin/archx-agent"
else
  CLI="$(command -v archx-agent || echo "$HERE/.venv/bin/archx-agent")"
fi
SOURCE=""
if [ "$#" -gt 0 ] && [ "${1#--}" = "$1" ]; then
  SOURCE="$1"
  shift
fi
URL_FILE="${ARCHX_URL_FILE:-$HERE/tunnel-url.txt}"
PICKS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --sdk) PICKS+=("$2"); shift 2 ;;
    --url-file) URL_FILE="$2"; shift 2 ;;
    *) printf 'unknown argument %s\n' "$1" >&2; exit 2 ;;
  esac
done

if [ -z "$SOURCE" ]; then
  if [ ! -f "$URL_FILE" ]; then
    printf 'no URL given and %s does not exist.\n' "$URL_FILE" >&2
    printf 'Run the "local model tunnel" workflow and download its artifact, or pass a URL:\n' >&2
    printf '  ./scripts/remote_model.sh https://something.trycloudflare.com\n' >&2
    exit 2
  fi
  SOURCE="$(grep -oE 'https?://[^ ]+' "$URL_FILE" | head -1)"
fi
SOURCE="${SOURCE%/}"
if [ -z "$SOURCE" ]; then
  printf 'could not read a URL from %s\n' "$URL_FILE" >&2
  exit 2
fi

printf '### endpoint\n%s\n' "$SOURCE"
printf 'curl /health      -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$SOURCE/health" || echo 000)"
printf 'curl /v1/models   -> %s\n' "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$SOURCE/v1/models" || echo 000)"
printf 'the server says: %s\n' "$(curl -s --max-time 10 "$SOURCE/v1/models" | head -c 300)"

# `--sdk` may be repeated; the default is every SDK this interpreter has installed.
if [ "${#PICKS[@]}" -eq 0 ]; then
  while IFS= read -r line; do
    [ -n "$line" ] && PICKS+=("$line")
  done < <("$PY" -c "
from archx_agent.adapters.sdk_transport import SDKS, sdk_available
for key in SDKS:
    if sdk_available(key)[0]:
        print(key)
" 2>/dev/null)
fi

printf '\n### the same endpoint through each official SDK\n'
FAILURES=0
PASSED=0
for sdk in "${PICKS[@]}"; do
  printf '\n--- %s\n' "$sdk"
  OUT="$("$PY" - "$sdk" "$SOURCE" <<'PY' 2>&1
import sys
sdk, base = sys.argv[1], sys.argv[2]
from archx_agent.adapters.model_runtime import GenerationParams
from archx_agent.adapters.sdk_transport import sdk_available, transport_for
from archx_agent.helpers.exceptions import ProviderError

ok, why = sdk_available(sdk)
if not ok:
    print(f"SKIP  {why}")
    raise SystemExit(0)

# cohere and ollama speak their own routes (/v2/chat, /api/chat); a llama.cpp server only
# answers the OpenAI shape, so pointing them here would test nothing but their 404 handling.
if sdk in ("cohere", "ollama"):
    print(f"SKIP  the {sdk} client speaks its own protocol; it cannot drive an OpenAI-shaped server")
    raise SystemExit(0)

# A local llama.cpp server ignores the key, but the client still has to send one. The OpenAI
# shape lives under /v1, and groq/together append /chat/completions to whatever they are given.
endpoint = base + "/v1" if sdk in ("openai", "groq", "together") else base
transport = transport_for(sdk, api_key="local-model-no-key", base_url=endpoint, timeout=120.0)
try:
    result = transport.chat(
        [{"role": "user", "content": "Say hello in five words."}],
        GenerationParams(temperature=0.2, max_tokens=32),
        model="local",
    )
except ProviderError as exc:
    print(f"FAIL  {type(exc).__name__}: {exc.message[:200]}")
    raise SystemExit(1)
finally:
    transport.close()
print(f"OK    {result.text.strip()[:200]!r}")
print(f"      tokens in/out {result.prompt_tokens}/{result.completion_tokens}  finish {result.finish_reason}")

# ...and streamed, because a client can get the shape right and the deltas wrong
try:
    pieces = list(transport.stream(
        [{"role": "user", "content": "Count to three."}],
        GenerationParams(temperature=0.2, max_tokens=32),
        model="local",
    ))
except ProviderError as exc:
    print(f"STREAM-FAIL  {type(exc).__name__}: {exc.message[:200]}")
    raise SystemExit(1)
joined = "".join(pieces)
print(f"      streamed {len(pieces)} chunk(s), {len(joined)} chars: {joined.strip()[:120]!r}")
if not joined.strip():
    print("STREAM-FAIL  the stream produced no text")
    raise SystemExit(1)
PY
)"
  printf '%s\n' "$OUT"
  case "$OUT" in
    OK*) PASSED=$((PASSED + 1)) ;;
    SKIP*) ;;
    *) FAILURES=$((FAILURES + 1)) ;;
  esac
  case "$OUT" in
    *STREAM-FAIL*) FAILURES=$((FAILURES + 1)) ;;
  esac
done

printf '\n### summary\n'
printf '%s SDK(s) completed a turn, %s failed\n' "$PASSED" "$FAILURES"

if [ "$PASSED" -gt 0 ] && [ -x "$CLI" ]; then
  printf '\n### and through Archx itself (the app, not just the SDK)\n'
  HOME_DIR="${ARCHX_PATHS_HOME:-$(mktemp -d /tmp/archx-remote-XXXXXX)}"
  export ARCHX_PATHS_HOME="$HOME_DIR"
  "$CLI" init >/dev/null 2>&1
  printf 'home %s\n' "$HOME_DIR"
  for sdk in "${PICKS[@]}"; do
    case " $SOURCE " in
      *" 127.0.0.1"*|*" localhost"*) READY="loopback, so no consent is needed" ;;
      *) READY="remote: the four consent rungs apply before chat will send anything" ;;
    esac
    printf '\n$ archx-agent models add-sdk --name remote-%s --sdk %s --model local --base-url %s\n' "$sdk" "$sdk" "$SOURCE"
    "$CLI" models add-sdk --name "remote-$sdk" --sdk "$sdk" --model local \
      --base-url "$SOURCE" 2>&1 | sed 's/^/  /'
    printf '  (%s)\n' "$READY"
    printf '  probe:\n'
    "$CLI" models probe "remote-$sdk" --capability chat 2>&1 | sed 's/^/    /'
  done
fi

if [ "$PASSED" -eq 0 ]; then
  exit 3
fi
exit 0
