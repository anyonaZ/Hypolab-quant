"""Phase 3 (1.5.0): card drafts, live checks, approval to my_cards.yaml, and the Claude Projects hand-offs."""
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

import yaml  # noqa: E402

from hypolab import config  # noqa: E402
from hypolab import hypotheses as hyp  # noqa: E402
from hypolab.concepts import CONCEPTS, match_concepts  # noqa: E402
from hypolab.journal import Journal  # noqa: E402
from hypolab.research import Researcher  # noqa: E402
from ideaengine import drafts as D  # noqa: E402
from ideaengine import planner  # noqa: E402
from ideaengine.store import IdeaStore  # noqa: E402

GOOD = {
    "id": "IE_INV_BUILD", "title": "Inventory piling up faster than sales", "category": "auto",
    "family": "inventory_build", "horizon": "slow", "strength": 2, "sign": "-1",
    "story": "When inventory grows faster than sales, demand is weaker than managers expected and margins will be "
             "cut later; investors read the income statement first and react to the balance sheet late.",
    "why_persists": "The signal sits in the balance sheet, which few investors read; analysts anchor on guidance.",
    "references": ["Thomas & Zhang (2002) Inventory Changes and Future Returns, Review of Accounting Studies"],
    "roles": {"inv": {"concept": "inventory"}, "sales": {"concept": "sales"}},
    "ladder": [{"name": "core",
                "expr": "-group_rank(ts_delta(ts_backfill({inv}, 63) / ts_backfill({sales}, 63), 252), subindustry)",
                "teaches": "Change in inventory per unit of sales over a year, against peers."}],
    "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
    "expected_turnover": [0.02, 0.1],
}


class _Home(unittest.TestCase):
    """Each test gets its own ~/.hypolab so approved cards never leak into other test modules."""

    def setUp(self):
        self._old_home = config.HOME
        self._tmp = tempfile.TemporaryDirectory()
        config.HOME = Path(self._tmp.name)
        hyp._LIB_CACHE.clear()
        self.store = IdeaStore(":memory:")
        self.drafts = D.Drafts(self.store)

    def tearDown(self):
        config.HOME = self._old_home
        hyp._LIB_CACHE.clear()
        self._tmp.cleanup()


class TestFormAndYaml(_Home):
    def test_every_builtin_card_survives_form_and_yaml(self):
        for cid, (c, _src) in D.library_raw().items():
            back = yaml.safe_load(D.card_yaml(D.card_from_form(D.form_defaults(c), c)))[0]
            self.assertEqual(hyp._hypothesis(c, "x"), hyp._hypothesis(back, "x"), cid)

    def test_form_keeps_keys_it_does_not_show(self):
        c = dict(GOOD, beginner=True, roles={"inv": {"concept": "inventory", "categories": ["fundamental"],
                                                      "min_coverage": 0.5}, "sales": "sales"})
        c["ladder"] = [dict(GOOD["ladder"][0], when={"inv": ["stock"]})]
        back = D.card_from_form(D.form_defaults(c), c)
        self.assertTrue(back["beginner"])
        self.assertEqual(back["roles"]["inv"]["categories"], ["fundamental"])
        self.assertEqual(back["roles"]["inv"]["min_coverage"], 0.5)
        self.assertEqual(back["ladder"][0]["when"], {"inv": ["stock"]})

    def test_empty_rows_are_dropped_and_none_concept_ignored(self):
        v = D.form_defaults(GOOD)
        v["roles"][3] = {"name": "", "concept": D.NO_CONCEPT, "optional": False, "note": ""}
        card = D.card_from_form(v, GOOD)
        self.assertEqual(set(card["roles"]), {"inv", "sales"})
        self.assertEqual(len(card["ladder"]), 1)

    def test_copy_of_picks_a_free_id(self):
        a = D.copy_of("PV_52W_HIGH")
        self.assertEqual(a["id"], "IE_PV_52W_HIGH_V2")
        b = D.copy_of("PV_52W_HIGH", taken=["IE_PV_52W_HIGH_V2"])
        self.assertEqual(b["id"], "IE_PV_52W_HIGH_V3")


