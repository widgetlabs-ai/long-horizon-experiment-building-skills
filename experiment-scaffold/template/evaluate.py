"""Turning a measurement into metrics, and into what the brief tells an agent.

The metrics list is the part of an experiment that cannot be copied from
another one: every search has its own ways of returning nothing, and naming
them is the only thing that makes `reward = 0` readable in a summary of
fifteen rollouts.

`ZERO_REASONS` is that list for this search. A new experiment answers the same
question for itself — *name every way this can return zero* — and gets its own.
"""

from __future__ import annotations

# Every way a rollout can produce no measurement. Each is emitted as a 0/1
# metric on every trace, so a zero in the summary always says which kind it is.
# Include a reason for the validity check refusing a candidate (contracts.md §7).
ZERO_REASONS = (
    "artifact_unchanged",  # the agent returned what it was given
    "guard_rejected",      # the artifact reached outside the text it was handed
    "score_error",         # the scorer could not produce a number
)


def summarize(report: dict) -> dict:
    """Metrics for one trace: every reason present, defaulted, never inferred."""
    metrics: dict[str, float | None] = {reason: 0.0 for reason in ZERO_REASONS}
    metrics["reward"] = report.get("reward")
    for reason in ZERO_REASONS:
        if report.get(reason):
            metrics[reason] = 1.0
    metrics["rows"] = float(report.get("rows", 0))
    return metrics


def worst_categories(report: dict, limit: int = 3) -> list[str]:
    """The measured categories with the lowest F1, weakest first.

    A category with no support is not "bad"; it is unmeasured, and telling an
    agent to work on it would send it after rows that do not exist.
    """
    measured = [
        (stats["f1"], name)
        for name, stats in report.get("per_category", {}).items()
        if stats.get("f1") is not None
    ]
    measured.sort()
    return [name for _, name in measured[:limit]]


def gain(reward: float | None, baseline: float | None) -> float | None:
    """Reward minus baseline, or None when either side was never measured."""
    if reward is None or baseline is None:
        return None
    return round(reward - baseline, 9)
