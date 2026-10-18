"""MockBrain: a stand-in for BrainClient backed by the offline sandbox.

Same methods the research workflow uses (simulate, alpha, yearly_stats, pnl,
correlations, checks, submit, diversity ...), so every notebook can be
practised end-to-end with NO account, NO network and NO risk - region "SBX".
Results are synthetic: use them to learn the workflow, not to judge ideas.
"""
from __future__ import annotations

import itertools
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .sandbox.backtest import backtest
from .sandbox.evaluator import Data, EvalError, Evaluator
from .sandbox.market import make_market
from .rules import dataset_profile

PREFIX_CATEGORY = {"fnd": "fundamental", "anl": "analyst", "ern": "earnings", "mdl": "model", "snt": "sentiment",
                   "nz": "model"}
PV = {"open", "high", "low", "close", "vwap", "volume", "adv20", "returns", "cap", "sharesout"}


def sandbox_catalog_payload(data: Data) -> dict:
    rows = data.catalog_rows()
    datasets = {}
    for r in rows:
        pre = r["id"].split("_")[0]
        cat = PREFIX_CATEGORY.get(pre, "pv")
        ds = f"sbx_{cat}"
        r["dataset"], r["category"] = ds, cat
        datasets[ds] = {"id": ds, "name": f"Sandbox {cat} data", "category": cat, "description": "synthetic"}
    return {"region": "SBX", "universe": "SANDBOX", "delay": 1, "datasets": list(datasets.values()), "fields": rows}


