"""The command surface. Every phase of the loop is a subcommand here.

One entry point rather than a script per phase, so the exit-code contract holds
across all of them: 0 ok, 1 this candidate lost, 2 the substrate is broken and
the run must stop. The supervisor reads nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from __EXPERIMENT__.substrate import corpus, evaluate, measure
from __EXPERIMENT__.substrate.errors import EXIT_LOST, EXIT_OK, EXIT_SUBSTRATE, SubstrateError

ARTIFACT_RELATIVE = "artifact/rules.py"


def _experiment_root() -> Path:
    # The experiment's own root, not the repository's: three levels up from
    # this file is the project directory that owns the artifact and the scripts.
    return Path(__file__).resolve().parents[3]


def _default_artifact() -> Path:
    return _experiment_root() / ARTIFACT_RELATIVE


def _read_source(args) -> str:
    path = Path(args.source) if getattr(args, "source", None) else _default_artifact()
    if not path.is_file():
        raise SubstrateError(f"artifact not found: {path}")
    return path.read_text()


def _stage(args) -> int:
    import os

    raw = os.environ.get(corpus.STATE_ENV)
    if not raw:
        print(f"substrate: {corpus.STATE_ENV} is not set; it must name the experiment's state directory", file=sys.stderr)
        return EXIT_SUBSTRATE
    state = Path(raw)
    state.mkdir(parents=True, exist_ok=True)
    counts = corpus.stage(state, seed=args.seed, n=args.rows)
    print(json.dumps(counts, sort_keys=True))
    return EXIT_OK


def _pin(args) -> int:
    state = corpus.resolve_state_root()
    pin = {"instrument": measure.instrument_pin(), "files": list(measure.INSTRUMENT_FILES)}
    (state / "instrument.json").write_text(json.dumps(pin, indent=2, sort_keys=True) + "\n")
    print(json.dumps(pin, sort_keys=True))
    return EXIT_OK


def _check_pin(state: Path) -> None:
    """Refuse to produce a number with a ruler nobody pinned."""
    path = state / "instrument.json"
    if not path.is_file():
        raise SubstrateError("the instrument is not pinned; run `cli pin`")
    pinned = json.loads(path.read_text())["instrument"]
    current = measure.instrument_pin()
    if pinned != current:
        raise SubstrateError(
            f"the instrument changed since it was pinned ({pinned} -> {current}); re-pin and re-baseline"
        )


def _baseline(args) -> int:
    state = corpus.resolve_state_root()
    _check_pin(state)
    source = _read_source(args)
    splits = corpus.SPLITS if args.split == "all" else (args.split,)
    written = {}
    for split in splits:
        report = measure.measure_source(source, split, state)
        (state / f"baseline_{split}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        written[split] = report["reward"]
    print(json.dumps(written, sort_keys=True))
    return EXIT_OK


def _score(args) -> int:
    state = corpus.resolve_state_root()
    _check_pin(state)
    source = _read_source(args)
    report = measure.measure_source(source, args.split, state)
    metrics = evaluate.summarize(report)
    print(json.dumps({**report, **metrics}, indent=2, sort_keys=True))
    return EXIT_OK if report["reward"] is not None else EXIT_LOST


def _candidates(args) -> int:
    state = corpus.resolve_state_root()
    root = state / "candidates"
    names = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    print(json.dumps(names, indent=2))
    return EXIT_OK


def _report(args) -> int:
    state = corpus.resolve_state_root()
    source = _read_source(args)
    report = measure.measure_source(source, args.split, state)
    print(json.dumps({
        "reward": report["reward"],
        "rows": report["rows"],
        "worst_categories": evaluate.worst_categories(report, args.limit),
        "per_category": report["per_category"],
    }, indent=2, sort_keys=True))
    return EXIT_OK


def _promote(args) -> int:
    from __EXPERIMENT__.substrate import promote

    return promote.promote(corpus.resolve_state_root())


def _gate(args) -> int:
    from __EXPERIMENT__.substrate import regression_gate

    return regression_gate.gate(corpus.resolve_state_root())


def _adopt(args) -> int:
    from __EXPERIMENT__.substrate import promote

    return promote.adopt(corpus.resolve_state_root())


def _selftest(args) -> int:
    from __EXPERIMENT__.substrate import selftest

    return selftest.run(corpus.resolve_state_root())


def _post_generation(args) -> int:
    from __EXPERIMENT__.substrate import selftest

    return selftest.post_generation(corpus.resolve_state_root(), Path(args.run))


REVIEW_CONFIG = "review.toml"


def _review(args) -> int:
    import difflib
    import os

    from __EXPERIMENT__.substrate import promote, review

    config_path = Path(args.config) if args.config else _experiment_root() / REVIEW_CONFIG
    config = review.load_config(config_path)
    if args.check:
        # The preflight's question: could this reviewer run? No call is made.
        problems = review.readiness(config, config_path.parent / config.rubric)
        for problem in problems:
            print(f"review: {problem}", file=sys.stderr)
        if problems:
            return EXIT_SUBSTRATE
        print(f"review: {'ready' if config.enabled else 'disabled'} ({config_path.name})")
        return EXIT_OK
    if not config.enabled:
        print(f"review: disabled ({config_path.name})")
        return EXIT_OK

    state = corpus.resolve_state_root()

    pending_path = state / "pending.json"
    if not pending_path.is_file():
        print("review: nothing pending")
        return EXIT_LOST
    pending = json.loads(pending_path.read_text())
    if not pending.get("gate_passed"):
        print("review: refusing to review a candidate the gate has not passed")
        return EXIT_LOST

    # From here on the candidate is gated but unreviewed. Any way out other
    # than a pass -- a refusal, an absent reviewer, a missing rubric, an
    # exception nobody foresaw -- discards it, so a hand-run `adopt` cannot
    # adopt what the reviewer never approved.
    try:
        rubric_path = config_path.parent / config.rubric
        if not rubric_path.is_file():
            raise SubstrateError(f"review: enabled, but its rubric does not exist: {rubric_path}")

        # From ARTIFACT_RELATIVE rather than a literal filename, so this handler
        # reads the same in the template, where the artifact is somebody else's.
        candidate = (state / "staged" / Path(ARTIFACT_RELATIVE).name).read_text()
        adopted = promote.resolve_artifact_path().read_text()
        diff = "".join(difflib.unified_diff(
            adopted.splitlines(keepends=True), candidate.splitlines(keepends=True),
            fromfile=f"{ARTIFACT_RELATIVE} (adopted)", tofile=f"{ARTIFACT_RELATIVE} (candidate)",
        ))
        measured = measure.measure_source(candidate, "train", state)
        report = {
            "train_reward": measured["reward"],
            "baseline_train_reward": promote._baseline(state, "train").get("reward"),
            "gain": pending.get("gain"),
            "per_category": measured["per_category"],
        }
        fake = os.environ.get("SYNTH_FAKE_REVIEW")
        code = review.review(
            state, config, rubric_path.read_text(), (_experiment_root() / "brief.md").read_text(),
            diff, report, trace=pending.get("trace"), generation=promote._generation(state),
            transport=review.fake_transport(fake) if fake else review.http_transport,
        )
        if code != EXIT_OK:
            promote.discard_pending(state)
    except BaseException:
        promote.discard_pending(state)
        raise
    return code


SUBCOMMANDS = {
    "stage": (_stage, "generate the corpus and split it three ways"),
    "pin": (_pin, "pin the instrument's content hash"),
    "baseline": (_baseline, "measure the current artifact: the high-water marks"),
    "score": (_score, "score one artifact source against one split"),
    "candidates": (_candidates, "list the candidates returned by rollouts"),
    "promote": (_promote, "pick the best eligible candidate on train, stage it"),
    "gate": (_gate, "rescore the staged candidate on val; discard it if it fails"),
    "review": (_review, "ask the reviewer whether the gated candidate earned its score"),
    "adopt": (_adopt, "adopt a gated candidate and rewrite the baselines"),
    "report": (_report, "the current artifact's weakest categories"),
    "selftest": (_selftest, "the scoring invariants: determinism, quantization, cache"),
    "post-generation": (_post_generation, "read one generation's traces and explain every rollout"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="__EXPERIMENT__")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in SUBCOMMANDS.items():
        child = sub.add_parser(name, help=help_text)
        if name == "stage":
            child.add_argument("--seed", type=int, default=7)
            child.add_argument("--rows", type=int, default=2000)
        if name in {"baseline", "score", "report"}:
            child.add_argument("--source", default=None, help="artifact source file; default: the checkout's")
            child.add_argument("--split", default="all" if name == "baseline" else "train")
        if name == "review":
            child.add_argument("--config", default=None, help=f"default: the experiment's {REVIEW_CONFIG}")
            child.add_argument("--check", action="store_true",
                               help="only check the reviewer could run: key set, rubric has concerns, URL; no call")
        if name == "report":
            child.add_argument("--limit", type=int, default=3)
        if name == "post-generation":
            child.add_argument("--run", required=True, help="an eval run directory holding traces.jsonl")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = SUBCOMMANDS[args.command][0]
    try:
        return handler(args)
    except SubstrateError as exc:
        print(f"substrate: {exc}", file=sys.stderr)
        return EXIT_SUBSTRATE
    except SystemExit as exc:  # resolve_state_root exits 2 with its own message
        return int(exc.code or 0)
    except Exception:
        # Anything unforeseen is a broken substrate, never a lost candidate. An
        # uncaught exception exits 1, which the supervisor reads as "nothing
        # eligible, continue" — and the run then spends every remaining
        # generation measuring nothing while its numbers stay plausible.
        traceback.print_exc()
        print("substrate: unexpected failure (see the traceback above)", file=sys.stderr)
        return EXIT_SUBSTRATE


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
