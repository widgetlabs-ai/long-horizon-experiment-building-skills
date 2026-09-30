#!/usr/bin/env python3
"""Does the code-first method match reality? B for synthetic_search vs a real run.

    python3 test/fixtures_vs_real.py [--reference DIR]

Runs two things and compares their shape:

  B  test/synthetic_generator.py -- the experiment's real writers with the
     measuring layer mocked. This is what a scaffolder can build without ever
     running the search, and what `reference/generator.md` prescribes.

  R  examples/synthetic_search/tools/reference_run.py -- the same writers with
     only the AGENT scripted. The scorer, the CLI, promote, the gate and adopt
     all run for real.

A difference here is a flaw in the METHOD, not in a viewer: the code, run with
the measurement mocked, did not produce what the code produces when the
measurement is real. Fix the generator's mock layer, or declare the difference
in synthetic_shape_rules.txt with its reason.

Needs the orchestrator extra: `uv sync --extra orchestrator` in
examples/synthetic_search.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SKILLS_ROOT = SKILL.parent
EXPERIMENT = SKILLS_ROOT / "examples" / "synthetic_search"
sys.path.insert(0, str(SKILL / "scripts"))
import shape_diff  # noqa: E402

# A floor, not a nicety. shape_diff runs with subset=True, so a generator that
# writes nothing produces an empty diff and the run reports PASS over a hole.
# The real B writes a corpus manifest, an instrument pin, three baselines,
# promotions, a gate report, candidates and one traces file per generation.
MIN_FILES = 8


class TooFewFiles(RuntimeError):
    """The comparison had too little to compare to mean anything."""


def check_floor(left: dict) -> None:
    if len(left) < MIN_FILES:
        raise TooFewFiles(
            f"only {len(left)} file(s) to compare, need at least {MIN_FILES}: "
            "the generator wrote almost nothing and a clean diff would prove nothing"
        )


def _python() -> str:
    venv = EXPERIMENT / ".venv" / "bin" / "python"
    if not venv.is_file():
        raise SystemExit(
            f"no interpreter at {venv} — run `uv sync --extra orchestrator` in {EXPERIMENT} first"
        )
    return str(venv)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", type=Path, default=None,
                    help="an existing reference root; default: generate one")
    args = ap.parse_args(argv)

    python = _python()
    with tempfile.TemporaryDirectory() as tmp:
        b = Path(tmp) / "b"
        gen = subprocess.run([python, str(HERE / "synthetic_generator.py"), "--out", str(b)],
                             capture_output=True, text=True)
        if gen.returncode != 0:
            print(gen.stdout, gen.stderr, sep="\n")
            print("FAIL: generator did not run")
            return 1

        reference = args.reference
        if reference is None:
            reference = Path(tmp) / "r"
            ref = subprocess.run([python, str(EXPERIMENT / "tools" / "reference_run.py"),
                                  "--out", str(reference)], capture_output=True, text=True)
            if ref.returncode != 0:
                print(ref.stdout, ref.stderr, sep="\n")
                print("FAIL: reference run did not run")
                return 1

        rules = shape_diff.load_rules((HERE / "synthetic_shape_rules.txt").read_text())
        left = shape_diff.shape_of(b, rules)
        try:
            check_floor(left)
        except TooFewFiles as exc:
            print(f"FAIL: {exc}")
            return 1
        right = shape_diff.shape_of(reference, rules, only=set(left))
        out = shape_diff.diff(left, right, rules, subset=True)

    for line in out:
        print(line)
    print(f"FAIL: {len(out)} undeclared difference(s)" if out else f"PASS ({len(left)} files compared)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
