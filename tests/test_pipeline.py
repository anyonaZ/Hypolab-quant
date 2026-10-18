"""End-to-end tests on the offline sandbox (synthetic market with planted signals).

These prove the whole loop works: idea -> bind -> lint -> simulate -> diagnose -> robustness -> gate -> submit,
and that the system can tell planted signal from noise.
"""
import os
import tempfile
import unittest

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab.catalog import Catalog  # noqa: E402
from hypolab.ideas import generate_ideas  # noqa: E402
from hypolab.research import Researcher  # noqa: E402
from hypolab import playground as pg  # noqa: E402


class TestSandboxLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R = Researcher.sandbox()
        cls.cards = {c.hypothesis.id: c for c in cls.R.ideas("SBX", n=40, one_per_family=False)}

    def test_ideas_bind_and_lint(self):
        self.assertGreaterEqual(len(self.cards), 10)
        for c in self.cards.values():
            self.assertTrue(c.steps, c.hypothesis.id)
            for s in c.steps:
                self.assertTrue(s.lint.ok, f"{c.hypothesis.id}: {s.lint.report() if hasattr(s.lint, 'report') else ''}")

    def test_full_loop_to_submission(self):
        card = self.cards["ANL_REVISION_BREADTH"]
        t = self.R.test(card, rung=min(1, len(card.steps) - 1))
        self.assertEqual(t.diagnosis.verdict, "PASS", t.diagnosis.headline)
        again = self.R.test(card, rung=min(1, len(card.steps) - 1))
        self.assertTrue(again.cached)                          # no simulation wasted on a repeat
        rb = self.R.robustness(t)
        gate = self.R.gate(t, rb)
        self.assertTrue(gate.ready, gate.reasons)
        with self.assertRaises(Exception):
            self.R.submit(gate, confirm="yes")                 # must type the exact confirmation
        self.R.submit(gate, confirm=f"SUBMIT {gate.alpha_id}")
        self.assertEqual(len(self.R.journal.submissions()), 1)

    def test_linter_blocks_before_simulating(self):
        before = len(self.R.journal.experiments())
        t = self.R.test(expression="sigmoid(close)")
        self.assertEqual(t.diagnosis.verdict, "BLOCKED")
        self.assertEqual(len(self.R.journal.experiments()), before)


class TestSignalVsNoise(unittest.TestCase):
    def test_noise_does_not_pass_but_planted_signal_does(self):
        R = Researcher.sandbox()
        data = R.brain.data
        noise = pg.run([f"rank(ts_delta(nz_{j:03d}, 21))" for j in range(8)], data, decay=4)
        self.assertTrue((noise["sharpe"].abs() < 1.58).all(), noise)
        sig = pg.run(["group_rank(ts_mean(ts_backfill(anl_rev_up_30d, 21) - ts_backfill(anl_rev_down_30d, 21), 21), subindustry)"],
                     data, decay=4)
        self.assertGreater(sig["sharpe"].iloc[0], 1.58)


class TestBundledCatalog(unittest.TestCase):
    def test_glb_snapshot_ideas(self):
        cat = Catalog()
        if not cat.has_context("GLB", "MINVOL1M", 1):
            cat.load_bundled()
        cards = generate_ideas(cat, "GLB", "MINVOL1M", n=10)
        self.assertGreaterEqual(len(cards), 5)
        for c in cards:
            self.assertEqual(c.settings.get("neutralization") in ("SUBINDUSTRY", "INDUSTRY"), False,
                             "GLB should not use SUBINDUSTRY/INDUSTRY by default")


class TestVolumeAndOriginality(unittest.TestCase):
    """BRAIN expects high simulation volume; hypolab must spend it honestly and catch copied ideas."""

    @classmethod
    def setUpClass(cls):
        cls.R = Researcher.sandbox()

    def test_scan_rejects_noise_and_counts_every_probe(self):
        df = self.R.scan("sbx_model")
        self.assertGreaterEqual(len(df), 30)
        noise_hits = df[df["field"].str.startswith("nz_") & df["above_noise_bar"]]
        self.assertTrue(noise_hits.empty, noise_hits)
        # an alpha built from the luckiest scanned field is deflated by the whole scan
        best = df.iloc[0]
        card = self.R._cards[best["idea"]]
        t = self.R.test(card, rung=0)
        gate = self.R.gate(t, self.R.robustness(t))
        self.assertFalse(gate.ready)
        self.assertTrue(any("incl. dataset scan" in r for r in gate.reasons), gate.reasons)

    def test_copied_textbook_alpha_fails_production_correlation(self):
        cards = {c.hypothesis.id: c for c in self.R.ideas("SBX", n=40, one_per_family=False)}
        card = cards["FND_CASHFLOW_YIELD"]                    # rung 0 == the sandbox's "production" alpha
        t = self.R.test(card, rung=0)
        gate = self.R.gate(t, self.R.robustness(t))
        self.assertFalse(gate.ready)
        self.assertTrue(any("PRODUCTION correlation" in r for r in gate.reasons), gate.reasons)


class TestBoost(unittest.TestCase):
    """A weak-but-real alpha (Sharpe ~1.0) boosted by an independent signal, with honest bookkeeping."""

    @classmethod
    def setUpClass(cls):
        cls.R = Researcher.sandbox()
        cls.cards = {c.hypothesis.id: c for c in cls.R.ideas("SBX", n=40, one_per_family=False)}
        cls.base = cls.R.test(cls.cards["FND_GROSS_PROFITABILITY"], rung=0)
        cls.rep = cls.R.boost(cls.base, k=6)

    def test_boost_lifts_weak_alpha_to_pass(self):
        self.assertLess(self.base.summary["is_sharpe"], 1.58)
        self.assertIsNotNone(self.rep.best)
        self.assertEqual(self.rep.best.diagnosis.verdict, "PASS")
        self.assertGreater(self.rep.best.summary["is_sharpe"], 1.58)
        gate = self.R.gate(self.rep.best, self.R.robustness(self.rep.best))
        self.assertTrue(gate.ready, gate.reasons)

    def test_refuses_useless_or_dominant_boosters(self):
        why = dict(zip(self.rep.table["booster"], self.rep.table["why"]))
        self.assertIn("better ON ITS OWN", why["ERN_PEAD"])            # strong booster would carry the combo
        self.assertIn("no signal", why["ANL_EPS_REVISION"])          # booster without signal adds noise

    def test_combinations_count_as_tries_on_the_base_idea(self):
        n_combos = int(self.rep.table["combined_sharpe"].notna().sum())
        self.assertEqual(self.R.journal.trials(self.base.card.id), 1 + n_combos)

    def test_combine_keeps_variables_apart(self):
        from hypolab.linter import Linter
        from hypolab.research import _combine
        e = _combine("a = rank(close); b = ts_mean(a, 5); b", "a = rank(volume); -a")
        self.assertTrue(Linter().lint(e).ok, e)
        self.assertIn("base_sig_a", e)
        self.assertIn("boost_sig_a", e)


if __name__ == "__main__":
    unittest.main()
