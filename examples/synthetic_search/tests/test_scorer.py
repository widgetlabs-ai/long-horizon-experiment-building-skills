"""The scorer: macro-F1, quantized, and honest about a category it never saw."""

from synthetic_search.substrate import scorer


def test_macro_f1_is_one_for_perfect_predictions():
    assert scorer.macro_f1([("a", "a"), ("b", "b")]) == 1.0


def test_macro_f1_is_zero_when_nothing_is_right():
    assert scorer.macro_f1([("a", "b"), ("b", "a")]) == 0.0


def test_macro_f1_is_quantized_to_nine_places():
    value = scorer.macro_f1([("a", "a"), ("a", "b"), ("b", "b")])
    assert value == round(value, scorer.QUANTUM)


def test_macro_f1_averages_over_categories_not_rows():
    # Three "a" rows all correct, one "b" row wrong: per-row accuracy is 0.75,
    # but "b" scores 0, so the macro mean is well below it.
    pairs = [("a", "a"), ("a", "a"), ("a", "a"), ("b", "a")]
    assert scorer.macro_f1(pairs) < 0.75


def test_macro_f1_of_no_pairs_is_none():
    assert scorer.macro_f1([]) is None


def test_per_category_reports_none_for_zero_support():
    out = scorer.per_category([("a", "a")], categories=("a", "b"))
    assert out["b"]["f1"] is None
    assert out["b"]["support"] == 0


def test_per_category_reports_support():
    out = scorer.per_category([("a", "a"), ("a", "b")], categories=("a", "b"))
    assert out["a"]["support"] == 2


def test_per_category_precision_and_recall_are_quantized():
    out = scorer.per_category([("a", "a"), ("b", "a"), ("a", "b")], categories=("a", "b"))
    for stats in out.values():
        for key in ("precision", "recall", "f1"):
            if stats[key] is not None:
                assert stats[key] == round(stats[key], scorer.QUANTUM)


def test_macro_f1_ignores_categories_with_no_support():
    with_ghost = scorer.macro_f1([("a", "a")], categories=("a", "b"))
    without = scorer.macro_f1([("a", "a")], categories=("a",))
    assert with_ghost == without == 1.0
