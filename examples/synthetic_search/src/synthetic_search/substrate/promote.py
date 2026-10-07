"""Choosing a winner on train, and adopting one the gate has passed.

The framework has no notion of "this edit helped the category it was aimed at
and broke another one". That judgement is this module's, and it is deliberately
made on **train** — the same split the rewards used. Selecting on validation
would spend the only split that can still say no.

Two verdicts matter more than the ranking: `artifact_unchanged`, which is what
a rollout that spent its whole budget on analysis returns, and
`regresses_a_category`, which is the trade the mean is happy to hide.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from synthetic_search.substrate import evaluate, measure
from synthetic_search.substrate.errors import EXIT_LOST, EXIT_OK, SubstrateError

ARTIFACT_ENV = "SYNTH_ARTIFACT"
ARTIFACT_RELATIVE = "artifact/rules.py"

# What a candidate may take off any one category while still counting as a win.
CATEGORY_TOLERANCE = 0.002

# Below this much support in a split, a per-category gate is a coin flip dressed
# as a criterion: one row moves recall further than the tolerance. Such a
# category is exempt, and the exemption prints its support so the decision can
# be rechecked against the data rather than taken on trust.
MIN_GATE_SUPPORT = 5


def resolve_artifact_path() -> Path:
    raw = os.environ.get(ARTIFACT_ENV)
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[3] / ARTIFACT_RELATIVE


def category_tolerance(baseline_f1: float | None) -> float:
    """Zero for a category that is already perfect, `CATEGORY_TOLERANCE` otherwise.

    A perfect category has no defects left to trade, so any drop is one the
    candidate introduced. Allowing it a few thousandths per generation is how
    "every category works" decays into "every category nearly works".
    """
    if baseline_f1 is None:
        return CATEGORY_TOLERANCE
    if baseline_f1 >= 1.0:
        return 0.0
    return CATEGORY_TOLERANCE


def _baseline(state: Path, split: str) -> dict:
    path = state / f"baseline_{split}.json"
    if not path.is_file():
        raise SubstrateError(f"no baseline for {split!r}: run `cli baseline --split all`")
    return json.loads(path.read_text())


def write_baseline(state: Path, split: str, report: dict) -> None:
    (state / f"baseline_{split}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def read_promotions(state: Path) -> list[dict]:
    """Every adopted winner, oldest first.

    Split on "\\n" only: `splitlines()` also splits on U+2028, which JSON leaves
    raw inside strings and agent transcripts are full of. That difference once
    made a whole run read as zero episodes.
    """
    path = Path(state) / "promotions.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().split("\n") if line.strip()]


def regressions(before: dict, after: dict) -> list[str]:
    """Categories that dropped by more than their tolerance."""
    hurt = []
    for name, base_stats in before.items():
        base = base_stats.get("f1")
        new = after.get(name, {}).get("f1")
        if base is None:
            continue
        if new is None or base - new > category_tolerance(base):
            hurt.append(name)
    return hurt


RANKED_FILENAME = "ranked.json"


def read_ranked(state: Path) -> dict:
    """Every candidate already ranked, keyed by trace.

    Transient state under `state/*` (like `pending.json`): it remembers what a
    previous generation ranked, so a candidate the gate discarded is not
    re-measured — and, more importantly, not re-staged — later. A file that
    cannot be read is treated as empty: losing the memory re-measures, it never
    fails the loop.
    """
    path = Path(state) / RANKED_FILENAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def write_ranked(state: Path, ranked: dict) -> None:
    (Path(state) / RANKED_FILENAME).write_text(json.dumps(ranked, indent=2, sort_keys=True) + "\n")


def rank(state: Path) -> list[dict]:
    """Every candidate, scored on train, best first, each with its verdict.

    A candidate is measured at most once: one already in `ranked.json` is
    served from that record without being measured again. Recording the ranking
    is `promote`'s job, so a caller that only wants verdicts — a test, the
    viewer — never marks a candidate as seen.
    """
    state = Path(state)
    baseline = _baseline(state, "train")
    current_source = resolve_artifact_path().read_text() if resolve_artifact_path().is_file() else ""
    candidates_dir = state / "candidates"
    ranked = read_ranked(state)
    results: list[dict] = []

    for directory in sorted(candidates_dir.iterdir()) if candidates_dir.is_dir() else []:
        if directory.name in ranked:
            results.append(ranked[directory.name])
            continue

        source_path = directory / "rules.py"
        if not source_path.is_file():
            results.append({"trace": directory.name, "reward": None, "gain": None, "verdict": "no_artifact"})
            continue

        source = source_path.read_text()
        if source == current_source:
            results.append({"trace": directory.name, "reward": None, "gain": None, "verdict": "artifact_unchanged"})
            continue

        report = measure.measure_source(source, "train", state)
        entry = {
            "trace": directory.name,
            "reward": report["reward"],
            "gain": evaluate.gain(report["reward"], baseline["reward"]),
            "per_category": report["per_category"],
            "source": str(source_path),
        }
        if report["guard_rejected"]:
            entry["verdict"] = "guard_rejected"
        elif report["validity_failed"]:
            entry["verdict"] = "validity_failed"
            entry["violations"] = report["violations"]
        elif report["score_error"]:
            entry["verdict"] = "score_error"
        elif entry["gain"] is None or entry["gain"] <= 0:
            entry["verdict"] = "no_gain"
        elif regressions(baseline["per_category"], report["per_category"]):
            entry["verdict"] = "regresses_a_category"
            entry["regressed"] = regressions(baseline["per_category"], report["per_category"])
        else:
            entry["verdict"] = "eligible"
        results.append(entry)

    results.sort(key=lambda e: (e["verdict"] != "eligible", -(e["gain"] or 0.0)))
    return results


def promote(state: Path) -> int:
    """Stage the best eligible candidate. Exit 1 when there is none.

    Candidates already ranked by an earlier generation are skipped, so a
    candidate the gate discarded is not re-staged — and does not keep blocking
    the candidates the next generation produced.
    """
    state = Path(state)
    seen = set(read_ranked(state))
    ranked = rank(state)
    write_ranked(state, {entry["trace"]: entry for entry in ranked})

    for entry in ranked:
        print(f"{entry['trace']}: {entry['verdict']} reward={entry['reward']} gain={entry['gain']}")

    eligible = [e for e in ranked if e["verdict"] == "eligible" and e["trace"] not in seen]
    if not eligible:
        print("promote: nothing eligible this generation")
        return EXIT_LOST

    winner = eligible[0]
    staged = state / "staged"
    staged.mkdir(parents=True, exist_ok=True)
    source = Path(winner["source"]).read_text()
    (staged / "rules.py").write_text(source)

    pending = {
        "trace": winner["trace"],
        "train_reward": winner["reward"],
        "gain": winner["gain"],
        "artifact_digest": measure.artifact_mod.digest(source),
        "gate_passed": False,
    }
    (state / "pending.json").write_text(json.dumps(pending, indent=2, sort_keys=True) + "\n")
    print(f"promote: staged {winner['trace']} (train {winner['reward']}, gain {winner['gain']})")
    return EXIT_OK


def _generation(state: Path) -> int:
    path = state / "generation"
    if path.is_file():
        return int(path.read_text().strip())
    promotions = read_promotions(state)
    return max((p.get("generation", -1) for p in promotions), default=-1) + 1


def adopt(state: Path) -> int:
    """Replace the artifact with a gated winner and rewrite the baselines."""
    state = Path(state)
    pending_path = state / "pending.json"
    if not pending_path.is_file():
        print("adopt: nothing pending")
        return EXIT_LOST

    pending = json.loads(pending_path.read_text())
    if not pending.get("gate_passed"):
        print("adopt: refusing a candidate the gate has not passed")
        return EXIT_LOST

    source = (state / "staged" / "rules.py").read_text()
    artifact_path = resolve_artifact_path()
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(source)

    rewritten = {}
    for split in ("train", "val"):
        report = measure.measure_source(source, split, state)
        write_baseline(state, split, report)
        rewritten[split] = report["reward"]

    record = {
        **pending,
        "generation": _generation(state),
        "val_reward": rewritten["val"],
        "adopted_train_reward": rewritten["train"],
    }
    with (state / "promotions.jsonl").open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")

    pending_path.unlink()
    shutil.rmtree(state / "staged", ignore_errors=True)
    print(f"adopt: {record['trace']} adopted (train {rewritten['train']}, val {rewritten['val']})")
    return EXIT_OK


def discard_pending(state: Path) -> None:
    """Throw away the staged candidate and its pending record.

    Shared by every stage that can refuse after `promote`, so a refusal cannot
    leave behind a `gate_passed` record that a hand-run `adopt` would honour.
    """
    state = Path(state)
    (state / "pending.json").unlink(missing_ok=True)
    shutil.rmtree(state / "staged", ignore_errors=True)
