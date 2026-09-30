"""Every endpoint answers 200 with the expected shape; exit 0 = PASS.

    python smoke.py                 # against http://localhost:8000
    python smoke.py --port 8723
    python smoke.py --watch 10      # poll /api/status and print what changed
    python smoke.py --port 8723 --fixtures fixtures
                                    # also: runs and candidates in mtimes.json order

Stdlib only, so it runs against a viewer whose venv you have not activated.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import touch_fixtures

ENDPOINTS = ("/", "/api/status", "/api/runs", "/api/state", "/api/history", "/api/logs")


def get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
    return body if path == "/" else json.loads(body)


def check_order(fixtures: Path, runs: list, candidates: list) -> list[str]:
    """Runs and candidates must come newest first in the order mtimes.json
    gives. Without this, fixtures served from a fresh clone pass every other
    check in whatever order the file system happens to list them."""
    try:
        times = touch_fixtures.load(fixtures)
    except (OSError, ValueError) as exc:
        return [f"{fixtures}/{touch_fixtures.FILE}: {exc}"]
    failures = []
    for name, items in (("runs", runs), ("candidates", candidates)):
        ids = [str(item.get("id")) for item in items]
        expected = touch_fixtures.expected_order(times, ids)
        if expected is None:
            missing = [i for i in ids if touch_fixtures.expected_order(times, [i]) is None]
            failures.append(f"{name} with no entry in {touch_fixtures.FILE}: {', '.join(missing)}")
        elif ids != expected:
            failures.append(f"{name} out of order (run touch_fixtures.py first?): got {ids}, want {expected}")
    return failures


def check(base: str, fixtures: Path | None = None) -> int:
    failures = []
    data = {}
    for path in ENDPOINTS:
        try:
            data[path] = get(base, path)
        except Exception as exc:
            failures.append(f"{path}: {exc}")
    if failures:
        for line in failures:
            print("FAIL", line)
        return 1

    status, runs, state = data["/api/status"], data["/api/runs"], data["/api/state"]
    for key in ("experiment", "generated_at", "state_dir", "outputs_dir", "runs", "log"):
        if key not in status:
            failures.append(f"/api/status missing {key}")
    for key in ("promotions", "candidates", "gate", "extras"):
        if key not in state:
            failures.append(f"/api/state missing {key}")
    # Every note must land in a slot the page has: a misspelled section name
    # would otherwise render nowhere, silently.
    notes = state.get("notes", {})
    if not isinstance(notes, dict):
        failures.append("/api/state notes is not a dict")
        notes = {}
    for section, note in notes.items():
        if f'id="note-{section}"' not in data["/"]:
            failures.append(f"note for unknown section {section!r} (the page has no note-{section})")
        if isinstance(note, dict):
            terms = note.get("terms") or []
            if not all(isinstance(t, list) and len(t) == 2 for t in terms):
                failures.append(f"note {section!r}: terms must be [[term, definition], ...]")
        elif note is not None and not isinstance(note, str):
            failures.append(f"note {section!r} is neither a string nor {{text, terms}}")
    # Same for a block's place: an unknown one would fall back to the top.
    for block in state.get("extras") or []:
        place = block.get("place", "top")
        if place != "top" and f'id="extras-{place}"' not in data["/"]:
            failures.append(f"extras block {block.get('title')!r}: unknown place {place!r}")
    if not isinstance(runs, list):
        failures.append("/api/runs is not a list")
    for run in runs if isinstance(runs, list) else []:
        for key in ("id", "n_rollouts", "n_ok", "n_failed", "n_unreadable", "rollouts"):
            if key not in run:
                failures.append(f"/api/runs[{run.get('id')}] missing {key}")
        break

    # One rollout's trace, when there is one: the drill-down is the part most
    # likely to be broken by a mapping that looks fine on the summary tables.
    for run in runs if isinstance(runs, list) else []:
        for rollout in run.get("rollouts") or []:
            try:
                trace = get(base, f"/api/runs/{run['id']}/rollouts/{rollout['id']}")
                if "nodes" not in trace:
                    failures.append("rollout trace has no nodes")
            except Exception as exc:
                failures.append(f"rollout trace: {exc}")
            break
        break

    if fixtures is not None and isinstance(runs, list):
        failures += check_order(fixtures, runs, state.get("candidates") or [])

    for line in failures:
        print("FAIL", line)
    if failures:
        return 1
    n_rollouts = sum(r.get("n_rollouts", 0) for r in runs)
    print(f"PASS — {len(runs)} run(s), {n_rollouts} rollout(s), "
          f"{len(state.get('promotions') or [])} promotion(s), "
          f"{len(state.get('extras') or [])} extra block(s), "
          f"{len(state.get('notes') or {})} note(s)")
    return 0


def watch(base: str, every: int) -> int:
    previous = None
    while True:
        try:
            status = get(base, "/api/status")
            now = (status["log"]["generation"], len(status.get("containers") or []),
                   sum(r["rollouts"] for r in status["runs"]))
            if now != previous:
                print(time.strftime("%H:%M:%S"), "generation", now[0],
                      "containers", now[1], "rollouts", now[2])
                previous = now
        except Exception as exc:
            print(time.strftime("%H:%M:%S"), "error", exc)
        time.sleep(every)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--watch", type=int, metavar="SECONDS")
    parser.add_argument("--fixtures", type=Path, metavar="DIR",
                        help="the fixtures dir the server reads; checks the order mtimes.json gives")
    args = parser.parse_args()
    base = f"http://{args.host}:{args.port}"
    if args.watch:
        return watch(base, args.watch)
    return check(base, args.fixtures)


if __name__ == "__main__":
    sys.exit(main())
