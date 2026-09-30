"""Reading files without lying about them.

Shared by `app.py` and `experiment.py`. Every rule here was bought with a real
failure; read the comments before simplifying any of them.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def read_json(path) -> dict:
    """A JSON file, or {} when it is missing or half-written.

    A missing file is a section that does not render, never an error: an
    experiment mid-run has not written everything yet, and a viewer that 500s
    on a file that does not exist yet is a viewer nobody opens during a run.
    """
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, json.JSONDecodeError):
        return {}


def read_jsonl_counted(path) -> tuple[list[dict], int]:
    """Records of a .jsonl file and how many lines did not parse.

    Split on "\\n" only, NEVER `splitlines()`. Agent transcripts and rule-table
    source carry U+2028 and other Unicode line breaks; JSON leaves them raw inside
    strings and `splitlines()` splits on them, tearing whole records into
    unparseable fragments. That bug presented as *every run reading as zero
    episodes* — a broken reader that looks exactly like a broken experiment.

    A line that still will not parse is counted, not lost and not raised: while
    a run is live the last line is usually a record being written right now.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0
    out, skipped = [], 0
    for line in raw.split("\n"):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
    return out, skipped


def read_jsonl(path) -> list[dict]:
    return read_jsonl_counted(path)[0]


def mtime(path) -> str:
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""


def count_lines(path) -> int:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def now() -> str:
    """Every response is stamped. A dashboard showing generation 7 during
    generation 8 is lying; one that says how old its reading is, is not."""
    return datetime.now().isoformat(timespec="seconds")


