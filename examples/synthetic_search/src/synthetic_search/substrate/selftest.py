"""The invariants the whole search rests on, checked in seconds.

Everything here runs before a generation is spent, because each of these
failures is silent: the numbers stay plausible and only the conclusions are
wrong. Determinism is first because a scorer that disagrees with itself makes
every promotion a coin flip that nobody can see being tossed.

`post_generation` lives here too: an eval exits 0 whether its rollouts learned
anything or failed identically, so the exit code cannot tell you what happened
and something has to read the traces.
"""

from __future__ import annotations

import json
from pathlib import Path

from synthetic_search.substrate import evaluate, measure, promote, scorer
from synthetic_search.substrate.errors import EXIT_OK, EXIT_SUBSTRATE


def _fail(message: str) -> None:
    print(f"selftest: FAIL {message}")


def run(state: Path) -> int:
    """Return 0 when every invariant holds, 2 when the substrate is broken."""
    state = Path(state)
    failures = 0

    pin_path = state / "instrument.json"
    if not pin_path.is_file():
        _fail("the instrument is not pinned; run `cli pin`")
        return EXIT_SUBSTRATE
    pinned = json.loads(pin_path.read_text())["instrument"]
    if pinned != measure.instrument_pin():
        _fail(f"the instrument moved since it was pinned ({pinned} -> {measure.instrument_pin()})")
        return EXIT_SUBSTRATE

    for split in ("train", "val"):
        if not (state / f"baseline_{split}.json").is_file():
            _fail(f"no baseline for {split!r}; run `cli baseline --split all`")
            return EXIT_SUBSTRATE

    source_path = promote.resolve_artifact_path()
    if not source_path.is_file():
        _fail(f"artifact not found: {source_path}")
        return EXIT_SUBSTRATE
    source = source_path.read_text()

    # 1. Determinism. Two uncached measurements of the same tree must agree
    #    exactly, not nearly: a threshold comparison does not care how small the
    #    disagreement is.
    first = measure.measure_source(source, "train", state, use_cache=False)
    second = measure.measure_source(source, "train", state, use_cache=False)
    if first["reward"] != second["reward"]:
        _fail(f"scoring is not deterministic: {first['reward']} != {second['reward']}")
        failures += 1

    # 2. Quantization. Anything that feeds a comparison is rounded, so two
    #    builds that agree to nine places agree about who won.
    reward = first["reward"]
    if reward is not None and reward != round(reward, scorer.QUANTUM):
        _fail(f"the reward is not quantized to {scorer.QUANTUM} places: {reward!r}")
        failures += 1

    # 3. The cache answers with what the cold path produced.
    cached = measure.measure_source(source, "train", state)
    recached = measure.measure_source(source, "train", state)
    if not recached["cached"]:
        _fail("the cache did not answer a repeated measurement")
        failures += 1
    elif cached["reward"] != first["reward"]:
        _fail(f"the cache disagrees with a cold measurement: {cached['reward']} != {first['reward']}")
        failures += 1

    # 4. Every category the taxonomy names is one the scorer reports on.
    from synthetic_search.substrate import corpus

    reported = set(first.get("per_category", {}))
    if reported != set(corpus.CATEGORIES):
        _fail(f"the scorer reports on {sorted(reported)}, the taxonomy says {sorted(corpus.CATEGORIES)}")
        failures += 1

    # 5. The baseline was measured on this artifact and this corpus.
    baseline = json.loads((state / "baseline_train.json").read_text())
    if baseline["reward"] != first["reward"]:
        _fail(
            f"the train baseline ({baseline['reward']}) is not this artifact's score "
            f"({first['reward']}) — re-run `cli baseline --split all`"
        )
        failures += 1

    if failures:
        print(f"selftest: {failures} invariant(s) failed")
        return EXIT_SUBSTRATE
    print("selftest: ok — determinism, quantization, cache, taxonomy, baselines")
    return EXIT_OK


def read_traces(path: Path) -> tuple[list[dict], int]:
    """Every episode in a traces file, and how many lines did not parse.

    Split on "\\n" only. `splitlines()` also splits on U+2028, which JSON leaves
    raw inside strings; agent transcripts are full of it, and one such record
    would read as two broken ones.
    """
    if not Path(path).is_file():
        return [], 0
    episodes: list[dict] = []
    unreadable = 0
    for line in Path(path).read_text().split("\n"):
        if not line.strip():
            continue
        try:
            episodes.append(json.loads(line))
        except json.JSONDecodeError:
            unreadable += 1
    return episodes, unreadable


def _traces(episode: dict) -> list[dict]:
    """The per-agent records inside one episode.

    `write_episode` serializes one whole `Episode` per line, and an episode
    holds a LIST of traces (`verifiers/v1/episode.py:103`). Everything a
    rollout measured lives on its trace, not on the episode.
    """
    traces = episode.get("traces")
    return traces if isinstance(traces, list) else []


def trace_reward(episode: dict) -> float | None:
    """`score * weight`, summed over every named reward, read off the wire.

    Two things this must not do, both of which read a whole healthy generation
    as zero. It must not read `value`: that is a Python property
    (`verifiers/v1/trace.py:436`) and never reaches the serialized record. And
    it must not look for a top-level `rewards` list: rewards are a dict keyed
    by name (`verifiers/v1/trace.py:402`) on each TRACE. This reader was wrong
    about the second for its whole life, because its fixtures were written to
    match it rather than to match the framework -- see
    `test_the_fixture_has_the_shape_the_framework_writes`.
    """
    total = 0.0
    seen = False
    for trace in _traces(episode):
        rewards = trace.get("rewards")
        if not isinstance(rewards, dict):
            continue
        for reward in rewards.values():
            if not isinstance(reward, dict) or "score" not in reward:
                continue
            seen = True
            total += float(reward["score"]) * float(reward.get("weight", 1.0))
    return total if seen else None


def trace_metrics(episode: dict) -> dict:
    """Every trace's metrics, merged. Later traces win on a collision."""
    merged: dict = {}
    for trace in _traces(episode):
        metrics = trace.get("metrics")
        if isinstance(metrics, dict):
            merged.update(metrics)
    return merged


def post_generation(state: Path, run_dir: Path) -> int:
    """Explain every rollout of one generation: what it scored and why."""
    episodes, unreadable = read_traces(Path(run_dir) / "traces.jsonl")
    if not episodes:
        # A generation that produced no readable episode did not lose; it did
        # not run. Returning 0 here would make it indistinguishable from a
        # healthy generation to the supervisor, which is the very thing this
        # stage exists to prevent.
        print(f"post-generation: no episodes in {run_dir} ({unreadable} unreadable line(s))")
        return EXIT_SUBSTRATE

    baseline_path = Path(state) / "baseline_train.json"
    baseline = json.loads(baseline_path.read_text())["reward"] if baseline_path.is_file() else None

    for episode in episodes:
        reward = trace_reward(episode)
        metrics = trace_metrics(episode)
        reasons = [name for name in evaluate.ZERO_REASONS if metrics.get(name)]
        verdict = ", ".join(reasons) if reasons else "scored"
        gain = evaluate.gain(reward, baseline)
        print(
            f"{episode.get('id', '?')}: reward={reward} gain={gain} "
            f"turns={metrics.get('turns')} ok={episode.get('ok')} verdict={verdict}"
        )

    if unreadable:
        print(f"post-generation: {unreadable} line(s) did not parse")
    return EXIT_OK
