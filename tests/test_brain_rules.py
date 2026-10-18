"""1.3.2: BRAIN's own rules (docs/BRAIN_RULES.md) as HYPOLAB applies them.

Single-dataset test, sub-universe cutoff, fitness labels, BRAIN's day, quota headers, account regions and
simulation options, quarter Pyramids, multipliers, tie-breakers, Osmosis check, risk-set re-runs.
"""
import datetime as dt
import json
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

import pandas as pd  # noqa: E402

from hypolab import account as acct  # noqa: E402
from hypolab import config, rules  # noqa: E402
from hypolab.brain import make_payload, quota, record_quota  # noqa: E402
from hypolab.diagnose import diagnose  # noqa: E402
from hypolab.journal import Journal  # noqa: E402
from hypolab.pyramids import PyramidTracker, multiplier_table  # noqa: E402
from hypolab.research import Researcher  # noqa: E402

DS = {"close": "pv1", "cap": "pv1", "volume": "pv1", "fnd_x": "fundamental6", "anl_y": "analyst4"}.get


class TestSingleDataset(unittest.TestCase):
    def test_profile(self):
        p = rules.dataset_profile("group_rank(ts_delta(close, 5), subindustry)", DS)
        self.assertTrue(p["single"])
        self.assertEqual(p["cutoff"], 2.38)
        self.assertEqual(rules.dataset_profile("rank(close)", DS, delay=0)["cutoff"], 3.96)
        multi = rules.dataset_profile("group_rank(fnd_x / cap, industry)", DS)
        self.assertFalse(multi["single"])
        self.assertEqual(multi["datasets"], ["fundamental6", "pv1"])
        self.assertIsNone(rules.dataset_profile("rank(unknown_field)", DS)["single"])

    def test_grouping_fields_and_pv1_operators(self):
        # grouping fields don't count; inst_pnl()/convert() count as pv1 [S1]
        self.assertTrue(rules.dataset_profile("group_neutralize(fnd_x, bucket(rank(fnd_x), range=\"0,1,0.1\"))",
                                              DS)["single"])
        p = rules.dataset_profile("rank(fnd_x) * inst_pnl(fnd_x)", DS)
        self.assertEqual(p["datasets"], ["fundamental6", "pv1"])

    def test_assigned_variables_are_not_fields(self):
        self.assertEqual(rules.fields_in("a = ts_rank(close, 5); a / cap"), ["close", "cap"])

    def test_cards_carry_the_test(self):
        R = Researcher.sandbox()
        steps = [s for c in R.ideas() for s in c.steps]
        self.assertTrue(any(s.single_dataset for s in steps))
        self.assertTrue(any(s.single_dataset is False for s in steps))
        self.assertIn("2Y Sharpe >= 2.38", next(s.is_test for s in steps if s.single_dataset))

    def test_sandbox_applies_cutoff(self):
        R = Researcher.sandbox()
        single = R.test(expression="group_rank(ts_backfill(ern_eps_surprise, 63), subindustry)",
                        settings={"region": "SBX"})
        chk = {c["name"]: c for c in R.brain.alpha(single.alpha_id)["is"]["checks"]}
        self.assertEqual(chk["LOW_2Y_SHARPE"]["limit"], 2.38)
        self.assertIn("single dataset", single.diagnosis.markdown())
        multi = R.test(expression="group_rank(ts_backfill(fnd_cfo, 252) / cap, subindustry)",
                       settings={"region": "SBX"})
        chk = {c["name"]: c for c in R.brain.alpha(multi.alpha_id)["is"]["checks"]}
        self.assertEqual(chk["LOW_2Y_SHARPE"]["limit"], 1.58)
        # sub-universe = 0.75 * sqrt(0.5) * Sharpe for the sandbox's liquid half [S9]
        s = R.brain.alpha(multi.alpha_id)["is"]["sharpe"]
        self.assertAlmostEqual(chk["LOW_SUB_UNIVERSE_SHARPE"]["limit"], round(0.5303 * abs(s), 2), places=1)


class TestNumbers(unittest.TestCase):
    def test_sub_universe_example_from_brain(self):
        self.assertAlmostEqual(rules.sub_universe_cutoff(2.73, 1000, 3000), 1.18, places=2)

    def test_fitness_labels(self):
        self.assertEqual(rules.fitness_label(2.6), "Spectacular")
        self.assertEqual(rules.fitness_label(1.6), "Good")
        self.assertEqual(rules.fitness_label(1.0), "Needs Improvement")
        self.assertEqual(rules.fitness_label(1.6, delay=0), "Average")

    def test_brain_day_is_new_york(self):
        # 10 Oct 2026 05:00 UTC = 01:00 New York (EDT) -> day began 04:00 UTC
        t = dt.datetime(2026, 10, 10, 5, 0, tzinfo=dt.timezone.utc)
        start = dt.datetime.fromtimestamp(rules.brain_day_start(t), dt.timezone.utc)
        self.assertEqual((start.hour, start.day), (4, 10))
        # 02:00 UTC is still the previous New York day
        start = dt.datetime.fromtimestamp(rules.brain_day_start(t.replace(hour=2)), dt.timezone.utc)
        self.assertEqual((start.hour, start.day), (4, 9))

    def test_quarter_and_osmosis_deadline(self):
        self.assertEqual(rules.quarter_bounds(dt.date(2026, 10, 10)), (dt.date(2026, 10, 1), dt.date(2026, 12, 31)))
        self.assertEqual(rules.osmosis_lock_deadline(dt.date(2026, 12, 31)), dt.date(2026, 11, 15))


