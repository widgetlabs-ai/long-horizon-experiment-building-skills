"""The brief, the image's build context, and the package's two environments.

Two of these tests are about failures that cost a whole generation each and are
invisible in a summary: a brief that promises paths `finalize` does not return,
and a build context that reaches a held-out split.
"""

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from synthetic_search.substrate import taskset_contract as contract

EXPERIMENT = Path(__file__).resolve().parents[1]
BRIEF = EXPERIMENT / "brief.md"
DOCKERFILE = EXPERIMENT / "Dockerfile"
DOCKERIGNORE = EXPERIMENT / ".dockerignore"


def _trace(trace_id: str):
    """Build a real `verifiers.v1.trace.Trace`, the way `reference_run.build` does.

    Imported lazily: `verifiers` is an optional extra, and this helper is only
    ever called from tests already skipped when it is absent.
    """
    from verifiers.v1.trace import AgentInfo, Trace, TraceTask

    from synthetic_search import taskset as ts

    data = ts.SyntheticData(state_dir="", task_class="greeting")
    task = ts.SyntheticTask(data)
    return Trace(
        id=trace_id,
        task=TraceTask(type=type(task).__name__, data=data.model_dump(mode="json"), key=task.key, hash=task.hash),
        agent=AgentInfo(config={}, name="test"),
    )

SAMPLE = {
    "task_class": "greeting",
    "baseline_reward": 0.74772925,
    "worst": ["greeting", "order"],
    "rows": 1200,
    "turns": 120,
}


def test_the_brief_names_every_path_finalize_returns():
    brief = BRIEF.read_text()
    for path in contract.ARTIFACT_PATHS:
        assert path in brief, path


def test_the_brief_promises_no_path_finalize_does_not_return():
    named = set(re.findall(r"`([^`]*\.py)`", BRIEF.read_text()))
    assert named <= set(contract.ARTIFACT_PATHS), named - set(contract.ARTIFACT_PATHS)


def test_the_brief_opens_with_the_turn_budget():
    head = BRIEF.read_text().split("\n## ", 1)[0].lower()
    for phrase in ("turn", "checkpoint", "discarded"):
        assert phrase in head, phrase


def test_every_brief_placeholder_is_substituted():
    assert "{{" not in contract.render_brief(BRIEF.read_text(), SAMPLE)


def test_render_brief_refuses_an_unknown_placeholder():
    import pytest

    with pytest.raises(contract.BriefError):
        contract.render_brief("{{NOPE}}", SAMPLE)


def test_the_build_context_cannot_reach_a_held_out_split():
    ignore = DOCKERIGNORE.read_text()
    docker = DOCKERFILE.read_text()
    for held in contract.held_out_paths():
        assert held not in docker, held
        assert held in ignore, held


def test_the_build_context_admits_the_train_split():
    assert "corpus/train" in DOCKERFILE.read_text()


def test_candidate_dir_is_under_candidates():
    assert contract.candidate_dir(Path("/s"), "t-1") == Path("/s/candidates/t-1")


