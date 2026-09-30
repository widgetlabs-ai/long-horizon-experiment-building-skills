#!/usr/bin/env python3
"""Refuse a viewer that carries a measured number inside its own source.

The rule this enforces: **the scaffolding agent writes code, never values.**
Every figure the dashboard shows must be read from a file at request time. A
number typed into `experiment.py` renders exactly like a measured one and is
unfalsifiable by looking at the page — which is what makes it different from an
ordinary bug, and why it gets a check of its own.

Scope is the Python only (`app.py`, `lib.py`, `experiment.py`). The front end is not
scanned: it has no file access, so it can only draw what the API handed it, and
scanning chart geometry (`w = 640`, `font-size="10"`, `toFixed(5)`) is nothing
but false positives. The gap that leaves is real and written down in SKILL.md —
a value hardcoded into JS display text passes both this check and the endpoint
diff.

    python check_literals.py            # exit 0 clean, 1 with findings

WHAT COUNTS AS A MEASUREMENT. Not every digit is one, and a check that cries
wolf gets deleted, so the predicate is deliberately narrow:

  * any float literal (0.002, 1e-6) — the shape of a score, a mean, a tolerance
  * any integer >= 2 that is not in a structural position

Structural positions, allowed: slices and indices, `len(...) > n`, timeouts and
ports, HTTP status codes, digits inside a non-numeric string ("utf-8"), and
0 / 1 / -1 anywhere (counters, flags, empty returns). A string whose whole
contents are a number ("0.9942") is a finding, not a pass.

PROSE IS STRICTER. Digits inside an ordinary string are structure ("utf-8"),
except in prose: a note that says "5 tasks x 3 rollouts" goes stale the day the
run config changes, and reads exactly as true as it did before. So in
`experiment.py`, every string literal inside `notes()` (its docstring aside) and
every string under an extras block's "note" key is checked for a MEASURED
figure — a standalone numeral or a decimal ("3 rollouts", "0.75", "12"). A
digit that is part of a NAME, bound directly to a letter with nothing between
them ("macro-F1", "R2", "P95"), is not a figure and is allowed: a metric's
name is not something a note reads from a file at call time, there is nothing
to interpolate. A figure a note needs is read at call time and interpolated
into an f-string — the literal parts of that f-string are what is checked.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

FILES = ("app.py", "lib.py", "experiment.py")

# Removed from a line before what remains is searched for numbers.
STRUCTURAL = (
    r"#.*$",                                  # comment
    r"\[\s*-?\d+\s*:\s*-?\d*\s*\]",           # [8:], [-6000:]
    r"\[\s*:\s*-?\d+\s*\]",                   # [:12]
    r"\[\s*-?\d+\s*\]",                       # [0], parents[1]
    r"\blen\s*\([^()]*\)\s*[<>=!]=?\s*\d+",   # len(parts) >= 3
    r"\b(?:timeout|port)\s*=\s*\d+",          # timeout=10
    r"HTTPException\(\s*\d{3}",               # HTTPException(404, ...)
    r"\.\w+\(\s*-?\d+\s*(?:,\s*-?\d+\s*)?\)", # .slice(8), .round(1, 2)
    r"(?<![\w.])-?[01](?![\w.])",             # 0, 1, -1 anywhere
)

# A quoted string is structural unless the whole thing is a number.
STRING = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""")
NUMERIC_STRING = re.compile(r"^\s*-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?\s*$")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
DOCSTRING = re.compile(r'"""(?:.|\n)*?"""')


def _blank_strings(line: str) -> str:
    def repl(m: re.Match) -> str:
        return m.group(0) if NUMERIC_STRING.match(m.group(2)) else " "
    return STRING.sub(repl, line)


def findings(path: Path) -> list[tuple[int, str, str]]:
    source = path.read_text(encoding="utf-8")
    source = DOCSTRING.sub(lambda m: "\n" * m.group(0).count("\n"), source)
    out = []
    for n, line in enumerate(source.split("\n"), 1):
        rest = _blank_strings(line)
        for pattern in STRUCTURAL:
            rest = re.sub(pattern, " ", rest)
        for match in NUMBER.finditer(rest):
            out.append((n, match.group(0), line.strip()))
    return out


def _strings(node: ast.AST):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub


# A measured figure: a run of digits, optionally decimal. Whether it is a
# figure or part of a name is decided by what touches it, not by this pattern.
PROSE_NUMERAL = re.compile(r"\d+(?:\.\d+)?")


def _is_name_bound(text: str, start: int, end: int) -> bool:
    """True when a digit run sits directly after a letter -- a NAME, not a figure.

    "macro-F1", "R2" and "P95" all have the letter BEFORE the digits, with
    nothing between; a hyphen or a space there is enough to make it prose
    again, not a name. Only the preceding side counts. A letter directly
    AFTER the digits is a unit or multiplier suffix, not a name -- "10x
    faster" and "grew 2x" are exactly the kind of measured figure this check
    exists to catch, and they go stale the same way the docstring's own
    motivating example does ("5 tasks x 3 rollouts" after the run moved to
    one rollout per task). Checking only "before" also decides the one
    residual case a symmetric rule would have to special-case: "x2" reads as
    a multiplier in the same family as "2x", but its letter is on the
    allowed (preceding) side, so it is let through here too. That is a
    deliberate side effect of the simplest rule that covers every real name
    in this codebase, not a targeted exception -- see test_check_literals.py
    for the pinned behaviour on both "2x" and "x2".

    A hyphenated metric name -- "top-5", "BLEU-4" -- fails this check: the
    letter is on the allowed side but a hyphen sits between it and the digit,
    so it reads as a figure and is refused in note prose. That is the rule
    failing closed on an ambiguous case, not a bug, and it must not be
    special-cased away (a hyphen before a digit is exactly as often a real
    minus or a range as it is a name). Put a hyphenated metric's name in an
    extras block's "title" instead, which this check does not scan, rather
    than loosening the rule to let it through in a "note".
    """
    before = text[start - 1] if start > 0 else ""
    return before.isalpha()


def prose_findings(path: Path) -> list[tuple[int, str, str]]:
    """Digits in note prose: notes() bodies and extras blocks' "note" values."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "notes":
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                body = body[1:]                      # the docstring is not a note
            targets += body
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "note" and value is not None:
                    targets.append(value)
    out, seen = [], set()
    for target in targets:
        for const in _strings(target):
            figures = [m.group(0) for m in PROSE_NUMERAL.finditer(const.value)
                       if not _is_name_bound(const.value, m.start(), m.end())]
            if figures and id(const) not in seen:
                seen.add(id(const))
                out.append((const.lineno, figures[0], const.value.strip()[:80]))
    return out


def main() -> int:
    here = Path(__file__).resolve().parent
    bad = 0
    for name in FILES:
        path = here / name
        if not path.is_file():
            print(f"{name}: missing")
            return 1
        for line_no, number, line in findings(path):
            print(f"{name}:{line_no}: numeric literal {number!r} in  {line}")
            bad += 1
        if name == "experiment.py":
            for line_no, number, text in prose_findings(path):
                print(f"{name}:{line_no}: digit {number!r} in note prose  {text!r}")
                bad += 1
    if bad:
        print()
        print(f"{bad} numeric literal(s) outside the allowlist.")
        print("A viewer reads its numbers from files at request time. If one of these is")
        print("structure rather than a measurement, widen STRUCTURAL above — deliberately,")
        print("and never by exempting a whole file. A digit in note prose is never structure:")
        print("read the figure at call time and interpolate it.")
        return 1
    print(f"clean: no measured values in {', '.join(FILES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