class TestParse(_Home):
    def test_fenced_card_with_from_line(self):
        text = "Here is the card:\n```yaml\n# from: B-20261012-1\n" + yaml.safe_dump([GOOD], sort_keys=False) + "```"
        p = D.parse_cards(text)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0].card["id"], "IE_INV_BUILD")
        self.assertEqual(p[0].source, "B-20261012-1")

    def test_two_cards_and_wrong_pastes(self):
        two = yaml.safe_dump([GOOD, dict(GOOD, id="IE_OTHER")], sort_keys=False)
        self.assertEqual([x.card["id"] for x in D.parse_cards(two)], ["IE_INV_BUILD", "IE_OTHER"])
        self.assertIn("VERDICT", D.parse_cards("verdict:\n  id: X\n  decision: keep\n")[0].errors[0])
        self.assertIn("PLAN", D.parse_cards("plan:\n  week: 2026-W43\n")[0].errors[0])
        err = D.parse_cards("- id: X\n  title: [unclosed\n")[0].errors[0]
        self.assertIn("Not valid YAML", err)


class TestChecks(_Home):
    @classmethod
    def setUpClass(cls):
        cls.R = Researcher.sandbox()

    def test_blank_template_lists_what_is_missing(self):
        rep = D.check_card(D.template(), self.R.catalog, "SBX")
        self.assertFalse(rep.ok)
        where = {c.where for c in rep.errors}
        self.assertTrue({"title", "family", "story", "why_persists", "rung 1"} <= where, where)
        self.assertEqual(rep.state, "draft")

    def test_good_card_passes_and_binds_in_the_sandbox(self):
        rep = D.check_card(GOOD, self.R.catalog, "SBX", journal=self.R.journal)
        self.assertTrue(rep.ok, rep.table())
        self.assertEqual(rep.state, "checked")
        self.assertIsNotNone(rep.idea)
        self.assertEqual({b["field"] for b in rep.bindings}, {"fnd_inventory", "fnd_sales"})
        self.assertTrue(rep.rungs[0]["is_test"].startswith("single dataset"))
        self.assertIn("dry run in SBX", "\n".join(rep.dry_run_lines()))

    def test_errors_surface(self):
        bad = dict(GOOD, id="PV_52W_HIGH", family="Bad Family", strength=5,
                   roles={"inv": {"concept": "inventry"}},
                   ladder=[{"name": "core", "expr": "winsorize({inv}, 4) + rank({missing})", "teaches": "x"}])
        rep = D.check_card(bad, self.R.catalog, "SBX")
        msgs = " | ".join(f"{c.where}: {c.message}" for c in rep.errors)
        self.assertIn("already exists", msgs)               # duplicate id refused
        self.assertIn("snake_case", msgs)
        self.assertIn("did you mean inventory", msgs)
        self.assertIn("NAMED_PARAMETER", msgs)              # Gold operator rule from the linter
        self.assertIn("['missing'] have no role", msgs)
        self.assertIn("strength", msgs)

    def test_warnings_for_fixed_fields_windows_and_family(self):
        c = dict(GOOD, family="pv_momentum",
                 ladder=[{"name": "core", "expr": "rank(ts_mean(fnd6_xyz, 37)) + rank({inv} / {sales})",
                          "teaches": "x"}])
        rep = D.check_card(c, self.R.catalog, "SBX")
        text = " | ".join(c.message for c in rep.checks)
        self.assertIn("field id(s) written directly: fnd6_xyz", text)
        self.assertIn("ARBITRARY_WINDOW", text)
        self.assertIn("same family as", text)

    def test_dead_end_family_from_the_journal(self):
        j = Journal(":memory:")
        j.db.execute("INSERT INTO ideas (id, hypothesis_id, region, family, title, categories, created) "
                     "VALUES ('IE_X@USA','IE_X','USA','inventory_build','x','',0)")
        for i in range(6):
            j.db.execute("INSERT INTO experiments (idea_id, rung, purpose, expression, fingerprint, created, "
                         "verdict, sharpe, backend) VALUES ('IE_X@USA','core','explore',?,?,?, 'NOISE', 0.1, 'brain')",
                         (f"e{i}", f"f{i}", time.time()))
        rep = D.check_card(GOOD, self.R.catalog, "SBX", journal=j)
        self.assertTrue(rep.family_journal["dead_end"])
        self.assertTrue(any("dead end" in c.message for c in rep.warnings))
        self.assertTrue(rep.ok)                              # a warning, not a block: the decision is Zacc's

    def test_does_not_bind_is_explained(self):
        c = dict(GOOD, roles={"tax": {"concept": "income_tax"}},
                 ladder=[{"name": "core", "expr": "rank(ts_backfill({tax}, 63) / cap)", "teaches": "x"}])
        rep = D.check_card(c, self.R.catalog, "SBX")
        self.assertIsNone(rep.idea)
        self.assertTrue(any("no field for tax (income_tax)" in w.message for w in rep.warnings))

    def test_critic_message_is_valid_yaml_with_the_dry_run(self):
        rep = D.check_card(GOOD, self.R.catalog, "SBX")
        msg = D.critic_message(GOOD, rep, "B-1")
        self.assertTrue(msg.startswith("# from: B-1"))
        self.assertIn("# role inv (inventory) -> fnd_inventory", msg)
        self.assertEqual(yaml.safe_load(msg)[0]["id"], "IE_INV_BUILD")


