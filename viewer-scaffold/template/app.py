"""Long-horizon search viewer — the skeleton.

This file is generic across experiments and is NOT the file you edit when
scaffolding a viewer. Everything experiment-specific lives in `experiment.py`,
which this module imports and calls. If you find yourself adding a category, a
class, a corpus or any other domain noun here, it belongs there instead.

Run from the generated viewer directory:

    uv run uvicorn app:app --port 8000

Paths come from `experiment.py`; nothing is configured by environment here
except the port, which is uvicorn's.

Stateless: every request re-reads files from disk. Read-only: it never runs
eval, promote, gate or adopt, and never writes anything.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import experiment
from lib import count_lines, mtime, now, read_json, read_jsonl, read_jsonl_counted  # noqa: F401

HERE = Path(__file__).resolve().parent

if not Path(experiment.STATE_DIR).is_dir():
    raise SystemExit(f"state dir {experiment.STATE_DIR} is not a directory")

app = FastAPI(title=f"{experiment.NAME}-viewer")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


# --------------------------------------------------------------- live probes

def containers() -> list[dict] | None:
    """Containers running this experiment's image; None when docker is
    unavailable or the experiment declares no image (the UI then says so
    rather than drawing an empty, reassuring zero)."""
    image = getattr(experiment, "DOCKER_IMAGE", None)
    if not image:
        return None
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", f"ancestor={image}",
             "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0:
        return None
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            rows.append({"id": parts[0][:12], "name": parts[1], "status": parts[2]})
    return rows


def processes() -> list[str] | None:
    pattern = getattr(experiment, "PROCESS_PATTERN", None)
    if not pattern:
        return None
    try:
        out = subprocess.run(["pgrep", "-af", pattern],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if out.returncode == 1:
        return []
    if out.returncode != 0:
        return None
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def log_files() -> list[Path]:
    globs = getattr(experiment, "LOG_GLOB", None)
    if not globs:
        return []
    paths = [p for p in Path(globs[0]).glob(globs[1]) if p.is_file()]
    return sorted(paths, key=lambda p: p.stat().st_mtime)


def generation_from_log(text: str) -> int | None:
    pattern = getattr(experiment, "GENERATION_RE", None)
    if not pattern:
        return None
    found = [int(m) for m in re.findall(pattern, text, re.M)]
    return max(found) if found else None


# ------------------------------------------------------------------- spine

def run_state(n_rollouts: int, unreadable: int, newest: bool, live: list[str] | None) -> str | None:
    """"running" for the newest run while the search process is up; "died" for a
    run that wrote no episode and never will — any older run, or the newest once
    nothing is running. None otherwise, and None when liveness is unknown: an eval
    still starting also has no episodes, and it must not be called dead."""
    if newest and live:
        return "running"
    if n_rollouts or unreadable:
        return None
    if not newest or live == []:
        return "died"
    return None


def run_summary(run_id: str, newest: bool = False, live: list[str] | None = None) -> dict:
    rollouts, unreadable = experiment.rollouts(run_id)
    return {
        "id": run_id,
        "n_rollouts": len(rollouts),
        "n_ok": sum(1 for r in rollouts if r.get("ok")),
        "n_failed": sum(1 for r in rollouts if not r.get("ok")),
        "n_unreadable": unreadable,
        "state": run_state(len(rollouts), unreadable, newest, live),
        "mtime": experiment.run_mtime(run_id),
        "rollouts": rollouts,
        "error_counts": error_counts(rollouts),
    }


def error_counts(rollouts: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rollouts:
        for err in r.get("errors") or []:
            key = str(err).split(":")[0][:60]
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------- endpoints

@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/status")
def api_status():
    logs = log_files()
    newest = logs[-1] if logs else None
    tail, generation = "", None
    if newest:
        try:
            text = newest.read_text(encoding="utf-8", errors="replace")
            tail = text[-6000:]
            generation = generation_from_log(text)
        except OSError:
            pass
    return {
        "experiment": experiment.NAME,
        "generated_at": now(),
        "state_dir": str(experiment.STATE_DIR),
        "outputs_dir": str(experiment.OUTPUTS_DIR),
        "containers": containers(),
        "processes": processes(),
        "runs": [
            {"id": r, "rollouts": experiment.run_rollout_count(r), "mtime": experiment.run_mtime(r)}
            for r in experiment.runs()
        ],
        "log": {"file": newest.name if newest else None, "generation": generation, "tail": tail},
    }


@app.get("/api/runs")
def api_runs():
    live = processes()
    return [run_summary(r, i == 0, live) for i, r in enumerate(experiment.runs())]


@app.get("/api/runs/{run_id}/rollouts/{rollout_id}")
def api_rollout(run_id: str, rollout_id: str):
    trace = experiment.rollout_trace(run_id, rollout_id)
    if trace is None:
        raise HTTPException(404, "rollout not found")
    return trace


@app.get("/api/history")
def api_history():
    return {"generated_at": now(), "promotions": experiment.promotions()}


@app.get("/api/state")
def api_state():
    return {
        "generated_at": now(),
        "promotions": experiment.promotions(),
        "gate": experiment.gate(),
        "candidates": experiment.candidates(),
        "extras": experiment.extras(),
        "reviews": _optional("reviews", []),
        "notes": _optional("notes", {}),
    }


def _optional(name: str, default):
    # A spine function added after a viewer was generated is optional: a viewer
    # generated before it existed simply has none, and keeps working.
    fn = getattr(experiment, name, None)
    return fn() if fn else default


@app.get("/api/logs")
def api_logs():
    return {
        "files": [
            {"name": p.name, "size": p.stat().st_size, "mtime": mtime(p)}
            for p in log_files()
        ]
    }


@app.get("/api/logs/{name}")
def api_log(name: str):
    if "/" in name or ".." in name:
        raise HTTPException(404, "bad name")
    match = [p for p in log_files() if p.name == name]
    if not match:
        raise HTTPException(404, "log not found")
    try:
        return {"name": name, "content": match[0].read_text(encoding="utf-8", errors="replace")[-100000:]}
    except OSError as exc:
        raise HTTPException(500, str(exc))
