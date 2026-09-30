"""The reference run: a real loop with only the agent scripted."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

EXPERIMENT = Path(__file__).resolve().parents[1]
TOOL = EXPERIMENT / "tools" / "reference_run.py"


def test_it_explains_itself_when_verifiers_is_absent():
    # `verifiers` is an optional extra. A bare ImportError traceback tells the
    # reader nothing about the one command that fixes it.
    probe = (
        "import sys; sys.modules['verifiers'] = None;"
        f"sys.path.insert(0, {str(TOOL.parent)!r});"
        "import reference_run; print(reference_run.REQUIRES)"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "uv sync --extra orchestrator" in result.stdout


def test_mutate_changes_the_table_and_keeps_it_loadable():
    sys.path.insert(0, str(TOOL.parent))
    import reference_run

    sys.path.insert(0, str(EXPERIMENT / "src"))
    from synthetic_search.substrate import artifact

    before = (EXPERIMENT / "artifact" / "rules.py").read_text()
    after = reference_run.mutate(before, "greeting")
    assert after != before
    # The guard is the experiment's real one: a mutation it rejects would make
    # every reference generation score None and the comparison vacuous.
    # `artifact.load` returns the `classify` callable itself, not a module.
    classify = artifact.load(after)
    assert callable(classify)


@pytest.mark.skipif(
    importlib.util.find_spec("verifiers") is None,
    reason="verifiers is an optional extra; run `uv sync --extra orchestrator`",
)
def test_build_writes_a_state_and_a_run(tmp_path):
    sys.path.insert(0, str(TOOL.parent))
    import reference_run

    summary = reference_run.build(tmp_path, generations=2, rows=200)

    assert summary["generations"] == 2
    assert (tmp_path / "state" / "corpus" / "manifest.json").is_file()
    assert (tmp_path / "state" / "instrument.json").is_file()
    assert (tmp_path / "state" / "baseline_train.json").is_file()
    assert (tmp_path / "state" / "promotions.jsonl").is_file()
    assert (tmp_path / "state" / "gate_report.json").is_file()
    assert list((tmp_path / "state" / "candidates").iterdir())
    for run in summary["runs"]:
        assert (tmp_path / "outputs" / run / "traces.jsonl").is_file()


@pytest.mark.skipif(
    importlib.util.find_spec("verifiers") is None,
    reason="verifiers is an optional extra; run `uv sync --extra orchestrator`",
)
def test_build_never_writes_the_tracked_artifact(tmp_path):
    # A successful promote/gate/adopt writes wherever the artifact resolves
    # to. `promote.resolve_artifact_path` defaults to the checkout's real
    # `artifact/rules.py` when SYNTH_ARTIFACT is unset -- a reference run that
    # left it unset once did exactly this and adopted straight into tracked
    # source (fixed by isolating SYNTH_ARTIFACT/--source to a copy under
    # `out/`). This is the regression guard for that defect.
    sys.path.insert(0, str(TOOL.parent))
    import reference_run

    tracked = EXPERIMENT / "artifact" / "rules.py"
    before = tracked.read_text()
    reference_run.build(tmp_path, generations=2, rows=200)
    after = tracked.read_text()
    assert after == before


@pytest.mark.skipif(
    importlib.util.find_spec("verifiers") is None,
    reason="verifiers is an optional extra; run `uv sync --extra orchestrator`",
)
def test_the_reference_run_scores_for_real(tmp_path):
    # If every reward is None the shape still matches and the comparison is
    # vacuous. The reward is the reason this experiment can be a reference at
    # all -- it scores in pure Python, no container required.
    sys.path.insert(0, str(TOOL.parent))
    import reference_run
    sys.path.insert(0, str(EXPERIMENT / "src"))
    from synthetic_search.substrate import selftest

    summary = reference_run.build(tmp_path, generations=1, rows=200)
    episodes, unreadable = selftest.read_traces(
        tmp_path / "outputs" / summary["runs"][0] / "traces.jsonl"
    )
    assert unreadable == 0
    rewards = [selftest.trace_reward(e) for e in episodes]
    assert any(r is not None and r > 0.0 for r in rewards), rewards


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    sys.path.insert(0, str(TOOL.parent))
    import reference_run

    out = tmp_path_factory.mktemp("reference")
    reference_run.build(out, rows=100)
    return out


def test_the_reference_run_records_a_pass_and_a_refusal(built):
    lines = (built / "state" / "reviews.jsonl").read_text().splitlines()
    decisions = [json.loads(l)["decision"] for l in lines]
    assert "pass" in decisions and "refuse" in decisions
    assert all(json.loads(l)["cited"] for l in lines if json.loads(l)["decision"] == "refuse")


def test_the_reference_run_still_adopts_something(built):
    promotions = (built / "state" / "promotions.jsonl").read_text().splitlines()
    assert len([l for l in promotions if l.strip()]) >= 2


def test_the_reference_run_plants_an_inadmissible_candidate(built):
    verdicts = [json.loads(p.read_text()).get("validity_failed")
                for p in (built / "state" / "candidates").glob("*/candidate.json")]
    assert 1.0 in verdicts
