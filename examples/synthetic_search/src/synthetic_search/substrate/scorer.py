"""The frozen scorer: macro-F1 over categories.

Frozen means exactly that: the search may not edit this file, and a candidate
that cannot be measured by it does not count. Changing it is a deliberate act
that re-pins the instrument and re-measures every baseline.

Two rules hold throughout:

- **Counts are integers; divide once, at the end.** Accumulating floats and
  subtracting them produces values that cancel to ±1e-16 with a sign that
  depends on the build, and a `> 0` test then disagrees between two machines
  that are running the same code.
- **Quantize anything that feeds a comparison.** `QUANTUM` places, everywhere,
  so two builds that agree to nine decimals agree about who won.
"""

from __future__ import annotations

QUANTUM = 9


def _q(value: float) -> float:
    return round(value, QUANTUM)


def per_category(pairs: list[tuple[str, str]], categories: tuple[str, ...] | None = None) -> dict[str, dict]:
    """Precision, recall, F1 and support per category.

    A category with no rows in this split scores `None`, never `0.0`. On a
    dashboard — and in a mean — a zero is a reading, and a reading nobody took
    is a lie that arithmetic will happily propagate.
    """
    if categories is None:
        categories = tuple(sorted({gold for gold, _ in pairs} | {pred for _, pred in pairs}))

    out: dict[str, dict] = {}
    for category in categories:
        true_positive = sum(1 for gold, pred in pairs if gold == category and pred == category)
        false_positive = sum(1 for gold, pred in pairs if gold != category and pred == category)
        support = sum(1 for gold, _ in pairs if gold == category)

        if support == 0:
            out[category] = {"precision": None, "recall": None, "f1": None, "support": 0}
            continue

        predicted = true_positive + false_positive
        precision = _q(true_positive / predicted) if predicted else 0.0
        recall = _q(true_positive / support)
        denominator = precision + recall
        f1 = _q(2 * precision * recall / denominator) if denominator else 0.0
        out[category] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
    return out


def macro_f1(pairs: list[tuple[str, str]], categories: tuple[str, ...] | None = None) -> float | None:
    """The mean F1 over categories that have support. `None` when none do."""
    stats = per_category(pairs, categories)
    scored = [s["f1"] for s in stats.values() if s["f1"] is not None]
    if not scored:
        return None
    return _q(sum(scored) / len(scored))
