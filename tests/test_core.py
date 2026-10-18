"""Fast tests: parser, operators, linter, hypothesis library, overfitting maths, journal, diagnosis.

Run:  python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

import numpy as np  # noqa: E402

from hypolab import fastexpr  # noqa: E402
from hypolab.diagnose import diagnose, flip  # noqa: E402
from hypolab.hypotheses import load_library, validate_library  # noqa: E402
from hypolab.journal import Journal, fingerprint  # noqa: E402
from hypolab.linter import Linter  # noqa: E402
from hypolab.operators import GOLD  # noqa: E402
from hypolab.overfit import deflated_sharpe, expected_max_sharpe  # noqa: E402
from hypolab.robustness import twist_windows  # noqa: E402


def codes(result):
    return {i.code for i in result.issues}


class TestParser(unittest.TestCase):
    def test_roundtrip_and_helpers(self):
        e = "group_rank(ts_delta(ts_backfill(est_eps, 63), 21) / close, subindustry)"
        tree = fastexpr.parse(e)
        self.assertTrue(set(fastexpr.operators_used(tree)) >= {"group_rank", "ts_delta", "ts_backfill"})
        self.assertIn("est_eps", fastexpr.names_used(tree))
        self.assertEqual(fastexpr.canonical(e), fastexpr.canonical(e.replace(" ", "")))

    def test_multi_statement_comments_ternary_kwargs(self):
        e = "a = rank(close); # comment\nb = a > 0.5 ? 1 : -1;\nwinsorize(b, std=4)"
        tree = fastexpr.parse(e)
        self.assertIn("winsorize", set(fastexpr.operators_used(tree)))

    def test_syntax_error(self):
        with self.assertRaises(fastexpr.ParseError):
            fastexpr.parse("rank(close")


class TestOperators(unittest.TestCase):
    def test_gold_registry_has_pdf_operators(self):
        for op in ("ts_rank", "group_neutralize", "vec_avg", "trade_when", "hump", "winsorize", "ts_backfill",
                   "ts_regression", "group_backfill", "bucket", "days_from_last_change", "ts_decay_linear"):
            self.assertIn(op, GOLD, op)

    def test_non_gold_operators_are_not_in_registry(self):
        # used by the zip's BOOSTER/ITERATOR notebooks but not on the Gold PDF
        for op in ("arc_sin", "sigmoid", "s_log_1p"):
            self.assertNotIn(op, GOLD, op)


class TestLinter(unittest.TestCase):
    def setUp(self):
        self.L = Linter()

    def test_clean(self):
        self.assertTrue(self.L.lint("rank(ts_delta(close, 5))").ok)

    def test_unknown_operator_blocks(self):
        r = self.L.lint("sigmoid(close)")
        self.assertFalse(r.ok)

    def test_named_parameter_required(self):
        r = self.L.lint("winsorize(close, 4)")
        self.assertFalse(r.ok)
        self.assertIn("NAMED_PARAMETER", codes(r))

    def test_unused_variable_is_error(self):
        r = self.L.lint("a = rank(close); b = rank(volume); a")
        self.assertFalse(r.ok)

    def test_syntax_error_blocks(self):
        self.assertFalse(self.L.lint("rank(close").ok)


class TestLibrary(unittest.TestCase):
    def test_library_validates(self):
        lib = load_library()
        self.assertGreaterEqual(len(lib), 40)
        self.assertEqual(validate_library(lib), [])

    def test_every_card_has_mechanism_and_ladder(self):
        for h in load_library():
            self.assertTrue(h.story and h.why_persists, h.id)
            self.assertTrue(h.ladder, h.id)
            self.assertTrue(h.references, h.id)


class TestOverfit(unittest.TestCase):
    def test_expected_max_grows_with_trials(self):
        a, b = expected_max_sharpe(10), expected_max_sharpe(1000)
        self.assertLess(a, b)
        self.assertAlmostEqual(b, 1.46, delta=0.15)

    def test_deflated_sharpe_penalises_many_trials(self):
        rng = np.random.default_rng(0)
        pnl = rng.normal(0.0006, 0.01, 1260)   # ~ Sharpe 0.95
        one = deflated_sharpe(pnl, 1)["dsr"]
        many = deflated_sharpe(pnl, 500)["dsr"]
        self.assertGreater(one, many)


class TestJournal(unittest.TestCase):
    def test_fingerprint_ignores_whitespace_and_dedupes(self):
        s = {"region": "USA", "universe": "TOP3000", "delay": 1, "decay": 0, "neutralization": "SUBINDUSTRY"}
        self.assertEqual(fingerprint("rank( close )", s), fingerprint("rank(close)", s))
        self.assertNotEqual(fingerprint("rank(close)", s), fingerprint("rank(close)", {**s, "decay": 3}))
        j = Journal(":memory:")
        j.record("idea1", "r1", "explore", "rank(close)", s, {"alpha_id": "A1", "is_sharpe": 1.2, "status": "COMPLETE"})
        self.assertIsNotNone(j.already_run("rank(close)", s))
        self.assertEqual(j.trials("idea1"), 1)


class TestDiagnose(unittest.TestCase):
    def test_error_gets_hint(self):
        d = diagnose({"status": "ERROR", "error": "Invalid number of inputs"}, "winsorize(x, 4)")
        self.assertEqual(d.verdict, "ERROR")
        self.assertIn("NAMED", d.actions[0].why)

    def test_inverted(self):
        d = diagnose({"alpha_id": "X", "is_sharpe": -1.9, "is_fitness": -1.2, "is_turnover": 0.2,
                      "is_returns": -0.08, "failed": ["LOW_SHARPE"]}, "rank(close)", {"decay": 0})
        self.assertEqual(d.verdict, "INVERTED")

    def test_fitness_bound_suggests_decay(self):
        d = diagnose({"alpha_id": "X", "is_sharpe": 1.9, "is_fitness": 0.7, "is_turnover": 0.6,
                      "is_returns": 0.06, "failed": ["LOW_FITNESS"]}, "rank(close)", {"decay": 0})
        self.assertIn(d.verdict, ("NEAR", "WEAK"))
        self.assertTrue(any(a.settings.get("decay") for a in d.actions))

    def test_flip(self):
        self.assertTrue(flip("rank(close)").startswith("-"))


class TestRobustnessHelpers(unittest.TestCase):
    def test_twist_windows(self):
        out = twist_windows("ts_mean(close, 20)", 1.15)
        self.assertIn("23", out)


class TestNoiseBar(unittest.TestCase):
    def test_bar_grows_with_probes_and_noise_spread(self):
        from hypolab.overfit import noise_bar
        self.assertLess(noise_bar(10), noise_bar(1000))
        wide = noise_bar(40, sharpes=list(np.random.default_rng(1).normal(0, 1.0, 40)))
        self.assertGreater(wide, noise_bar(40))


if __name__ == "__main__":
    unittest.main()
