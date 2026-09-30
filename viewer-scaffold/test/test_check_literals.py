import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "template"))
import check_literals  # noqa: E402


def experiment_py(notes_body: str) -> Path:
    root = Path(tempfile.mkdtemp())
    path = root / "experiment.py"
    path.write_text(
        "def notes():\n"
        "    \"\"\"docstring, never checked.\"\"\"\n"
        f"    return {{\n{notes_body}\n    }}\n"
    )
    return path


class CheckLiteralsProse(unittest.TestCase):
    def test_letter_bound_digit_is_allowed(self):
        for text in ("macro-F1 is the reward split by category.",
                     "R2 measures how well the fit explains variance.",
                     "P95 latency is read from the newest run.",
                     "F1 is the reward this search maximises.",
                     "x2 the sample size before trusting this split."):
            path = experiment_py(f'        "s": {text!r},')
            self.assertEqual(check_literals.prose_findings(path), [],
                              f"{text!r} should not be flagged")

    def test_standalone_numeral_or_decimal_is_refused(self):
        for text in ("3 rollouts per task", "reward of 0.75", "12 categories",
                      "the agent ran 2x this generation", "10x faster than before"):
            path = experiment_py(f'        "s": {text!r},')
            findings = check_literals.prose_findings(path)
            self.assertEqual(len(findings), 1, f"{text!r} should be flagged")


if __name__ == "__main__":
    unittest.main()
