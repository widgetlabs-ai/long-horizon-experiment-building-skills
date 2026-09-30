"""measure_source: the only way anything is scored, cached and unambiguous."""

import json
import time
from pathlib import Path

import pytest

from synthetic_search.substrate import corpus, evaluate, measure

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"
EXPERIMENT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def staged(tmp_path):
    corpus.stage(tmp_path, seed=7, n=200)
    return tmp_path


def test_measure_returns_a_reward(staged):
    out = measure.measure_source(ARTIFACT.read_text(), "train", staged)
    assert 0.0 < out["reward"] <= 1.0


def test_measure_is_deterministic(staged):
    source = ARTIFACT.read_text()
    first = measure.measure_source(source, "train", staged)["reward"]
    second = measure.measure_source(source, "train", staged, use_cache=False)["reward"]
    assert first == second


def test_measure_caches_on_the_second_call(staged):
    source = ARTIFACT.read_text()
    measure.measure_source(source, "train", staged)
    started = time.perf_counter()
    out = measure.measure_source(source, "train", staged)
    assert out["cached"] is True
    assert time.perf_counter() - started < 0.05


def test_measure_reports_score_error_rather_than_zero(staged):
    out = measure.measure_source("def classify(t):\n    raise ValueError('x')\n", "train", staged)
    assert out["score_error"] == 1.0
    assert out["reward"] is None


def test_measure_reports_a_guarded_candidate_rather_than_zero(staged):
    out = measure.measure_source("import json\ndef classify(t): return 'a'\n", "train", staged)
    assert out["guard_rejected"] == 1.0
    assert out["reward"] is None
    assert "import" in out["error"]


def test_measure_reports_per_category(staged):
    out = measure.measure_source(ARTIFACT.read_text(), "train", staged)
    assert set(out["per_category"]) == set(corpus.CATEGORIES)


def test_cache_key_changes_with_the_artifact(staged):
    first = measure.cache_key("def classify(t): return 'a'", "train", staged)
    second = measure.cache_key("def classify(t): return 'b'", "train", staged)
    assert first != second


def test_cache_key_changes_with_the_split(staged):
    source = ARTIFACT.read_text()
    assert measure.cache_key(source, "train", staged) != measure.cache_key(source, "val", staged)


def test_cache_key_changes_when_the_instrument_changes(staged, monkeypatch):
    source = ARTIFACT.read_text()
    before = measure.cache_key(source, "train", staged)
    monkeypatch.setattr(measure, "instrument_pin", lambda root=None: "0000000000000000")
    assert measure.cache_key(source, "train", staged) != before


def test_instrument_pin_covers_the_scorer(staged):
    assert "scorer.py" in " ".join(measure.INSTRUMENT_FILES)


def test_instrument_pin_is_stable():
    assert measure.instrument_pin() == measure.instrument_pin()


def test_cache_key_changes_when_the_rows_change(staged):
    # The manifest is written last by `stage`, so an interrupted re-stage leaves
    # changed rows under an unchanged manifest. A key that covers only the
    # manifest then serves a stale reward that looks entirely plausible.
    source = ARTIFACT.read_text()
    before = measure.cache_key(source, "train", staged)
    rows = staged / "corpus" / "train" / "rows.jsonl"
    kept = rows.read_text().split("\n")[:10]
    rows.write_text("\n".join(kept) + "\n")
    assert measure.cache_key(source, "train", staged) != before


def test_a_stale_cache_is_not_served_after_the_rows_change(staged):
    source = ARTIFACT.read_text()
    first = measure.measure_source(source, "train", staged)
    rows = staged / "corpus" / "train" / "rows.jsonl"
    rows.write_text("\n".join(rows.read_text().split("\n")[:10]) + "\n")
    second = measure.measure_source(source, "train", staged)
    assert second["rows"] != first["rows"]


def test_a_cache_written_by_an_older_shape_does_not_crash_a_reader(staged):
    source = ARTIFACT.read_text()
    measure.measure_source(source, "train", staged)
    key = measure.cache_key(source, "train", staged)
    path = staged / "cache" / f"{key}.json"
    path.write_text(json.dumps({"reward": 0.5}))
    report = measure.measure_source(source, "train", staged)
    for field in ("guard_rejected", "score_error", "per_category", "rows", "error"):
        assert field in report, field


MEMORISING = (
    "def classify(text):\n"
    "    t = text.lower()\n"
    "    if t == 'hello how are you': return 'greeting'\n"
    "    return 'unknown'\n"
)


def test_the_validity_module_is_part_of_the_instrument():
    # A cached report must not outlive a change to what makes a candidate admissible.
    assert "validity.py" in measure.INSTRUMENT_FILES


