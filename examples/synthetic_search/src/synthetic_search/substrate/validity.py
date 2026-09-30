"""Is this candidate admissible at all -- the question the reward cannot ask.

The reward says how good a candidate is. It cannot say whether the candidate
earned its number, and a cheap model handed a fixed split and a scalar to
maximise will eventually stop solving the problem and start solving the
measurement. These invariants hold, or the candidate is not measured at all.

Every one is *behavioural*. None reads the table's structure, so none can be
evaded by restructuring it and none constrains how a candidate is written.
`robust_to_perturbation` is the one that earns its place: a rule keyed to an
exact training string dies under a rewrite the grammar guarantees preserves the
label, and an inlined copy of that rule dies exactly the same way.

Not `selftest.py`. That module checks the invariants the whole SEARCH rests on,
once, before a generation is spent. These are the CANDIDATE's, checked once per
candidate, and a failure here is an ordinary lost candidate rather than a
broken substrate.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass

from synthetic_search.substrate import artifact as artifact_mod
from synthetic_search.substrate import corpus
from synthetic_search.substrate.errors import CandidateError

# The whole check -- the first pass, the determinism pass and the perturbation
# pass -- must fit in this. Several hundred times the measured cost on purpose:
# it catches a table that is slow but finishes, not a performance budget. A
# table that never finishes cannot be caught here (Python cannot interrupt a
# running regex in-process). Only rollout scoring bounds that: the host's
# scoring subprocess timeout, `taskset.SCORE_TIMEOUT`. `promote`, `gate`,
# `adopt`, `review` and `rt` measure in-process with no timeout at all, so a
# table that never finishes hangs them.
TIME_BUDGET_SECONDS = 5.0

# Violations reported per invariant. A table that returns one invented label
# breaks on every row, and a thousand identical lines in a log is a log nobody
# reads.
MAX_REPORTED = 5

_RAISED = object()


@dataclass(frozen=True)
class Violation:
    invariant: str
    detail: str

    def __str__(self) -> str:
        return f"{self.invariant}: {self.detail}"


def _safe(classify, text):
    """`classify(text)`, or `_RAISED`. Never lets a candidate's bug reach a caller."""
    try:
        return classify(text)
    except Exception:  # noqa: BLE001 - the candidate's bug is the candidate's
        return _RAISED


def _as_loader(load):
    """A zero-argument loader as given, or a bare `classify` wrapped as one.

    A bare `classify` is shared by every pass, which is only sound for a table
    with no state; the loop always passes a loader.
    """
    try:
        inspect.signature(load).bind()
    except (TypeError, ValueError):
        return lambda: load
    return load


def check(load, rows: list[dict]) -> list[Violation]:
    """Every invariant this candidate breaks, in a fixed order. Empty is a pass.

    `load` is a zero-argument callable returning a FRESH `classify` each call,
    and every pass gets its own. One instance serving every pass let a table
    count its calls in a module-level list, answer honestly for as long as the
    check was asking, and cheat once scoring began. `measure_source` loads yet
    another instance to score, so the number is the one for the table this
    check saw. A bare one-argument `classify` is still accepted, shared.

    A pass whose load raises `CandidateError` is the `load_stable` violation,
    naming the pass, and ends the check: this is a lost candidate, and letting
    the error out would make it a stopped run.

    Rows the candidate cannot classify at all are skipped rather than reported:
    the scorer already names that `score_error` with a better message, and one
    defect reported twice under two names is one defect nobody can count.
    """
    load = _as_loader(load)
    started = time.perf_counter()
    violations: list[Violation] = []
    try:
        classify = _fresh(load, 1)
        usable = [(row, _safe(classify, row["text"])) for row in rows]
        usable = [(row, label) for row, label in usable if label is not _RAISED]
        violations += _labels_in_vocabulary(usable)
        violations += _deterministic(_fresh(load, 2), usable)
        robust = _robust_to_perturbation(_fresh(load, 3), usable)
    except _Unstable as exc:
        # The passes already run are kept: a later load failing does not make
        # an earlier violation any less real.
        return violations + [exc.violation]
    elapsed = time.perf_counter() - started
    if elapsed > TIME_BUDGET_SECONDS:
        violations.append(
            Violation("bounded_time", f"the check took {elapsed:.2f}s, over the {TIME_BUDGET_SECONDS:.2f}s budget")
        )
    return violations + robust


class _Unstable(Exception):
    """A pass could not load its table."""

    def __init__(self, violation: Violation):
        super().__init__(str(violation))
        self.violation = violation


def _fresh(load, n: int):
    """`load()` for pass `n`, or `_Unstable` naming the pass it failed on.

    Every pass loads its own table, so every pass is a chance for the load to
    fail -- a table can carry state between loads through anything they share
    and refuse to load the second time. That is this candidate failing, never
    the substrate: a `CandidateError` escaping here stops the whole search.
    """
    try:
        return load()
    except CandidateError as exc:
        raise _Unstable(Violation("load_stable", f"the table failed to load on pass {n}: {exc}")) from exc


def _labels_in_vocabulary(usable) -> list[Violation]:
    allowed = set(corpus.CATEGORIES) | {artifact_mod.UNKNOWN}
    found = []
    for row, label in usable:
        if not isinstance(label, str) or label not in allowed:
            found.append(Violation("labels_in_vocabulary", f"row {row['id']} classified as {label!r}, which is not a category"))
        if len(found) == MAX_REPORTED:
            break
    return found


def _deterministic(classify, usable) -> list[Violation]:
    """Each row, asked twice of an instance the first pass never touched.

    Twice, because a fresh instance alone would hide a table that keeps state
    between calls: it would replay the first pass exactly. Asking again on the
    same instance is what exposes an answer that depends on having been asked.
    """
    found = []
    for row, label in usable:
        for again in (_safe(classify, row["text"]), _safe(classify, row["text"])):
            if again is _RAISED:
                found.append(Violation("deterministic", f"row {row['id']} classified {label!r} then raised"))
                break
            if again != label:
                found.append(Violation("deterministic", f"row {row['id']} classified {label!r} then {again!r}"))
                break
        if len(found) == MAX_REPORTED:
            break
    return found


def _robust_to_perturbation(classify, usable) -> list[Violation]:
    """Rows the candidate gets RIGHT must survive a label-preserving rewrite.

    Restricted to correct rows on purpose. A row the table already gets wrong
    changing its answer under a rewrite says nothing -- it was not relying on
    anything worth protecting.
    """
    found = []
    for row, label in usable:
        if label != row["label"]:
            continue
        for name, rewritten in corpus.perturbations(row["text"], row["label"]).items():
            after = _safe(classify, rewritten)
            if after is _RAISED:
                found.append(Violation("robust_to_perturbation", f"row {row['id']} raised under {name}: {rewritten!r}"))
            elif after != label:
                found.append(Violation("robust_to_perturbation", f"row {row['id']} was {label!r}, became {after!r} under {name}: {rewritten!r}"))
            if len(found) == MAX_REPORTED:
                return found
    return found