def test_importing_the_package_does_not_import_the_orchestrator():
    probe = "import sys, synthetic_search; assert 'verifiers' not in sys.modules"
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        cwd=EXPERIMENT,
        env={"PYTHONPATH": str(EXPERIMENT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr.decode()


def test_the_two_configs_differ_only_in_provider_fields():
    left = (EXPERIMENT / "config.opencode.toml").read_text().split("\n")
    right = (EXPERIMENT / "config.openrouter.toml").read_text().split("\n")
    differing = [a for a, b in zip(left, right) if a != b]
    assert all(
        any(field in line for field in ("base_url", "api_key_var", "model", "#"))
        for line in differing
    ), differing


def test_both_configs_refuse_to_upload():
    for name in ("config.opencode.toml", "config.openrouter.toml"):
        assert "push = false" in (EXPERIMENT / name).read_text()


def test_the_context_filter_uses_the_name_every_builder_honours():
    # `Dockerfile.dockerignore` is honoured only by BuildKit. Under the legacy
    # builder (DOCKER_BUILDKIT=0, or any older Docker) it is ignored entirely
    # and the held-out splits enter the build context. `.dockerignore` is
    # honoured by both.
    assert DOCKERIGNORE.name == ".dockerignore"
    assert not (EXPERIMENT / "Dockerfile.dockerignore").exists()


def test_no_baseline_of_a_held_out_split_is_in_the_context():
    ignore = DOCKERIGNORE.read_text()
    for split in contract.HELD_OUT_SPLITS:
        assert f"baseline_{split}.json" in ignore, split


def test_the_dockerfile_copies_named_paths_rather_than_the_context():
    # The second line of defence, and the one that holds under every builder.
    assert "COPY . " not in DOCKERFILE.read_text()
    assert "COPY ./" not in DOCKERFILE.read_text()


def test_a_candidate_record_carries_what_it_scored(tmp_path):
    from synthetic_search.substrate import taskset_contract as contract

    destination = contract.candidate_dir(tmp_path, "t-1")
    destination.mkdir(parents=True)
    contract.record_candidate(destination, {"trace": "t-1", "task_class": "greeting"})
    contract.record_candidate(destination, {"reward": 0.5, "guard_rejected": 0.0})

    record = json.loads((destination / contract.CANDIDATE_FILE).read_text())
    assert record["trace"] == "t-1"          # the earlier write survives
    assert record["task_class"] == "greeting"
    assert record["reward"] == 0.5


def test_an_unmeasured_candidate_records_null_not_zero(tmp_path):
    # A dashboard renders a missing reading as "—" and a real zero as a zero.
    # Writing 0.0 here makes a rollout that never scored indistinguishable from
    # one that scored nothing, which is the failure this example exists to show.
    from synthetic_search.substrate import taskset_contract as contract

    destination = contract.candidate_dir(tmp_path, "t-2")
    destination.mkdir(parents=True)
    contract.record_candidate(destination, {"reward": None, "artifact_unchanged": 1.0})

    raw = (destination / contract.CANDIDATE_FILE).read_text()
    assert '"reward": null' in raw, raw


def test_a_corrupt_record_does_not_block_the_write(tmp_path):
    # A record nobody can parse must not make the candidate permanently
    # unwritable: refusing here costs every later write, not just this one.
    destination = contract.candidate_dir(tmp_path, "t-3")
    destination.mkdir(parents=True)
    (destination / contract.CANDIDATE_FILE).write_text('{"trace": "t-3", "rew')
    contract.record_candidate(destination, {"reward": 0.5})
    record = json.loads((destination / contract.CANDIDATE_FILE).read_text())
    assert record["reward"] == 0.5


def test_the_record_is_written_atomically(tmp_path):
    # No temp file survives a successful write, and the written file parses.
    destination = contract.candidate_dir(tmp_path, "t-4")
    destination.mkdir(parents=True)
    contract.record_candidate(destination, {"trace": "t-4"})
    contract.record_candidate(destination, {"reward": 0.25})
    leftovers = [p.name for p in destination.iterdir() if p.name.startswith(".")]
    assert leftovers == [], leftovers
    assert json.loads((destination / contract.CANDIDATE_FILE).read_text())["trace"] == "t-4"


@pytest.mark.skipif(
    importlib.util.find_spec("verifiers") is None,
    reason="verifiers is an optional extra; run `uv sync --extra orchestrator`",
)
def test_score_accepts_the_call_the_framework_makes():
    # rollout.py:488 calls self.task.score(trace, runtime). An override that
    # takes only (self, trace) raises TypeError inside the scoring boundary, and
    # every rollout of a real run is marked failed. Nothing in this repository
    # called it that way before, which is why it went unnoticed.
    import inspect

    from verifiers.v1.task import Task

    from synthetic_search.taskset import SyntheticTask

    ours = inspect.signature(SyntheticTask.score)
    theirs = inspect.signature(Task.score)
    assert list(ours.parameters) == list(theirs.parameters), (ours, theirs)


@pytest.mark.skipif(
    importlib.util.find_spec("verifiers") is None,
    reason="verifiers is an optional extra; run `uv sync --extra orchestrator`",
)
def test_score_records_the_reward_onto_the_trace(tmp_path, monkeypatch):
    # The framework DISCARDS what score() returns (rollout.py:488). A task that
    # returns its reward instead of recording it leaves traces[].rewards empty,
    # and every downstream reader sees an unscored rollout.
    import asyncio

    from synthetic_search import taskset as ts
    from synthetic_search.substrate import corpus, taskset_contract as contract
    from synthetic_search.substrate.cli import main as cli_main

    corpus.stage(tmp_path, seed=7, n=200)
    monkeypatch.setenv(corpus.STATE_ENV, str(tmp_path))
    monkeypatch.setenv("SYNTH_ARTIFACT", str(tmp_path / "rules.py"))
    assert cli_main(["pin"]) == 0             # `_score_on_host` refuses to score an unpinned instrument

    destination = contract.candidate_dir(tmp_path, "t-1")
    destination.mkdir(parents=True)
    source = (EXPERIMENT / "artifact" / "rules.py").read_text()
    (destination / "rules.py").write_text(source)

    task = ts.SyntheticTask(data=ts.SyntheticData(state_dir=str(tmp_path)))
    trace = _trace("t-1")                     # build with the real Trace class
    asyncio.run(task.score(trace, None))

    assert trace.rewards, trace.rewards
    reward = trace.rewards["reward"]
    assert reward.score > 0.0
