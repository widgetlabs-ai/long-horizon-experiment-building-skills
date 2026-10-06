"""`rt` — the agent's tool inside the rollout container.

The numbers it prints are *steering*, not the reward: the reward is computed on
the host, against the host's rows, by the same scorer. They agree because the
box carries the same frozen instrument — but the box only ever carries the
train rows, and asking it for a held-out split is refused rather than answered.
That refusal is not politeness. A box that can score itself on the split it is
gated against can be optimised against that split, and the gate stops meaning
anything.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

from synthetic_search.substrate import artifact as artifact_mod
from synthetic_search.substrate import corpus, evaluate, measure, promote, taskset_contract, validity
from synthetic_search.substrate.errors import EXIT_LOST, EXIT_OK, EXIT_SUBSTRATE, CandidateError, SubstrateError

IN_BOX_SPLIT = "train"


def _state() -> Path:
    return corpus.resolve_state_root()


def _source() -> str:
    path = promote.resolve_artifact_path()
    if not path.is_file():
        raise SubstrateError(f"artifact not found: {path}")
    return path.read_text()


def _baseline_reward(state: Path) -> float | None:
    path = state / f"baseline_{IN_BOX_SPLIT}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text())["reward"]


def _repo_root() -> Path | None:
    """The in-box git repository holding the artifact, or None when there is none.

    A box run outside a rollout (or a test) has no repository to checkpoint
    into, and must not treat some unrelated ancestor's `.git` as its own.
    """
    artifact = promote.resolve_artifact_path().resolve()
    for candidate in artifact.parents:
        if (candidate / ".git").is_dir():
            return candidate
    return None


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _best_score(repo: Path) -> float | None:
    """The score recorded on the best tag, or None when the tag does not exist."""
    result = _git(repo, ["tag", "--list", "--format=%(contents)", taskset_contract.BEST_TAG])
    text = (result.stdout or "").strip()
    if not text:
        return None
    try:
        return float(text.splitlines()[0].strip())
    except ValueError:
        return None


def _artifact_relative(repo: Path) -> str:
    artifact = promote.resolve_artifact_path().resolve()
    try:
        return artifact.relative_to(repo).as_posix()
    except ValueError:
        return promote.ARTIFACT_RELATIVE


def _seed_best(repo: Path, state: Path) -> None:
    """Make the unedited baseline the floor of "best".

    A rollout that never beats its baseline should hand back what it was given,
    not its least-bad edit, so the first checkpoint seeds the tag and the
    materialised source from the repository's root commit.
    """
    if _best_score(repo) is not None:
        return
    baseline = _baseline_reward(state)
    if baseline is None:
        return
    root = _git(repo, ["rev-list", "--max-parents=0", "HEAD"]).stdout.strip()
    if not root:
        return
    _git(repo, ["tag", "-f", "-a", taskset_contract.BEST_TAG, "-m", f"{baseline:.6f}", root])
    content = _git(repo, ["show", f"{root}:{_artifact_relative(repo)}"]).stdout
    if content:
        Path(taskset_contract.CHECKPOINT_PATH).write_text(content)


def _checkpoint(source: str, reward: float, state: Path) -> None:
    """Commit a passing version and move the best tag to the highest scorer.

    Only a version that passed the check reaches here: an inadmissible edit is
    never committed, so the tag can only ever point at something the host would
    accept. The box's git is throwaway state that `finalize` alone reads.
    """
    repo = _repo_root()
    if repo is None:
        return
    _seed_best(repo, state)
    relative = _artifact_relative(repo)
    _git(repo, ["add", "--", relative])
    commit = _git(
        repo,
        ["-c", "user.email=rt@example.invalid", "-c", "user.name=rt",
         "commit", "-qm", f"rt score {reward:.6f}"],
    )
    if commit.returncode != 0:
        # Nothing to commit: the table did not change since the last commit.
        return
    best = _best_score(repo)
    if best is None or reward > best:
        head = _git(repo, ["rev-parse", "HEAD"]).stdout.strip()
        if not head:
            return
        _git(repo, ["tag", "-f", "-a", taskset_contract.BEST_TAG, "-m", f"{reward:.6f}", head])
        Path(taskset_contract.CHECKPOINT_PATH).write_text(source)


def _score(args) -> int:
    if args.split != IN_BOX_SPLIT:
        print(
            f"rt: only the {IN_BOX_SPLIT!r} rows are in this container. "
            f"{args.split!r} is held out and is scored on the host.",
            file=sys.stderr,
        )
        return EXIT_SUBSTRATE

    state = _state()
    source = _source()
    report = measure.measure_source(source, IN_BOX_SPLIT, state, use_cache=False)
    if report["reward"] is None:
        print(f"rt: no score — {report['error']}")
        return EXIT_LOST

    baseline = _baseline_reward(state)
    delta = evaluate.gain(report["reward"], baseline)
    print(f"reward {report['reward']:.6f}   delta {delta if delta is None else format(delta, '+.6f')}")
    print()
    for name, stats in sorted(report["per_category"].items()):
        f1 = "     —" if stats["f1"] is None else f"{stats['f1']:.4f}"
        print(f"  {name:<12} f1 {f1}   support {stats['support']}")
    _checkpoint(source, report["reward"], state)
    return EXIT_OK


def _check(args) -> int:
    """The guard, then the validity check -- what the host will ask, asked early.

    The host enforces both whether or not this is run. This exists so the agent
    finds out on turn 12 instead of after the rollout, when finding out teaches
    it nothing.
    """
    try:
        source = _source()
        artifact_mod.load(source)
    except Exception as exc:  # a guard or load error: the message is what the agent needs to read
        print(f"rt: the table would be rejected — {exc}")
        return EXIT_LOST
    # A loader, as the host passes: every pass gets a fresh table, so this asks
    # exactly what `measure_source` will ask.
    violations = validity.check(lambda: artifact_mod.load(source), corpus.load_split(_state(), IN_BOX_SPLIT))
    if violations:
        print("rt: the table would be refused as inadmissible, whatever it scores:")
        for violation in violations:
            print(f"  {violation}")
        return EXIT_LOST
    print("rt: the table passes the guard and the validity check")
    return EXIT_OK


def _rows(args) -> int:
    state = _state()
    rows = corpus.load_split(state, IN_BOX_SPLIT)
    if args.cls:
        rows = [r for r in rows if r["label"] == args.cls]
    try:
        classify = artifact_mod.load(_source())
    except CandidateError as exc:  # the table's fault: say why, as `rt check` does
        print(f"rt: the table would be rejected — {exc}")
        return EXIT_LOST
    sample = random.Random(0).sample(rows, min(args.limit, len(rows)))
    for row in sample:
        predicted = classify(row["text"])
        mark = " " if predicted == row["label"] else "!"
        print(f"{mark} label {row['label']:<12} predicted {predicted:<12} {row['text']}")
    return EXIT_OK


COMMANDS = {
    "score": (_score, "score the current table against the train rows"),
    "check": (_check, "run the guard and the validity check without scoring"),
    "rows": (_rows, "sample rows with what the table currently predicts"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rt")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        child = sub.add_parser(name, help=help_text)
        if name == "score":
            child.add_argument("--split", default=IN_BOX_SPLIT)
        if name == "rows":
            child.add_argument("--class", dest="cls", default=None)
            child.add_argument("--limit", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command][0](args)
    except SubstrateError as exc:
        print(f"rt: {exc}", file=sys.stderr)
        return EXIT_SUBSTRATE
    except SystemExit as exc:
        return int(exc.code or 0)


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
