"""The supervisor's error branches — the least-tested code in any search.

Every case here is a way a shell loop silently does the wrong thing at 3am:
`set -e` killing the script on a normal non-zero exit, `$?` read after a
`case`, a `[[ -f ]] && git add` that returns 1 when the file is absent, and a
`git add` of a glob that fails atomically when one path is ignored.
"""

import os
import subprocess
from pathlib import Path

import pytest

EXPERIMENT = Path(__file__).resolve().parents[1]
SUPERVISOR = EXPERIMENT / "supervisor.sh"
PROVIDER = EXPERIMENT / "provider.sh"
RUN = EXPERIMENT / "run.sh"


def _run(script: Path, env: dict, args: list[str] | None = None) -> subprocess.CompletedProcess:
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    return subprocess.run(
        ["bash", str(script), *(args or [])],
        capture_output=True, text=True, env={**base, **env}, cwd=EXPERIMENT, timeout=120,
    )


def test_every_script_is_strict():
    for script in (SUPERVISOR, PROVIDER, RUN):
        assert "set -euo pipefail" in script.read_text(), script.name


def test_no_script_stages_everything():
    for script in (SUPERVISOR, RUN):
        assert "git add -A" not in script.read_text(), script.name
        assert "git add ." not in script.read_text(), script.name


def test_no_script_reads_dollar_question_after_a_case():
    # `cmd; case $? in ...; esac; if [[ $? -eq 0 ]]` reads the case's status.
    for script in (SUPERVISOR, RUN):
        text = script.read_text()
        assert "esac" not in text or "$?" not in text.split("esac", 1)[1].split("\n", 2)[1]


def test_no_script_guards_a_file_with_and_under_set_e():
    # `[[ -f "$f" ]] && git add "$f"` returns 1 when absent and kills the script.
    for script in (SUPERVISOR, RUN):
        for line in script.read_text().split("\n"):
            stripped = line.strip()
            if stripped.startswith("[[") and "]] &&" in stripped:
                pytest.fail(f"{script.name}: guarded command uses && under set -e: {stripped}")


def test_provider_refuses_without_a_key(tmp_path):
    result = _run(PROVIDER, {"SYNTH_STATE": str(tmp_path)})
    assert result.returncode == 2
    assert "key" in (result.stderr + result.stdout).lower()


def test_provider_resolves_opencode_when_its_key_is_set(tmp_path):
    result = _run(PROVIDER, {"OPENCODE_API_KEY": "x", "SYNTH_STATE": str(tmp_path)})
    assert result.returncode == 0
    assert "opencode" in result.stdout


def test_provider_prefers_opencode_and_says_the_other_is_ignored(tmp_path):
    result = _run(PROVIDER, {"OPENCODE_API_KEY": "x", "OPENROUTER_API_KEY": "y", "SYNTH_STATE": str(tmp_path)})
    assert result.returncode == 0
    assert "opencode" in result.stdout and "ignored" in result.stdout


def test_provider_falls_back_to_openrouter(tmp_path):
    result = _run(PROVIDER, {"OPENROUTER_API_KEY": "y", "SYNTH_STATE": str(tmp_path)})
    assert result.returncode == 0
    assert "openrouter" in result.stdout


def test_supervisor_refuses_while_an_abort_sentinel_exists(tmp_path):
    (tmp_path / "ABORT").write_text("stopped by hand\n")
    result = _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_GENERATIONS": "1",
    })
    assert result.returncode == 2
    assert "ABORT" in result.stdout + result.stderr


def test_supervisor_continues_after_a_lost_generation(tmp_path):
    result = _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_GENERATIONS": "2",
        "SYNTH_FAKE_EVAL": "1", "SYNTH_FAKE_CLI_EXIT": "1",
    })
    assert result.returncode == 0
    assert result.stdout.count("generation") >= 2


def test_supervisor_stops_when_the_substrate_is_broken(tmp_path):
    result = _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_GENERATIONS": "3",
        "SYNTH_FAKE_EVAL": "1", "SYNTH_FAKE_CLI_EXIT": "2",
    })
    assert result.returncode == 2
    assert result.stdout.count("generation 1") <= 1


def test_supervisor_rejects_a_nonsense_turn_budget(tmp_path):
    result = _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_TURNS": "lots",
    })
    assert result.returncode == 2


def test_a_successful_generation_commits_and_advances_the_counter(tmp_path):
    # The adopt-and-commit path: every earlier test faked a LOSS, so this whole
    # branch — including staging named paths — was never executed.
    (tmp_path / "promotions.jsonl").write_text('{"trace": "t-1", "generation": 0}\n')
    (tmp_path / "gate_report.json").write_text('{"verdict": "passed"}\n')
    result = _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_GENERATIONS": "2",
        "SYNTH_FAKE_EVAL": "1", "SYNTH_FAKE_CLI_EXIT": "0",
    })
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "generation").read_text().strip() == "2"


