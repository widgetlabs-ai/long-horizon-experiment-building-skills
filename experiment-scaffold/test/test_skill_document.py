"""SKILL.md has to be findable, honest about its own procedure, and unbroken."""

import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL = SKILL_DIR / "SKILL.md"


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("---\n"):
        return {}
    block = text.split("---\n", 2)[1]
    out = {}
    for line in block.split("\n"):
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


class SkillDocument(unittest.TestCase):
    def test_frontmatter_names_the_skill(self):
        self.assertEqual(frontmatter(SKILL).get("name"), "experiment-scaffold")

    def test_frontmatter_describes_when_to_use_it(self):
        description = frontmatter(SKILL).get("description", "")
        self.assertGreater(len(description), 60, "a description too short to match on")

    def test_every_referenced_file_exists(self):
        missing = []
        for ref in re.findall(r"`((?:reference|template|test)/[^`\s]+)`", SKILL.read_text()):
            if not (SKILL_DIR / ref).exists():
                missing.append(ref)
        self.assertEqual(missing, [], f"referenced but absent: {missing}")

    def test_it_names_its_three_stops(self):
        text = SKILL.read_text().lower()
        for stop in ("classif", "spike", "design.md"):
            self.assertIn(stop, text)

    def test_it_forbids_claiming_an_unrun_check(self):
        text = SKILL.read_text().lower()
        self.assertIn("not checked", text)

    def test_it_points_at_the_sibling_skill(self):
        self.assertIn("viewer-scaffold", SKILL.read_text())

    def test_the_validity_check_is_a_contract_not_an_example(self):
        contracts = (SKILL_DIR / "reference" / "contracts.md").read_text()
        self.assertIn("## 7. The validity check", contracts)
        # The clause that makes it a rail rather than a suggestion.
        self.assertIn("outside the editable area", contracts)
        skill = SKILL.read_text()
        self.assertTrue(
            "validity check" in skill.split("## Procedure")[0], "must be a non-negotiable"
        )

    def test_the_brief_template_names_the_validity_check(self):
        brief = (SKILL_DIR / "template" / "brief.md").read_text()
        self.assertIn("whatever it scores", " ".join(brief.split()))

    def test_the_reviewer_is_a_contract(self):
        contracts = (SKILL_DIR / "reference" / "contracts.md").read_text()
        self.assertIn("## 8. The reviewer", contracts)
        self.assertIn("must not restate the reward", " ".join(contracts.split()))

    def test_the_reviewer_is_a_known_limit(self):
        # A non-deterministic stage in a loop whose argument is determinism is a
        # permanent caveat, stated plainly, not a bug somebody will later "fix".
        limits = SKILL.read_text().split("## Known limits", 1)[1]
        self.assertIn("reviewer", limits)
        self.assertIn("deterministic", limits)

    def test_the_review_template_ships_enabled(self):
        import tomllib

        config = tomllib.loads((SKILL_DIR / "template" / "review.toml").read_text())
        self.assertIs(config["review"]["enabled"], True)


if __name__ == "__main__":
    unittest.main()