class TestQuotaAndRegions(unittest.TestCase):
    def test_quota_headers(self):
        q = record_quota({"X-Ratelimit-Limit": "5000", "X-Ratelimit-Remaining": "4321", "X-Ratelimit-Reset": "3600"})
        self.assertEqual(q["remaining"], 4321)
        self.assertEqual(quota()["limit"], 5000)
        self.assertIsNone(record_quota({"Content-Type": "json"}))
        record_quota({"X-Ratelimit-Remaining": "1", "X-Ratelimit-Reset": "0"})
        self.assertIsNone(quota())            # already reset

    def test_account_regions_default(self):
        self.assertEqual(config.account_regions(),
                         ["USA", "GLB", "EUR", "ASI", "CHN", "JPN", "AMR", "IND", "DEU", "GBR"])
        self.assertNotIn("KOR", config.account_regions())

    def test_unknown_universe_is_refused_until_synced(self):
        saved = dict(config.REGION_DEFAULTS["DEU"])
        try:
            config.REGION_DEFAULTS["DEU"]["universe"] = None
            with self.assertRaises(ValueError):
                make_payload("rank(close)", region="DEU")
            config.apply_sim_options([{"region": "DEU", "delays": [1, 0], "universes": ["TOP400", "TOP1200"],
                                       "neutralizations": ["MARKET", "SUBINDUSTRY", "SLOW", "FAST"]}])
            self.assertEqual(make_payload("rank(close)", region="DEU")["settings"]["universe"], "TOP1200")
            self.assertIn("SLOW", config.region_neutralizations("DEU"))
        finally:
            config.REGION_DEFAULTS["DEU"] = saved


class TestDiagnose(unittest.TestCase):
    def _summary(self, failed, tvr=0.1):
        return {"alpha_id": "A", "status": "COMPLETE", "is_sharpe": 2.0, "is_fitness": 1.6, "is_turnover": tvr,
                "is_returns": 0.1, "failed": failed}

    def test_correlation_advice_follows_brain(self):
        d = diagnose(self._summary(["SELF_CORRELATION"]), "rank(close)", {"region": "USA", "decay": 0})
        self.assertIn("equivalent", d.actions[0].title)
        self.assertEqual(d.metrics["fitness_label"], "Good")

    def test_risk_set_suggested_when_offered(self):
        saved = config.REGION_DEFAULTS["USA"].get("neutralizations")
        try:
            config.REGION_DEFAULTS["USA"]["neutralizations"] = ["MARKET", "SUBINDUSTRY", "SLOW", "SLOW_AND_FAST"]
            d = diagnose(self._summary(["PROD_CORRELATION"], tvr=0.05), "rank(close)",
                         {"region": "USA", "neutralization": "SUBINDUSTRY"})
            self.assertTrue(any(a.settings.get("neutralization") == "SLOW" for a in d.actions))
            d = diagnose(self._summary(["PROD_CORRELATION"], tvr=0.4), "rank(close)",
                         {"region": "USA", "neutralization": "SUBINDUSTRY"})
            self.assertTrue(any(a.settings.get("neutralization") == "SLOW_AND_FAST" for a in d.actions))
        finally:
            config.REGION_DEFAULTS["USA"]["neutralizations"] = saved

    def test_sub_universe_split_decay(self):
        d = diagnose(self._summary(["LOW_SUB_UNIVERSE_SHARPE"]), "rank(close)", {"region": "USA"})
        self.assertIn("ts_decay_linear(rank(close), 5) * rank(volume * close)", d.actions[0].expression)


def _alpha(i, region, date, code, **kw):
    a = {"id": f"{region}{i}", "type": "REGULAR", "status": "ACTIVE", "dateSubmitted": date,
         "settings": {"region": region, "delay": 1, "universe": "TOP500"}, "regular": {"code": code},
         "is": {"sharpe": 1.5, "turnover": 0.12}}
    a.update(kw)
    return a


