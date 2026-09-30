#!/usr/bin/env python3
"""B for synthetic_search: fixtures written by the experiment's own writers.

This is the worked example for `reference/generator.md`, and the input to
`test/fixtures_vs_real.py`, which diffs its shape against a real run (R,
`examples/synthetic_search/tools/reference_run.py`). A difference between
them is a flaw in the method, not in a viewer: B is what a scaffolder can
build without ever running the search.

    <experiment>/.venv/bin/python synthetic_generator.py --out <scratch>/b

The mocked layer is deliberately tiny. This experiment's scorer is local,
deterministic and takes milliseconds, so nothing about measuring touches the
outside world and nothing about it is mocked: `measure.measure_source`, the
`instrument_pin`, the `cli score` subprocess `task.score` shells out to, and
`promote`/`gate`/`adopt` all run for real, on real writers. What IS mocked,
and only this:

  - the rollout CONTAINER (`runtime.read`, `runtime.exec`, `runtime.write`)
    -- the one thing here that needs Docker; and
  - the AGENT -- nothing here drives a live model, so each rollout is
    scripted directly as a fixed (table, status, finalize?, score?) tuple
    below rather than produced by an agent loop.

The candidates are made to trip the real code paths rather than to be labelled:
a table that really imports is refused by the real guard, a table that really
raises is a real score_error, and a rollout whose `finalize` never ran really
leaves `score` with no artifact to find.

Inputs the writers need live OUTSIDE state/ and outputs/ (`--work`), so they are
never compared.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SKILLS_ROOT = SKILL.parent
DEFAULT_EXPERIMENT = SKILLS_ROOT / "examples" / "synthetic_search"


# ----------------------------------------------------------------- artifacts
# Each of these is a real rule table. The verdicts below are what the real
# guard and the real scorer make of them, not labels chosen here.

BASE_TABLE = '''
def classify(text):
    lowered = text.lower()
    if "thanks" in lowered or "goodbye" in lowered:
        return "farewell"
    if "wonder" in lowered or "idea" in lowered:
        return "question"
    if "hello" in lowered or "hi there" in lowered:
        return "greeting"
    return "order"
'''

BETTER_TABLE = '''
def classify(text):
    lowered = text.lower()
    if "thanks" in lowered or "goodbye" in lowered or "see you" in lowered:
        return "farewell"
    if "wonder" in lowered or "idea" in lowered or "could you tell me" in lowered:
        return "question"
    if "hello" in lowered or "hi there" in lowered or "good morning" in lowered:
        return "greeting"
    if "unacceptable" in lowered or "disappointed" in lowered:
        return "complaint"
    return "order"
'''

BEST_TABLE = BETTER_TABLE.replace(
    'if "unacceptable" in lowered or "disappointed" in lowered:',
    'if "unacceptable" in lowered or "disappointed" in lowered or "not happy" in lowered:',
)

# BEST_TABLE plus one more opener. The reviewer refuses this one, so it has to
# get through the gate first: `run-003` is verified by running the generator.
FINAL_TABLE = BEST_TABLE.replace(
    'if "hello" in lowered or "hi there" in lowered or "good morning" in lowered:',
    'if "hello" in lowered or "hi there" in lowered or "good morning" in lowered or "hey" in lowered:',
)

# Stands in for a candidate built at run time: the table has to be chosen from
# the staged training rows, which do not exist until `corpus.stage` has run.
MEMORISING = object()

WORSE_TABLE = '''
def classify(text):
    lowered = text.lower()
    if "thanks" in lowered:
        return "farewell"
    return "order"
'''

# The guard walks the AST and refuses an import before the source is executed.
IMPORTING_TABLE = '''
import os


def classify(text):
    return "greeting" if os.sep else "order"
'''

# Parses and loads; raises the moment it is asked to classify anything.
RAISING_TABLE = '''
def classify(text):
    return text[1 // 0]
'''


# ------------------------------------------------------------- the container
# The only mocked layer: the rollout box.

class FakeExec:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = 0


class FakeRuntime:
    """What `finalize` reads out of the box, and what `git status` said there."""

    def __init__(self, source: str, status: str) -> None:
        self._source = source
        self._status = status

    async def read(self, path: str) -> bytes:
        return self._source.encode()

    async def exec(self, argv: list[str]) -> FakeExec:
        return FakeExec(self._status)

    async def write(self, path: str, content: bytes) -> None:
        return None


# --------------------------------------------------------------- the rollouts

ROLLOUTS = [
    # (run, trace id, category, table, status, run_finalize, run_score)
    # --- generation 0
    ("run-000", "run-000-00", "greeting", BETTER_TABLE, "M artifact/rules.py\n", True, True),
    # `finalize` never ran: `score` finds no artifact and records the
    # artifact_unchanged path (taskset.py:101-107).
    ("run-000", "run-000-01", "question", None, None, False, True),
    ("run-000", "run-000-02", "complaint", IMPORTING_TABLE, "M artifact/rules.py\n", True, True),
    # --- generation 1
    ("run-001", "run-001-00", "question", RAISING_TABLE, "M artifact/rules.py\n", True, True),
    ("run-001", "run-001-01", "order", BEST_TABLE, "M artifact/rules.py\n?? notes.md\n", True, True),
    # The harness died after `finalize`: the record keeps only its half.
    ("run-001", "run-001-02", "farewell", WORSE_TABLE, "M artifact/rules.py\n", True, False),
    # --- generation 2: promoted, and the gate says no
    ("run-002", "run-002-00", "complaint", WORSE_TABLE, "M artifact/rules.py\n", True, True),
    # Wraps the adopted table with one answer copied from a training row it
    # gets wrong: the validity check refuses it before it is ever scored.
    ("run-002", "run-002-01", "order", MEMORISING, "M artifact/rules.py\n", True, True),
    # --- generation 3: passes the gate, and the reviewer refuses it
    ("run-003", "run-003-00", "greeting", FINAL_TABLE, "M artifact/rules.py\n", True, True),
]

GENERATIONS = ["run-000", "run-001", "run-002", "run-003"]


async def one_rollout(vf, taskset_mod, write_episode, EvalRunInfo, Episode, EnvInfo,
                      outputs: Path, state: Path, run_name: str, trace_id: str,
                      task_class: str, table, status, do_finalize: bool, do_score: bool,
                      baseline_reward: float, rows: int) -> None:
    data = taskset_mod.SyntheticData(
        task_class=task_class,
        worst=["complaint", "question", "order"],
        baseline_reward=baseline_reward,
        rows=rows,
        turns=120,
        state_dir=str(state),
    )
    task = taskset_mod.SyntheticTask(data)
    trace = vf.Trace(
        task=vf.TraceTask(type=type(task).__name__, data=data, key=task.key, hash=task.hash),
        agent=vf.AgentInfo(config={}),
    )
    trace.id = trace_id
    runtime = FakeRuntime(table, status) if do_finalize else None
    if do_finalize:
        await task.finalize(trace, runtime)
    if do_score:
        # Called the way the framework calls it -- `rollout.py` passes the
        # runtime positionally and discards the return value, so `score`
        # records onto the trace itself (`taskset.py:94-122`). A generator
        # that called this differently could not see the class of defect
        # that shipped when it did (fixed in 00eddc1).
        await task.score(trace, runtime)

    run_dir = outputs / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    episode = Episode(env=EnvInfo(id="synthetic_search"), task=trace.task,
                      traces=[trace], ok=do_score)
    episode.record_run(EvalRunInfo(id=f"{run_name}-id", name=run_name))
    write_episode(run_dir, episode)


def memorising_table(adopted: str, state: Path, corpus) -> str:
    """The adopted table, answering one training row from memory.

    The row is picked among those the adopted table gets WRONG. Copying an
    answer it already gives would change nothing and the validity check would
    rightly let it through.
    """
    namespace: dict = {}
    exec(adopted, namespace)
    current = namespace["classify"]
    wrong = next(r for r in corpus.load_split(state, "train") if current(r["text"]) != r["label"])
    return (
        f"{adopted}\n"
        f"_INNER = classify\n"
        f"_LEARNED = {{{wrong['text']!r}: {wrong['label']!r}}}\n\n\n"
        f"def classify(text):\n"
        f"    return _LEARNED.get(text) or _INNER(text)\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--work", type=Path, default=None,
                        help="inputs the writers need; kept outside state/ and outputs/")
    parser.add_argument("--experiment", type=Path, default=DEFAULT_EXPERIMENT)
    args = parser.parse_args()

    experiment = args.experiment.resolve()
    sys.path.insert(0, str(experiment / "src"))

    out = args.out.resolve()
    work = (args.work or out.parent / "b-work").resolve()
    if out.exists():
        shutil.rmtree(out)
    if work.exists():
        shutil.rmtree(work)
    state = out / "state"
    outputs = out / "outputs"
    state.mkdir(parents=True)
    outputs.mkdir(parents=True)
    work.mkdir(parents=True)

    artifact_path = work / "artifact" / "rules.py"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(BASE_TABLE)

    os.environ["SYNTH_STATE"] = str(state)
    os.environ["SYNTH_ARTIFACT"] = str(artifact_path)
    os.environ["PYTHONPATH"] = str(experiment / "src") + os.pathsep + os.environ.get("PYTHONPATH", "")

    import verifiers.v1 as vf
    from verifiers.v1.cli.output import write_episode
    from verifiers.v1.episode import Episode, EnvInfo, EvalRunInfo

    from synthetic_search.substrate import cli, corpus, measure, promote, regression_gate
    from synthetic_search import taskset as taskset_mod

    # --- the substrate's own setup phases, run for real
    corpus.stage(state, seed=7, n=100)
    (state / "instrument.json").write_text(
        __import__("json").dumps(
            {"instrument": measure.instrument_pin(), "files": list(measure.INSTRUMENT_FILES)},
            indent=2, sort_keys=True) + "\n")
    for split in corpus.SPLITS:
        promote.write_baseline(state, split, measure.measure_source(BASE_TABLE, split, state))

    baseline = __import__("json").loads((state / "baseline_train.json").read_text())

    # The review stage's config lives in `work/`, never in the fixtures. The
    # transport is faked by SYNTH_FAKE_REVIEW, so the key only has to be set.
    shutil.copy(experiment / "review.md", work / "review.md")
    review_config = work / "review.toml"
    review_config.write_text(
        "[review]\nenabled = true\n"
        'base_url = "https://fixtures.invalid/v1"\n'
        'api_key_var = "FIXTURE_REVIEW_KEY"\n'
        'model = "fixture-reviewer"\nrubric = "review.md"\n'
    )
    saved_env = {k: os.environ.get(k) for k in ("FIXTURE_REVIEW_KEY", "SYNTH_FAKE_REVIEW")}
    os.environ["FIXTURE_REVIEW_KEY"] = "not-a-key"

    for run_name in GENERATIONS:
        for entry in ROLLOUTS:
            if entry[0] != run_name:
                continue
            _, trace_id, task_class, table, status, do_finalize, do_score = entry
            if table is MEMORISING:
                table = memorising_table(artifact_path.read_text(), state, corpus)
            asyncio.run(one_rollout(
                vf, taskset_mod, write_episode, EvalRunInfo, Episode, EnvInfo,
                outputs, state, run_name, trace_id, task_class, table, status,
                do_finalize, do_score, baseline["reward"], baseline.get("rows", 0)))

        # --- the outer loop's own phases, run for real
        if promote.promote(state) == 0:
            if regression_gate.gate(state) == 0:
                os.environ["SYNTH_FAKE_REVIEW"] = "refuse" if run_name == "run-003" else "pass"
                code = cli.main(["review", "--config", str(review_config)])
                if code == 2:
                    raise SystemExit("review exited 2: the reviewer or substrate is broken")
                if code == 0:
                    promote.adopt(state)
                    baseline = __import__("json").loads((state / "baseline_train.json").read_text())

    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    # The eval that died before writing an episode: `save_config`
    # (verifiers/v1/cli/output.py:137) starts an empty traces.jsonl up front.
    dead = outputs / "run-004"
    dead.mkdir(parents=True, exist_ok=True)
    (dead / "traces.jsonl").write_text("")

    print(f"wrote B to {out}")
    print("  runs:", sorted(p.name for p in outputs.iterdir()))
    print("  candidates:", sorted(p.name for p in (state / "candidates").iterdir()))
    print("  promotions:", len(promote.read_promotions(state)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
