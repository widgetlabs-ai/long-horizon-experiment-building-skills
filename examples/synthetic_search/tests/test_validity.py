"""tests/test_validity.py — is this candidate admissible at all."""

import pathlib

from synthetic_search.substrate import artifact as artifact_mod
from synthetic_search.substrate import corpus, validity

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
ROWS = corpus.generate(seed=7, n=300)


def _load(source: str):
    return artifact_mod.load(source)


def _names(violations):
    return {v.invariant for v in violations}


def test_the_shipped_artifact_is_admissible():
    # The gate. If this fails the invariants are wrong, not the artifact:
    # generation 0 would be dead on arrival for every reader of the example.
    classify = _load((EXPERIMENT / "artifact" / "rules.py").read_text())
    assert validity.check(classify, ROWS) == []


def test_a_memorising_table_is_refused():
    rules = "".join(
        f"    if re.search({row['text']!r}, t): return {row['label']!r}\n" for row in ROWS[:40]
    )
    source = f"def classify(text):\n    t = text.lower()\n{rules}    return 'unknown'\n"
    violations = validity.check(_load(source), ROWS)
    assert "robust_to_perturbation" in _names(violations)


def test_an_invented_label_is_refused():
    source = "def classify(text):\n    return 'urgent'\n"
    assert "labels_in_vocabulary" in _names(validity.check(_load(source), ROWS))


def test_a_nondeterministic_table_is_refused():
    # Keyed on the text, not a global counter: a counter flipping every call
    # returns the same answer for a row whose two calls are an even distance
    # apart -- which, over a 300-row split, is every row.
    seen = set()

    def classify(text):
        if text in seen:
            return "question"
        seen.add(text)
        return "greeting"

    assert "deterministic" in _names(validity.check(classify, ROWS))


def test_every_pass_gets_a_fresh_classify():
    # A zero-argument loader is called once per pass, so no pass can see state
    # an earlier one left behind.
    shipped = (EXPERIMENT / "artifact" / "rules.py").read_text()
    loads = []

    def load():
        loads.append(1)
        return _load(shipped)

    assert validity.check(load, ROWS) == []
    assert len(loads) == 3                         # first, determinism, perturbation


def test_state_kept_between_calls_is_still_nondeterminism_with_fresh_loads():
    # Fresh instances must not hide a table that answers a repeated text
    # differently: the determinism pass asks its own instance twice.
    source = (
        "SEEN = set()\n"
        "def classify(text):\n"
        "    if text in SEEN: return 'question'\n"
        "    SEEN.add(text)\n"
        "    return 'greeting'\n"
    )
    assert "deterministic" in _names(validity.check(lambda: _load(source), ROWS))


def test_a_table_that_changes_after_n_calls_is_nondeterminism():
    source = (
        f"SEEN = []\nN = {len(ROWS)}\n"
        "def classify(text):\n"
        "    SEEN.append(text)\n"
        "    return 'question' if len(SEEN) > N else 'greeting'\n"
    )
    assert "deterministic" in _names(validity.check(lambda: _load(source), ROWS))


def test_a_slow_table_is_refused(monkeypatch):
    monkeypatch.setattr(validity, "TIME_BUDGET_SECONDS", 0.0)
    classify = _load((EXPERIMENT / "artifact" / "rules.py").read_text())
    assert "bounded_time" in _names(validity.check(classify, ROWS))


def test_raising_on_a_perturbed_row_is_a_violation_not_a_crash():
    # Review Focus 4. The original classifies fine; the perturbation explodes.
    # That is a violation naming the row, not an exception escaping the stage
    # and being misreported as `score_error`.
    def classify(text):
        if text.endswith("."):
            raise ValueError("boom")
        return "greeting"

    violations = validity.check(classify, ROWS)
    assert "robust_to_perturbation" in _names(violations)
    assert any("raised" in v.detail for v in violations)


def test_raising_on_an_original_row_is_left_to_the_scorer():
    # The scorer already reports this as `score_error` with its own message.
    # Validity must not crash on it and must not claim it as a violation of its
    # own, or one defect is reported twice under two different names.
    def classify(text):
        raise ValueError("boom")

    assert validity.check(classify, ROWS) == []


def test_a_violation_names_the_row_and_the_perturbation():
    source = "def classify(text):\n    return 'greeting' if text == %r else 'unknown'\n" % ROWS[0]["text"]
    violations = validity.check(_load(source), ROWS)
    details = [v.detail for v in violations if v.invariant == "robust_to_perturbation"]
    # Every perturbation breaks an exact-match rule; the one that matters must
    # be among them, named, against the right row.
    assert any(ROWS[0]["id"] in d and "noise_swap" in d for d in details), details


def test_reported_violations_are_capped():
    source = "def classify(text):\n    return 'urgent'\n"
    violations = [v for v in validity.check(_load(source), ROWS) if v.invariant == "labels_in_vocabulary"]
    assert 0 < len(violations) <= validity.MAX_REPORTED


def test_an_unhashable_label_is_a_violation_not_a_crash():
    def classify(text):
        return ["greeting"]

    violations = validity.check(classify, ROWS)
    assert "labels_in_vocabulary" in _names(violations)


def test_a_second_call_that_raises_is_nondeterminism():
    seen = set()

    def classify(text):
        if text in seen:
            raise ValueError("boom")
        seen.add(text)
        return "greeting"

    assert "deterministic" in _names(validity.check(classify, ROWS))


def test_rows_the_candidate_gets_wrong_are_not_checked_for_robustness():
    def classify(text):
        # Wrong on every row (no row is labelled `farewell` below), and the
        # answer changes under a perturbation.
        return "question" if text.endswith(".") else "greeting"

    rows = [dict(r, label="farewell") for r in ROWS]
    violations = validity.check(classify, rows)
    assert "robust_to_perturbation" not in _names(violations)


def test_unknown_is_an_allowed_label():
    def classify(text):
        return artifact_mod.UNKNOWN

    assert "labels_in_vocabulary" not in _names(validity.check(classify, ROWS))
