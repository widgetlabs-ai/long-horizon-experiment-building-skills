"""A comparison that compares nothing must not report success."""

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fixtures_vs_real  # noqa: E402


class VacuousPass(unittest.TestCase):
    def test_a_floor_of_files_is_required(self):
        # shape_diff runs with subset=True: if the generator writes nothing,
        # `left` is empty, the diff is empty, and the old code printed
        # "PASS (0 files compared)". A green line over a hole is worse than red.
        self.assertGreater(fixtures_vs_real.MIN_FILES, 0)

    def test_compare_refuses_below_the_floor(self):
        with self.assertRaises(fixtures_vs_real.TooFewFiles):
            fixtures_vs_real.check_floor({"state/only.json": {}})


if __name__ == "__main__":
    unittest.main()
