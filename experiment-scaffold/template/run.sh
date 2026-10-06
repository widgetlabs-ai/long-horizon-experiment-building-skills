#!/usr/bin/env bash
# Preflight, then the supervisor.
#
# Everything knowable at generation 0 is checked here, because the alternative
# is a weekend run that dies on generation 9 for a missing file. The last check
# is one real model call: a key that is set but wrong is indistinguishable from
# a key that works until something actually calls the endpoint.
#
# A stage that cannot run says so by name, and `--check` still fails loudly if
# a stage that *must* pass did not. "Skipped" and "passed" are never conflated:
# a preflight that reports readiness on the strength of what it skipped is
# worse than no preflight at all.
set -euo pipefail

EXPERIMENT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$EXPERIMENT"

SYNTH_STATE="${SYNTH_STATE:-$EXPERIMENT/state}"
export SYNTH_STATE
export PYTHONPATH="$EXPERIMENT/src${PYTHONPATH:+:$PYTHONPATH}"
CLI="python3 -m synthetic_search.substrate.cli"

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
fi

SKIPPED=()

note_skip() {
  SKIPPED+=("$1")
  echo "preflight: SKIPPED $1"
}

# 1. A provider resolves. No key means no run, and the line names the endpoint
#    every later check and the run log will use.
. "$EXPERIMENT/provider.sh"

# 2. No abort sentinel, no half-finished promotion.
if [[ -e "$SYNTH_STATE/ABORT" ]]; then
  echo "preflight: $SYNTH_STATE/ABORT exists — refusing" >&2
  exit 2
fi
if [[ -f "$SYNTH_STATE/pending.json" ]]; then
  echo "preflight: $SYNTH_STATE/pending.json is left over — gate and adopt it, or delete it" >&2
  exit 2
fi

# 3. The corpus is staged and the instrument is pinned. Both refuse rather than
#    default, so a wrong path costs nothing instead of a night.
status=0
$CLI candidates >/dev/null || status=$?
if [[ "$status" -ne 0 ]]; then
  echo "preflight: no staged corpus under $SYNTH_STATE — run \`cli stage\`" >&2
  exit 2
fi

# 4. The scoring invariants.
status=0
$CLI selftest || status=$?
if [[ "$status" -ne 0 ]]; then
  echo "preflight: selftest failed" >&2
  exit 2
fi

# 5. The reviewer, if enabled, could run: its key is set, its rubric names a
#    concern, its base_url is an http(s) URL. No call is made. Otherwise a
#    misconfigured reviewer is found only after a whole generation is spent.
status=0
$CLI review --check || status=$?
if [[ "$status" -ne 0 ]]; then
  echo "preflight: the reviewer cannot run — fix review.toml or set its key" >&2
  exit 2
fi

# 6. The rollout image matches the artifact and the train baseline.
if [[ -n "${SYNTH_SKIP_IMAGE:-}" ]]; then
  note_skip "the rollout image build (SYNTH_SKIP_IMAGE is set) — run: docker build -f Dockerfile -t synthetic-search:pinned ."
elif ! command -v docker >/dev/null 2>&1; then
  note_skip "the rollout image build (docker is not installed) — run: docker build -f Dockerfile -t synthetic-search:pinned ."
else
  docker build -f Dockerfile -t synthetic-search:pinned .
fi

# 7. One real model call. A key that is set but wrong looks exactly like a key
#    that works, right up until a rollout spends its budget discovering it.
if [[ -n "${SYNTH_SKIP_MODEL_CALL:-}" ]]; then
  note_skip "the live model call (SYNTH_SKIP_MODEL_CALL is set) — run: ./run.sh --check with a working key"
else
  status=0
  python3 - <<'PY' || status=$?
import json, os, sys, urllib.request

endpoint = os.environ["ENDPOINT"].rstrip("/") + "/chat/completions"
payload = json.dumps({
    "model": os.environ["MODEL"],
    "max_tokens": 8,
    "messages": [{"role": "user", "content": "reply with the digit 1"}],
}).encode()
request = urllib.request.Request(
    endpoint,
    data=payload,
    headers={
        "Authorization": f"Bearer {os.environ[os.environ['KEY_VAR']]}",
        "Content-Type": "application/json",
        "User-Agent": "long-horizon-preflight/1",
    },
)
try:
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()
except Exception as exc:
    print(f"preflight: the live model call failed: {exc}", file=sys.stderr)
    sys.exit(2)
print("preflight: the live model call succeeded")
PY
  if [[ "$status" -ne 0 ]]; then
    echo "preflight: the provider rejected a real call — fix the key or the endpoint before running" >&2
    exit 2
  fi
fi

if [[ "${#SKIPPED[@]}" -gt 0 ]]; then
  echo
  echo "preflight: passed what it could run. NOT CHECKED:"
  for item in "${SKIPPED[@]}"; do
    echo "  - $item"
  done
else
  echo "preflight: all checks passed"
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  exit 0
fi

exec "$EXPERIMENT/supervisor.sh"
