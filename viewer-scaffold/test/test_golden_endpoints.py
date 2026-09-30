"""The template must keep rendering the shape we signed off.

This is a drift guard, not an independence check. Its source of truth is the
template itself, so it cannot catch the template baking in an assumption -- it
catches the template CHANGING. Regenerate deliberately with --update and read
the diff.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILLS_ROOT = HERE.parents[1]
VIEWER = SKILLS_ROOT / "examples" / "synthetic_search" / "viewer"
FIXTURES = VIEWER / "fixtures"
GOLDEN = HERE / "golden" / "synthetic_endpoints.json"

# /api/status keys dropped outright rather than kept and normalised. They are
# properties of the machine or of wall-clock time, not of the viewer, so a
# snapshot that kept them would pass here and fail in every clone. See
# `_normalize` for the reasoning behind each one, and for the two fields
# (`state_dir`, `outputs_dir`) that are transformed instead of dropped.
VOLATILE = ("generated_at", "containers", "processes", "log")


def _normalize(out: dict) -> dict:
    """Strip or reduce whatever in a capture varies by host or by clock.

    Every field touched here, and why:

    - `generated_at` -- `now()` at request time (app.py:151, 191, 196), on
      `/api/status`, `/api/history` and `/api/state`. Dropped everywhere it
      appears, or the snapshot differs on every single run.
    - `/api/status["containers"]`, `["processes"]` -- live probes of the
      host's docker daemon and process table (app.py:47-84). Not a property
      of the viewer or the fixtures; dropped.
    - `/api/status["log"]` -- the tail of whichever fixture log file happens
      to be newest plus a generation number parsed out of it (app.py:159-166).
      Also a live-ish read of file content rather than a stable shape;
      dropped as a whole rather than picked apart.
    - `/api/status["state_dir"]`, `["outputs_dir"]` -- absolute paths
      (app.py:153-154) that encode where this checkout happens to sit on
      disk. Reduced to a path relative to the viewer directory instead of
      dropped outright, so a real regression -- e.g. state and outputs
      suddenly resolving to the same directory -- still shows up in the
      diff.
    - Each run summary's `state` in `/api/runs` -- derived from
      `processes()` (app.py:105-117, 126), so it depends on whether a
      process matching the experiment's pattern happens to be alive on the
      machine running the test right now. Dropped from every run summary.

    `/api/status["runs"]` (each entry's `mtime`) and each run summary's own
    `mtime` in `/api/runs` are KEPT: `touch_fixtures.py` makes them
    deterministic, and pinning them is what the mtime-ordering test is for.
    """
    out = copy.deepcopy(out)

    status = out["/api/status"]
    status.pop("generated_at", None)
    status.pop("containers", None)
    status.pop("processes", None)
    status.pop("log", None)
    status["state_dir"] = Path(status["state_dir"]).relative_to(VIEWER.resolve()).as_posix()
    status["outputs_dir"] = Path(status["outputs_dir"]).relative_to(VIEWER.resolve()).as_posix()

    for run in out["/api/runs"]:
        run.pop("state", None)

    out["/api/history"].pop("generated_at", None)
    out["/api/state"].pop("generated_at", None)

    return out


def _testclient_unavailable_reason() -> str | None:
    """None when `fastapi.testclient.TestClient` can be imported here; otherwise why not.

    Two distinct ways this fails, both against THIS interpreter, not the viewer's
    own: `fastapi` may simply not be installed (a fresh checkout's stock
    interpreter has nothing beyond the standard library), or `fastapi` may be
    present while `starlette.testclient` still refuses to import because no
    httpx-family client is installed -- `fastapi`/`starlette` do not pull one in
    themselves. This tree does not otherwise depend on fastapi or an httpx
    client anywhere outside this one test; only the generated viewer's own
    `pyproject.toml` declares one (as a dev dependency), for exactly this case.
    """
    if importlib.util.find_spec("fastapi") is None:
        return "fastapi is not installed"
    try:
        import fastapi.testclient  # noqa: F401
    except (ImportError, RuntimeError) as exc:
        return f"fastapi.testclient could not be imported: {exc}"
    return None


# Named so the skip message can tell a stranger exactly what to run -- the
# viewer's environment lives one level down and is synced independently of
# whatever installed this test's own interpreter.
_SYNC_HINT = (
    "the viewer has its own environment, separate from this test's interpreter: "
    f"run `cd {VIEWER} && uv sync`, then re-run this suite with that interpreter, "
    f"e.g. `cd {VIEWER} && uv run python3 -m unittest discover -s {HERE} "
    "-p 'test_golden_endpoints.py'`"
)


def capture() -> dict:
    """Every stable endpoint, as parsed JSON, against the committed fixtures."""
    sys.path.insert(0, str(VIEWER))
    os.environ["VIEWER_EXPERIMENT_ROOT"] = "fixtures"
    for name in ("app", "experiment", "lib"):
        sys.modules.pop(name, None)
    from fastapi.testclient import TestClient  # noqa: E402

    import app as viewer_app  # noqa: E402

    client = TestClient(viewer_app.app)
    out: dict = {}
    out["/api/status"] = client.get("/api/status").json()
    # /api/runs returns a LIST of run summaries, not an object wrapping one.
    out["/api/runs"] = client.get("/api/runs").json()
    out["/api/history"] = client.get("/api/history").json()
    out["/api/state"] = client.get("/api/state").json()
    for run in out["/api/runs"]:
        for rollout in run["rollouts"]:
            rid = rollout["id"]
            out[f"/api/runs/{run['id']}/rollouts/{rid}"] = client.get(
                f"/api/runs/{run['id']}/rollouts/{rid}"
            ).json()
    return _normalize(out)


class GoldenEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        if not VIEWER.is_dir():
            self.skipTest(f"no viewer at {VIEWER}")
        # Git stores no mtimes and the viewer sorts by them. Without this the
        # order in a fresh clone is whatever the file system lists first.
        subprocess.run([sys.executable, str(VIEWER / "touch_fixtures.py"), str(FIXTURES)],
                       check=True, capture_output=True)
        # Probed once here, not inside capture(): only one test needs it, and a
        # bare except around all of capture() would also swallow a genuine
        # import error inside the viewer's own app/experiment/lib modules,
        # silently stopping the guard from testing anything at all.
        self._testclient_unavailable = _testclient_unavailable_reason()

    def test_mtimes_are_distinct(self):
        sys.path.insert(0, str(VIEWER))
        import touch_fixtures

        times = touch_fixtures.load(FIXTURES)          # raises on a collision
        self.assertEqual(len(set(times.values())), len(times))

    def test_no_volatile_key_reaches_the_golden_file(self):
        golden = json.loads(GOLDEN.read_text())
        for key in VOLATILE:
            self.assertNotIn(key, golden["/api/status"])

    def test_the_endpoints_match_the_golden_file(self):
        if self._testclient_unavailable:
            self.skipTest(f"{self._testclient_unavailable} -- {_SYNC_HINT}")
        self.assertEqual(capture(), json.loads(GOLDEN.read_text()))


if __name__ == "__main__":
    if "--update" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(VIEWER / "touch_fixtures.py"), str(FIXTURES)],
                       check=True, capture_output=True)
        GOLDEN.write_text(json.dumps(capture(), indent=2, sort_keys=True) + "\n")
        print(f"wrote {GOLDEN}")
    else:
        unittest.main()
