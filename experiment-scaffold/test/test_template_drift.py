"""The verbatim templates must still be the example's files.

A template is a copy, and a copy rots. The example is the version that is
actually run and tested, so it is the source of truth; when the two disagree,
the template is the one that is wrong.

Where the example is absent — a checkout that ships no examples — this skips
with that reason. The skill has to work in a repository that has none.
"""

import re
import unittest
from pathlib import Path

from test_manifest_matches_template import MANIFEST, TEMPLATE, parse_manifest

SKILLS_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = SKILLS_ROOT / "examples" / "synthetic_search"

# Where a verbatim template lives in the example, when the names differ.
SOURCE_OF = {
    "errors.py": "src/synthetic_search/substrate/errors.py",
    "review.py": "src/synthetic_search/substrate/review.py",
    "supervisor.sh": "supervisor.sh",
    "provider.sh": "provider.sh",
    "run.sh": "run.sh",
    "gitignore": None,
}

EXCEPTION_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|$")


def declared_exceptions(path: Path) -> dict[str, str]:
    """The manifest's 'Declared differences' table."""
    text = path.read_text()
    if "### Declared differences" not in text:
        return {}
    section = text.split("### Declared differences", 1)[1]
    rows = {}
    for line in section.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") and "---" not in stripped:
            match = EXCEPTION_ROW.match(stripped)
            if match and match.group(1) != "file":
                rows[match.group(1)] = match.group(2)
    return rows


class TemplateDrift(unittest.TestCase):
    def setUp(self):
        if not EXAMPLE.is_dir():
            self.skipTest(f"example absent: {EXAMPLE} — nothing to diff against")
        self.manifest = parse_manifest(MANIFEST)
        self.exceptions = declared_exceptions(MANIFEST)

    def test_every_declared_exception_carries_a_reason(self):
        for name, reason in self.exceptions.items():
            self.assertTrue(reason.strip(), f"{name} is excepted with no reason")

    def test_every_declared_exception_names_a_manifest_file(self):
        unknown = sorted(set(self.exceptions) - set(self.manifest))
        self.assertEqual(unknown, [], f"excepted but not in the manifest: {unknown}")

    def test_verbatim_templates_match_the_example(self):
        drifted = []
        for name, tier in self.manifest.items():
            if tier != "verbatim" or name in self.exceptions:
                continue
            relative = SOURCE_OF.get(name, name)
            if relative is None:
                continue
            source = EXAMPLE / relative
            if not source.is_file():
                drifted.append(f"{name}: no source at {relative}")
                continue
            if (TEMPLATE / name).read_text() != source.read_text():
                drifted.append(f"{name}: differs from {relative}")
        self.assertEqual(drifted, [], "\n".join(drifted))


if __name__ == "__main__":
    unittest.main()
