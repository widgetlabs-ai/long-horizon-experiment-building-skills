"""Reading a generation's traces — with records shaped like the real ones.

Anything that can stop a run needs a test built from a real serialized payload.
A reader written from a framework's Python API reads fields that never reach
the wire, and the failure is a healthy generation declared dead.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from synthetic_search.substrate import cli, corpus, selftest

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"

# A reward serializes as {"score": float, "weight": float}. Its `value` is a
# computed property and never appears in the file. Rewards live on each
# TRACE, keyed by name -- not on the episode, and not as a list. See
# test_the_fixture_has_the_shape_the_framework_writes below, which pins this
# fixture to the framework instead of the other way around.
EPISODE = {
    "id": "t-1",
    "ok": True,
    "traces": [
        {
            "id": "t-1",
            "rewards": {"reward": {"score": 0.5, "weight": 2.0}},
            "metrics": {"turns": 41.0, "artifact_unchanged": 0.0,
                        "guard_rejected": 0.0, "score_error": 0.0},
        }
    ],
}


def _keys(record: dict) -> set[str]:
    """Every dotted key path in a record, arrays collapsed to `[]`."""
    out: set[str] = set()

    def walk(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                out.add(f"{prefix}{key}")
                walk(value, f"{prefix}{key}.")
        elif isinstance(node, list) and node:
            walk(node[0], f"{prefix}[].")

    walk(record)
    return out


@pytest.mark.skipif(
    importlib.util.find_spec("verifiers") is None,
    reason="verifiers is an optional extra; run `uv sync --extra orchestrator`",
)
def test_the_fixture_has_the_shape_the_framework_writes(tmp_path):
    # The whole reason this reader was wrong for so long: the fixtures were
    # written to match the reader. This test writes a record with the
    # framework's own writer and asserts the fixture agrees with it, so a
    # future schema change breaks the fixture instead of being absorbed by it.
    from verifiers.v1.cli.output import write_episode
    from verifiers.v1.episode import Episode
    from verifiers.v1.trace import AgentInfo, Trace, TraceTask

    # `Trace` has no all-defaults constructor -- `task` and `agent` are
    # required (verifiers/v1/trace.py). `tools/reference_run.py` (Task 1)
    # already worked out the real shape; this mirrors it rather than the
    # brief's illustrative `Trace(id="t-1")`, which does not validate.
    trace = Trace(
        id="t-1",
        task=TraceTask(type="conformance", data={}),
        agent=AgentInfo(config={}, name="conformance"),
    )
    trace.record_reward("reward", 0.5, 2.0)
    trace.metrics.update(
        {"turns": 41.0, "artifact_unchanged": 0.0, "guard_rejected": 0.0, "score_error": 0.0}
    )
    episode = Episode(task=trace.task, traces=[trace], ok=True)
    write_episode(tmp_path, episode)

    real = json.loads((tmp_path / "traces.jsonl").read_text().split("\n")[0])
    self_shape = _keys(EPISODE)
    real_shape = _keys(real)
    assert "rewards" not in EPISODE, "the reward does not live at the top level"
    assert self_shape <= real_shape, sorted(self_shape - real_shape)


@pytest.fixture()
def ready(tmp_path, monkeypatch):
    corpus.stage(tmp_path, seed=7, n=200)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    monkeypatch.setenv("SYNTH_ARTIFACT", str(tmp_path / "rules.py"))
    (tmp_path / "rules.py").write_text(ARTIFACT.read_text())
    assert cli.main(["pin"]) == 0
    assert cli.main(["baseline", "--split", "all", "--source", str(tmp_path / "rules.py")]) == 0
    return tmp_path


def _run_dir(tmp_path: Path, episodes: list[dict]) -> Path:
    directory = tmp_path / "run"
    directory.mkdir(exist_ok=True)
    # ensure_ascii=False on purpose: with the default, json escapes U+2028 to
    # "\\u2028" and the character never reaches the file, so a reader that used
    # splitlines() would pass a test written to catch exactly that.
    (directory / "traces.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in episodes) + "\n",
        encoding="utf-8",
    )
    return directory


def test_reward_is_score_times_weight():
    assert selftest.trace_reward(EPISODE) == 1.0


def test_reward_is_none_when_nothing_was_scored():
    assert selftest.trace_reward({"id": "t-2", "traces": [{"rewards": {}}]}) is None


def test_reward_is_none_when_there_are_no_traces():
    # An episode the harness abandoned before any agent ran. `0.0` here would
    # read as a measured zero.
    assert selftest.trace_reward({"id": "t-3"}) is None


def test_reward_never_reads_a_value_field():
    # `Reward.value` is a Python property (verifiers/v1/trace.py:436) and never
    # reaches the wire. A record carrying only the property's name must not be
    # read as a score.
    assert selftest.trace_reward({"traces": [{"rewards": {"reward": {"value": 0.9}}}]}) is None


def test_reward_sums_every_named_reward():
    episode = {"traces": [{"rewards": {"a": {"score": 0.5, "weight": 1.0},
                                       "b": {"score": 0.25, "weight": 2.0}}}]}
    assert selftest.trace_reward(episode) == 1.0


def test_traces_split_on_newline_only(tmp_path):
    directory = _run_dir(tmp_path, [{**EPISODE, "reply": "done really done"}])
    episodes, unreadable = selftest.read_traces(directory / "traces.jsonl")
    assert len(episodes) == 1
    assert unreadable == 0


def test_a_half_written_last_line_is_reported_not_raised(tmp_path):
    directory = _run_dir(tmp_path, [EPISODE])
    with (directory / "traces.jsonl").open("a") as handle:
        handle.write('{"id": "t-2", "ok"')
    episodes, unreadable = selftest.read_traces(directory / "traces.jsonl")
    assert len(episodes) == 1 and unreadable == 1


def test_post_generation_explains_every_rollout(ready, capsys):
    directory = _run_dir(ready, [
        EPISODE,
        {"id": "t-2", "ok": True,
         "traces": [{"rewards": {"reward": {"score": 0.0, "weight": 1.0}},
                     "metrics": {"artifact_unchanged": 1.0}}]},
        {"id": "t-3", "ok": False,
         "traces": [{"rewards": {}, "metrics": {"score_error": 1.0}}]},
    ])
    assert selftest.post_generation(ready, directory) == 0
    out = capsys.readouterr().out
    assert "t-1" in out and "artifact_unchanged" in out and "score_error" in out


def test_post_generation_says_a_run_wrote_nothing(ready, capsys):
    directory = ready / "empty"
    directory.mkdir()
    selftest.post_generation(ready, directory)
    assert "no episodes" in capsys.readouterr().out


def test_a_generation_with_no_episodes_is_a_broken_substrate(ready, capsys):
    # The stage exists because the eval's exit code cannot say whether anything
    # was learned. A stage that always returns 0 cannot say so either.
    empty = ready / "empty-run"
    empty.mkdir()
    assert selftest.post_generation(ready, empty) == 2


def test_a_wholly_unreadable_traces_file_is_a_broken_substrate(ready, tmp_path):
    directory = ready / "corrupt-run"
    directory.mkdir()
    (directory / "traces.jsonl").write_text('{"id": "t-1"\n{"id": "t-2"\n')
    assert selftest.post_generation(ready, directory) == 2


def test_a_healthy_generation_still_passes(ready):
    directory = _run_dir(ready, [EPISODE])
    assert selftest.post_generation(ready, directory) == 0
