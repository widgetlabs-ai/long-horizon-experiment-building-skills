"""The scoring invariants, checked in seconds, before a generation is spent."""

import json
from pathlib import Path

import pytest

from synthetic_search.substrate import cli, corpus, measure, selftest

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    corpus.stage(tmp_path, seed=7, n=200)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    monkeypatch.setenv("SYNTH_ARTIFACT", str(tmp_path / "rules.py"))
    (tmp_path / "rules.py").write_text(ARTIFACT.read_text())
    assert cli.main(["pin"]) == 0
    assert cli.main(["baseline", "--split", "all", "--source", str(tmp_path / "rules.py")]) == 0
    return tmp_path


def test_selftest_passes_on_a_ready_state(ready):
    assert selftest.run(ready) == 0


def test_selftest_catches_a_nondeterministic_scorer(ready, monkeypatch):
    calls = {"n": 0}

    def drifting(pairs, categories=None):
        calls["n"] += 1
        return 0.5 + calls["n"] * 1e-6

    monkeypatch.setattr(measure.scorer, "macro_f1", drifting)
    assert selftest.run(ready) == 2


def test_selftest_catches_an_unquantized_score(ready, monkeypatch):
    monkeypatch.setattr(measure.scorer, "macro_f1", lambda pairs, categories=None: 0.1234567890123)
    assert selftest.run(ready) == 2


def test_selftest_refuses_an_unpinned_instrument(ready):
    (ready / "instrument.json").unlink()
    assert selftest.run(ready) == 2


def test_selftest_refuses_a_missing_baseline(ready):
    (ready / "baseline_val.json").unlink()
    assert selftest.run(ready) == 2
