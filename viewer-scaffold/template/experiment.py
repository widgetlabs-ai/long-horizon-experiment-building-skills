"""THE ONLY FILE THE SCAFFOLDER WRITES.

Everything here maps one experiment's own files onto the spine that `app.py`
and `static/index.html` render. Nothing else in the generated viewer should
need editing, and when the experiment's state layout later changes, this is the
file to change.

The spine, in full — see `reference/spine.md` for the field-by-field contract:

    run           one generation's eval output     runs(), run_mtime(), run_rollout_count()
    rollout       one container, one agent         rollouts(run), rollout_trace(run, id)
    promotion     an adopted winner                promotions()
    gate          the held-out check on a winner   gate()
    review        a stronger model's veto          reviews()  (optional)
    candidate     a returned artifact, scored      candidates()
    extras        everything else, self-describing extras()

THE RULE THIS FILE EXISTS TO KEEP: return values read from files at call time.
Never write a measured number into this file as a literal. Every figure on the
page must be traceable to a file on disk at the moment of the request — that is
what makes the dashboard an instrument rather than a report. `check_literals.py`
enforces it; it is not decoration.
"""

from __future__ import annotations

import os
from pathlib import Path

from lib import count_lines, mtime, read_json, read_jsonl, read_jsonl_counted

# --------------------------------------------------------------------- where

NAME = "TODO"                      # short experiment name, shown in the header
# The experiment root: <experiment>/viewer/.. by default. VIEWER_EXPERIMENT_ROOT
# points the viewer at any other root holding state/ and outputs/ — the committed
# fixtures (`VIEWER_EXPERIMENT_ROOT=fixtures`), a B output, or a copy of a real
# run. A relative value resolves against this directory, not the cwd.
_HERE = Path(__file__).resolve().parent
ROOT = (_HERE / os.environ["VIEWER_EXPERIMENT_ROOT"]).resolve() if os.environ.get("VIEWER_EXPERIMENT_ROOT") else _HERE.parent
STATE_DIR = ROOT / "state"         # TODO: the experiment's state dir
OUTPUTS_DIR = ROOT / "outputs"     # TODO: where one run dir per generation lands

# Optional live probes. Leave any of them None and the UI says "unavailable"
# instead of drawing a zero that reads as "nothing is running".
DOCKER_IMAGE = None                # TODO e.g. "myexperiment-harness:pinned"
PROCESS_PATTERN = None             # TODO e.g. "supervisor.sh|uv run eval"
LOG_GLOB = None                    # TODO e.g. (STATE_DIR / "runs", "*.log")
GENERATION_RE = None               # TODO e.g. r"^--- generation (\d+)\b"


# ---------------------------------------------------------------------- runs

def runs() -> list[str]:
    """Run ids, newest first. One run = one generation's eval output."""
    raise NotImplementedError("TODO")


def run_mtime(run_id: str) -> str:
    raise NotImplementedError("TODO")


def run_rollout_count(run_id: str) -> int:
    """Cheap count for the live cards — must not parse the whole trace file."""
    raise NotImplementedError("TODO")


# ------------------------------------------------------------------ rollouts

def rollouts(run_id: str) -> tuple[list[dict], int]:
    """(rollout summaries, count of unreadable lines).

    Each summary:
        id       str   short, stable within the run
        ok       bool
        errors   list[str]
        stop     str | None    why the episode ended
        turns    int | None
        reward   float | None  this rollout's measured score
        gain     float | None  reward minus the current baseline
        verdict  str | None    what the host made of what came back
        label    str | None    which sub-problem this rollout worked on
        detail   list[str]     free strings shown in the last column
    """
    raise NotImplementedError("TODO")


def rollout_trace(run_id: str, rollout_id: str) -> dict | None:
    """One rollout's full transcript, or None when there is no such rollout.

        id, ok, errors, stop, rewards, metrics, tools, calls,
        nodes: [{role, content, tool_calls: [{name, input, call_id}]}]

    Read this from the harness's own trace file. Do not normalise or copy the
    trace into your own format: it is large (one generation is megabytes) and
    it is not yours to own.
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------- promotions

def promotions() -> list[dict]:
    """The adopted winners, in order. This is the reward curve.

        generation int
        id         str
        reward     float          the measure the search optimises
        baseline   float | None   the level before the search (first record only)
        gain       float | None
        held_out   float | None   the same measure on data the search never saw
        detail     list[str]
    """
    raise NotImplementedError("TODO")


# ---------------------------------------------------------------------- gate

def gate() -> dict | None:
    """The most recent held-out check, or None when there has not been one.

        generation int
        passed     bool
        before     float | None
        after      float | None
        failures   list[str]
    """
    raise NotImplementedError("TODO")


# OPTIONAL. Delete this function if the experiment has no reviewer stage; the
# page then shows no reviews section at all.
def reviews() -> list[dict]:
    """One entry per review, newest first. See reference/spine.md, `reviews`."""
    return []   # TODO: read the experiment's review record


# ---------------------------------------------------------------- candidates

def candidates() -> list[dict]:
    """Everything a rollout returned that was scored, adopted or not.

        id       str
        label    str | None
        reward   float | None
        verdict  str | None
        detail   list[str]
        status   str | None   free text, shown on hover
    """
    raise NotImplementedError("TODO")


# -------------------------------------------------------------------- extras

def extras() -> list[dict]:
    """Everything this experiment measures that the spine has no word for.

    Blocks are self-describing and the UI renders them without knowing the
    domain, so a new measurement needs a change here and nowhere else:

        {"kind": "kv",    "title": str, "note": str|None,
         "rows": [[label, value], ...]}

        {"kind": "table", "title": str, "note": str|None,
         "columns": [str], "rows": [[cell, ...], ...]}

        {"kind": "series","title": str, "note": str|None,
         "points": [[x, y], ...]}

    A table cell is a scalar, or {"text", "class", "title", "spark"} where
    `class` is one of ok/bad/warn/muted, `title` is the hover text and `spark`
    is [[x, y], ...] drawn as a sparkline inside the cell.

    Any block may add "place": "top" (default, under the live cards),
    "promotions" (under the reward curve) or "candidates" (under the list).

    Return [] when there is nothing beyond the spine.
    """
    raise NotImplementedError("TODO")


# --------------------------------------------------------------------- notes

def notes() -> dict:
    """Prose explaining each spine section, in this experiment's vocabulary.

        {section: note}   section is one of
                          live, runs, rollouts, promotions, gate, candidates,
                          reviews (only if the experiment has a reviewer stage)
        note              str, or {"text": str | None,
                                   "terms": [[term, definition], ...]}

    `terms` is a glossary — column names, verdicts, stop reasons. Everything is
    rendered as plain text.

    NO DIGITS IN NOTE TEXT. Prose is where a typed-in number goes stale
    unnoticed ("5 tasks x 3 rollouts" after the run moved to one rollout per
    task). If a note needs a figure, read it at call time and interpolate it:
    f"up to {max_turns} turns". `check_literals.py` flags any digit in a string
    literal inside this function, and in any extras block's "note".

    Return {} for no notes; a section with no note renders nothing.
    """
    return {}
