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

from pathlib import Path

from __EXPERIMENT__.substrate import corpus

# Everything a rollout may change, and everything that comes back. Relative to
# the container's workdir.
ARTIFACT_PATHS = ("artifact/rules.py",)

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