class TestAccountGenius(unittest.TestCase):
    def setUp(self):
        self.J = Journal(":memory:")
        al = [_alpha(i, "IND", "2026-08-03T12:00:00-04:00", "rank(ts_delta(mdl_x, 5))", osmosisPoints=100000)
              for i in range(12)]
        al.append(_alpha(1, "GLB", "2026-10-05T12:00:00-04:00", "group_rank(fnd_x / cap, subindustry)",
                         pyramids=[{"name": "GLB/D1/FUNDAMENTAL"}, {"name": "GLB/D1/PRICE VOLUME"}]))
        al.append(_alpha(2, "USA", "2026-10-06T12:00:00-04:00", "rank(anl_y)"))
        acct.store_alphas(self.J, al, op_names=["rank", "ts_delta", "group_rank", "divide"])

    def test_tiebreakers_match_genius_definition(self):
        tb = acct.tiebreakers(self.J, 2026, 4)
        self.assertEqual(tb["alphas"], 2)
        self.assertEqual(tb["operators per alpha"], 1.5)      # {group_rank, divide} and {rank}
        self.assertEqual(tb["distinct fields"], 3)            # fnd_x, cap, anl_y (subindustry is a group)

    def test_quarter_pyramids(self):
        class Cat:
            def fields(self, region, universe, delay, enrich=False):
                return pd.DataFrame({"id": ["anl_y"], "category": ["analyst"]})
        counts, notes = acct.quarter_pyramids(self.J, Cat(), 2026, 4)
        cells = {(r.region, r.category) for r in counts.itertuples()}
        self.assertEqual(cells, {("GLB", "fundamental"), ("GLB", "pv"), ("USA", "analyst")})
        self.assertFalse(any("IND" in n for n in notes))      # Q3 alphas are not this quarter

    def test_osmosis_check(self):
        tab, notes = acct.osmosis_check(self.J)
        ind = tab[tab["scope"] == "IND / D1"].iloc[0]
        self.assertTrue(ind["eligible"])
        self.assertTrue(any("1,200,000" in n for n in notes))
        self.assertTrue(any("needs at least 3" in n for n in notes))

    def test_old_journal_gains_extra_column(self):
        path = os.path.join(tempfile.mkdtemp(), "j.sqlite")
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE account_alphas (alpha_id TEXT PRIMARY KEY, type TEXT, status TEXT, "
                   "date_submitted TEXT, date_created TEXT, region TEXT, universe TEXT, delay INTEGER, "
                   "neutralization TEXT, decay INTEGER, truncation REAL, code TEXT, sharpe REAL, fitness REAL, "
                   "turnover REAL, returns REAL, drawdown REAL, operators TEXT, fields TEXT, name TEXT, tags TEXT, "
                   "synced REAL)")
        db.commit()
        db.close()
        J = Journal(path)
        self.assertEqual(acct.store_alphas(J, [_alpha(1, "USA", "2026-10-06T12:00:00-04:00", "rank(close)")],
                                           op_names=["rank"]), 1)


class TestPyramidMultipliers(unittest.TestCase):
    def test_snapshot_and_offered_cells(self):
        m = multiplier_table()
        self.assertEqual(len(m), 225)
        t = PyramidTracker(None, multipliers=m)
        self.assertEqual(t.multiplier("DEU", 1, "analyst"), 1.8)
        self.assertFalse(t.offered("JPN", 1, "news"))          # blank on the Genius page
        plan = t.plan(200)
        self.assertFalse(((plan["region"] == "JPN") & (plan["category"] == "News")).any())
        self.assertGreaterEqual(t.plan(5, by="multiplier")["multiplier"].iloc[0], 1.8)
        self.assertTrue(set(t.plan(200, delay=0)["region"]) <= {"USA", "EUR", "CHN", "JPN", "AMR", "DEU", "GBR"})

    def test_live_shape_is_parsed(self):
        live = pd.DataFrame([{"region": "USA", "delay": 1, "category.id": "analyst", "multiplier": 1.2}])
        m = multiplier_table(live)
        self.assertEqual(m.attrs["source"], "BRAIN (live)")
        self.assertEqual(m.iloc[0]["multiplier"], 1.2)


class TestRerun(unittest.TestCase):
    def test_variants_and_budget(self):
        R = Researcher.sandbox()
        saved = config.REGION_DEFAULTS["SBX"].get("neutralizations")
        try:
            config.REGION_DEFAULTS["SBX"]["neutralizations"] = ["MARKET", "SUBINDUSTRY", "SLOW", "FAST"]
            a = {"alpha_id": "X9", "code": "group_rank(ts_backfill(ern_eps_surprise, 63), subindustry)",
                 "region": "SBX", "universe": "SANDBOX", "delay": 1, "neutralization": "SUBINDUSTRY", "decay": 3,
                 "truncation": 0.08}
            v = R.rerun_variants(a)
            self.assertEqual([x["settings"]["neutralization"] for x in v], ["SLOW", "FAST"])
            res = R.rerun(a, v)
            self.assertEqual({t.key for t in res}, {"rerun:X9"})
            self.assertEqual(R.journal.trials("rerun:X9"), 2)
            self.assertEqual(R.journal.idea("rerun:X9")["family"], "rerun")
        finally:
            config.REGION_DEFAULTS["SBX"]["neutralizations"] = saved


if __name__ == "__main__":
    unittest.main()
