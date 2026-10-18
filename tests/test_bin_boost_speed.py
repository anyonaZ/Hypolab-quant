"""1.4.3: bin noise cards, see boosted alphas and their PnL, and a faster start on big catalogs."""
import os
import tempfile
import time
import unittest

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab import config  # noqa: E402
from hypolab.catalog import Catalog  # noqa: E402
from hypolab.concepts import CONCEPTS  # noqa: E402
from hypolab.research import BoostReport, Researcher, card_of_idea  # noqa: E402


class TestBin(unittest.TestCase):
    def test_bin_hides_card_everywhere_and_restore_brings_it_back(self):
        R = Researcher.sandbox()
        first = R.ideas(n=40)
        victim = first[0].hypothesis.id
        R.bin(victim, "noise - no real signal")
        self.assertIn(victim, R.journal.binned_ids())
        self.assertNotIn(victim, [c.hypothesis.id for c in R.ideas(n=40)])
        for seed in range(6):
            self.assertFalse(any(i.card is not None and i.card.hypothesis.id == victim
                                 for i in R.roll(n=4, mode="cards", seed=seed)))
        b = R.binned()
        self.assertEqual(list(b["hypothesis_id"]), [victim])
        self.assertEqual(b["reason"].iloc[0], "noise - no real signal")
        R.restore(victim)
        self.assertEqual(R.journal.binned_ids(), set())
        self.assertIn(victim, [c.hypothesis.id for c in R.ideas(n=40)])

    def test_binned_results_leave_the_restore_list_but_stay_in_the_journal(self):
        R = Researcher.sandbox()
        card = R.card("ERN_PEAD", "SBX")
        R.test(card)
        self.assertEqual(len(R.recent_results()), 1)
        R.bin("ERN_PEAD")
        self.assertEqual(R.recent_results(), [])
        self.assertEqual(len(R.journal.experiments()), 1)

    def test_card_of_idea(self):
        self.assertEqual(card_of_idea("ERN_PEAD@USA"), "ERN_PEAD")
        self.assertEqual(card_of_idea("play:ERN_PEAD@USA"), "ERN_PEAD")
        self.assertIsNone(card_of_idea("play:wild:pv1@USA"))
        self.assertIsNone(card_of_idea("manual@USA"))
        self.assertIsNone(card_of_idea(None))


class TestBoostVisible(unittest.TestCase):
    def _base(self, R):
        # a real-but-weak alpha in the practice market (Sharpe ~0.8 at seed 7) that boosters can lift
        t = R.test(R.card("FND_CASHFLOW_YIELD", "SBX"), rung=0)
        self.assertTrue(t.alpha_id)
        return t

    def test_boost_results_are_labelled_listed_and_drawable(self):
        R = Researcher.sandbox()
        base = self._base(R)
        rep = R.boost(base, k=6)
        self.assertIsInstance(rep, BoostReport)
        self.assertGreater(len(rep.results), 0)                  # combinations were really simulated
        self.assertTrue(all(b.rung.startswith("booster alone") for b in rep.boosters.values()))
        self.assertEqual(set(rep.boosters), set(rep.table["booster"]))
        self.assertIn("booster_alpha", rep.table.columns)
        self.assertIn("combined_alpha", rep.table.columns)
        lab = rep.lab_results()
        if rep.best is not None:
            self.assertIs(lab[-1], rep.best)                    # the best is the one the Lab shows
        for t in rep.results.values():
            self.assertIn("boost:", t.rung)
            self.assertIn(t, lab)
        self.assertTrue({base.alpha_id} <= rep.alpha_ids())
        ex = R.journal.experiments()
        boosts = ex[ex["purpose"] == "boost"]
        self.assertEqual(len(boosts), len(rep.results))
        self.assertTrue(all("boost:" in r for r in boosts["rung"]))   # recognisable after a restart
        back = R.recent_results(50)
        self.assertEqual(sum("boost:" in t.rung for t in back), len(rep.results))

    def test_performance_draws_pnl_with_comparison_lines(self):
        R = Researcher.sandbox()
        base = self._base(R)
        other = R.test(R.card("ERN_PEAD", "SBX"), rung=0)
        p = R.performance(base, compare={"other": other.alpha_id if other.alpha_id != base.alpha_id else None})
        self.assertEqual(p["error"], "")
        self.assertFalse(p["pnl"].empty)
        self.assertTrue(p["pnl"].columns[0].startswith("this alpha"))
        from ideaengine import views
        fig = views.pnl_figure(p["pnl"], title="t")
        self.assertEqual(len(fig.axes[0].lines) - 1, len(p["pnl"].columns))   # minus the zero line
        blocked = R.test(expression="rank(", settings={"region": "SBX"})
        self.assertIn("no alpha id", R.performance(blocked)["error"])