class TestStoreAndApprove(_Home):
    def test_round_trip_states_and_rename(self):
        rep = D.check_card(GOOD, None, None)
        self.drafts.save(GOOD, "B-1", report=rep)
        row = self.drafts.get("IE_INV_BUILD")
        self.assertEqual(row["state"], "checked")
        self.assertEqual(row["card"]["roles"], GOOD["roles"])
        self.drafts.save(dict(GOOD, id="IE_INV_BUILD2"), old_id="IE_INV_BUILD")
        self.assertIsNone(self.drafts.get("IE_INV_BUILD"))
        self.assertEqual(self.drafts.get("IE_INV_BUILD2")["source"], "B-1")
        self.drafts.bin("IE_INV_BUILD2", "weak story")
        self.assertEqual(self.drafts.get("IE_INV_BUILD2")["reason"], "weak story")
        self.assertEqual(self.drafts.counts(), {"binned": 1})
        self.drafts.restore("IE_INV_BUILD2")
        self.assertEqual(self.drafts.get("IE_INV_BUILD2")["state"], "draft")

    def test_approve_writes_yaml_that_load_library_loads(self):
        rep = D.check_card(GOOD, None, None)
        self.drafts.save(GOOD, "B-1", report=rep)
        path = self.drafts.approve("IE_INV_BUILD", rep)
        self.assertEqual(path, config.HOME / "library" / "my_cards.yaml")
        mine = [h for h in hyp.load_library() if h.source == "mine"]
        self.assertEqual([h.id for h in mine], ["IE_INV_BUILD"])
        self.assertEqual(hyp.LOAD_WARNINGS, [])
        self.assertEqual(self.drafts.get("IE_INV_BUILD")["state"], "approved")
        self.assertFalse(path.with_suffix(".yaml.bak").exists())
        # approved drafts are read-only, and the same id can never be appended twice
        with self.assertRaises(ValueError):
            self.drafts.save(GOOD)
        with self.assertRaises(ValueError):
            D.append_to_my_cards(GOOD)
        # a second card appends, keeps the first, and leaves a backup
        other = dict(GOOD, id="IE_SECOND")
        rep2 = D.check_card(other, None, None)
        self.assertTrue(rep2.ok)
        self.drafts.save(other, report=rep2)
        self.drafts.approve("IE_SECOND", rep2)
        self.assertEqual([h.id for h in hyp.load_library() if h.source == "mine"], ["IE_INV_BUILD", "IE_SECOND"])
        self.assertTrue(path.with_suffix(".yaml.bak").exists())
        # re-checking an approved card does not flag its own id
        self.assertTrue(D.check_card(GOOD, None, None, allow_id="IE_INV_BUILD").ok)
        self.assertFalse(D.check_card(GOOD, None, None).ok)

    def test_approve_refuses_errors(self):
        bad = dict(GOOD, story="")
        rep = D.check_card(bad, None, None)
        self.drafts.save(bad, report=rep)
        with self.assertRaises(ValueError):
            self.drafts.approve("IE_INV_BUILD", rep)
        self.assertFalse((config.HOME / "library" / "my_cards.yaml").exists())

    def test_verdicts(self):
        self.drafts.save(GOOD)
        text = ("```yaml\nverdict:\n  id: IE_INV_BUILD\n  decision: Rewrite\n  scores: {novelty: 2, clarity: 4}\n"
                "  fixes: [add a peer rung]\n  one_line: close\n```\n\nZacc, add a peer rung.")
        v = self.drafts.attach_verdict(text)
        self.assertEqual(v["decision"], "rewrite")
        row = self.drafts.get("IE_INV_BUILD")
        self.assertEqual(row["decision"], "rewrite")
        self.assertIn("REWRITE", D.verdict_markdown(row["verdict"]))
        self.assertEqual(row["state"], "draft")             # advice only: nothing approved or binned
        with self.assertRaises(ValueError):
            self.drafts.attach_verdict("verdict:\n  id: IE_INV_BUILD\n  decision: maybe\n")
        with self.assertRaises(KeyError):
            self.drafts.attach_verdict("verdict:\n  id: IE_NOPE\n  decision: keep\n")


