"""The val gate: the one thing in the loop that can say no.

`promote` chose on train, which is the split the rewards already used. The gate
re-scores that same artifact on a split nothing in the loop has fitted, per
category rather than on the mean, and a failure discards the candidate outright
— re-gating it could only fail again.

The report records the artifact it judged. A verdict nobody can tie back to a
tree is a verdict nobody can check.
"""

from __future__ import annotations

import json
from pathlib import Path

from synthetic_search.substrate import measure, promote
from synthetic_search.substrate.errors import EXIT_LOST, EXIT_OK, SubstrateError


def gate(state: Path) -> int:
    state = Path(state)
    pending_path = state / "pending.json"
    if not pending_path.is_file():
        print("gate: nothing pending")
        return EXIT_LOST

    pending = json.loads(pending_path.read_text())
    staged = state / "staged" / "rules.py"
    if not staged.is_file():
        raise SubstrateError(f"pending.json exists but the staged artifact does not: {staged}")

    source = staged.read_text()
    baseline = json.loads((state / "baseline_val.json").read_text())
    report = measure.measure_source(source, "val", state)

    failures: list[str] = []
    exempt: list[str] = []
    per_category = {}

    if report["reward"] is None:
        failures.append(f"the staged artifact did not measure on val: {report['error']}")
    elif report["reward"] < baseline["reward"]:
        failures.append(f"val mean fell: {baseline['reward']} -> {report['reward']}")

    for name, base_stats in baseline["per_category"].items():
        after = report["per_category"].get(name, {})
        support = base_stats.get("support", 0)
        entry = {"before": base_stats.get("f1"), "after": after.get("f1"), "support": support}
        if support < promote.MIN_GATE_SUPPORT:
            entry["exempt"] = True
            exempt.append(name)
            print(f"gate: {name} is exempt — support {support} < {promote.MIN_GATE_SUPPORT}")
        elif base_stats.get("f1") is not None:
            tolerance = promote.category_tolerance(base_stats["f1"])
            after_f1 = after.get("f1")
            if after_f1 is None or base_stats["f1"] - after_f1 > tolerance:
                failures.append(f"{name} dropped {base_stats['f1']} -> {after_f1} (tolerance {tolerance})")
        per_category[name] = entry

    verdict = "passed" if not failures else "failed"
    gate_report = {
        "verdict": verdict,
        "trace": pending.get("trace"),
        "artifact_digest": measure.artifact_mod.digest(source),
        "val_reward": report["reward"],
        "baseline_val_reward": baseline["reward"],
        "per_category": per_category,
        "exempt": exempt,
        "failures": failures,
    }
    (state / "gate_report.json").write_text(json.dumps(gate_report, indent=2, sort_keys=True) + "\n")

    if failures:
        for line in failures:
            print(f"gate: {line}")
        promote.discard_pending(state)
        print("gate: failed — the staged candidate is discarded")
        return EXIT_LOST

    pending["gate_passed"] = True
    pending_path.write_text(json.dumps(pending, indent=2, sort_keys=True) + "\n")
    print(f"gate: passed (val {report['reward']} vs baseline {baseline['reward']})")
    return EXIT_OK
