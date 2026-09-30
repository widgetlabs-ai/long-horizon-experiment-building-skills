#!/usr/bin/env bash
# The outer loop. One generation = one eval, then:
#   post-generation (explain) -> promote (best eligible on train)
#   -> gate (val, per category) -> review (a stronger model; veto only)
#   -> adopt (artifact + baselines) -> commit.
#
# Exit 2 anywhere means the substrate is broken: stop the run, because every
# further generation would measure nothing while its numbers stayed plausible.
# A lost generation (nothing eligible, or the gate said no) is ordinary and the
# loop continues; the artifact is never touched unless a winner is adopted.
#
# Every error branch below is written the long way on purpose. Under `set -e`
# the short forms are silent-failure machines: a normal non-zero exit kills the
# script, `$?` read after a `case` is the case's status, and
# `[[ -f "$f" ]] && git add "$f"` returns 1 when the file is absent. This is the
# least-tested code in any search and it runs at 3am.
set -euo pipefail

EXPERIMENT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$EXPERIMENT"

SYNTH_STATE="${SYNTH_STATE:-$EXPERIMENT/state}"
export SYNTH_STATE
mkdir -p "$SYNTH_STATE/runs"

LOG="${1:-$SYNTH_STATE/runs/supervisor.log}"
if [[ -z "${SYNTH_LOG_TO_STDOUT:-}" ]]; then
  mkdir -p "$(dirname "$LOG")"
  exec >>"$LOG" 2>&1
fi

# Where the eval framework writes its run directories. Not under the state
# directory: the ignore rules, the README and the field guide all place it at
# the experiment root, and one of those being wrong is a stage that silently
# reads an empty path every generation.
OUTPUTS_DIR="${SYNTH_OUTPUTS:-$EXPERIMENT/outputs}"

MAX_GENERATIONS="${MAX_GENERATIONS:-1}"
NUM_ROLLOUTS="${NUM_ROLLOUTS:-3}"
MAX_CONCURRENT="${MAX_CONCURRENT:-3}"
MAX_TURNS="${MAX_TURNS:-}"