class TestWeeklyHandOffs(_Home):
    PLAN = ("Review...\n\nplan:\n  week: 2026-W43\n  region: USA\n  categories: [pv, Model, nonsense]\n"
            "  dataset_focus: model26\n  card_target: 4\n  submit_target: 40\n  retry: [IE_X@USA]\n"
            "  dead_ends: [pv_reversal]\n  lessons: [backfill quarterly data first]\n"
            "  review_note: Good week.\n\nNext ideas: ...")

    def test_plan_is_parsed_clipped_and_applied_once(self):
        plan, probs = D.parse_plan(self.PLAN, ["USA", "GLB"])
        self.assertIsNotNone(plan, probs)
        self.assertEqual(plan["categories"], ["pv", "model"])
        self.assertEqual(plan["submit_target"], 20)                 # 4 a day x 5 working days
        self.assertTrue(any("nonsense" in p for p in probs))
        j = Journal(":memory:")
        res = D.apply_plan(self.store, j, plan)
        self.assertEqual(res["lessons_added"], 2)
        self.assertEqual(D.apply_plan(self.store, j, plan)["lessons_added"], 0)
        saved = self.store.plan("2026-W43")
        self.assertEqual(saved["extra"]["retry"], ["IE_X@USA"])
        self.assertEqual(saved["region"], "USA")
        # saving from the Week form later keeps the Reviewer's extras
        self.store.save_plan({k: v for k, v in saved.items() if k != "extra"})
        self.assertEqual(self.store.plan("2026-W43")["extra"]["dead_ends"], ["pv_reversal"])

    def test_plan_errors(self):
        plan, probs = D.parse_plan("plan:\n  week: W43\n  region: MARS\n  categories: []\n", ["USA"])
        self.assertIsNone(plan)
        self.assertEqual(sum(p.startswith("error:") for p in probs), 3)
        self.assertIsNone(D.parse_plan("hello", ["USA"])[0])

    def test_digest(self):
        R = Researcher.sandbox()
        for c in R.ideas(n=2):
            R.test(c, 0)
        R.journal.add_lesson("quarterly data needs ts_backfill", family="fund")
        self.drafts.save(GOOD)
        txt = D.digest(R.journal, self.store, planner.iso_week())
        self.assertIn(f"### DIGEST {planner.iso_week()}", txt)
        self.assertIn("simulations: 2 on 2 ideas", txt)
        self.assertIn("verdicts:", txt)
        self.assertIn("drafts waiting 1", txt)
        self.assertIn("quarterly data needs ts_backfill", txt)
        self.assertIn("near misses (NEAR):", txt)

    def test_old_ideas_file_gets_the_new_columns(self):
        path = Path(self._tmp.name) / "old_ideas.sqlite"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE plans (week TEXT PRIMARY KEY, region TEXT, universe TEXT, delay INTEGER, "
                   "categories TEXT, dataset_focus TEXT, card_target INTEGER, review_note TEXT DEFAULT '', updated REAL)")
        db.execute("INSERT INTO plans VALUES ('2026-W42','USA','TOP3000',1,'[\"pv\"]','',5,'',0)")
        db.commit()
        db.close()
        s = IdeaStore(path)
        self.assertEqual(s.plan("2026-W42")["extra"], {})
        D.Drafts(s).save(GOOD)
        self.assertEqual(D.Drafts(s).list()["id"].tolist(), ["IE_INV_BUILD"])

    def test_knowledge_pack_rebuild(self):
        out = Path(self._tmp.name) / "pack"
        files = D.rebuild_knowledge_pack(None, self.store, out)
        self.assertTrue((out / "02_concepts.md").exists())
        self.assertIn("income_tax", (out / "02_concepts.md").read_text())
        self.assertGreaterEqual(len(files), 10)


class TestNewConcepts(unittest.TestCase):
    def test_gap_concepts_match_typical_descriptions(self):
        cases = {"income_tax": "Income taxes expense, quarterly", "pretax_income": "Pretax income (income before tax)",
                 "esg_score": "ESG combined score, higher is better", "credit_spread": "5-year CDS spread in bps",
                 "management_change": "CEO change flag: new chief executive appointed"}
        for concept, desc in cases.items():
            self.assertIn(concept, CONCEPTS)
            got = [m.concept for m in match_concepts("x_field", desc)]
            self.assertIn(concept, got, f"{concept}: {got}")


if __name__ == "__main__":
    unittest.main()
