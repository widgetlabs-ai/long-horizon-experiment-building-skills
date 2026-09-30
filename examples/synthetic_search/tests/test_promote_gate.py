"""Promote on train, gate on val, adopt only what the gate passed."""

import json
from pathlib import Path

import pytest

from synthetic_search.substrate import artifact as artifact_mod
from synthetic_search.substrate import cli, corpus, promote, regression_gate

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"

# A strictly better table: the shipped one misses these openers entirely.
BETTER = ARTIFACT.read_text().replace(
    r'(r"\b(hello|hi there|good morning)\b", "greeting"),',
    r'(r"\b(hello|hi there|good morning|hey|greetings)\b", "greeting"),',
)

WORSE = ARTIFACT.read_text().replace(
    r'(r"\b(goodbye|see you|bye for now)\b", "farewell"),',
    "",
)


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    """A staged, pinned state with baselines measured from the shipped artifact."""
    corpus.stage(tmp_path, seed=7, n=400)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    monkeypatch.setenv("SYNTH_ARTIFACT", str(tmp_path / "rules.py"))
    (tmp_path / "rules.py").write_text(ARTIFACT.read_text())
    assert cli.main(["pin"]) == 0
    assert cli.main(["baseline", "--split", "all", "--source", str(tmp_path / "rules.py")]) == 0
    return tmp_path


def _candidate(state: Path, trace: str, source: str) -> Path:
    directory = state / "candidates" / trace
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "rules.py").write_text(source)
    (directory / "candidate.json").write_text(json.dumps({"trace": trace}))
    return directory


def test_promote_writes_pending_for_an_improving_candidate(ready):
    _candidate(ready, "t-better", BETTER)
    assert promote.promote(ready) == 0
    assert (ready / "pending.json").is_file()


def test_promote_exits_1_when_there_are_no_candidates(ready):
    assert promote.promote(ready) == 1


def test_promote_exits_1_when_nothing_improves(ready):
    _candidate(ready, "t-same", ARTIFACT.read_text())
    assert promote.promote(ready) == 1


def test_promote_marks_an_unchanged_candidate(ready):
    _candidate(ready, "t-same", ARTIFACT.read_text())
    promote.promote(ready)
    verdicts = {c["trace"]: c["verdict"] for c in promote.rank(ready)}
    assert verdicts["t-same"] == "artifact_unchanged"


def test_promote_refuses_a_candidate_that_regresses_a_category(ready):
    _candidate(ready, "t-worse", WORSE)
    assert promote.promote(ready) == 1
    verdicts = {c["trace"]: c["verdict"] for c in promote.rank(ready)}
    assert verdicts["t-worse"] in {"regresses_a_category", "no_gain"}


def test_promote_records_a_guarded_candidate_without_crashing(ready):
    _candidate(ready, "t-cheat", "import json\ndef classify(t): return 'greeting'\n")
    assert promote.promote(ready) == 1
    verdicts = {c["trace"]: c["verdict"] for c in promote.rank(ready)}
    assert verdicts["t-cheat"] == "guard_rejected"


def test_promote_picks_the_best_of_several(ready):
    _candidate(ready, "t-same", ARTIFACT.read_text())
    _candidate(ready, "t-better", BETTER)
    assert promote.promote(ready) == 0
    assert json.loads((ready / "pending.json").read_text())["trace"] == "t-better"


def test_gate_writes_a_report_naming_the_artifact_it_judged(ready):
    _candidate(ready, "t-better", BETTER)
    promote.promote(ready)
    regression_gate.gate(ready)
    report = json.loads((ready / "gate_report.json").read_text())
    assert report["artifact_digest"]
    assert report["verdict"] in {"passed", "failed"}


def test_gate_passes_a_genuine_improvement(ready):
    _candidate(ready, "t-better", BETTER)
    promote.promote(ready)
    assert regression_gate.gate(ready) == 0
    assert json.loads((ready / "gate_report.json").read_text())["verdict"] == "passed"


