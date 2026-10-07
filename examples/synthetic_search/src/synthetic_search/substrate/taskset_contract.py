"""What the taskset promises, separated from the framework that delivers it.

`taskset.py` needs the eval framework; this file does not, so the facts the
brief and the image depend on can be tested — and read inside the rollout
container — without installing an orchestrator.

The one fact worth stating twice: `ARTIFACT_PATHS` is the single definition of
what comes back from a rollout. The brief renders from it and `finalize`
returns it. When those two drift apart, agents spend their budget writing to a
path that is deleted with the container, every rollout looks healthy, and the
only symptom is that nothing ever improves.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from synthetic_search.substrate import corpus

# Everything a rollout may change, and everything that comes back. Relative to
# the container's workdir.
ARTIFACT_PATHS = ("artifact/rules.py",)

# The in-box checkpoint. `rt score` commits every admissible version to the
# container's git and tags the best-scoring one, then materialises that tagged
# version to `CHECKPOINT_PATH`. `finalize` returns it rather than the working
# tree, so a rollout that improves and then regresses hands back its best
# admissible version, not its last edit. The container's git is throwaway state
# that only `finalize` reads; `CHECKPOINT_PATH` is how the tagged content crosses
# the runtime's file API, which cannot reach git objects directly.
BEST_TAG = "rt-best"
CHECKPOINT_PATH = "/tmp/rt-best"

# The environment variable that carries the rollout's turn budget into the box.
# `taskset.runtime_env` sets it; `box` reads it to report how many turns remain.
# One definition, so the writer and the reader cannot drift onto different names.
TURN_BUDGET_ENV = "SYNTH_MAX_TURNS"

# Splits that must never enter the rollout image's build context. A box that can
# read the split it is gated on turns the gate into decoration, and nothing
# anywhere errors.
HELD_OUT_SPLITS = ("val", "test")

BRIEF_PLACEHOLDERS = ("{{CLASS}}", "{{BASELINE}}", "{{WORST}}", "{{ROWS}}", "{{TURNS}}")


class BriefError(RuntimeError):
    """The brief could not be rendered — a missing or unknown placeholder."""


def held_out_paths() -> tuple[str, ...]:
    return tuple(f"corpus/{split}" for split in HELD_OUT_SPLITS)


def candidate_dir(state: Path, trace_id: str) -> Path:
    """Where a rollout's returned artifact lands."""
    return Path(state) / "candidates" / str(trace_id)


CANDIDATE_FILE = "candidate.json"


def record_candidate(destination: Path, fields: dict) -> None:
    """Merge `fields` into the candidate's record.

    Two callers write this file at different moments -- `finalize` knows what
    came back, `score` knows what it was worth -- and neither owns the whole
    record. A plain write from the second would drop the first's fields.

    `None` is written as `null` and never coerced to a number: a dashboard
    shows a missing reading as "—" and a measured zero as a zero, and a reader
    cannot tell them apart once they are the same value.

    Two failure modes matter here because this is read-modify-write and
    `finalize` then `score` both call it for the same candidate:

    - A process killed between "read" and "write" must not leave a truncated
      file that every later call then trips over. Write to a temp file in the
      same directory and `os.replace` it over the real one: `os.replace` is
      atomic within a filesystem, so a reader always sees either the whole old
      file or the whole new one, never a partial write.
    - An unreadable existing record (from an earlier crash, or anything else)
      must not make the candidate permanently unwritable -- refusing here
      would fail every future write to this candidate, not just this one.
      Start from an empty record instead and carry on. That loses whatever
      the earlier writer put there, but a candidate with a smaller record is
      recoverable; a candidate that can never be written to again is not.
    """
    path = Path(destination) / CANDIDATE_FILE
    try:
        record = json.loads(path.read_text()) if path.is_file() else {}
    except json.JSONDecodeError:
        record = {}
    record.update(fields)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def render_brief(template: str, data: dict) -> str:
    """Substitute every placeholder, and refuse one nobody defined."""
    values = {
        "{{CLASS}}": str(data["task_class"]),
        "{{BASELINE}}": f"{data['baseline_reward']:.5f}",
        "{{WORST}}": "\n".join(f"    {name}" for name in data["worst"]) or "    (none recorded)",
        "{{ROWS}}": str(data["rows"]),
        "{{TURNS}}": str(data["turns"]),
    }
    out = template
    for placeholder, value in values.items():
        out = out.replace(placeholder, value)
    if "{{" in out:
        unknown = out[out.index("{{") : out.index("{{") + 40]
        raise BriefError(f"unknown placeholder in the brief: {unknown!r}")
    return out


def task_classes() -> tuple[str, ...]:
    """One task per category: the sub-problems a generation divides into."""
    return corpus.CATEGORIES
