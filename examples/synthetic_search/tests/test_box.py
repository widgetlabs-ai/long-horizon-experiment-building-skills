"""`rt`, the agent's in-box tool, and the taskset module's static contract."""

import ast
import json
from pathlib import Path

import pytest

from synthetic_search.substrate import box, cli, corpus

ARTIFACT = Path(__file__).resolve().parents[1] / "artifact" / "rules.py"
TASKSET = Path(__file__).resolve().parents[1] / "src" / "synthetic_search" / "taskset.py"


@pytest.fixture()
def boxed(tmp_path, monkeypatch):
    corpus.stage(tmp_path, seed=7, n=200)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    monkeypatch.setenv("SYNTH_ARTIFACT", str(tmp_path / "rules.py"))
    (tmp_path / "rules.py").write_text(ARTIFACT.read_text())
    assert cli.main(["pin"]) == 0
    assert cli.main(["baseline", "--split", "train", "--source", str(tmp_path / "rules.py")]) == 0
    return tmp_path


def test_rt_score_prints_a_reward_and_a_delta(boxed, capsys):
    assert box.main(["score"]) == 0
    out = capsys.readouterr().out
    assert "reward" in out and "delta" in out


def test_rt_score_prints_turns_remaining_when_a_budget_is_set(boxed, capsys, monkeypatch):
    monkeypatch.setenv("SYNTH_MAX_TURNS", "10")
    assert box.main(["score"]) == 0
    assert "turns remaining: 9" in capsys.readouterr().out

    assert box.main(["score"]) == 0
    assert "turns remaining: 8" in capsys.readouterr().out


def test_rt_score_omits_turns_when_no_budget_is_set(boxed, capsys):
    assert box.main(["score"]) == 0
    assert "turns remaining" not in capsys.readouterr().out


def test_rt_score_never_touches_a_held_out_split(boxed):
    assert box.main(["score", "--split", "val"]) == 2


def test_rt_check_accepts_the_shipped_table(boxed, capsys):
    assert box.main(["check"]) == 0
    assert "passes" in capsys.readouterr().out


def test_rt_check_rejects_a_table_that_imports(boxed, capsys):
    (boxed / "rules.py").write_text("import json\ndef classify(t): return 'a'\n")
    assert box.main(["check"]) == 1
    assert "import" in capsys.readouterr().out


def test_rt_check_refuses_a_memorising_table(boxed, capsys):
    target = corpus.load_split(boxed, "train")[0]
    (boxed / "rules.py").write_text(
        "def classify(text):\n"
        f"    if text == {target['text']!r}: return {target['label']!r}\n"
        "    return 'unknown'\n"
    )
    assert box.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "robust_to_perturbation" in out and target["id"] in out


def test_rt_rows_samples_rows_with_predictions(boxed, capsys):
    assert box.main(["rows", "--class", "greeting", "--limit", "3"]) == 0
    assert "predicted" in capsys.readouterr().out


def test_taskset_returns_only_the_contract_paths():
    tree = ast.parse(TASKSET.read_text())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "ARTIFACT_PATHS" in names
    assert "candidate_dir" in names


def test_taskset_names_no_artifact_path_of_its_own():
    literals = {
        n.value for n in ast.walk(ast.parse(TASKSET.read_text()))
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.endswith(".py")
    }
    assert literals == set()


def test_rt_check_refuses_a_table_that_fails_a_later_load(boxed, capsys, monkeypatch):
    from test_measure import _fail_on_load

    source = ARTIFACT.read_text() + "\n# flaky\n"
    (boxed / "rules.py").write_text(source)
    # rt check loads once for the guard, then once per validity pass.
    _fail_on_load(monkeypatch, source, {3})
    assert box.main(["check"]) == 1
    out = capsys.readouterr().out
    assert "load_stable" in out and "pass 2" in out


def test_rt_rows_refuses_a_rejected_table_rather_than_crashing(boxed, capsys):
    (boxed / "rules.py").write_text("import json\ndef classify(t): return 'a'\n")
    assert box.main(["rows"]) == 1
    assert "import" in capsys.readouterr().out
