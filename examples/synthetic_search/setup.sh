#!/usr/bin/env bash
# One-shot setup: the python environment, a staged corpus, a pinned instrument
# and measured baselines. Everything here is local and offline.
set -euo pipefail

EXPERIMENT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$EXPERIMENT"

SYNTH_STATE="${SYNTH_STATE:-$EXPERIMENT/state}"
export SYNTH_STATE
mkdir -p "$SYNTH_STATE"

uv sync --group dev

CLI="uv run python -m synthetic_search.substrate.cli"
$CLI stage --seed "${SEED:-7}" --rows "${ROWS:-2000}"
$CLI pin
$CLI baseline --split all

echo
echo "ready. state: $SYNTH_STATE"
echo "next: ./run.sh --check   (needs OPENCODE_API_KEY or OPENROUTER_API_KEY)"