class MockBrain:
    is_mock = True

    def __init__(self, data: Optional[Data] = None, seed: int = 7):
        self.data = data or make_market(seed=seed)
        self.ev = Evaluator(self.data)
        self._alphas: Dict[str, dict] = {}
        self._results: Dict[str, object] = {}
        self._submitted: List[str] = []
        self._ids = (f"SBX{n:05d}" for n in itertools.count(1))
        self.user_id = "sandbox"
        self._ds_map = {r["id"]: r["dataset"] for r in sandbox_catalog_payload(self.data)["fields"]}

    def _dataset_of(self, field_id: str):
        return self._ds_map.get(field_id)

    # ------------------------------------------------------------ session
    def login(self, force: bool = False):
        print("Sandbox mode: no login needed (synthetic data, region SBX).")
        return {"user": {"id": "sandbox"}}

    def whoami(self):
        return {"user": {"id": "sandbox"}}

    def ensure(self):
        pass

    def seconds_left(self):
        return 1e9

    # ----------------------------------------------------------- simulate
    def simulate(self, payloads: List[dict], batch_size=None, concurrency=None, progress=print,
                 on_submitted=None) -> List[dict]:
        out = []
        for p in payloads:
            if on_submitted:
                on_submitted([p], f"sandbox://simulation/{len(self._alphas) + 1}")
            st = p["settings"]
            try:
                a = self.ev(p["regular"])
            except (EvalError, Exception) as e:  # noqa: BLE001 - surface any evaluation error like BRAIN does
                out.append({"ok": False, "alpha_id": None, "status": "ERROR", "error": str(e), "payload": p})
                continue
            tp = str(st.get("testPeriod", "P2Y"))
            years = float(tp[1:tp.index("Y")]) if "Y" in tp else 0.0
            prof = dataset_profile(p["regular"], self._dataset_of, int(st.get("delay", 1)))
            th = {"sharpe_2y": prof["cutoff"]} if prof.get("single") else None
            res = backtest(a, self.data, decay=int(st.get("decay", 0)), neutralization=st.get("neutralization", "MARKET"),
                           truncation=float(st.get("truncation", 0.08)), test_years=years, thresholds=th)
            aid = next(self._ids)
            self._results[aid] = res
            self._alphas[aid] = {
                "id": aid, "type": "REGULAR", "settings": dict(st), "regular": {"code": p["regular"]},
                "is": {**res.stats, "checks": res.checks}, "train": res.train or None, "test": res.test or None,
                "status": "UNSUBMITTED", "dateCreated": time.time(),
            }
            out.append({"ok": True, "alpha_id": aid, "status": "COMPLETE", "error": "", "payload": p})
        if progress:
            progress(f"sandbox: {sum(r['ok'] for r in out)}/{len(out)} simulated")
        return out

    # ------------------------------------------------------------- results
    def alpha(self, alpha_id: str) -> dict:
        return self._alphas[alpha_id]

    def yearly_stats(self, alpha_id: str) -> pd.DataFrame:
        return self._results[alpha_id].yearly

    def pnl(self, alpha_id: str) -> pd.Series:
        return self._results[alpha_id].pnl.cumsum()

    def daily_pnl(self, alpha_id: str) -> pd.Series:
        return self._results[alpha_id].pnl

    # Stand-in for BRAIN's production pool: textbook alphas "other consultants already submitted".
    # Copying a well-known idea shows up as high PRODUCTION correlation, exactly as on the platform.
    PROD_POOL = {
        "POOL_reversal": "-rank(ts_sum(returns, 5))",
        "POOL_cash_yield": "group_rank(ts_backfill(fnd_cfo, 252) / cap, subindustry)",
        "POOL_pead": "group_rank(ts_backfill(ern_eps_surprise, 63), subindustry)",
    }

    def _prod_pool(self) -> Dict[str, pd.Series]:
        if not hasattr(self, "_pool"):
            self._pool = {}
            for name, expr in self.PROD_POOL.items():
                try:
                    self._pool[name] = backtest(self.ev(expr), self.data, decay=2).pnl
                except Exception:  # noqa: BLE001
                    pass
        return self._pool

    def correlations(self, alpha_id: str, kind: str = "self") -> dict:
        me = self._results[alpha_id].pnl
        rows = []
        if kind == "prod":
            for name, other in self._prod_pool().items():
                c = float(np.corrcoef(me.to_numpy(), other.to_numpy())[0, 1])
                rows.append({"id": name, "correlation": round(c, 4), "sharpe": None})
            df = pd.DataFrame(rows, columns=["id", "correlation", "sharpe"])
            return {"max": float(df["correlation"].max()) if not df.empty else 0.0, "min": None, "table": df}
        for other in self._submitted:
            if other == alpha_id:
                continue
            c = float(np.corrcoef(me.to_numpy(), self._results[other].pnl.to_numpy())[0, 1])
            rows.append({"id": other, "correlation": round(c, 4), "sharpe": self._results[other].stats["sharpe"]})
        df = pd.DataFrame(rows, columns=["id", "correlation", "sharpe"])
        return {"max": float(df["correlation"].max()) if not df.empty else 0.0, "min": None, "table": df}

    def checks(self, alpha_id: str) -> pd.DataFrame:
        base = list(self._alphas[alpha_id]["is"]["checks"])
        sc = self.correlations(alpha_id)["max"] or 0.0
        base.append({"name": "SELF_CORRELATION", "limit": 0.7, "value": round(sc, 4),
                     "result": "PASS" if sc < 0.7 else "FAIL"})
        return pd.DataFrame(base)

    def set_properties(self, alpha_id: str, **kw) -> int:
        self._alphas[alpha_id].update({k: v for k, v in kw.items() if v is not None})
        return 200

    def submit(self, alpha_id: str, confirm: str = "") -> dict:
        if confirm != f"SUBMIT {alpha_id}":
            raise RuntimeError(f'Refusing to submit. Re-run with confirm="SUBMIT {alpha_id}"')
        self._submitted.append(alpha_id)
        self._alphas[alpha_id]["status"] = "ACTIVE"
        return {"status_code": 200, "body": "sandbox submission recorded"}

    # ------------------------------------------------------------- account
    def my_alphas(self, status=None, region=None, max_items=2000):
        return [a for a in self._alphas.values() if status is None or a["status"] == status]

    def _categories(self, code: str) -> List[str]:
        import re
        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code))
        cats = {PREFIX_CATEGORY[n.split("_")[0]] for n in names if n.split("_")[0] in PREFIX_CATEGORY}
        if names & PV:
            cats.add("pv")
        return sorted(cats)

    def diversity(self) -> pd.DataFrame:
        rows = []
        for aid in self._submitted:
            a = self._alphas[aid]
            for c in self._categories(a["regular"]["code"]):
                rows.append({"region": "SBX", "delay": 1, "category": c, "alphas": 1})
        df = pd.DataFrame(rows, columns=["region", "delay", "category", "alphas"])
        return df.groupby(["region", "delay", "category"], as_index=False)["alphas"].sum() if not df.empty else df

    def pyramid_multipliers(self) -> pd.DataFrame:
        return pd.DataFrame()

    def simulation_options(self) -> pd.DataFrame:
        return pd.DataFrame([{"region": "SBX", "delays": [1], "universes": ["SANDBOX"],
                              "neutralizations": ["NONE", "MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY"]}])

    def platform_link(self, alpha_id: str) -> str:
        return f"(sandbox alpha {alpha_id})"
