"""Tests for the pieces that connect HYPOLAB to the Idea Engine and the marimo cockpit:
your own card files, building one card by id, the read-only journal, and submissions that survive a restart."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab import config  # noqa: E402
from hypolab import hypotheses as hyp  # noqa: E402
from hypolab.journal import Journal  # noqa: E402
from hypolab.research import Researcher  # noqa: E402

MY_CARD = """
- id: IE_TEST_REVERSAL
  title: Test card - one-week reversal written by me
  category: pv
  family: ie_test_reversal
  horizon: fast
  strength: 1
  story: Liquidity-driven moves revert.
  why_persists: You are paid for providing liquidity.
  references: ["Jegadeesh (1990)"]
  roles: {}
  ladder:
    - name: core
      expr: "group_rank(-ts_sum(returns, 5), subindustry)"
      teaches: "Plain reversal."
  settings: {neutralization: SUBINDUSTRY, decay: 3, truncation: 0.08}
  expected_turnover: [0.2, 0.7]
"""

CLASH = """
- id: PV_REV_QUIET
  title: A card that tries to replace a built-in one
  family: x
  ladder:
    - name: core
      expr: "rank(close)"
"""


class OwnHome:
    """Point config.HOME at a fresh folder for one test, so other test modules never see these files."""

    def __enter__(self):
        self.old = config.HOME
        config.HOME = Path(tempfile.mkdtemp(prefix="hypolab_links_"))
        hyp.user_library_dir().mkdir(parents=True)
        return config.HOME

    def __exit__(self, *exc):
        config.HOME = self.old


class TestUserLibrary(unittest.TestCase):
    def test_builtin_only_without_user_files(self):
        with OwnHome():
            lib = hyp.load_library()
            self.assertEqual({h.source for h in lib}, {"library"})
            self.assertEqual(hyp.LOAD_WARNINGS, [])

    def test_user_cards_load_and_are_marked_mine(self):
        with OwnHome():
            (hyp.user_library_dir() / "my_cards.yaml").write_text(MY_CARD)
            lib = hyp.load_library()
            mine = [h for h in lib if h.source == "mine"]
            self.assertEqual([h.id for h in mine], ["IE_TEST_REVERSAL"])
            self.assertEqual(hyp.validate_library(mine), [])
            self.assertEqual(len(hyp.load_library(include_user=False)), len(lib) - 1)

    def test_clash_and_broken_file_never_break_the_library(self):
        with OwnHome():
            d = hyp.user_library_dir()
            (d / "a_clash.yaml").write_text(CLASH)
            (d / "b_broken.yaml").write_text("- id: [unclosed")
            lib = hyp.load_library()
            builtin = next(h for h in lib if h.id == "PV_REV_QUIET")
            self.assertEqual(builtin.source, "library")            # built-in id wins
            self.assertEqual(sum(h.id == "PV_REV_QUIET" for h in lib), 1)
            self.assertEqual(len(hyp.LOAD_WARNINGS), 2, hyp.LOAD_WARNINGS)


class TestCardById(unittest.TestCase):
    def test_builtin_and_own_card_bind_in_sandbox(self):
        with OwnHome():
            (hyp.user_library_dir() / "my_cards.yaml").write_text(MY_CARD)
            R = Researcher.sandbox()
            c = R.card("ANL_REVISION_BREADTH")
            self.assertTrue(c.steps and all(s.lint.ok for s in c.steps))
            mine = R.card("IE_TEST_REVERSAL")
            self.assertEqual(mine.hypothesis.source, "mine")
            t = R.test(mine, rung=0)
            self.assertIn(t.diagnosis.verdict, {"PASS", "NEAR", "WEAK", "NOISE", "INVERTED"})
            with self.assertRaises(KeyError):
                R.card("NO_SUCH_CARD")


class TestJournalAccess(unittest.TestCase):
    def test_wal_and_readonly(self):
        path = Path(tempfile.mkdtemp()) / "journal.sqlite"
        j = Journal(path)
        self.assertEqual(j.db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        j.add_lesson("written by the notebook")
        ro = Journal.open_readonly(path)
        self.assertEqual(len(ro.lessons()), 1)                 # the reader sees the writer's rows
        with self.assertRaises(sqlite3.OperationalError):
            ro.add_lesson("the cockpit must not write through a read-only journal")

    def test_readonly_on_a_fresh_install(self):
        path = Path(tempfile.mkdtemp()) / "journal.sqlite"
        ro = Journal.open_readonly(path)
        self.assertTrue(ro.experiments().empty)


class TestSubmitAfterRestart(unittest.TestCase):
    def test_family_and_categories_come_from_the_journal(self):
        R = Researcher.sandbox()
        card = R.card("ANL_REVISION_BREADTH")
        t = R.test(card, rung=min(1, len(card.steps) - 1))
        self.assertEqual(t.diagnosis.verdict, "PASS", t.diagnosis.headline)
        gate = R.gate(t, R.robustness(t))
        self.assertTrue(gate.ready, gate.reasons)
        R._cards.clear()                                       # what a kernel restart does
        R.submit(gate, confirm=f"SUBMIT {gate.alpha_id}")
        sub = R.journal.submissions().iloc[-1]
        self.assertEqual(sub["family"], card.family)
        self.assertEqual(sorted(sub["categories"].split(",")), sorted(card.categories))


class TestSandboxLeavesCatalogAlone(unittest.TestCase):
    def test_sandbox_does_not_write_the_real_catalog_and_live_gets_glb(self):
        from hypolab.catalog import Catalog
        with OwnHome():
            Researcher.sandbox()
            real = Catalog()
            self.assertFalse(real.has_context("SBX", "SANDBOX", 1))     # practice data stayed in memory
            # an old install where the sandbox DID write into the file
            real.ingest_payload({"region": "SBX", "universe": "SANDBOX", "delay": 1, "datasets": [],
                                 "fields": [{"id": "x", "dataset": "d"}]})
            from unittest import mock
            with mock.patch("hypolab.connect.client", return_value=object()):
                R = Researcher.live("GLB", login=False, sync=False)
            self.assertTrue(R.catalog.has_context("GLB", "MINVOL1M", 1))
            self.assertFalse(R.catalog.has_context("SBX", "SANDBOX", 1))


class TestPyramidCountsWithGaps(unittest.TestCase):
    """Seen live on 2026-10-10: BRAIN's diversity rows without a delay crashed the Pyramids tab."""

    def test_missing_values_do_not_crash(self):
        import pandas as pd
        from hypolab.pyramids import PyramidTracker
        df = pd.DataFrame([{"region": "USA", "delay": 1.0, "category": "analyst", "alphas": 2},
                           {"region": "USA", "delay": None, "category": "pv", "alphas": 3},
                           {"region": None, "delay": 1, "category": "pv", "alphas": 1},
                           {"region": "GLB", "delay": float("nan"), "category": None, "alphas": None}])
        t = PyramidTracker(df, alphas_per_pyramid=3, regions=["USA", "GLB"])
        m = t.matrix()
        self.assertEqual(int(m.loc["USA", "Analyst"]), 2)
        self.assertEqual(int(m.loc["USA", "Price Volume"]), 3)
        self.assertEqual(int(m.loc["GLB", "Other"]), 0)          # a row without a category is a total, not Other
        self.assertEqual(len(t.notes), 2)
        self.assertFalse(t.plan(5).empty)

    def test_live_rows_from_2026_10_10(self):
        """Zacc's real diversity answer: category cells plus per-region subtotals (category null)."""
        from hypolab.brain import BrainClient
        from hypolab.pyramids import PyramidTracker
        cell = lambda reg, cat, n: {"region": reg, "delay": 1, "alphaCount": n,
                                    "dataDiversity": {"check": "PASS", "limit": 0.3},
                                    "dataCategory": {"id": cat, "name": cat.title()}}
        none = {"name": None, "id": None}
        raw = [cell("GLB", "fundamental", 1), cell("GLB", "model", 1), cell("GLB", "other", 1), cell("GLB", "pv", 1),
               {"region": "GLB", "delay": 1, "dataCategory": none, "alphaCount": 2},
               {"region": "GLB", "delay": None, "dataCategory": none, "alphaCount": 2},
               cell("IND", "model", 20),
               {"region": "IND", "delay": 1, "dataCategory": none, "alphaCount": 20},
               {"region": "IND", "delay": None, "dataCategory": none, "alphaCount": 20}]

        class B:
            user_id = "self"

            def _get_json(self, path, params=None):
                return {"alphas": raw}
        df = BrainClient.diversity(B())
        self.assertEqual(list(df["kind"]).count("cell"), 5)
        t = PyramidTracker(df, alphas_per_pyramid=3, regions=["GLB", "IND"])
        m = t.matrix()
        self.assertEqual(int(m.loc["IND", "Model"]), 20)
        self.assertEqual(int(m.loc["IND", "Other"]), 0)
        self.assertEqual(int(m.loc["GLB", "Other"]), 1)
        self.assertEqual(int(m.loc["GLB", "Price Volume"]), 1)
        self.assertEqual(t.notes, [])
        tot = t.totals.set_index(["region", "delay"])["alphas"].to_dict()
        self.assertEqual(tot, {("GLB", "1"): 2, ("GLB", "all"): 2, ("IND", "1"): 20, ("IND", "all"): 20})
        self.assertEqual(t.filled(), 1)


class TestConfig(unittest.TestCase):
    def test_region_defaults_hold_only_regions(self):
        for k, v in config.REGION_DEFAULTS.items():
            self.assertIsInstance(v, dict, k)
            self.assertIn("universe", v, k)


if __name__ == "__main__":
    unittest.main()
