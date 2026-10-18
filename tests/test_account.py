"""Your account's live operator list and submitted alphas (no network: BRAIN's answers are faked)."""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("HYPOLAB_HOME", tempfile.mkdtemp(prefix="hypolab_test_"))

from hypolab import account as acct  # noqa: E402
from hypolab import config  # noqa: E402
from hypolab import operators as ops  # noqa: E402
from hypolab.brain import BrainClient  # noqa: E402
from hypolab.journal import Journal  # noqa: E402
from hypolab.linter import Linter  # noqa: E402

API_OPERATORS = [
    {"name": "rank", "category": "Cross Sectional", "scope": ["REGULAR", "COMBO"], "definition": "rank(x)"},
    {"name": "ts_rank", "category": "Time Series", "scope": ["REGULAR"], "definition": "ts_rank(x, d)"},
    {"name": "ts_backfill", "category": "Time Series", "scope": ["REGULAR"], "definition": "ts_backfill(x, d)"},
    {"name": "sigmoid", "category": "Arithmetic", "scope": ["REGULAR"], "definition": "sigmoid(x)"},
    {"name": "subtract", "category": "Arithmetic", "scope": ["REGULAR"], "definition": "x - y"},
    {"name": "multiply", "category": "Arithmetic", "scope": ["REGULAR"], "definition": "x * y"},
    {"name": "greater", "category": "Logical", "scope": ["REGULAR"], "definition": "x > y"},
    {"name": "group_rank", "category": "Group", "scope": ["REGULAR"], "definition": "group_rank(x, g)"},
    {"name": "combo_a", "category": "Combo", "scope": ["COMBO"], "definition": "combo_a(alpha)"},
]


def alpha(i, date, code, typ="REGULAR", region="USA"):
    a = {"id": f"A{i}", "type": typ, "status": "ACTIVE", "dateSubmitted": date, "dateCreated": date,
         "settings": {"region": region, "universe": "TOP3000", "delay": 1, "neutralization": "SUBINDUSTRY",
                      "decay": 4, "truncation": 0.08},
         "is": {"sharpe": 1.7, "fitness": 1.1, "turnover": 0.2, "returns": 0.08, "drawdown": 0.04}}
    if typ == "REGULAR":
        a["regular"] = {"code": code}
    else:
        a["combo"] = {"code": code}
    return a


SUBMITTED = [
    alpha(1, "2026-10-05T10:00:00-04:00", "group_rank(ts_rank(ts_backfill(anl4_eps, 63), 252), subindustry)"),
    alpha(2, "2026-10-06T10:00:00-04:00", "a = rank(close - vwap); a * (rank(volume) > 0.5)"),
    alpha(3, "2026-09-20T10:00:00-04:00", "sigmoid(ts_rank(fnd6_cfo, 252))"),
    alpha(4, "2026-10-07T10:00:00-04:00", "combo_a(alpha)", typ="SUPER"),
]


class FakeBrain:
    """Answers /users/self/alphas page by page and /operators, like BRAIN."""

    def __init__(self):
        self.calls = []

    def operators(self):
        return API_OPERATORS

    def submitted_alphas(self):
        return BrainClient.submitted_alphas(self)

    def _paged(self, path, params, page=50, max_items=100000):
        return BrainClient._paged(self, path, params, page, max_items)

    def _get_json(self, path, params=None, **kw):
        self.calls.append((path, dict(params or {})))
        off, lim = params["offset"], params["limit"]
        rows = sorted(SUBMITTED, key=lambda a: a["dateSubmitted"], reverse=True)
        return {"count": len(rows), "results": rows[off:off + lim]}


