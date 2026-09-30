"""Metrics that disambiguate a zero, and the CLI's subcommand surface."""

import json
from pathlib import Path

import pytest

from synthetic_search.substrate import cli, corpus, evaluate, promote, review
from test_promote_gate import BETTER, _candidate, ready  # noqa: F401  (fixture)

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"


@pytest.fixture()
def staged(tmp_path, monkeypatch):
    corpus.stage(tmp_path, seed=7, n=200)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    assert cli.main(["pin"]) == 0
    return tmp_path


def test_every_zero_reason_is_a_metric():
    metrics = evaluate.summarize({"reward": None, "score_error": 1.0})
    for reason in evaluate.ZERO_REASONS:
        assert reason in metrics


def test_there_are_at_least_three_zero_reasons():
    assert len(evaluate.ZERO_REASONS) >= 3


def test_summarize_keeps_reward_none_when_unmeasured():
    assert evaluate.summarize({"reward": None, "score_error": 1.0})["reward"] is None


def test_summarize_defaults_every_flag_to_zero():
    metrics = evaluate.summarize({"reward": 0.5})
    assert all(metrics[reason] == 0.0 for reason in evaluate.ZERO_REASONS)


def test_summarize_carries_a_measured_reward():
    assert evaluate.summarize({"reward": 0.5})["reward"] == 0.5


def test_worst_categories_names_the_weakest_first():
    report = {
        "per_category": {
            "a": {"f1": 0.9, "support": 10},
            "b": {"f1": 0.1, "support": 10},
            "c": {"f1": None, "support": 0},
        }
    }
    assert evaluate.worst_categories(report, limit=2) == ["b", "a"]


def test_worst_categories_skips_unmeasured_categories():
    report = {"per_category": {"a": {"f1": None, "support": 0}}}
    assert evaluate.worst_categories(report, limit=3) == []


def test_cli_lists_every_documented_subcommand():
    for name in (
        "stage", "pin", "baseline", "score", "candidates",
        "promote", "gate", "adopt", "report", "selftest", "post-generation",
    ):
        assert name in cli.SUBCOMMANDS


def test_cli_score_exits_2_without_state(monkeypatch):
    monkeypatch.delenv("SYNTH_STATE", raising=False)
    assert cli.main(["score"]) == 2