def test_every_report_names_validity_even_when_it_passed(staged):
    report = measure.measure_source(ARTIFACT.read_text(), "train", staged, use_cache=False)
    assert report["validity_failed"] == 0.0
    assert report["violations"] == []


def test_an_inadmissible_candidate_is_never_scored(staged):
    # Build a state whose train split contains the exact row being memorised,
    # so the candidate is right on it and the perturbation has something to break.
    rows = corpus.load_split(staged, "train")
    target = rows[0]
    source = (
        "def classify(text):\n"
        f"    if text == {target['text']!r}: return {target['label']!r}\n"
        "    return 'unknown'\n"
    )
    report = measure.measure_source(source, "train", staged, use_cache=False)
    assert report["validity_failed"] == 1.0
    assert report["reward"] is None          # never measured, so never 0
    assert report["violations"]
    assert "not admissible" in report["error"]


def test_validity_is_checked_on_train_only(staged):
    # The held-out splits are the gate's; validity runs where the reward does.
    rows = corpus.load_split(staged, "val")
    target = rows[0]
    source = (
        "def classify(text):\n"
        f"    if text == {target['text']!r}: return {target['label']!r}\n"
        "    return 'unknown'\n"
    )
    report = measure.measure_source(source, "val", staged, use_cache=False)
    assert report["validity_failed"] == 0.0


def _call_counting_cheat(rows) -> str:
    """The shipped table, until it has been called more than 2*N times.

    One classify instance used to serve the first validity pass (N calls), the
    determinism pass (N more) and then scoring. A table that counts its calls in
    a module-level list can therefore pass validity honestly and answer from a
    memorised copy of the split only once scoring starts.
    """
    honest = ARTIFACT.read_text().replace("def classify(text):", "def _honest(text):")
    memo = {row["text"]: row["label"] for row in rows}
    return honest + (
        f"\nSEEN = []\nMEMO = {memo!r}\nN = {len(rows)}\n\n"
        "def classify(text):\n"
        "    SEEN.append(text)\n"
        "    if len(SEEN) > 2 * N:\n"
        "        return MEMO.get(text, _honest(text))\n"
        "    return _honest(text)\n"
    )


def test_a_table_that_counts_its_calls_is_scored_as_validity_saw_it(staged):
    rows = corpus.load_split(staged, "train")
    honest = measure.measure_source(ARTIFACT.read_text(), "train", staged, use_cache=False)
    assert honest["reward"] < 1.0                        # otherwise the probe proves nothing
    report = measure.measure_source(_call_counting_cheat(rows), "train", staged, use_cache=False)
    assert report["reward"] != 1.0
    assert report["validity_failed"] == 1.0 or report["reward"] == honest["reward"]


def test_validity_failed_is_a_named_zero_reason():
    assert "validity_failed" in evaluate.ZERO_REASONS


def _fail_on_load(monkeypatch, source: str, failing: set[int]) -> None:
    """Make loading `source` raise `CandidateError` on the given loads (1-based).

    A stand-in for any table whose later load fails -- state carried between
    loads through something shared, say. Every other source loads normally, so
    a good candidate beside it is untouched.
    """
    from synthetic_search.substrate import artifact as artifact_mod
    from synthetic_search.substrate.errors import CandidateError

    real = artifact_mod.load
    seen = {"n": 0}

    def load(text):
        if text != source:
            return real(text)
        seen["n"] += 1
        if seen["n"] in failing:
            raise CandidateError(f"the artifact raised while loading: load {seen['n']}")
        return real(text)

    monkeypatch.setattr(artifact_mod, "load", load)


def test_a_table_that_fails_its_second_load_is_a_lost_candidate(staged, monkeypatch):
    source = ARTIFACT.read_text() + "\n# flaky\n"
    _fail_on_load(monkeypatch, source, {2})
    report = measure.measure_source(source, "train", staged, use_cache=False)
    assert report["reward"] is None
    assert report["validity_failed"] == 1.0
    assert report["violations"][0].startswith("load_stable: the table failed to load on pass 1")


def test_a_table_that_fails_a_later_validity_load_is_a_lost_candidate(staged, monkeypatch):
    source = ARTIFACT.read_text() + "\n# flaky\n"
    _fail_on_load(monkeypatch, source, {4})
    report = measure.measure_source(source, "train", staged, use_cache=False)
    assert report["reward"] is None
    assert report["validity_failed"] == 1.0
    assert any(v.startswith("load_stable: the table failed to load on pass 3") for v in report["violations"])


def test_a_table_that_fails_its_scoring_load_is_a_lost_candidate(staged, monkeypatch):
    # Loads on train: the guard's, three validity passes, then scoring's.
    source = ARTIFACT.read_text() + "\n# flaky\n"
    _fail_on_load(monkeypatch, source, {5})
    report = measure.measure_source(source, "train", staged, use_cache=False)
    assert report["reward"] is None
    assert report["guard_rejected"] == 1.0
    assert "load 5" in report["error"]
    assert evaluate.summarize(report)["guard_rejected"] == 1.0


