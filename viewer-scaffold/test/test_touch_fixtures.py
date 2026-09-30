import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "template"))
import touch_fixtures  # noqa: E402


def fixtures(entries: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for path in entries:
        target = root / path
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}")
        else:
            target.mkdir(parents=True, exist_ok=True)
    (root / touch_fixtures.FILE).write_text(json.dumps(entries))
    return root


class TouchFixtures(unittest.TestCase):
    def test_sets_listed_times_on_files_and_dirs(self):
        root = fixtures({"outputs/run-a": "2026-01-01T10:00:00",
                         "outputs/run-a/traces.jsonl": "2026-01-01T10:05:00",
                         "outputs/run-b": "2026-01-01T11:00:00"})
        touch_fixtures.touch(root)
        self.assertLess(os.stat(root / "outputs/run-a").st_mtime, os.stat(root / "outputs/run-b").st_mtime)
        # the dir keeps its own time although a file inside it was touched after
        self.assertLess(os.stat(root / "outputs/run-a").st_mtime,
                        os.stat(root / "outputs/run-a/traces.jsonl").st_mtime)

    def test_equal_times_are_refused(self):
        root = fixtures({"outputs/a": "2026-01-01T10:00:00", "outputs/b": "2026-01-01T10:00:00"})
        with self.assertRaises(ValueError):
            touch_fixtures.touch(root)

    def test_missing_path_is_refused(self):
        root = fixtures({"outputs/a": "2026-01-01T10:00:00"})
        (root / "outputs/a").rmdir()
        with self.assertRaises(FileNotFoundError):
            touch_fixtures.touch(root)

    def test_expected_order_newest_first_by_path_component(self):
        times = touch_fixtures.load(fixtures({
            "outputs/r1": "2026-01-01T10:00:00",
            "outputs/r2": "2026-01-01T12:00:00",
            "state/candidates/c1/candidate.json": "2026-01-01T11:00:00",
            "state/candidates/c2/candidate.json": "2026-01-01T09:00:00"}))
        self.assertEqual(touch_fixtures.expected_order(times, ["r1", "r2"]), ["r2", "r1"])
        self.assertEqual(touch_fixtures.expected_order(times, ["c2", "c1"]), ["c1", "c2"])
        self.assertIsNone(touch_fixtures.expected_order(times, ["r1", "r9"]))

    def test_short_ids_match_the_full_component(self):
        times = touch_fixtures.load(fixtures({
            "state/candidates/aaaa1111ffff/candidate.json": "2026-01-01T10:00:00",
            "state/candidates/bbbb2222ffff/candidate.json": "2026-01-01T11:00:00"}))
        self.assertEqual(touch_fixtures.expected_order(times, ["aaaa1111", "bbbb2222"]), ["bbbb2222", "aaaa1111"])


if __name__ == "__main__":
    unittest.main()