class TestOperatorList(unittest.TestCase):
    def setUp(self):
        self.home, config.HOME = config.HOME, Path(tempfile.mkdtemp())
        self.saved = dict(ops.GOLD.specs)

    def tearDown(self):
        config.HOME = self.home
        ops.GOLD.specs = self.saved

    def test_without_download_pdf_list_is_used(self):
        self.assertEqual(ops.regular_operator_catalog()["source"].iloc[0], "PDF")
        self.assertFalse(Linter().lint("sigmoid(close)").ok)

    def test_download_caches_and_linter_accepts_account_operators(self):
        res = ops.sync_operators(FakeBrain())
        self.assertEqual(res["regular"], 8)
        self.assertIn("sigmoid", res["added_to_linter"])
        self.assertTrue(ops.api_cache_path().exists())
        self.assertTrue(Linter().lint("sigmoid(close)").ok)
        cat = ops.regular_operator_catalog()
        self.assertNotIn("combo_a", set(cat["name"]))                   # COMBO-only operators stay out
        self.assertEqual(cat["source"].iloc[0], "BRAIN")


class TestSubmittedAlphas(unittest.TestCase):
    def setUp(self):
        self.home, config.HOME = config.HOME, Path(tempfile.mkdtemp())
        self.saved = dict(ops.GOLD.specs)
        self.j = Journal(":memory:")
        self.brain = FakeBrain()
        self.res = acct.sync_account(self.brain, self.j)

    def tearDown(self):
        config.HOME = self.home
        ops.GOLD.specs = self.saved

    def test_download_is_paged_and_filtered_on_submission(self):
        path, params = self.brain.calls[0]
        self.assertEqual(path, "/users/self/alphas")
        self.assertIn("dateSubmitted>", params)
        self.assertEqual(self.res["alphas"], 4)

    def test_counts_by_quarter(self):
        c = acct.counts(self.j, 2026, 4)
        self.assertEqual(c, {"lifetime_regular": 3, "lifetime_super": 1, "quarter_regular": 2, "quarter_super": 1})
        self.assertEqual(acct.counts(self.j, 2026, 3)["quarter_regular"], 1)

    def test_operator_audit(self):
        summary, by_cat, used, unused = acct.operator_audit(self.j, 2026, 4)
        self.assertEqual(summary["regular counted"], 2)
        self.assertEqual(summary["super left out"], 1)
        got = set(used["operator"])
        self.assertEqual(got, {"group_rank", "ts_rank", "rank", "subtract", "multiply", "greater"})
        self.assertNotIn("ts_backfill", got | set(unused["operator"]))   # left out of the count entirely
        self.assertIn("sigmoid", set(unused["operator"]))                 # used in Q3 only
        row = by_cat.set_index("category").loc["Arithmetic"]
        self.assertEqual((row["used"], row["available"]), (2, 3))

    def test_field_usage(self):
        f = acct.field_usage(self.j).set_index("field")
        self.assertEqual(set(f.index), {"anl4_eps", "close", "vwap", "volume", "fnd6_cfo"})


class TestReadOnlyJournal(unittest.TestCase):
    def test_account_views_work_on_a_readonly_journal(self):
        path = Path(tempfile.mkdtemp()) / "journal.sqlite"
        import sqlite3
        sqlite3.connect(path).executescript("CREATE TABLE lessons (id INTEGER PRIMARY KEY);")   # an old journal
        ro = Journal.open_readonly(path)
        self.assertTrue(acct.account_alphas(ro).empty)
        self.assertIsNone(acct.last_sync(ro))
        self.assertEqual(acct.counts(ro)["lifetime_regular"], 0)
        acct.operator_audit(ro)


class TestParsing(unittest.TestCase):
    KNOWN = {"rank", "ts_rank", "winsorize", "subtract", "add", "divide", "equal", "if_else", "less", "multiply"}

    def test_named_argument_is_not_equality(self):
        self.assertEqual(acct.operators_in_code("winsorize(x, std=4)", self.KNOWN), {"winsorize"})
        self.assertIn("equal", acct.operators_in_code("x == 1 ? a : b", self.KNOWN))

    def test_scientific_notation_and_comments(self):
        self.assertEqual(acct.operators_in_code("rank(x) * 1e-3  # - y", self.KNOWN), {"rank", "multiply"})

    def test_fields_skip_variables_groups_and_arguments(self):
        f = acct.fields_in_code("a = ts_rank(fnd_x, 63); group_rank(a, subindustry) * winsorize(a, std=4)",
                                self.KNOWN)
        self.assertEqual(f, {"fnd_x"})


if __name__ == "__main__":
    unittest.main()
