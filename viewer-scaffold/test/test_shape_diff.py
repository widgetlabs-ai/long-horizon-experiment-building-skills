"""shape_diff: run with  python3 -m unittest discover -s test -p 'test_*.py'  from the skill dir."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import shape_diff  # noqa: E402


def root(files: dict[str, object]) -> Path:
    base = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".jsonl"):
            p.write_text("".join(json.dumps(x) + "\n" for x in content))
        elif rel.endswith(".json"):
            p.write_text(json.dumps(content))
        else:
            p.write_text(str(content))
    return base


def run(left, right, rules="", subset=False):
    r = shape_diff.load_rules(rules)
    a = shape_diff.shape_of(root(left), r)
    b = shape_diff.shape_of(root(right), r, only=set(a) if subset else None)
    return shape_diff.diff(a, b, r, subset=subset)


class ShapeDiff(unittest.TestCase):
    def test_identical_shapes(self):
        f = {"state/gate.json": {"passed": True, "after": 0.5}}
        self.assertEqual(run(f, f), [])

    def test_key_missing_on_one_side(self):
        out = run({"state/gate.json": {"passed": True, "after": 0.5}},
                  {"state/gate.json": {"passed": True}})
        self.assertEqual(out, ["state/gate.json::after: only in left"])

    def test_int_and_float_are_one_type_null_is_not(self):
        self.assertEqual(run({"state/g.json": {"x": 1}}, {"state/g.json": {"x": 1.5}}), [])
        out = run({"state/g.json": {"x": 1}}, {"state/g.json": {"x": None}})
        self.assertEqual(out, ["state/g.json::x: types left {number} right {null}"])

    def test_ids_are_normalized(self):
        a = {"state/candidates/0339cc46aa33/candidate.json": {"t": "x"}}
        b = {"state/candidates/ffffffff0000/candidate.json": {"t": "y"}}
        self.assertEqual(run(a, b), [])

    def test_run_dirs_are_normalized(self):
        a = {"outputs/run-one/traces.jsonl": [{"id": "a"}]}
        b = {"outputs/other--model--1a4d0d92/traces.jsonl": [{"id": "b"}]}
        self.assertEqual(run(a, b), [])

    def test_jsonl_lines_merge(self):
        a = {"state/p.jsonl": [{"a": 1}, {"b": 2}]}
        b = {"state/p.jsonl": [{"a": 1, "b": 2}]}
        self.assertEqual(run(a, b), [])

    def test_map_rule_collapses_keys(self):
        a = {"state/b.json": {"per_category": {"category-a": {"s": 1}}}}
        b = {"state/b.json": {"per_category": {"real-category": {"s": 0.5}}}}
        self.assertEqual(len(run(a, b)), 2)
        self.assertEqual(run(a, b, "map state/b.json per_category"), [])

    def test_ignore_rule_needs_a_reason(self):
        a = {"state/g.json": {"x": 1, "extra": 1}}
        b = {"state/g.json": {"x": 1}}
        self.assertEqual(run(a, b, "ignore state/g.json extra  # only A writes it"), [])
        with self.assertRaises(ValueError):
            shape_diff.load_rules("ignore state/g.json extra")

    def test_brackets_in_rule_paths_are_literal(self):
        a = {"state/g.jsonl": [{"t": [{"n": 1, "x": 1}]}]}
        b = {"state/g.jsonl": [{"t": [{"n": 1}]}]}
        self.assertEqual(run(a, b, "ignore state/g.jsonl t[].x  # A only"), [])
        self.assertEqual(run(a, b, "ignore state/g.jsonl t[[]].x  # A only"), [])
        self.assertEqual(run(a, b, "ignore state/g.jsonl t[].n  # wrong key"), ["state/g.jsonl::t[].x: only in left"])
        deep_a = {"state/g.jsonl": [{"t": [{"n": [{"x": 1, "y": 1}]}]}]}
        deep_b = {"state/g.jsonl": [{"t": [{"n": [{"x": 1}]}]}]}
        self.assertEqual(run(deep_a, deep_b, "ignore state/g.jsonl t[].n[].y  # A only"), [])

    def test_subset_skips_right_only_files(self):
        a = {"state/g.json": {"x": 1}}
        b = {"state/g.json": {"x": 1}, "state/engine-src/a.ts": "x"}
        self.assertEqual(run(a, b, subset=True), [])
        self.assertEqual(run(a, b), ["state/engine-src/a.ts: only in right"])

    def test_follows_symlinked_tops(self):
        real = root({"state/g.json": {"x": 1}})
        link = Path(tempfile.mkdtemp())
        (link / "state").symlink_to(real / "state")
        self.assertIn("state/g.json", shape_diff.shape_of(link, shape_diff.load_rules("")))

    def test_an_always_empty_array_is_not_a_difference(self):
        a = {"state/g.json": {"f": ["x"], "g": [{"k": 1}]}}
        b = {"state/g.json": {"f": [], "g": []}}
        self.assertEqual(run(a, b), [])

    def test_array_items_are_compared(self):
        a = {"state/g.json": {"f": ["x"]}}
        b = {"state/g.json": {"f": [1]}}
        self.assertEqual(run(a, b), ["state/g.json::f[]: types left {str} right {number}"])


if __name__ == "__main__":
    unittest.main()
