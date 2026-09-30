"""Give the fixture files the modification times listed in fixtures/mtimes.json.

    python3 touch_fixtures.py               # fixtures/ next to this file
    python3 touch_fixtures.py path/to/fixtures

The viewer orders runs and candidates by the mtime of files the experiment's
writers create. Git does not store mtimes and `cp` does not keep them, so after
a clone every fixture file has the same one and the order is whatever the file
system lists first. `mtimes.json` records the order the fixtures stand for:

    {"outputs/<run>": "2026-01-01T10:00:00", "state/candidates/<id>/candidate.json": "..."}

Paths are relative to the fixtures directory. Times must be distinct. Run this
before serving the fixtures. It changes only mtimes, and only under fixtures/.
Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

FILE = "mtimes.json"


def load(fixtures: Path) -> dict[str, float]:
    """Path (relative to fixtures) -> epoch seconds. Raises on a bad file."""
    raw = json.loads((fixtures / FILE).read_text())
    times = {path: datetime.fromisoformat(stamp).timestamp() for path, stamp in raw.items()}
    seen: dict[float, str] = {}
    for path, t in times.items():
        if t in seen:
            raise ValueError(f"{FILE}: {path} and {seen[t]} have the same time; the order would be arbitrary")
        seen[t] = path
    return times


def touch(fixtures: Path) -> int:
    times = load(fixtures)
    missing = [p for p in times if not (fixtures / p).exists()]
    if missing:
        raise FileNotFoundError(f"{FILE} lists paths that do not exist: {', '.join(missing)}")
    # Deepest first: a directory's mtime is set after anything inside it.
    for path in sorted(times, key=lambda p: -len(Path(p).parts)):
        os.utime(fixtures / path, (times[path], times[path]))
    return len(times)


def expected_order(times: dict[str, float], ids: list[str]) -> list[str] | None:
    """The ids newest first by the latest entry with a path component that is
    the id or starts with it (the spine's ids are often shortened), or None
    when some id has no entry at all."""
    latest: dict[str, float] = {}
    for path, t in times.items():
        for part in Path(path).parts:
            for i in ids:
                if i and part.startswith(i):
                    latest[i] = max(t, latest.get(i, t))
    if any(i not in latest for i in ids):
        return None
    return sorted(ids, key=lambda i: latest[i], reverse=True)


def main() -> int:
    fixtures = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "fixtures"
    try:
        n = touch(fixtures)
    except (OSError, ValueError) as exc:
        print("FAIL", exc)
        return 1
    print(f"touched {n} path(s) under {fixtures}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
