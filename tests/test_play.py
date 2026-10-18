"""1.4.0: the playground - random alphas from random cards and random fields, outside the Pyramid plan."""
import os
import tempfile
import unittest

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab import play, theme  # noqa: E402
from hypolab.diagnose import Diagnosis  # noqa: E402
from hypolab.research import Researcher  # noqa: E402


class TestRoll(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = Researcher.sandbox()

    def test_roll_is_free_linted_and_reproducible(self):
        a = self.R.roll(n=6, mode="mix", seed=11)
        b = self.R.roll(n=6, mode="mix", seed=11)
        self.assertEqual([i.expression for i in a], [i.expression for i in b])
        self.assertEqual(len(a), 6)
        self.assertTrue(all(i.lint_ok for i in a))
        self.assertEqual(len({i.expression for i in a}), 6)
        self.assertEqual(len(self.R.journal.experiments()), 0)        # rolling simulates nothing

    def test_modes(self):
        self.assertTrue(all(i.source == "card" for i in self.R.roll(n=4, mode="cards", seed=2)))
        wild = self.R.roll(n=6, mode="wild", seed=2)
        self.assertTrue(all(i.source == "wild" for i in wild))
        # two fields always come from one dataset, so wild rolls stay single dataset
        self.assertTrue(all(i.profile.get("single") for i in wild))
        self.assertFalse(any("-(-" in i.expression for i in wild))

    def test_settings_shuffle_uses_region_options(self):
        items = self.R.roll(n=8, mode="wild", seed=5, shuffle_settings=True)
        self.assertGreater(len({(i.settings["decay"], i.settings["neutralization"]) for i in items}), 1)
        fixed = self.R.roll(n=4, mode="wild", seed=5, shuffle_settings=False)
        self.assertEqual({i.settings["decay"] for i in fixed}, {0})

    def test_table(self):
        t = play.items_table(self.R.roll(n=3, seed=1))
        self.assertEqual(list(t.columns), ["source", "rolled", "expression", "settings", "IS test", "linter", "idea"])


class TestPlay(unittest.TestCase):
    def test_play_journals_and_counts_as_tries(self):
        R = Researcher.sandbox()
        items = R.roll(n=3, mode="mix", seed=21)
        res = R.play(items)
        self.assertEqual(len(res), 3)
        ex = R.journal.experiments()
        self.assertEqual(set(ex["purpose"]), {"play"})
        self.assertTrue(all(str(k).startswith("play:") for k in ex["idea_id"]))
        # every roll is a try for its idea: the gate's deflated Sharpe sees it
        self.assertEqual(sum(R.journal.trials(k) for k in set(ex["idea_id"])), 3)
        self.assertEqual(R.journal.idea(res[0].key)["family"], "play")
        st = play.play_stats(R.journal)
        self.assertEqual((st["plays"], st["today"]), (3, 3))
        self.assertIsNotNone(st["best_sharpe"])

    def test_stats_on_empty_journal(self):
        R = Researcher.sandbox()
        self.assertEqual(play.play_stats(R.journal)["plays"], 0)


class TestTheme(unittest.TestCase):
    def test_verdict_badges_and_loading_lines(self):
        md = Diagnosis("PASS", "clears Sharpe and fitness", [], [], {}).markdown()
        self.assertIn('class="hl-verdict hl-v-pass"', md)
        self.assertTrue(theme.loading_line("2 alphas").endswith("[2 alphas]"))
        self.assertEqual(theme.TEAL, theme.CODE)           # old names still work


if __name__ == "__main__":
    unittest.main()