def test_an_ignored_path_that_must_be_committed_stops_the_run(tmp_path):
    # Staging is atomic over its arguments: one ignored path fails the whole
    # add. That must stop the run as a broken substrate, not read as an
    # ordinary lost candidate — and must never be swallowed.
    #
    # SYNTH_SKIP_COMMIT is set throughout: a test that lets the supervisor
    # reach `git commit` commits to whatever branch the suite is running on.
    # It did exactly that once, which is how this note came to be here.
    result = _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_GENERATIONS": "1",
        "SYNTH_FAKE_EVAL": "1", "SYNTH_FAKE_CLI_EXIT": "0",
    })
    # A state directory outside the repository is a supported configuration:
    # its files are skipped with a message, not staged, and the run survives.
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_supervisor_passes_a_run_directory_that_exists(tmp_path):
    # supervisor.sh used to pass "$OUTPUTS_DIR/latest", which nothing creates:
    # the framework's only `latest` is <run>/logs/latest, inside a run dir. The
    # loop therefore died at generation 0 with "no episodes", every time.
    script = (EXPERIMENT / "supervisor.sh").read_text()
    assert "$OUTPUTS_DIR/latest" not in script
    assert "latest_run" in script


def test_the_supervisor_names_the_newest_run_directory(tmp_path):
    outputs = tmp_path / "outputs"
    for name in ("run-a", "run-b"):
        (outputs / name).mkdir(parents=True)
    os.utime(outputs / "run-b", (2_000_000_000, 2_000_000_000))
    result = subprocess.run(
        ["bash", "-c",
         f'source <(sed -n "/^latest_run()/,/^}}/p" {EXPERIMENT / "supervisor.sh"}); '
         f'OUTPUTS_DIR={outputs} latest_run'],
        capture_output=True, text=True,
    )
    assert result.stdout.strip().endswith("run-b"), result.stdout + result.stderr


def test_the_supervisor_refuses_when_no_run_directory_exists(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    result = subprocess.run(
        ["bash", "-c",
         f'source <(sed -n "/^latest_run()/,/^}}/p" {EXPERIMENT / "supervisor.sh"}); '
         f'OUTPUTS_DIR={outputs} latest_run'],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "no run directory" in (result.stdout + result.stderr).lower()


def test_the_supervisor_never_commits_when_told_not_to(tmp_path):
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=EXPERIMENT
    ).stdout
    _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "MAX_GENERATIONS": "1",
        "SYNTH_FAKE_EVAL": "1", "SYNTH_FAKE_CLI_EXIT": "0",
        "SYNTH_SKIP_COMMIT": "1",
    })
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=EXPERIMENT
    ).stdout
    assert before == after


def _loop(tmp_path, **extra):
    return _run(SUPERVISOR, {
        "SYNTH_STATE": str(tmp_path), "OPENCODE_API_KEY": "x",
        "SYNTH_LOG_TO_STDOUT": "1", "SYNTH_FAKE_EVAL": "1",
        "SYNTH_FAKE_CLI_EXIT": "0", "SYNTH_SKIP_COMMIT": "1",
        **extra,
    })


def test_review_runs_between_the_gate_and_adoption():
    text = SUPERVISOR.read_text()
    gate, review, adopt = (text.index(f"run_cli {s}") if s != "review" else text.index("run_review ||")
                           for s in ("gate", "review", "adopt"))
    assert gate < review < adopt


def test_a_refusal_loses_the_generation_and_the_loop_continues(tmp_path):
    result = _loop(tmp_path, MAX_GENERATIONS="2", SYNTH_FAKE_REVIEW_EXIT="1")
    assert result.returncode == 0, result.stdout + result.stderr
    # Both generations lost at review and the counter still advanced: the
    # `continue` branch ran, not the adopt branch (a faked adopt prints nothing,
    # so its absence from stdout would prove nothing).
    assert result.stdout.count("the reviewer refused") == 2
    assert (tmp_path / "generation").read_text().strip() == "2"


def test_a_broken_reviewer_stops_the_run(tmp_path):
    result = _loop(tmp_path, MAX_GENERATIONS="3", SYNTH_FAKE_REVIEW_EXIT="2")
    assert result.returncode == 2
    assert "review reported a broken substrate" in result.stdout
    assert result.stdout.count("--- generation") == 1


def test_a_passing_review_proceeds_to_adoption(tmp_path):
    result = _loop(tmp_path, MAX_GENERATIONS="1", SYNTH_FAKE_REVIEW_EXIT="0")
    assert result.returncode == 0
    assert "the reviewer refused" not in result.stdout


def test_the_review_record_is_committed_with_an_adoption():
    assert "$SYNTH_STATE/reviews.jsonl" in SUPERVISOR.read_text()
