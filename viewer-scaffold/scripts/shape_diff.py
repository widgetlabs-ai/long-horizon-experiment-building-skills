#!/usr/bin/env python3
"""Compare the shape of two experiment roots — the files under state/ and
outputs/, and the key/type tree of every JSON and JSONL file in them.

    python3 scripts/shape_diff.py LEFT RIGHT [--rules FILE] [--subset]

Values are never compared, only shape: which files exist (ids and run names
normalised), which keys each object has, and which JSON types each key holds
(int and float are one type, "number"; null is its own). `--subset` ignores
files only RIGHT has — for comparing a small generated root with a real one.

Rules file, one per line, `#` starts a comment:

    map    <file-glob> <json-path>             keys at that path are data (category names): compare as one key "*"
    ignore <file-glob> <path-glob>  # reason   drop matching differences; the reason is required

`[]` in a rule's path is literal ("array item"), not an fnmatch set.

Exit 0 = same shape, 1 = differences (printed), 2 = bad arguments or rules.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

TOP = ("state", "outputs")
HEX = re.compile(r"[0-9a-f]{8,}")


@dataclass
class Rules:
    maps: list[tuple[str, str]] = field(default_factory=list)
    ignores: list[tuple[str, str]] = field(default_factory=list)

    def is_map(self, file: str, path: str) -> bool:
        return any(fnmatch.fnmatch(file, f) and path == p for f, p in self.maps)

    def ignored(self, file: str, path: str) -> bool:
        return any(fnmatch.fnmatch(file, f) and fnmatch.fnmatch(path, p) for f, p in self.ignores)


def load_rules(text: str) -> Rules:
    rules = Rules()
    for n, raw in enumerate(text.splitlines(), 1):
        line, _, reason = raw.partition("#")
        parts = line.split()
        if not parts:
            continue
        if len(parts) != 3 or parts[0] not in ("map", "ignore"):
            raise ValueError(f"rules line {n}: expected `map|ignore <file-glob> <path>`: {raw!r}")
        if parts[0] == "ignore" and not reason.strip():
            raise ValueError(f"rules line {n}: an ignore needs a `# reason`: {raw!r}")
        if parts[0] == "map":
            rules.maps.append((parts[1], parts[2]))
        else:
            rules.ignores.append((parts[1], _literal_brackets(parts[2])))
    return rules


def _literal_brackets(glob: str) -> str:
    """`[]` in a JSON path means "array item", but fnmatch reads `[...]` as a
    character set, so `t[].n[].y` would silently match nothing. Make every `[]`
    literal; an already-escaped `[[]]` is left as it is."""
    return glob.replace("[[]]", "\0").replace("[]", "[[]]").replace("\0", "[[]]")


def normalize(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "outputs" and len(parts) > 2:
        parts[1] = "<run>"
    return "/".join(HEX.sub("<id>", p) for p in parts)


def _node() -> dict:
    return {"types": set(), "keys": {}, "item": None}


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _absorb(node: dict, value, file: str, path: str, rules: Rules) -> None:
    if value is None:
        node["types"].add("null")
    elif isinstance(value, bool):
        node["types"].add("bool")
    elif isinstance(value, (int, float)):
        node["types"].add("number")
    elif isinstance(value, str):
        node["types"].add("str")
    elif isinstance(value, list):
        node["types"].add("array")
        node["item"] = node["item"] or _node()
        for v in value:
            _absorb(node["item"], v, file, path + "[]", rules)
    elif isinstance(value, dict):
        node["types"].add("object")
        as_map = rules.is_map(file, path)
        for k, v in value.items():
            key = "*" if as_map else str(k)
            _absorb(node["keys"].setdefault(key, _node()), v, file, _join(path, key), rules)


def _files(base: Path) -> list[Path]:
    """Every file under base, following symlinked directories (a real root is
    compared through links to its state/ and outputs/)."""
    return sorted(Path(d, f) for d, _, fs in os.walk(base, followlinks=True) for f in fs)


def shape_of(root: Path, rules: Rules, only: set[str] | None = None) -> dict[str, dict]:
    shapes: dict[str, dict] = {}
    for top in TOP:
        base = root / top
        if not base.is_dir():
            continue
        for p in _files(base):
            file = normalize(p.relative_to(root).as_posix())
            if only is not None and file not in only:
                continue
            node = shapes.setdefault(file, _node())
            try:
                text = p.read_text(encoding="utf-8")
                if p.suffix == ".json":
                    _absorb(node, json.loads(text), file, "", rules)
                elif p.suffix == ".jsonl":
                    for line in text.split("\n"):
                        if line.strip():
                            _absorb(node, json.loads(line), file, "", rules)
                else:
                    node["types"].add("file")
            except (UnicodeDecodeError, json.JSONDecodeError):
                node["types"].add("file" if p.suffix not in (".json", ".jsonl") else "unparseable")
    return shapes


def _types(s: set[str]) -> str:
    return "{" + ", ".join(sorted(s)) + "}"


def _walk(a: dict, b: dict, file: str, path: str, rules: Rules, out: list[str]) -> None:
    if not a["types"] or not b["types"]:
        return  # items of an array that was empty every time on one side: nothing observed to compare
    where = f"{file}::{path or '<root>'}"
    if a["types"] != b["types"] and not rules.ignored(file, path):
        out.append(f"{where}: types left {_types(a['types'])} right {_types(b['types'])}")
    for key in sorted(set(a["keys"]) | set(b["keys"])):
        sub = _join(path, key)
        if key not in b["keys"]:
            if not rules.ignored(file, sub):
                out.append(f"{file}::{sub}: only in left")
        elif key not in a["keys"]:
            if not rules.ignored(file, sub):
                out.append(f"{file}::{sub}: only in right")
        else:
            _walk(a["keys"][key], b["keys"][key], file, sub, rules, out)
    if a["item"] and b["item"]:
        _walk(a["item"], b["item"], file, path + "[]", rules, out)


def diff(left: dict, right: dict, rules: Rules, subset: bool = False) -> list[str]:
    out: list[str] = []
    for file in sorted(set(left) | set(right)):
        if file not in right:
            if not rules.ignored(file, ""):
                out.append(f"{file}: only in left")
        elif file not in left:
            if not subset and not rules.ignored(file, ""):
                out.append(f"{file}: only in right")
        else:
            _walk(left[file], right[file], file, "", rules, out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("left", type=Path)
    ap.add_argument("right", type=Path)
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--subset", action="store_true", help="ignore files only RIGHT has")
    args = ap.parse_args(argv)
    try:
        rules = load_rules(args.rules.read_text() if args.rules else "")
    except (OSError, ValueError) as e:
        print(f"shape_diff: {e}", file=sys.stderr)
        return 2
    left = shape_of(args.left, rules)
    right = shape_of(args.right, rules, only=set(left) if args.subset else None)
    out = diff(left, right, rules, subset=args.subset)
    for line in out:
        print(line)
    print(f"shape_diff: {len(out)} difference(s)" if out else f"shape_diff: same shape ({len(left)} files)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
