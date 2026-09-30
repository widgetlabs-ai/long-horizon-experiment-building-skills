"""Measuring one artifact against one split — the only way anything is scored.

Candidate rewards, baselines and the gate all come through here, so there is
one definition of "the number" and no second path that can drift from it.

Two properties matter more than the arithmetic:

**Extract once, score many.** The agent scores dozens of times per rollout, so
the cached path has to be cheap or the whole loop is unusable. The cache key
covers everything that could change the answer — the artifact, the instrument,
the split's manifest — because a cache that silently disagrees with the code
that filled it is the worst kind of bug: every number stays plausible.

**A zero is never ambiguous.** `reward` is `None` unless a measurement actually
happened, and each way of not happening has its own flag. A report that cannot
distinguish "the candidate is bad" from "the candidate never arrived" from "the
scorer broke" makes a whole generation unreadable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from synthetic_search.substrate import artifact as artifact_mod
from synthetic_search.substrate import corpus, scorer, validity
from synthetic_search.substrate.errors import CandidateError, SubstrateError

SUBSTRATE_DIR = Path(__file__).resolve().parent

# The frozen instrument. Anything that can change a score belongs in this list,
# because the pin is what refuses to compare numbers produced by two different
# rulers.
INSTRUMENT_FILES = ("scorer.py", "measure.py", "artifact.py", "corpus.py", "validity.py")

# Where a candidate's admissibility is decided. Train, because train is what
# produces the reward and is the only split the box carries; checking a
# held-out split would spend it on a question the gate is not asking.
VALIDITY_SPLIT = "train"


def instrument_pin(root: Path | None = None) -> str:
    """A content hash over the frozen files."""
    root = Path(root) if root is not None else SUBSTRATE_DIR
    digest = hashlib.sha256()
    for name in INSTRUMENT_FILES:
        path = root / name
        if not path.is_file():
            raise SubstrateError(f"instrument file missing: {path}")
        digest.update(name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def cache_key(source: str, split: str, state: Path) -> str:
    parts = (
        artifact_mod.digest(source),
        instrument_pin(),
        corpus.split_digest(state, split),
        split,
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def _empty_report() -> dict:
    """Every way this can fail, named, so no caller has to guess at a zero."""
    return {
        "reward": None,
        "per_category": {},
        "rows": 0,
        "error": None,
        "guard_rejected": 0.0,
        "score_error": 0.0,
        "validity_failed": 0.0,
        "violations": [],
        "cached": False,
    }


def measure_source(source: str, split: str, state: Path, use_cache: bool = True) -> dict:
    """Score one artifact source against one split."""
    state = Path(state)
    report = _empty_report()

    key = cache_key(source, split, state)
    cache_path = state / "cache" / f"{key}.json"
    if use_cache and cache_path.is_file():
        # Merge over the empty report rather than returning the file as-is: a
        # cache written by an older shape is missing fields that callers index
        # directly, and a KeyError deep in promote is a broken run, not a lost
        # candidate.
        cached = {**_empty_report(), **json.loads(cache_path.read_text())}
        cached["cached"] = True
        return cached

    try:
        classify = artifact_mod.load(source)
    except CandidateError as exc:
        report["guard_rejected"] = 1.0
        report["error"] = str(exc)
        return report

    rows = corpus.load_split(state, split)
    if split == VALIDITY_SPLIT:
        # A fresh instance for every validity pass and another for scoring, so
        # a table that keeps state between calls is scored as validity saw it.
        violations = validity.check(lambda: artifact_mod.load(source), rows)
        if violations:
            # Refused before scoring, so never scored: `reward` stays None. A
            # zero here would be indistinguishable on the curve from a candidate
            # that was measured and was bad.
            report["validity_failed"] = 1.0
            report["violations"] = [str(v) for v in violations]
            report["error"] = f"the artifact is not admissible: {violations[0]}"
            return report
        try:
            classify = artifact_mod.load(source)
        except CandidateError as exc:
            # `guard_rejected`, because that is what `load` refusing a source
            # means everywhere in this function: the table never reached a
            # classifier, so it was not measured and did not raise while
            # classifying (`score_error`). It is not `validity_failed` either:
            # every validity pass loaded and passed, and a report must not
            # claim a violation the check never found. Never raised further:
            # one candidate failing here would otherwise exit 2 and stop the
            # whole search.
            report["guard_rejected"] = 1.0
            report["error"] = f"the artifact passed the validity check, then failed to load for scoring: {exc}"
            return report

    try:
        pairs = [(row["label"], classify(row["text"])) for row in rows]
    except Exception as exc:  # the candidate's classifier raising is the candidate's problem
        report["score_error"] = 1.0
        report["error"] = f"the artifact raised while classifying: {exc!r}"
        return report

    report["reward"] = scorer.macro_f1(pairs, corpus.CATEGORIES)
    report["per_category"] = scorer.per_category(pairs, corpus.CATEGORIES)
    report["rows"] = len(rows)
    if report["reward"] is None:
        report["score_error"] = 1.0
        report["error"] = f"no category in split {split!r} had any support"
        return report

    if use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report