if [[ -n "$MAX_TURNS" && ! "$MAX_TURNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "substrate: MAX_TURNS must be a positive integer, got '$MAX_TURNS'"
  exit 2
fi

export PYTHONPATH="$EXPERIMENT/src${PYTHONPATH:+:$PYTHONPATH}"
CLI="python3 -m synthetic_search.substrate.cli"

# Which upstream. run.sh has usually resolved this already; a supervisor started
# on its own resolves it here, so the log still opens with the provider line.
. "$EXPERIMENT/provider.sh"

echo "=== synthetic-search supervisor starting $(date -Is) (log: $LOG) ==="

# The abort sentinel. A rollout that discovers the substrate is broken cannot
# cancel its siblings, but it can leave this file, and nothing starts while it
# exists.
if [[ -e "$SYNTH_STATE/ABORT" ]]; then
  echo "substrate: $SYNTH_STATE/ABORT exists — refusing to start"
  cat "$SYNTH_STATE/ABORT" || true
  exit 2
fi

# Generations are numbered across runs, not within one, so the promotions, the
# commit messages and any dashboard read as a single continuing search.
GEN_FILE="$SYNTH_STATE/generation"
if [[ -f "$GEN_FILE" ]]; then
  FIRST_GEN="$(cat "$GEN_FILE")"
else
  FIRST_GEN=0
fi

run_cli() {
  # One place where a command's exit code is captured rather than inherited, so
  # `set -e` cannot end the run on an ordinary "this candidate lost".
  local status=0
  if [[ -n "${SYNTH_FAKE_CLI_EXIT:-}" ]]; then
    return "${SYNTH_FAKE_CLI_EXIT}"
  fi
  $CLI "$@" || status=$?
  return "$status"
}

run_eval() {
  local status=0
  if [[ -n "${SYNTH_FAKE_EVAL:-}" ]]; then
    echo "eval: faked (SYNTH_FAKE_EVAL)"
    return 0
  fi
  uv run eval @ "$CONFIG" \
    --num-rollouts "$NUM_ROLLOUTS" \
    --max-concurrent "$MAX_CONCURRENT" \
    ${MAX_TURNS:+--max-turns "$MAX_TURNS"} \
    --no-push --no-rich -v || status=$?
  return "$status"
}

run_review() {
  # Its own seam, because SYNTH_FAKE_CLI_EXIT fakes every stage with one code
  # and a test needs the gate to pass while the reviewer refuses.
  local status=0
  if [[ -n "${SYNTH_FAKE_REVIEW_EXIT:-}" ]]; then
    echo "review: faked (SYNTH_FAKE_REVIEW_EXIT=${SYNTH_FAKE_REVIEW_EXIT})"
    return "${SYNTH_FAKE_REVIEW_EXIT}"
  fi
  run_cli review || status=$?
  return "$status"
}

stage_named() {
  # Named paths only. Staging everything in an unattended loop is a loop that
  # can commit a key sitting untracked in the tree; a glob is worse still,
  # because staging is atomic over its arguments and one ignored path fails the
  # whole add — silently, under the `|| true` the first generation needs.
  #
  # Three things can go wrong per path, and each has to be told apart:
  #   - the file does not exist yet (the first generation): skip it, quietly;
  #   - the file lives outside this repository (a state directory elsewhere, a
  #     supported configuration): skip it, and say so;
  #   - the file is IGNORED but we mean to commit it: that is a
  #     misconfiguration which would otherwise leave every later commit empty.
  #     Stop the run as a broken substrate, rather than exiting 1, which the
  #     loop reads as an ordinary lost candidate.
  local path status
  local toplevel
  toplevel="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  for path in "$@"; do
    if [[ ! -f "$path" ]]; then
      continue
    fi
    if [[ -z "$toplevel" || "$(cd "$(dirname "$path")" && pwd)" != "$toplevel"* ]]; then
      echo "stage: $path is outside this repository — not committed"
      continue
    fi
    if git check-ignore -q "$path"; then
      echo "substrate: $path must be committed but is ignored — fix the ignore rules"
      exit 2
    fi
    status=0
    git add "$path" || status=$?
    if [[ "$status" -ne 0 ]]; then
      echo "substrate: staging $path failed (git add exited $status)"
      exit 2
    fi
  done
}

latest_run() {
  # The eval framework names its own run directory and creates no `outputs/latest`
  # symlink -- its only `latest` is <run>/logs/latest, pointing at an attempt's
  # log directory INSIDE a run dir. Resolve the newest directory instead, and
  # refuse loudly rather than hand post-generation a path that does not exist:
  # that path reads as "no episodes", which is a broken substrate, and the run
  # would stop every generation with a message about the wrong thing.
  local newest
  newest="$(find "$OUTPUTS_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' 2>/dev/null \
            | sort -rn | head -1 | cut -d' ' -f2-)"
  if [[ -z "$newest" ]]; then
    echo "substrate: no run directory under $OUTPUTS_DIR -- the eval wrote nothing" >&2
    return 1
  fi
  printf '%s\n' "$newest"
}

generation=0
while [[ "$generation" -lt "$MAX_GENERATIONS" ]]; do
  number=$((FIRST_GEN + generation))
  echo "--- generation $number ($(date -Is)) ---"

  if [[ -e "$SYNTH_STATE/ABORT" ]]; then
    echo "substrate: ABORT appeared mid-run — stopping"
    exit 2
  fi

  status=0
  run_eval || status=$?
  if [[ "$status" -eq 2 ]]; then
    echo "substrate: eval reported a broken substrate — stopping"
    exit 2
  fi

  status=0
  if [[ -n "${SYNTH_FAKE_EVAL:-}" ]]; then
    # A faked eval writes no run directory at all -- there is nothing for
    # latest_run to find, by design. Hand post-generation a placeholder; its
    # own exit is faked too (SYNTH_FAKE_CLI_EXIT), so the placeholder is never
    # read for real.
    run_dir="$OUTPUTS_DIR/faked"
  else
    run_dir="$(latest_run)" || status=$?
    if [[ "$status" -ne 0 ]]; then
      echo "substrate: cannot locate this generation's run directory -- stopping"
      exit 2
    fi
  fi
  status=0
  run_cli post-generation --run "$run_dir" || status=$?
  if [[ "$status" -eq 2 ]]; then
    echo "substrate: post-generation reported a broken substrate — stopping"
    exit 2
  fi

  status=0
  run_cli promote || status=$?
  if [[ "$status" -eq 2 ]]; then
    echo "substrate: promote reported a broken substrate — stopping"
    exit 2
  fi
  if [[ "$status" -ne 0 ]]; then
    echo "generation $number: nothing eligible — continuing"
    generation=$((generation + 1))
    echo "$((number + 1))" > "$GEN_FILE"
    continue
  fi

  status=0
  run_cli gate || status=$?
  if [[ "$status" -eq 2 ]]; then
    echo "substrate: gate reported a broken substrate — stopping"
    exit 2
  fi
  if [[ "$status" -ne 0 ]]; then
    echo "generation $number: the gate said no — continuing"
    generation=$((generation + 1))
    echo "$((number + 1))" > "$GEN_FILE"
    continue
  fi

  status=0
  run_review || status=$?
  if [[ "$status" -eq 2 ]]; then
    echo "substrate: review reported a broken substrate — stopping"
    exit 2
  fi
  if [[ "$status" -ne 0 ]]; then
    echo "generation $number: the reviewer refused — continuing"
    generation=$((generation + 1))
    echo "$((number + 1))" > "$GEN_FILE"
    continue
  fi

  status=0
  run_cli adopt || status=$?
  if [[ "$status" -ne 0 ]]; then
    echo "substrate: adopt failed after a passing gate — stopping"
    exit 2
  fi

  if [[ -z "${SYNTH_SKIP_COMMIT:-}" ]]; then
    stage_named "artifact/rules.py" "$SYNTH_STATE/promotions.jsonl" "$SYNTH_STATE/gate_report.json" \
      "$SYNTH_STATE/reviews.jsonl"
    git commit -q -m "feat(search): adopt generation $number" || echo "nothing to commit"
  fi

  generation=$((generation + 1))
  echo "$((number + 1))" > "$GEN_FILE"
done

echo "=== supervisor done $(date -Is) ==="
