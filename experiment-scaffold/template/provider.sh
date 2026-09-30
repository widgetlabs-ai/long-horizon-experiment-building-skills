#!/usr/bin/env bash
# Which upstream, and therefore which config — resolved from the keys that are
# set, never defaulted.
#
# Two rules are worth the small amount of code here. First, no default: a run
# with no key refuses rather than quietly reaching for something. Second, a
# fixed precedence, so a key left over in a shell cannot silently move a search
# to a different endpoint halfway through. Whichever wins, the line this prints
# opens both the preflight output and the run log, so the log always says what
# produced its generations.
#
# Sourced by run.sh and supervisor.sh; runnable on its own to see the answer.
set -euo pipefail

EXPERIMENT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# A key may also live in a gitignored env file beside this script.
for candidate in "$EXPERIMENT/.env.opencode" "$EXPERIMENT/.env.openrouter"; do
  if [[ -f "$candidate" ]]; then
    # shellcheck disable=SC1090
    . "$candidate"
  fi
done

if [[ -n "${OPENCODE_API_KEY:-}" ]]; then
  PROVIDER="opencode"
  ENDPOINT="https://opencode.ai/zen/go/v1"
  KEY_VAR="OPENCODE_API_KEY"
  MODEL="deepseek-v4.1-flash"
  CONFIG="${CONFIG:-config.opencode.toml}"
  IGNORED=""
  if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    IGNORED=" (OPENROUTER_API_KEY is set and ignored)"
  fi
elif [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  PROVIDER="openrouter"
  ENDPOINT="https://openrouter.ai/api/v1"
  KEY_VAR="OPENROUTER_API_KEY"
  MODEL="deepseek/deepseek-v4.1-flash"
  CONFIG="${CONFIG:-config.openrouter.toml}"
  IGNORED=""
else
  echo "substrate: no API key set — export OPENCODE_API_KEY or OPENROUTER_API_KEY" >&2
  exit 2
fi

export PROVIDER ENDPOINT KEY_VAR MODEL CONFIG

echo "provider: ${PROVIDER} — ${KEY_VAR} -> ${ENDPOINT}, model ${MODEL}, config ${CONFIG}${IGNORED}"