def _load_counting_cheat(rows) -> str:
    """The reviewer's probe: count loads on `re.search`, cheat on the scoring one.

    On train, `measure_source` loads the table five times -- the guard's, three
    validity passes, then scoring's -- so `loads % 5 == 0` is exactly the scored
    instance. Fresh loads alone do not stop this: the counter lives on an object
    every load shares. The bare `except` is because the artifact has no
    `AttributeError` to name.
    """
    honest = ARTIFACT.read_text().replace("def classify(text):", "def _honest(text):")
    memo = {row["text"]: row["label"] for row in rows}
    return honest + (
        "\ntry:\n"
        "    re.search.loads += 1\n"
        "except:\n"
        "    re.search.loads = 1\n"
        f"MEMO = {memo!r}\n\n"
        "def classify(text):\n"
        "    if re.search.loads % 5 == 0:\n"
        "        return MEMO.get(text, _honest(text))\n"
        "    return _honest(text)\n"
    )


def test_a_table_that_counts_its_loads_is_not_scored_as_a_cheat(staged):
    rows = corpus.load_split(staged, "train")
    honest = measure.measure_source(ARTIFACT.read_text(), "train", staged, use_cache=False)
    assert honest["reward"] < 1.0                        # otherwise the probe proves nothing
    report = measure.measure_source(_load_counting_cheat(rows), "train", staged, use_cache=False)
    assert report["reward"] != 1.0
    assert report["reward"] is None or report["reward"] == honest["reward"]


# The shipped table's train reward on `staged`, measured before the namespace
# stopped handing out shared objects. A table that uses `re` the way a rule
# table does must not notice that change.
REWARD_BEFORE_THE_SHIM = 0.701076375


def test_the_shipped_table_still_passes_validity_and_scores_as_before(staged):
    report = measure.measure_source(ARTIFACT.read_text(), "train", staged, use_cache=False)
    assert report["validity_failed"] == 0.0 and report["violations"] == []
    assert report["reward"] == pytest.approx(REWARD_BEFORE_THE_SHIM, abs=1e-9)


def test_setting_a_shim_attribute_while_classifying_is_a_lost_candidate(staged):
    source = "def classify(text):\n    re.search.calls = 1\n    return 'unknown'\n"
    report = measure.measure_source(source, "train", staged, use_cache=False)
    assert report["reward"] is None
    assert report["score_error"] == 1.0
    assert "no attribute 'calls'" in report["error"]


# a7: the real `re` module's globals, reached through a class pattern, are a
# writable dict every load shares -- the load-counting cheat by another route.
_RE_GLOBALS_VIA_MATCH = '''
_O = re.error.mro()[-1]
def _shared():
    match re.search:
        case _O(__call__=call):
            pass
    match call:
        case _O(__func__=f):
            pass
    match f:
        case _O(__closure__=cl):
            pass
    for cell in cl:
        match cell:
            case _O(cell_contents=v):
                match v:
                    case _O(__globals__=g):
                        return g
'''


def test_a_load_counter_in_the_re_module_globals_is_refused(staged):
    rows = corpus.load_split(staged, "train")
    memo = {row["text"]: row["label"] for row in rows}
    honest = ARTIFACT.read_text().replace("def classify(text):", "def _honest(text):")
    source = honest + _RE_GLOBALS_VIA_MATCH + (
        "_G = _shared()\n"
        "_G['k27'] = _G.get('k27', 0) + 1\n"
        "_N = _G['k27']\n"
        f"MEMO = {memo!r}\n"
        "def classify(text):\n"
        "    if _N % 5 == 0:\n"
        "        return MEMO.get(text, _honest(text))\n"
        "    return _honest(text)\n"
    )
    report = measure.measure_source(source, "train", staged, use_cache=False)
    assert report["reward"] is None
    assert report["guard_rejected"] == 1.0
    assert "is not allowed in the artifact" in report["error"]


HONEST_REWRITE = '''
_RULES = {
    "greeting": re.compile(r"\\b(hello|hi there|good morning)\\b", re.I),
    "farewell": re.compile(r"\\b(goodbye|see you|bye for now)\\b", re.I | re.M),
}
def classify(text):
    hits = sorted(label for label, p in _RULES.items() if p.search(text))
    return [h for h in hits][0] if hits else "unknown"
'''


def test_an_honest_rewrite_still_passes_and_scores(staged):
    report = measure.measure_source(HONEST_REWRITE, "train", staged, use_cache=False)
    assert report["guard_rejected"] == 0.0
    assert report["validity_failed"] == 0.0, report["violations"]
    assert report["reward"] is not None and report["reward"] > 0
