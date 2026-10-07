"""The verifiers v1 taskset: one task per category.

A rollout gets a container holding the artifact, the train rows and `rt`, plus
a brief naming its category and the table's weakest ones. It edits the table,
self-scores, and stops by replying with a number. `finalize` copies the table
out; the reward re-scores that copy **on the host**, in a subprocess, so a
candidate that hangs or loops costs that candidate and never the generation.

The paths are not spelled here: they come from `taskset_contract`, which the
brief also renders from. One definition, so the two cannot drift.

This module imports the orchestrator and is reachable only through the lazy
accessor in `__init__.py` — the rollout container needs the substrate, not the
framework, and an eager import here fails its build.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
from pathlib import Path

import verifiers.v1 as vf

from __EXPERIMENT__.substrate import corpus, evaluate
from __EXPERIMENT__.substrate import taskset_contract as contract
from __EXPERIMENT__.substrate.errors import EXIT_SUBSTRATE, SubstrateError

EXPERIMENT = Path(__file__).resolve().parents[2]
BRIEF_PATH = EXPERIMENT / "brief.md"
ABORT_NAME = "ABORT"
SCORE_TIMEOUT = 900

# The episode ends when the reply ends with a number: the agent's own score.
_FINAL = re.compile(r"-?\d*\.?\d+[.!]?\s*$")


class SyntheticData(vf.TaskData):
    """One task: improve the rule table, starting from one category."""

    task_class: str = ""
    worst: list[str] = []
    baseline_reward: float = 0.0
    rows: int = 0
    turns: int = 0
    state_dir: str = ""


class SyntheticTask(vf.Task[SyntheticData]):
    NEEDS_CONTAINER = True

    def runtime_env(self) -> dict[str, str]:
        # The box cannot see the model's turn count, so the harness hands it the
        # budget it can count down from. `box.rt` reads this variable and prints
        # how many turns remain on each `rt score`.
        return {contract.TURN_BUDGET_ENV: str(self.data.turns)}

    async def setup(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        workdir = self.data.workdir or "/workspace"
        await runtime.write(f"{workdir}/BRIEF.md", self._brief().encode())

    def _brief(self) -> str:
        # A missing brief must fail loudly rather than send an empty one: a
        # rollout with no instructions still costs a full budget to discover.
        if not BRIEF_PATH.is_file():
            raise SubstrateError(f"brief not found: {BRIEF_PATH}")
        return contract.render_brief(
            BRIEF_PATH.read_text(),
            {
                "task_class": self.data.task_class,
                "baseline_reward": self.data.baseline_reward,
                "worst": self.data.worst,
                "rows": self.data.rows,
                "turns": self.data.turns,
            },
        )

    @vf.stop
    async def final_answer(self, trace: vf.Trace) -> bool:
        return trace.num_turns >= 1 and _FINAL.search(trace.last_reply or "") is not None

    async def finalize(self, trace: vf.Trace, runtime: vf.Runtime) -> None:
        """Copy back the best admissible version, not the last one.

        `rt score` snapshots its best-scoring admissible version as it goes, so
        a rollout that improves and then regresses must hand back the
        improvement, not whatever the working tree held when the turn cap hit.
        The box materialises that best version to `CHECKPOINT_PATH`; when it is
        absent (the agent never scored an admissible version) the working tree
        is the fallback.
        """
        workdir = self.data.workdir or "/workspace"
        destination = contract.candidate_dir(Path(self.data.state_dir), trace.id)
        destination.mkdir(parents=True, exist_ok=True)

        checkpoint = await self._checkpoint_source(runtime)
        returned = contract.BEST_TAG if checkpoint is not None else "working-tree"

        for relative in contract.ARTIFACT_PATHS:
            if checkpoint is not None and relative == contract.ARTIFACT_PATHS[0]:
                content = checkpoint
            else:
                content = await runtime.read(f"{workdir}/{relative}")
            target = destination / Path(relative).name
            target.write_bytes(content)

        status = await runtime.exec(["git", "-C", workdir, "status", "--porcelain"])
        (destination / "status.txt").write_text(status.stdout or "")
        (destination / "candidate.json").write_text(
            json.dumps({"trace": str(trace.id), "task_class": self.data.task_class, "returned": returned}, sort_keys=True) + "\n"
        )

    async def _checkpoint_source(self, runtime: vf.Runtime) -> bytes | None:
        """The box's best-scoring source, or None when it never checkpointed one."""
        try:
            content = await runtime.read(contract.CHECKPOINT_PATH)
        except Exception:
            return None
        return content if content else None

    async def score(self, trace: vf.Trace) -> vf.Reward:
        """The host's number. The box's is steering; this is the reward."""
        destination = contract.candidate_dir(Path(self.data.state_dir), trace.id)
        source_path = destination / Path(contract.ARTIFACT_PATHS[0]).name
        if not source_path.is_file():
            trace.metrics.update(evaluate.summarize({"reward": None, "artifact_unchanged": 1.0}))
            return vf.Reward(score=0.0, weight=1.0)

        report = await asyncio.to_thread(self._score_on_host, source_path)
        trace.metrics.update(evaluate.summarize(report))
        trace.metrics["turns"] = float(trace.num_turns)
        return vf.Reward(score=float(report["reward"] or 0.0), weight=1.0)

    def _score_on_host(self, source_path: Path) -> dict:
        """Score in a subprocess: a candidate that hangs costs only itself."""
        result = subprocess.run(
            [sys.executable, "-m", "__EXPERIMENT__.substrate.cli",
             "score", "--source", str(source_path), "--split", "train"],
            capture_output=True,
            text=True,
            timeout=SCORE_TIMEOUT,
            env={**_env(), "__STATE_ENV__": self.data.state_dir},
        )
        if result.returncode == EXIT_SUBSTRATE:
            raise SubstrateError(f"scoring is broken, not this candidate: {result.stderr.strip()}")
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"reward": None, "score_error": 1.0, "error": result.stderr.strip()[:500]}


def _env() -> dict:
    import os

    return dict(os.environ)


def load_taskset(num_tasks: int = 5, **kwargs) -> list[SyntheticData]:
    """One task per category, richest sub-problem first.

    Resolution happens here, at load time, so a wrong path costs zero tokens
    rather than a night of rollouts scoring against nothing.
    """
    state = corpus.resolve_state_root()
    if (state / ABORT_NAME).exists():
        raise SubstrateError(f"{state / ABORT_NAME} exists; refusing to start")

    baseline_path = state / "baseline_train.json"
    if not baseline_path.is_file():
        raise SubstrateError("no train baseline; run `cli baseline --split all`")
    baseline = json.loads(baseline_path.read_text())
    worst = evaluate.worst_categories(baseline, limit=3)
    rows = baseline.get("rows", 0)

    classes = contract.task_classes()[:num_tasks]
    return [
        SyntheticData(
            task_class=name,
            worst=worst,
            baseline_reward=baseline["reward"],
            rows=rows,
            turns=kwargs.get("max_turns", 120),
            state_dir=str(state),
        )
        for name in classes
    ]
