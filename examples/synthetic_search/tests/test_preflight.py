"""Preflight: everything knowable before the first generation, and nothing guessed."""

import os
import shutil
import subprocess
from pathlib import Path

EXPERIMENT = Path(__file__).resolve().parents[1]
RUN = EXPERIMENT / "run.sh"


def _cli(args: list[str], env: dict) -> subprocess.CompletedProcess:
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
            "PYTHONPATH": str(EXPERIMENT / "src")}
    result = subprocess.run(
        ["python3", "-m", "synthetic_search.substrate.cli", *args],
        capture_output=True, text=True, env={**base, **env}, cwd=EXPERIMENT, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result


def _check(env: dict) -> subprocess.CompletedProcess:
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    return subprocess.run(
        ["bash", str(RUN), "--check"],
        capture_output=True, text=True, env={**base, **env}, cwd=EXPERIMENT, timeout=300,
    )


def test_preflight_refuses_without_a_provider(tmp_path):
    result = _check({"SYNTH_STATE": str(tmp_path)})
    assert result.returncode == 2


def test_preflight_refuses_an_unstaged_corpus(tmp_path):
    result = _check({"SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x"})
    assert result.returncode == 2
    assert "corpus" in (result.stdout + result.stderr).lower()


def test_preflight_says_which_stages_it_skipped(tmp_path):
    env = {"SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x"}
    _cli(["stage", "--seed", "7", "--rows", "200"], env)
    _cli(["pin"], env)
    _cli(["baseline", "--split", "all"], env)
    result = _check({**env, "SYNTH_SKIP_MODEL_CALL": "1", "SYNTH_SKIP_IMAGE": "1"})
    combined = result.stdout + result.stderr
    assert "skipped" in combined.lower()


def test_preflight_refuses_a_misconfigured_reviewer(tmp_path):
    # A reviewer with no key would otherwise be found only after a whole
    # generation's rollouts had been paid for. Run on a copy of the experiment,
    # so its review.toml can be enabled without touching the committed one.
    copy = tmp_path / "experiment"
    copy.mkdir()
    for name in ("run.sh", "provider.sh", "supervisor.sh", "brief.md", "review.md"):
        shutil.copy2(EXPERIMENT / name, copy / name)
    for name in ("src", "artifact"):
        shutil.copytree(EXPERIMENT / name, copy / name, ignore=shutil.ignore_patterns("__pycache__"))
    (copy / "review.toml").write_text(
        '[review]\nenabled = true\nbase_url = "https://example.invalid/v1"\n'
        'api_key_var = "REVIEW_KEY_NOBODY_SET"\nmodel = "reviewer"\nrubric = "review.md"\n'
    )
    state = tmp_path / "state"
    env = {"SYNTH_STATE": str(state), "OPENCODE_API_KEY": "x"}
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), "PYTHONPATH": str(copy / "src")}
    for args in (["stage", "--seed", "7", "--rows", "200"], ["pin"], ["baseline", "--split", "all"]):
        subprocess.run(["python3", "-m", "synthetic_search.substrate.cli", *args], check=True,
                       capture_output=True, env={**base, **env}, cwd=copy, timeout=120)
    result = subprocess.run(
        ["bash", str(copy / "run.sh"), "--check"], capture_output=True, text=True, cwd=copy, timeout=300,
        env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"),
             **env, "SYNTH_SKIP_MODEL_CALL": "1", "SYNTH_SKIP_IMAGE": "1"},
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "REVIEW_KEY_NOBODY_SET" in result.stderr
    assert "reviewer" in result.stderr
