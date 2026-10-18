"""Tests for the Idea Engine's planner, store and the cockpit's view helpers."""
import datetime as dt
import os
import tempfile
import unittest

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab.journal import Journal  # noqa: E402
from hypolab.research import Researcher  # noqa: E402
from ideaengine import planner, views  # noqa: E402
from ideaengine.connection import open_researcher  # noqa: E402
from ideaengine.store import IdeaStore  # noqa: E402


class TestWeeks(unittest.TestCase):
    def test_iso_weeks(self):
        self.assertEqual(planner.iso_week(dt.date(2026, 10, 9)), "2026-W41")
        self.assertEqual(planner.week_start("2026-W42"), dt.date(2026, 10, 12))
        self.assertEqual(planner.next_week("2026-W52"), "2026-W53")
        self.assertEqual(planner.next_week("2026-W53"), "2027-W01")

    def test_quarter(self):
        self.assertEqual(planner.quarter_bounds("2026-Q4"), (dt.date(2026, 10, 1), dt.date(2026, 12, 31)))
        self.assertEqual(planner.quarter_bounds("2027-Q1"), (dt.date(2027, 1, 1), dt.date(2027, 3, 31)))
        self.assertEqual(planner.weeks_left("2026-Q4", dt.date(2026, 10, 9)), 12.0)
        self.assertEqual(planner.weeks_left("2026-Q4", dt.date(2027, 1, 5)), 0.0)

    def test_starting_plan_covers_ten_pyramids(self):
        cells = {(r, c) for r, cats in planner.STARTING_PLAN.values() if r in ("USA", "GLB") for c in cats}
        self.assertEqual(len(cells), 10)             # W42-W45: USA and GLB x the five tier-1 categories

    def test_guide_dataset_skips_the_avoid_note(self):
        self.assertEqual(planner.guide_dataset("analyst"), "analyst11")
        self.assertEqual(planner.guide_dataset("model"), "model26")


class TestStore(unittest.TestCase):
    def test_goals_default_to_the_genius_page(self):
        s = IdeaStore(":memory:")
        g = s.goals().set_index("key")
        self.assertEqual(g.loc["signals", "bar"], 20)
        self.assertEqual(g.loc["pyramids", "still_needed"], 10)
        s.set_goal("signals", 5, 20)
        self.assertEqual(s.goals().set_index("key").loc["signals", "still_needed"], 15)

    def test_plan_roundtrip_and_proposal(self):
        s = IdeaStore(":memory:")
        p = planner.propose("2026-W42")
        self.assertEqual((p["region"], p["categories"]), ("USA", ["analyst", "fundamental"]))
        s.save_plan(dict(p, review_note="revisions worked"))
        back = s.plan("2026-W42")
        self.assertEqual(back["categories"], ["analyst", "fundamental"])
        self.assertEqual(planner.propose("2026-W42", saved=back)["review_note"], "revisions worked")
        self.assertEqual(s.weeks_planned(), ["2026-W42"])

    def test_goal_pace(self):
        s = IdeaStore(":memory:")
        g = planner.goals_view(s, Journal(":memory:"), today=dt.date(2026, 10, 9)).set_index("key")
        self.assertAlmostEqual(g.loc["signals", "per_week_needed"], round(19 / 12, 2))
        self.assertTrue(g.loc["combined_perf", "per_week_needed"] is None
                        or g["per_week_needed"].isna()["combined_perf"])


class TestViewsOnSandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.R, problem = open_researcher()            # sandbox is the default mode in tests
        assert problem == "" and cls.R.is_sandbox
        cls.card = cls.R.card("ANL_REVISION_BREADTH")
        cls.t = cls.R.test(cls.card, rung=0)

    def test_cards_table_and_result_row(self):
        df = views.cards_table([self.card])
        self.assertEqual(df.loc[0, "id"], "ANL_REVISION_BREADTH")
        row = views.result_row(self.t)
        self.assertEqual(row["idea"], "ANL_REVISION_BREADTH")
        self.assertIn(row["verdict"], views.VERDICT_ORDER)

    def test_week_progress_and_tries(self):
        wk = planner.week_progress(self.R.journal, planner.iso_week())
        self.assertGreaterEqual(wk["simulations"], 1)
        tries = views.tries_per_idea(self.R.journal.experiments(), 10)
        self.assertIn("ANL_REVISION_BREADTH@SBX", set(tries["idea_id"]))
        self.assertFalse(views.verdict_mix(self.R.journal.experiments()).empty)

    def test_action_choices_are_followable(self):
        for label, i in views.action_choices(self.t).items():
            a = self.t.diagnosis.actions[i]
            self.assertTrue(a.expression or a.settings, label)

    def test_heatmap_renders(self):
        import matplotlib
        matplotlib.use("Agg")
        from hypolab.pyramids import PyramidTracker
        fig = views.pyramid_heatmap(PyramidTracker(regions=["USA", "GLB"]).matrix(), 3)
        self.assertEqual(len(fig.axes), 1)


class TestSubmissionPlan(unittest.TestCase):
    def test_superalpha_unlock_dates_from_58(self):
        s = IdeaStore(":memory:")
        st = planner.submission_status(s, Journal(":memory:"), today=dt.date(2026, 10, 9))
        self.assertEqual((st["lifetime"], st["to_unlock"], st["cap"]), (58, 42, 4))
        self.assertFalse(st["superalpha_unlocked"])
        # 4 today, then 38 more at 4 per working day = 10 working days -> Fri 23 Oct
        self.assertEqual(st["unlock_at_cap"], dt.date(2026, 10, 23))
        # default target 10 a week = 2 per working day: 2 today, 40 more = 20 working days -> Fri 6 Nov
        self.assertEqual(st["unlock_at_target"], dt.date(2026, 11, 6))
        self.assertIn("42 to go", planner.submission_summary(st))

    def test_lifetime_counts_new_submissions_and_unlocks(self):
        import tempfile as tf
        from pathlib import Path
        j = Journal(Path(tf.mkdtemp()) / "journal.sqlite")
        s = IdeaStore(":memory:")
        s.set_goal("lifetime_alphas", 99, 100)
        j.record_submission("A1", "X@USA", "fam", "USA", 1, ["analyst"])
        st = planner.submission_status(s, j)
        self.assertEqual((st["lifetime"], st["submitted_today"], st["left_today"]), (100, 1, 3))
        self.assertTrue(st["superalpha_unlocked"])
        self.assertIn("unlocked", planner.submission_summary(st))

    def test_plan_keeps_weekly_submission_target(self):
        s = IdeaStore(":memory:")
        p = planner.propose("2026-W42")
        self.assertEqual(p["submit_target"], planner.DEFAULT_WEEKLY_SUBMISSIONS)
        s.save_plan(dict(p, submit_target=14))
        self.assertEqual(s.plan("2026-W42")["submit_target"], 14)


class TestDailySubmissionCap(unittest.TestCase):
    def test_fifth_submission_of_the_day_is_refused(self):
        R = Researcher.sandbox()
        card = R.card("ANL_REVISION_BREADTH")
        t = R.test(card, rung=min(1, len(card.steps) - 1))
        gate = R.gate(t, R.robustness(t))
        self.assertTrue(gate.ready, gate.reasons)
        for i in range(4):                                   # four earlier submissions today
            R.journal.record_submission(f"OLD{i}", "x@SBX", "f", "SBX", 1, ["pv"])
        with self.assertRaises(RuntimeError):
            R.submit(gate, confirm=f"SUBMIT {gate.alpha_id}")
        self.assertEqual(R.journal.submissions_today(), 4)


if __name__ == "__main__":
    unittest.main()