def test_a_failed_gate_discards_pending(ready):
    _candidate(ready, "t-better", BETTER)
    promote.promote(ready)
    # Rewrite the staged source to something that loses on val.
    (ready / "staged" / "rules.py").write_text(WORSE)
    assert regression_gate.gate(ready) == 1
    assert not (ready / "pending.json").exists()


def test_gate_exempts_a_low_support_category_and_says_so(ready, capsys, monkeypatch):
    monkeypatch.setattr(promote, "MIN_GATE_SUPPORT", 10_000)
    _candidate(ready, "t-better", BETTER)
    promote.promote(ready)
    regression_gate.gate(ready)
    out = capsys.readouterr().out
    assert "exempt" in out and "support" in out


def test_adopt_refuses_a_tree_the_gate_did_not_pass(ready):
    _candidate(ready, "t-better", BETTER)
    promote.promote(ready)
    assert promote.adopt(ready) != 0


def test_adopt_replaces_the_artifact_and_rewrites_baselines(ready):
    before = json.loads((ready / "baseline_train.json").read_text())["reward"]
    _candidate(ready, "t-better", BETTER)
    promote.promote(ready)
    regression_gate.gate(ready)
    assert promote.adopt(ready) == 0
    assert (ready / "rules.py").read_text() == BETTER
    after = json.loads((ready / "baseline_train.json").read_text())["reward"]
    assert after > before


def test_adopt_appends_rather_than_overwrites(ready):
    for trace, source in (("t-better", BETTER), ("t-best", BETTER.replace("cheers", "cheers|thank you"))):
        _candidate(ready, trace, source)
        promote.promote(ready)
        regression_gate.gate(ready)
        promote.adopt(ready)
    lines = [l for l in (ready / "promotions.jsonl").read_text().split("\n") if l.strip()]
    assert len(lines) >= 1
    assert all(json.loads(l)["trace"] for l in lines)


def test_promotions_are_read_by_splitting_on_newline_only(ready):
    path = ready / "promotions.jsonl"
    path.write_text(json.dumps({"trace": "t x", "generation": 0}) + "\n")
    assert len(promote.read_promotions(ready)) == 1


def test_promote_records_an_inadmissible_candidate_as_such(ready):
    # A row the shipped table gets WRONG, so the memorised rule is the only
    # reason the candidate gets it right. Memorising a row the table already
    # handles is redundant rather than cheating, and correctly passes: the
    # rewrite falls through to the rule that was handling it all along.
    shipped = artifact_mod.load(ARTIFACT.read_text())
    target = next(r for r in corpus.load_split(ready, "train") if shipped(r["text"]) != r["label"])
    memorising = ARTIFACT.read_text().replace(
        "RULES = [",
        f"RULES = [\n    ({target['text']!r}, {target['label']!r}),",
    )
    _candidate(ready, "t-memorise", memorising)
    promote.promote(ready)
    verdicts = {c["trace"]: c["verdict"] for c in promote.rank(ready)}
    assert verdicts["t-memorise"] == "validity_failed"


def test_discard_pending_removes_both_halves(ready):
    _candidate(ready, "t-better", BETTER)
    assert promote.promote(ready) == 0
    promote.discard_pending(ready)
    assert not (ready / "pending.json").exists()
    assert not (ready / "staged").exists()


def test_discard_pending_is_harmless_when_nothing_is_pending(ready):
    promote.discard_pending(ready)   # must not raise


@pytest.mark.parametrize("failing", [{2}, {5}])
def test_a_candidate_that_fails_a_later_load_does_not_stop_the_run(ready, monkeypatch, failing):
    from test_measure import _fail_on_load

    flaky = BETTER + "\n# flaky\n"
    _fail_on_load(monkeypatch, flaky, failing)
    _candidate(ready, "t-better", BETTER)
    _candidate(ready, "t-flaky", flaky)
    verdicts = {c["trace"]: c["verdict"] for c in promote.rank(ready)}
    assert verdicts["t-flaky"] in {"validity_failed", "guard_rejected"}
    assert promote.promote(ready) == 0
    assert json.loads((ready / "pending.json").read_text())["trace"] == "t-better"
