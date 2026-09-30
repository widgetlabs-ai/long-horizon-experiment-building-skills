"""The manifest is the template's index: every file has a tier, and no more.

A template file with no tier is one the skill does not know how to use; a tier
naming a file that does not exist is a rotted instruction. Both are cheap to
check and expensive to discover during a scaffold.
"""

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
MANIFEST = SKILL / "reference" / "template-manifest.md"
TEMPLATE = SKILL / "template"

TIERS = {"verbatim", "adapt", "write-fresh"}
ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(verbatim|adapt|write-fresh)\s*\|")


def parse_manifest(path: Path) -> dict[str, str]:
    rows = {}
    for line in path.read_text().split("\n"):
        match = ROW.match(line.strip())
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def template_files() -> set[str]:
    return {
        str(p.relative_to(TEMPLATE))
        for p in TEMPLATE.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


class ManifestMatchesTemplate(unittest.TestCase):
    def test_the_manifest_parses(self):
        self.assertTrue(parse_manifest(MANIFEST), "no tier rows found in the manifest")

    def test_every_tier_is_one_of_three(self):
        self.assertLessEqual(set(parse_manifest(MANIFEST).values()), TIERS)

    def test_every_shipped_template_file_has_a_tier(self):
        listed = parse_manifest(MANIFEST)
        missing = sorted(template_files() - set(listed))
        self.assertEqual(missing, [], f"shipped but unlisted: {missing}")

    def test_every_copied_tier_names_a_shipped_file(self):
        listed = parse_manifest(MANIFEST)
        copied = {name for name, tier in listed.items() if tier in {"verbatim", "adapt"}}
        absent = sorted(copied - template_files())
        self.assertEqual(absent, [], f"listed as copied but not shipped: {absent}")

    def test_write_fresh_files_are_not_shipped(self):
        listed = parse_manifest(MANIFEST)
        fresh = {name for name, tier in listed.items() if tier == "write-fresh"}
        shipped = sorted(fresh & template_files())
        self.assertEqual(shipped, [], f"write-fresh but shipped as a template: {shipped}")


if __name__ == "__main__":
    unittest.main()
