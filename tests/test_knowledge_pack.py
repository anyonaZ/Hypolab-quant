"""The knowledge pack for the Claude Projects must match what HYPOLAB accepts."""
import os
import re
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

import yaml  # noqa: E402

from hypolab.concepts import CONCEPTS  # noqa: E402
from hypolab.hypotheses import load_cards, validate_library  # noqa: E402
from hypolab.journal import Journal  # noqa: E402
from hypolab.operators import GOLD  # noqa: E402
from ideaengine import knowledge_pack as kp  # noqa: E402
from ideaengine.store import IdeaStore  # noqa: E402


class TestKnowledgePack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.files = kp.build(cls.out, Journal(":memory:"), IdeaStore(":memory:"))

    def test_every_file_and_index(self):
        names = {p.name for p in self.files}
        self.assertEqual(names, set(kp.USED_BY) | {"INDEX.md"})
        for p in self.files:
            self.assertLess(p.stat().st_size, 60_000, p.name)       # small enough to upload

    def test_example_cards_are_valid_hypolab_cards(self):
        text = (self.out / "01_card_format.md").read_text()
        block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
        path = self.out / "examples.yaml"
        path.write_text(block)
        cards = load_cards(path)
        self.assertEqual({c.id for c in cards}, set(kp.EXAMPLE_CARDS))
        self.assertEqual(validate_library(cards), [])
        self.assertIsInstance(yaml.safe_load(block), list)

    def test_every_concept_and_operator_is_listed(self):
        concepts = (self.out / "02_concepts.md").read_text()
        for name in CONCEPTS:
            self.assertIn(f"| `{name}` |", concepts)
        ops = (self.out / "03_operators.md").read_text()
        self.assertEqual(ops.count("\n| `"), len(GOLD.table()))
        self.assertNotIn("`sales`: may also be written directly", concepts)   # only price/volume fields

    def test_goals_and_dead_ends(self):
        goals = (self.out / "06_goals_and_rules.md").read_text()
        self.assertIn("| Signals (submitted alphas) | 1 | 20 |", goals)
        self.assertIn("At most 4 alpha submissions a day", goals)
        self.assertIn("None yet", (self.out / "07_dead_ends.md").read_text())

    def test_dead_end_is_detected(self):
        j = Journal(":memory:")
        j.db.execute("INSERT INTO ideas (id, hypothesis_id, region, family, title, categories, created) "
                     "VALUES ('X@USA','X','USA','fam_dead','t','pv',0)")
        for i in range(5):
            j.db.execute("INSERT INTO experiments (idea_id, purpose, expression, fingerprint, region, verdict, "
                         "sharpe, backend, created) VALUES ('X@USA','explore','e',?, 'USA','NOISE',0.1,'brain',0)",
                         (f"fp{i}",))
        self.assertIn("| fam_dead | USA | 5 |", kp.dead_ends(j))


if __name__ == "__main__":
    unittest.main()
