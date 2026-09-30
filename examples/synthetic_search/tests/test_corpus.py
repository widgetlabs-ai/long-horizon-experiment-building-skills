"""The corpus: generated from a seed, split three ways, resolved without defaults."""

import pytest

from synthetic_search.substrate import corpus


def test_generate_is_deterministic_for_a_seed():
    assert corpus.generate(7, 50) == corpus.generate(7, 50)


def test_generate_differs_across_seeds():
    assert corpus.generate(7, 50) != corpus.generate(8, 50)


def test_every_category_appears():
    rows = corpus.generate(7, 200)
    assert {r["label"] for r in rows} == set(corpus.CATEGORIES)


def test_stage_splits_three_ways_and_is_stable(tmp_path):
    first = corpus.stage(tmp_path, seed=7, n=200)
    assert set(first) == {"train", "val", "test"}
    assert sum(first.values()) == 200
    assert corpus.stage(tmp_path, seed=7, n=200) == first


def test_stage_stratifies_every_category_into_every_split(tmp_path):
    corpus.stage(tmp_path, seed=7, n=200)
    for split in ("train", "val", "test"):
        labels = {r["label"] for r in corpus.load_split(tmp_path, split)}
        assert labels == set(corpus.CATEGORIES)


def test_stage_gives_train_the_largest_share(tmp_path):
    counts = corpus.stage(tmp_path, seed=7, n=200)
    assert counts["train"] > counts["val"]
    assert counts["train"] > counts["test"]


def test_load_split_refuses_an_unknown_split(tmp_path):
    corpus.stage(tmp_path, seed=7, n=50)
    with pytest.raises(corpus.SubstrateError):
        corpus.load_split(tmp_path, "holdout")


def test_resolve_state_root_exits_2_when_unset(monkeypatch):
    monkeypatch.delenv("SYNTH_STATE", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        corpus.resolve_state_root()
    assert excinfo.value.code == 2


def test_resolve_state_root_names_the_variable(monkeypatch, capsys):
    monkeypatch.delenv("SYNTH_STATE", raising=False)
    with pytest.raises(SystemExit):
        corpus.resolve_state_root()
    assert "SYNTH_STATE" in capsys.readouterr().err


def test_resolve_state_root_distinguishes_missing_from_unset(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path / "nowhere"))
    with pytest.raises(SystemExit) as excinfo:
        corpus.resolve_state_root()
    assert excinfo.value.code == 2
    assert "does not exist" in capsys.readouterr().err


def test_resolve_state_root_returns_a_staged_directory(monkeypatch, tmp_path):
    corpus.stage(tmp_path, seed=7, n=50)
    monkeypatch.setenv("SYNTH_STATE", str(tmp_path))
    assert corpus.resolve_state_root() == tmp_path


def test_growing_the_corpus_never_moves_a_staged_row(tmp_path):
    # Growing a corpus mid-search must not hand the gate rows the artifact was
    # already fitted on, nor take fitted rows out of the denominator.
    corpus.stage(tmp_path, seed=7, n=2000)
    before = {
        row["id"]: split
        for split in corpus.SPLITS
        for row in corpus.load_split(tmp_path, split)
    }
    corpus.stage(tmp_path, seed=7, n=2500)
    after = {
        row["id"]: split
        for split in corpus.SPLITS
        for row in corpus.load_split(tmp_path, split)
    }
    moved = {rid: (before[rid], after[rid]) for rid in before if after.get(rid) != before[rid]}
    assert moved == {}, f"{len(moved)} of {len(before)} rows changed split"


def test_split_of_is_what_stage_uses(tmp_path):
    # The documented property belongs to _split_of; stage must not reimplement
    # it differently.
    corpus.stage(tmp_path, seed=7, n=400)
    for split in corpus.SPLITS:
        for row in corpus.load_split(tmp_path, split):
            assert corpus._split_of(7, row["id"]) == split


def test_every_generated_row_decomposes():
    # If this fails, the grammar changed and `noise_swap` has silently stopped
    # being available for the rows it was written for.
    for row in corpus.generate(seed=7, n=300):
        opener, body = corpus.decompose(row["text"], row["label"])
        assert opener is not None and body is not None, row


def test_noise_swap_keeps_the_opener_and_the_body():
    for row in corpus.generate(seed=7, n=60):
        opener, body = corpus.decompose(row["text"], row["label"])
        swapped = corpus.perturbations(row["text"], row["label"])["noise_swap"]
        assert swapped.startswith(opener) and swapped.endswith(body)
        assert swapped != row["text"]


def test_structure_free_perturbations_are_always_offered():
    got = corpus.perturbations("hello how are you", "greeting")
    assert got["trailing_punct"] == "hello how are you."
    assert got["upper"] == "HELLO HOW ARE YOU"


def test_a_row_that_does_not_decompose_still_gets_the_structure_free_two():
    # Review Focus 3. A grammar edit must degrade the check, not disable it.
    got = corpus.perturbations("this text came from nowhere", "greeting")
    assert set(got) == {"trailing_punct", "upper"}
    got_unknown_label = corpus.perturbations("hello how are you", "not_a_category")
    assert set(got_unknown_label) == {"trailing_punct", "upper"}


def test_noise_swap_breaks_a_rule_keyed_to_an_exact_row():
    # The whole point: this is what memorisation looks like and what kills it.
    row = corpus.generate(seed=7, n=1)[0]
    swapped = corpus.perturbations(row["text"], row["label"])["noise_swap"]
    assert row["text"] not in swapped