class TestSpeed(unittest.TestCase):
    def test_concept_matching_unchanged_by_the_fast_path(self):
        samples = [("ern_eps_surprise", "Earnings surprise: actual minus consensus estimate"),
                   ("fnd_sales", "Total revenues"), ("turnover_ratio", "Asset turnover ratio"),
                   ("anl_est_eps_fy1", "Mean analyst EPS estimate FY1"), ("returns", "daily returns"),
                   ("ebitda", "EBITDA"), ("book_value_ps", "Book value per share")]
        import re
        for c in CONCEPTS.values():
            for fid, desc in samples:
                text = f"{fid.replace('_', ' ')} | {desc.lower()}"
                # the pre-1.4.3 algorithm, written out
                if fid in c.canonical:
                    want = (3.0, f"standard field '{fid}'")
                elif any(re.search(p, text) for p in c.exclude):
                    want = (0.0, "")
                else:
                    hits = [p for p in c.include if re.search(p, text)]
                    if not hits:
                        want = (0.0, "")
                    else:
                        s = 1.0 + 0.5 * (len(hits) - 1) + (0.5 if any(re.search(p, fid.replace("_", " "))
                                                                       for p in hits) else 0)
                        want = (s, f"matched /{hits[0]}/")
                self.assertEqual(c.match(fid, desc), want, (c.name, fid))

    def test_disk_cache_is_reused_and_invalidated_by_a_sync(self):
        home = tempfile.mkdtemp(prefix="hypolab_cache_")
        cat = Catalog(os.path.join(home, "catalog.sqlite"))
        payload = {"region": "XYZ", "universe": "TOP1", "delay": 1,
                   "datasets": [{"id": "ds1", "category": "fundamental"}],
                   "fields": [{"id": "fnd_sales", "dataset": "ds1", "description": "Total revenues", "coverage": 0.9},
                              {"id": "fnd_assets", "dataset": "ds1", "description": "Total assets", "coverage": 0.9}]}
        cat.ingest_payload(payload)
        a = cat.find_concept("sales", "XYZ", "TOP1", 1)
        files = sorted(os.listdir(os.path.join(home, "cache")))
        self.assertEqual(len(files), 2)                          # enriched fields + concept matches
        cat2 = Catalog(os.path.join(home, "catalog.sqlite"))
        cat2._find_concept = None                                # would crash if it recomputed
        self.assertEqual(list(cat2.find_concept("sales", "XYZ", "TOP1", 1)["id"]), list(a["id"]))
        time.sleep(0.01)
        payload["fields"].append({"id": "fnd_net_sales", "dataset": "ds1", "description": "Net sales",
                                  "coverage": 0.95})
        cat3 = Catalog(os.path.join(home, "catalog.sqlite"))
        cat3.ingest_payload(payload)
        self.assertIn("fnd_net_sales", list(cat3.find_concept("sales", "XYZ", "TOP1", 1)["id"]))
        self.assertEqual(len(os.listdir(os.path.join(home, "cache"))), 2)   # old files replaced, not piled up
        self.assertEqual(cat3.lookup_map("XYZ", "TOP1", 1)["fnd_net_sales"], "ds1")

    def test_in_memory_catalog_never_writes_a_cache(self):
        R = Researcher.sandbox()
        R.ideas(n=5)
        self.assertFalse(R.catalog._disk)

    def test_library_cache_follows_your_card_files(self):
        from hypolab import hypotheses as hyp
        n = len(hyp.load_library())
        self.assertIs(hyp.load_library()[0], hyp.load_library()[0])   # parsed once
        folder = hyp.user_library_dir()
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / "zz_test_cache.yaml"
        src = (config.LIBRARY_DIR / "hypotheses.yaml").read_text()
        import yaml
        raw = yaml.safe_load(src)
        cards = raw["hypotheses"] if isinstance(raw, dict) else raw
        card = dict(cards[0], id="ZZ_CACHE_TEST")
        f.write_text(yaml.safe_dump({"hypotheses": [card]} if isinstance(raw, dict) else [card]))
        try:
            self.assertEqual(len(hyp.load_library()), n + 1)
        finally:
            f.unlink()
        self.assertEqual(len(hyp.load_library()), n)


if __name__ == "__main__":
    unittest.main()