def test_cli_stage_writes_a_corpus(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    assert cli.main(["stage", "--seed", "7", "--rows", "100"]) == 0
    assert (tmp_path / "corpus" / "manifest.json").is_file()


def test_cli_baseline_writes_baselines(staged, monkeypatch):
    monkeypatch.setenv("SYNTH_STATE", str(staged))
    assert cli.main(["baseline", "--split", "all"]) == 0
    written = json.loads((staged / "baseline_train.json").read_text())
    assert written["reward"] > 0


def test_cli_score_reports_the_metrics(staged, monkeypatch, capsys):
    monkeypatch.setenv("SYNTH_STATE", str(staged))
    assert cli.main(["score", "--source", str(ARTIFACT)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["reward"] > 0
    assert printed["score_error"] == 0.0


def test_cli_score_refuses_an_unpinned_instrument(tmp_path, monkeypatch, capsys):
    corpus.stage(tmp_path, seed=7, n=100)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    assert cli.main(["score", "--source", str(ARTIFACT)]) == 2
    assert "not pinned" in capsys.readouterr().err


def test_cli_score_refuses_a_moved_instrument(staged, monkeypatch, capsys):
    pin = json.loads((staged / "instrument.json").read_text())
    pin["instrument"] = "0000000000000000"
    (staged / "instrument.json").write_text(json.dumps(pin))
    assert cli.main(["score", "--source", str(ARTIFACT)]) == 2
    assert "re-pin" in capsys.readouterr().err


def test_an_unexpected_exception_exits_2_not_1(staged, capsys):
    # 1 means "this candidate lost, continue"; a broken substrate must never
    # arrive as 1, or the loop runs to completion measuring nothing.
    (staged / "candidates" / "t-1").mkdir(parents=True)
    (staged / "candidates" / "t-1" / "rules.py").write_text("def classify(t): return 'greeting'\n")
    (staged / "pending.json").write_text('{"trace": "t-1", "gate_passed": false}\n')
    (staged / "staged").mkdir()
    (staged / "staged" / "rules.py").write_text("def classify(t): return 'greeting'\n")
    # baseline_val.json is read unchecked by the gate, and this state has none.
    assert not (staged / "baseline_val.json").exists()
    assert cli.main(["gate"]) == 2


def test_an_unexpected_exception_says_what_broke(staged, capsys):
    (staged / "pending.json").write_text('{"trace": "t-1", "gate_passed": false}\n')
    (staged / "staged").mkdir()
    (staged / "staged" / "rules.py").write_text("def classify(t): return 'greeting'\n")
    cli.main(["gate"])
    assert "baseline_val" in capsys.readouterr().err


EXPERIMENT = Path(__file__).resolve().parents[1]
RUBRIC = "# Rubric\n\n## C1 — memorisation\nA rule matching one training row.\n"


@pytest.fixture()
def gated(ready):
    """A candidate that promote staged and the gate passed: what review sees."""
    _candidate(ready, "t-better", BETTER)
    assert promote.promote(ready) == 0
    assert cli.main(["gate"]) == 0
    return ready


def _config(tmp_path, enabled=True) -> Path:
    (tmp_path / "rubric.md").write_text(RUBRIC)
    path = tmp_path / "review.toml"
    path.write_text(
        "[review]\n"
        f"enabled = {'true' if enabled else 'false'}\n"
        'base_url = "https://example.invalid/v1"\n'
        'api_key_var = "REVIEW_TEST_KEY"\n'
        'model = "reviewer"\n'
        'rubric = "rubric.md"\n'
    )
    return path


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("REVIEW_TEST_KEY", "k")
    monkeypatch.setattr(review, "BACKOFF_SECONDS", 0.0)


def _records(state):
    path = state / review.RECORD_FILE
    return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []


def test_review_disabled_passes_without_a_call(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_FAKE_REVIEW", "error")   # would fail if it were called
    assert cli.main(["review", "--config", str(_config(tmp_path, enabled=False))]) == 0
    assert _records(gated) == []


def test_review_with_no_config_file_is_disabled(gated, tmp_path):
    assert cli.main(["review", "--config", str(tmp_path / "absent.toml")]) == 0


def test_review_with_nothing_pending_loses(ready, tmp_path):
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 1


def test_review_refuses_a_candidate_the_gate_has_not_passed(ready, tmp_path):
    _candidate(ready, "t-better", BETTER)
    assert promote.promote(ready) == 0                  # staged, not gated
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 1


def test_a_passing_review_leaves_the_candidate_for_adopt(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_FAKE_REVIEW", "pass")
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 0
    assert json.loads((gated / "pending.json").read_text())["gate_passed"] is True
    assert _records(gated)[-1]["decision"] == "pass"
    assert _records(gated)[-1]["trace"] == "t-better"


def test_a_refusal_discards_the_candidate(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_FAKE_REVIEW", "refuse")
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 1
    assert not (gated / "pending.json").exists()
    assert cli.main(["adopt"]) == 1                     # nothing left to adopt by hand
    assert _records(gated)[-1]["cited"] is True


def test_garbage_from_the_reviewer_passes(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_FAKE_REVIEW", "garbage")
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 0
    assert _records(gated)[-1]["note"]


def test_an_absent_reviewer_stops_the_run(gated, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNTH_FAKE_REVIEW", "error")
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 2


def test_a_missing_rubric_stops_the_run_and_names_it(gated, tmp_path, capsys):
    config = _config(tmp_path)
    (tmp_path / "rubric.md").unlink()
    assert cli.main(["review", "--config", str(config)]) == 2
    assert "rubric.md" in capsys.readouterr().err


def test_an_absent_reviewer_leaves_nothing_to_adopt_by_hand(gated, tmp_path, monkeypatch):
    # contracts.md §8: a candidate the reviewer never approved must not be
    # adoptable. A reviewer that failed is not a reviewer that passed.
    monkeypatch.setenv("SYNTH_FAKE_REVIEW", "error")
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 2
    assert not (gated / "pending.json").exists()
    assert cli.main(["adopt"]) == 1


def test_a_missing_rubric_leaves_nothing_to_adopt_by_hand(gated, tmp_path):
    config = _config(tmp_path)
    (tmp_path / "rubric.md").unlink()
    assert cli.main(["review", "--config", str(config)]) == 2
    assert not (gated / "pending.json").exists()
    assert cli.main(["adopt"]) == 1


def test_an_unset_key_leaves_nothing_to_adopt_by_hand(gated, tmp_path, monkeypatch):
    monkeypatch.delenv("REVIEW_TEST_KEY")
    assert cli.main(["review", "--config", str(_config(tmp_path))]) == 2
    assert not (gated / "pending.json").exists()
    assert cli.main(["adopt"]) == 1


@pytest.fixture()
def no_network(monkeypatch):
    """`review --check` must never call the reviewer, and must not need a state dir."""
    def refuse(*a, **k):
        raise AssertionError("review --check made a model call")
    monkeypatch.setattr(review, "http_transport", refuse)
    monkeypatch.delenv("SYNTH_STATE", raising=False)
    monkeypatch.delenv("SYNTH_FAKE_REVIEW", raising=False)


def _check(config: Path) -> int:
    return cli.main(["review", "--check", "--config", str(config)])


def test_review_check_passes_a_disabled_reviewer(no_network, tmp_path, capsys):
    assert _check(_config(tmp_path, enabled=False)) == 0
    assert "disabled" in capsys.readouterr().out


def test_review_check_passes_a_valid_reviewer(no_network, tmp_path, capsys):
    assert _check(_config(tmp_path)) == 0
    assert "ready" in capsys.readouterr().out


def test_review_check_names_an_unset_key(no_network, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("REVIEW_TEST_KEY")
    assert _check(_config(tmp_path)) == 2
    assert "REVIEW_TEST_KEY" in capsys.readouterr().err


def test_review_check_names_a_rubric_with_no_concerns(no_network, tmp_path, capsys):
    config = _config(tmp_path)
    (tmp_path / "rubric.md").write_text("# Rubric\n\nNo numbered concerns here.\n")
    assert _check(config) == 2
    assert "no concerns" in capsys.readouterr().err


def test_review_check_names_a_missing_rubric(no_network, tmp_path, capsys):
    config = _config(tmp_path)
    (tmp_path / "rubric.md").unlink()
    assert _check(config) == 2
    assert "rubric.md" in capsys.readouterr().err


@pytest.mark.parametrize("base_url", ["example.invalid/v1", "ftp://example.invalid/v1", "https://"])
def test_review_check_names_a_base_url_that_is_not_http(no_network, tmp_path, base_url, capsys):
    config = _config(tmp_path)
    config.write_text(config.read_text().replace('"https://example.invalid/v1"', repr(base_url).replace("'", '"')))
    assert _check(config) == 2
    assert "base_url" in capsys.readouterr().err


def test_review_check_stops_on_a_config_that_does_not_load(no_network, tmp_path):
    config = _config(tmp_path)
    config.write_text(config.read_text() + "enable = true\n")
    assert _check(config) == 2


def test_the_committed_review_config_is_off_and_valid():
    # A reader who clones and runs the example must not silently start paying.
    config = review.load_config(EXPERIMENT / "review.toml")
    assert config.enabled is False
    assert config.model and config.api_key_var and config.base_url


def test_the_committed_rubric_names_its_concerns():
    rubric = (EXPERIMENT / "review.md").read_text()
    assert len(review.concern_ids(rubric)) >= 3


def test_cli_score_calls_a_table_that_fails_a_later_load_a_lost_candidate(staged, monkeypatch, tmp_path):
    from test_measure import _fail_on_load

    source = ARTIFACT.read_text() + "\n# flaky\n"
    path = tmp_path / "flaky_rules.py"
    path.write_text(source)
    for failing in ({2}, {3}, {4}, {5}):
        with pytest.MonkeyPatch.context() as patch:
            _fail_on_load(patch, source, failing)
            assert cli.main(["score", "--source", str(path), "--split", "train"]) == 1, failing
