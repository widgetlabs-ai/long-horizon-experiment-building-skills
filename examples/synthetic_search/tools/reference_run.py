#!/usr/bin/env python3
"""R: one real generation loop, with only the agent scripted.

    uv run --extra orchestrator python tools/reference_run.py --out DIR

Writes DIR/state/ and DIR/outputs/<run>/traces.jsonl the way a search does.
Everything is the experiment's own code run for real -- the CLI subcommands,
the scorer, promote, the gate, adopt -- except two things:

  - the AGENT, replaced by `mutate`, which edits the rule table the way a
    rollout would;
  - the CONTAINER, replaced by `StubRuntime` over a local directory.

The seam is therefore at the agent, not the measurement. That is the whole
point: this experiment scores in pure Python, so unlike an experiment that
needs a renderer or a GPU, its reward can be exercised for real here. What this
file cannot produce is anything only a live model writes -- message graphs,
tool calls, stop reasons other than the scripted one.

`verifiers` is an optional extra (`orchestrator`); importing it at module scope
would make this file unimportable in the default environment.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

EXPERIMENT = Path(__file__).resolve().parents[1]
REQUIRES = "uv sync --extra orchestrator"

# One extra rule per category, appended to the RULES list. Deliberately crude:
# the point is a table that differs and still loads, not a good classifier.
_EXTRA = {
    "greeting": (r"\bgreetings\b", "greeting"),
    "question": (r"\bquick question\b", "question"),
    "complaint": (r"\bfrustrated\b", "complaint"),
    "order": (r"\badd to my cart\b", "order"),
    "farewell": (r"\bbye for now\b", "farewell"),
}

# Openers the first tier missed. By generation 3 every first-tier rule is
# already in the adopted table, so `mutate` draws from these instead: they are
# real corpus openers, and they genuinely beat the adopted table.
_EXTRA_TWO = {
    "greeting": (r"\bhey\b", "greeting"),
    "question": (r"\bi wonder\b", "question"),
    "complaint": (r"\b(very poor|not happy)\b", "complaint"),
    "order": (r"\bi need\b", "order"),
    "farewell": (r"\b(thanks|cheers)\b", "farewell"),
}
_SECOND_TIER_FROM = 3

MARKER = "# --- reference_run additions ---"

# Two candidates, matched by (generation, index) to synthetic_generator.py's
# own run-000-02 and run-001-00, get source the real guard/scorer rejects
# instead of a `mutate()` edit -- the same real code paths that generator's
# IMPORTING_TABLE and RAISING_TABLE force. Without these, `reward` was null
# for those candidates in B (a real guard/score_error verdict) and a number in
# R (mutate() only ever appends a valid rule), and no ignore rule can close
# that gap honestly: unlike a candidate that was never measured, this is a
# real, content-dependent failure mode a `synthetic-search` rollout can hit,
# and a reference that never hits it is not comparable on the one field
# (`reward`) the viewer's dashboard renders.
_IMPORTING = '''
import os


def classify(text):
    return "greeting" if os.sep else "order"
'''

_RAISING = '''
def classify(text):
    return text[1 // 0]
'''

_BAD_SOURCE = {
    (0, 2): _IMPORTING,  # guard-rejected
    (1, 0): _RAISING,    # raises at classify-time -- a score_error
}


def _memorise(source: str, state: Path) -> str:
    """A table that memorises one training row it would otherwise get wrong.

    Chosen from rows the current table MISclassifies on purpose: memorising a
    row it already gets right is redundant rather than cheating, and the
    validity check correctly lets it through.
    """
    sys.path.insert(0, str(EXPERIMENT / "src"))
    from synthetic_search.substrate import artifact as artifact_mod, corpus

    classify = artifact_mod.load(source)
    row = next(r for r in corpus.load_split(state, "train") if classify(r["text"]) != r["label"])
    return f"{source}\nRULES.insert(0, ({row['text']!r}, {row['label']!r}))\n"


_MEMORISE_AT = (2, 1)   # generation, rollout index

# Which fake review each generation gets. Measured (default build): generations
# 0, 1 and 2 each stage a winner that passes its gate and is adopted (run-000-03,
# run-001-01, run-002-00); generation 3 stages run-003-02 from the second tier,
# which passes its gate (val 0.8869 vs 0.8469) and is refused with a cited
# quote. Three adoptions stay on the reward curve. Move the refusal only if a
# run shows that generation's gate failing.
REVIEW_KINDS = {3: "refuse"}
REVIEW_KEY_VAR = "REFERENCE_RUN_REVIEW_KEY"


def _review_config(out: Path) -> Path:
    shutil.copy(EXPERIMENT / "review.md", out / "review.md")
    path = out / "review.toml"
    path.write_text(
        "[review]\nenabled = true\n"
        'base_url = "https://reference-run.invalid/v1"\n'
        f'api_key_var = "{REVIEW_KEY_VAR}"\n'
        'model = "reference-run-reviewer"\nrubric = "review.md"\n'
    )
    return path


def mutate(source: str, category: str, second_tier: bool = False) -> str:
    """The scripted agent: append one rule for `category`.

    Additions accumulate under one marker, so a table adopted earlier keeps its
    rules. Returns the source unchanged if the category is unknown or the rule
    is already present -- a lost candidate either way.
    """
    extra = _EXTRA_TWO if second_tier else _EXTRA
    if category not in extra:
        return source
    pattern, label = extra[category]
    if not source.endswith("\n"):
        source += "\n"
    rule = f"RULES.append(({pattern!r}, {label!r}))\n"
    if rule in source:
        return source  # already there: an adopted table keeps what it earned
    # The marker directly follows the table's last line, with no blank
    # separator, so the candidate differs from its base by exactly two lines.
    if MARKER in source:
        return source + rule
    return f"{source}{MARKER}\n{rule}"

class StubRuntime:
    """A container stand-in over a local directory.

    The real `Runtime` talks to Docker. Everything the taskset asks of it --
    read a path, write a path, run git -- has a local answer, and using one
    keeps the real `setup`/`finalize` code paths on the executed line.
    """

    def __init__(self, workdir: Path) -> None:
        self.workdir = Path(workdir)

    def _resolve(self, path: str) -> Path:
        return self.workdir / str(path).lstrip("/").removeprefix("workspace/")

    async def read(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    async def exec(self, argv: list[str]) -> SimpleNamespace:
        # `finalize` runs `git status --porcelain` for the candidate's status
        # file. A workdir that is not a repository answers with empty output,
        # which is what a clean tree looks like too -- correct either way.
        result = subprocess.run(argv, capture_output=True, text=True)
        return SimpleNamespace(
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode
        )


def _cli(state: Path, artifact: Path, *argv: str, env: dict | None = None) -> int:
    """Run one CLI subcommand in-process, with the state and artifact env set.

    `promote.adopt` (and `selftest.run`, reached from `cli selftest`) resolve
    the artifact to overwrite through `SYNTH_ARTIFACT`, defaulting to the
    checkout's real `artifact/rules.py` when it is unset. A reference run that
    left it unset would let a winning generation adopt into the tracked file
    for real on every test run -- this env var is what keeps `adopt` inside
    `out/` instead.
    """
    sys.path.insert(0, str(EXPERIMENT / "src"))
    from synthetic_search.substrate.cli import main

    applied = {"SYNTH_STATE": str(state), "SYNTH_ARTIFACT": str(artifact), **(env or {})}
    saved = {name: os.environ.get(name) for name in applied}
    os.environ.update(applied)
    try:
        return main(list(argv))
    finally:
        for name, before in saved.items():
            if before is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = before


def build(out: Path, generations: int = 4, seed: int = 7, rows: int = 100) -> dict:
    """Write a state and one run directory per generation, for real.

    Ruling (ledgered against the installed verifiers==0.3.1, which differs
    from the brief's best-guess constructors):

    - `TraceTask` has no `id` field; it is `type` + `data` + `key` + `hash`,
      the same fields `Env.run` fills from `Task.key`/`Task.hash`.
    - `TraceTask.data` is the raw task-data OBJECT, not a dumped dict. A live
      episode/rollout always builds it as `data=task.data` (`env.py:260`,
      `rollout.py:86`); `TraceTask` is `Generic[DataT]` and left
      unparametrized here, so pydantic validates a passed-in `dict` against
      `DataT`'s bound (`TaskData`, `task.py:133`) and drops every field
      `SyntheticData` adds beyond it, but leaves an already-valid model
      instance alone. Passing `data.model_dump(mode="json")` here once
      silently dropped `task_class`, `baseline_reward`, `rows`, `turns`,
      `worst` and `state_dir` from every trace this reference wrote -- caught
      by `test/fixtures_vs_real.py` diffing this reference against
      `viewer-scaffold/test/synthetic_generator.py`, which passes the object
      and kept them.
    - `AgentInfo.config` is required (no default); `verifiers/v1/task.py`'s
      real agents always carry a resolved `AgentConfig`, so an empty dict
      stands in for "no agent config" the way `synthetic_generator.py` (the
      sibling reference for this same pin) also does.
    - `Episode` has no `trace=`/`rewards=`/`eval_run=` kwargs. It holds
      `traces: list[Trace]` (one trace per agent) and takes its task from
      `trace.task`; the run identity is set after construction via
      `episode.record_run(EvalRunInfo(...))`, not a constructor argument. A
      live eval run passes `name=` too (`cli/eval/runner.py:208`:
      `EvalRunInfo(id=config.run.id, name=config.run.name)`) -- omitting it
      here was the same class of shortcut as the `data=` one above.
    - `Trace.rewards` is `dict[str, Reward]`, keyed by reward name, not a
      list. `Task.score(trace, runtime)` is `verifiers`' own concrete method,
      called by `rollout.py` with the runtime positional and its return value
      discarded; `SyntheticTask.score` overrides it and records onto the
      trace itself with `trace.record_reward`, so this reference run calls it
      exactly the way a live rollout does -- it used to call a one-argument
      override that returned a `Reward` instead, which masked a `TypeError`
      every real rollout would have hit (see `taskset.SyntheticTask.score`).

    Two rollouts skip a phase on purpose, once each, so this reference covers
    the same real code paths `synthetic_generator.py`'s crafted candidates do
    rather than leaving them for that generator alone to exercise: generation
    0's second candidate never finalizes (`score` then finds no artifact --
    the "never measured" path, `taskset.py:105-115`), generation 1's third
    candidate finalizes but never scores (`candidate.json` then holds only
    `finalize`'s half -- the read-modify-write in `taskset_contract.py:50-75`),
    and two more candidates get real bad source instead of a `mutate()` edit
    (`_BAD_SOURCE` above) so a real guard rejection and a real score_error are
    on this side too, not only B's. `generations` defaults to 4 and `rows` to
    100 -- the same corpus size `synthetic_generator.py` stages -- so a
    generation reaches the second skip and the gate's small-support exemption
    (`promote.MIN_GATE_SUPPORT`, `regression_gate.py:52`) fires the same way
    on both sides; a bigger corpus gives every category enough val support
    that no category is ever exempt.

    Also isolates `SYNTH_ARTIFACT` to a copy under `out/`: `promote.adopt`
    writes wherever it resolves to, and unset that is the checkout's real
    `artifact/rules.py` -- see `_cli`.
    """
    import asyncio

    from verifiers.v1.cli.output import write_episode
    from verifiers.v1.episode import EnvInfo, Episode, EvalRunInfo
    from verifiers.v1.trace import AgentInfo, Trace, TraceTask

    sys.path.insert(0, str(EXPERIMENT / "src"))
    from synthetic_search import taskset as ts
    from synthetic_search.substrate import corpus, taskset_contract as contract

    out = Path(out)
    state = out / "state"
    state.mkdir(parents=True, exist_ok=True)

    artifact = out / "artifact" / "rules.py"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text((EXPERIMENT / "artifact" / "rules.py").read_text())

    assert _cli(state, artifact, "stage", "--seed", str(seed), "--rows", str(rows)) == 0
    assert _cli(state, artifact, "pin") == 0
    assert _cli(state, artifact, "baseline", "--split", "all", "--source", str(artifact)) == 0

    review_config = _review_config(out)
    runs: list[str] = []
    candidates = 0
    for generation in range(generations):
        run = f"run-{generation:03d}"
        runs.append(run)
        run_dir = out / "outputs" / run
        run_dir.mkdir(parents=True, exist_ok=True)

        for index, category in enumerate(corpus.CATEGORIES):
            trace_id = f"{run}-{index:02d}"
            workdir = out / "work" / trace_id
            (workdir / "artifact").mkdir(parents=True, exist_ok=True)
            base = artifact.read_text()
            if (generation, index) == _MEMORISE_AT:
                source = _memorise(base, state)
            else:
                source = _BAD_SOURCE.get((generation, index)) or mutate(base, category, generation >= _SECOND_TIER_FROM)
            (workdir / contract.ARTIFACT_PATHS[0]).write_text(source)

            data = ts.SyntheticData(
                task_class=category,
                worst=list(corpus.CATEGORIES[:3]),
                baseline_reward=json.loads((state / "baseline_train.json").read_text())["reward"],
                rows=rows,
                turns=120,
                state_dir=str(state),
            )
            task = ts.SyntheticTask(data)
            trace = Trace(
                id=trace_id,
                task=TraceTask(type=type(task).__name__, data=data, key=task.key, hash=task.hash),
                agent=AgentInfo(config={}, name="reference_run"),
            )
            runtime = StubRuntime(workdir)

            # See "Two rollouts skip a phase on purpose" above.
            skip_finalize = generation == 0 and index == 1
            skip_score = generation == 1 and index == 2

            if not skip_finalize:
                asyncio.run(task.finalize(trace, runtime))
            if not skip_score:
                # The reference run must call `score` with the framework's own
                # signature -- `score(trace, runtime)`, recording onto the trace
                # rather than returning -- because a driver that calls it
                # differently is a driver that cannot see this class of defect.
                # That is exactly what happened: this file and a scratch generator
                # were the only callers of the old `score(trace) -> Reward`
                # override, and both masked a `TypeError` a real `uv run eval`
                # would have hit on every rollout.
                asyncio.run(task.score(trace, runtime))
            trace.is_completed = True
            trace.ok = True
            trace.stop_condition = "final_answer"
            candidates += 1

            episode = Episode(env=EnvInfo(id="synthetic_search"), task=trace.task, traces=[trace], ok=True)
            episode.record_run(EvalRunInfo(id=run, name=run))
            write_episode(run_dir, episode)

        assert _cli(state, artifact, "post-generation", "--run", str(run_dir)) == 0
        if _cli(state, artifact, "promote") != 0:
            continue
        if _cli(state, artifact, "gate") != 0:
            continue
        kind = REVIEW_KINDS.get(generation, "pass")
        code = _cli(state, artifact, "review", "--config", str(review_config),
                    env={"SYNTH_FAKE_REVIEW": kind, REVIEW_KEY_VAR: "not-a-key"})
        assert code != 2, "review exited 2: the reviewer or substrate is broken, not a lost candidate"
        if code != 0:
            continue
        assert _cli(state, artifact, "adopt") == 0

    shutil.rmtree(out / "work", ignore_errors=True)
    return {"generations": generations, "candidates": candidates, "runs": runs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="reference_run", description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--generations", type=int, default=None)
    parser.add_argument("--rows", type=int, default=100)
    args = parser.parse_args(argv)
    kwargs = {} if args.generations is None else {"generations": args.generations}
    print(json.dumps(build(args.out, rows=args.rows, **kwargs), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
