"""A BRAIN-style daily backtester for the sandbox.

Mirrors the platform's pipeline: alpha vector each day -> (decay) ->
neutralize -> scale to the book -> truncate the largest weights -> hold for
one day (delay 1: data up to day t, earns the return of day t+1).

Metrics follow BRAIN's definitions as published:
  sharpe   = mean(daily pnl) / std(daily pnl) * sqrt(252)
  turnover = average daily traded value / book
  returns  = annualised pnl / (book / 2)
  fitness  = sharpe * sqrt(|returns| / max(turnover, 0.125))
  margin   = pnl per dollar traded (shown in basis points)
Absolute levels on synthetic data are NOT comparable with BRAIN - use the sandbox
for intuition and relative comparisons only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .evaluator import Data, _group_apply, _ts_decay_linear

BOOK = 20_000_000.0


@dataclass
class Result:
    stats: Dict[str, float]
    train: Dict[str, float]
    test: Dict[str, float]
    yearly: pd.DataFrame
    pnl: pd.Series
    weights: np.ndarray = field(repr=False, default=None)
    checks: List[dict] = field(default_factory=list)

    @property
    def failed(self) -> List[str]:
        return [c["name"] for c in self.checks if c["result"] == "FAIL"]


def _neutralize(a: np.ndarray, data: Data, how: str) -> np.ndarray:
    how = (how or "NONE").upper()
    if how == "NONE":
        return a
    key = {"MARKET": "market", "SECTOR": "sector", "INDUSTRY": "industry", "SUBINDUSTRY": "subindustry",
           "COUNTRY": "country"}.get(how, "market")   # STATISTICAL/FAST/SLOW... approximated by MARKET
    g = data.groups.get(key)
    if g is None:
        return a - np.nanmean(a, axis=1, keepdims=True)
    return a - _group_apply(a, g, "mean")


def weights_from_alpha(alpha: np.ndarray, data: Data, decay: int = 0, neutralization: str = "MARKET",
                       truncation: float = 0.08, universe_mask: Optional[np.ndarray] = None) -> np.ndarray:
    a = alpha.astype(float).copy()
    if universe_mask is not None:
        a[~universe_mask] = np.nan
    if decay and decay > 1:
        a = _ts_decay_linear(a, int(decay))
    a = _neutralize(a, data, neutralization)
    w = a / np.nansum(np.abs(a), axis=1, keepdims=True)
    if truncation and truncation > 0:
        for _ in range(6):
            w = np.clip(w, -truncation, truncation)
            w = w / np.nansum(np.abs(w), axis=1, keepdims=True)
    return np.nan_to_num(w)


def _stats(pnl: np.ndarray, w: np.ndarray) -> Dict[str, float]:
    pnl = np.asarray(pnl, float)
    if pnl.size < 5 or np.nanstd(pnl) == 0:
        return {"sharpe": 0.0, "fitness": 0.0, "turnover": 0.0, "returns": 0.0, "drawdown": 0.0, "margin": 0.0,
                "longCount": 0, "shortCount": 0}
    sharpe = float(np.nanmean(pnl) / np.nanstd(pnl) * np.sqrt(252))
    dw = np.abs(np.diff(w, axis=0)).sum(axis=1)
    gross = np.abs(w).sum(axis=1)[1:]
    turnover = float(np.nanmean(dw / np.where(gross > 0, gross, np.nan)))
    ret = float(np.nanmean(pnl) * 252 / (BOOK / 2))
    fitness = sharpe * np.sqrt(abs(ret) / max(turnover, 0.125))
    cum = np.nancumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(cum) - cum) / (BOOK / 2)) if cum.size else 0.0
    traded = np.nansum(dw) * BOOK
    margin = float(np.nansum(pnl) / traded * 1e4) if traded > 0 else 0.0
    return {"sharpe": round(sharpe, 2), "fitness": round(float(fitness), 2), "turnover": round(turnover, 4),
            "returns": round(ret, 4), "drawdown": round(dd, 4), "margin": round(margin, 2),
            "longCount": int(np.mean((w > 0).sum(axis=1))), "shortCount": int(np.mean((w < 0).sum(axis=1)))}


def _liquidity_rank(data: Data) -> np.ndarray:
    """Daily rank of dollar volume (1 = most liquid); cached on the Data object."""
    cached = getattr(data, "_liq_rank", None)
    if cached is None:
        liq = data.fields["adv20"] * data.fields["close"]
        cached = pd.DataFrame(liq).rank(axis=1, ascending=False).to_numpy()
        data._liq_rank = cached
    return cached


def backtest(alpha: np.ndarray, data: Data, decay: int = 0, neutralization: str = "SUBINDUSTRY",
             truncation: float = 0.08, test_years: float = 2.0, universe_top: Optional[int] = None,
             thresholds: Optional[dict] = None) -> Result:
    T, N = alpha.shape
    mask = None
    if universe_top and universe_top < N:
        mask = _liquidity_rank(data) <= universe_top
    w = weights_from_alpha(alpha, data, decay, neutralization, truncation, mask)
    r = np.nan_to_num(data.fields["returns"])
    pnl = np.zeros(T)
    pnl[1:] = (w[:-1] * r[1:]).sum(axis=1) * BOOK
    start = 252 if T > 600 else 21             # warm-up like BRAIN's lookback
    pnl_s = pd.Series(pnl[start:], index=data.dates[start:])
    w_s = w[start:]
    stats = _stats(pnl_s.to_numpy(), w_s)
    n_test = int(252 * test_years)
    train = _stats(pnl_s.to_numpy()[:-n_test], w_s[:-n_test]) if n_test and len(pnl_s) > n_test + 100 else {}
    test = _stats(pnl_s.to_numpy()[-n_test:], w_s[-n_test:]) if n_test and len(pnl_s) > n_test + 100 else {}
    years = []
    for y, grp in pnl_s.groupby(pnl_s.index.year):
        idx = np.where(pnl_s.index.year == y)[0]
        years.append({"year": y, **_stats(grp.to_numpy(), w_s[idx])})
    yearly = pd.DataFrame(years)
    # sub-universe: the more liquid half
    top = (_liquidity_rank(data) / N)[start:] <= 0.5
    w_sub = np.where(top, w_s, 0.0)
    pnl_sub = np.zeros(len(pnl_s))
    pnl_sub[1:] = (w_sub[:-1] * r[start + 1:]).sum(axis=1) * BOOK
    sub_sharpe = _stats(pnl_sub, w_sub)["sharpe"]
    last2 = _stats(pnl_s.to_numpy()[-504:], w_s[-504:])["sharpe"] if len(pnl_s) > 504 else stats["sharpe"]
    # sub_ratio: BRAIN's sub-universe cutoff is 0.75 * sqrt(sub_size / size) * Sharpe (BRAIN_RULES T3); the
    # sandbox's sub-universe is the more liquid half, so 0.75 * sqrt(0.5) = 0.53.
    # sharpe_2y: last-2-year Sharpe cutoff; a Single Dataset Alpha must clear 2.38 at D1 (BRAIN_RULES T1).
    th = {"sharpe": 1.58, "fitness": 1.0, "tvr_lo": 0.01, "tvr_hi": 0.7, "weight": 0.10,
          "sub_ratio": round(0.75 * np.sqrt(0.5), 4), "sharpe_2y": None}
    th.update(thresholds or {})
    lim_2y = th["sharpe_2y"] or th["sharpe"]
    maxw = float(np.nanmax(np.abs(w_s)))
    s = stats["sharpe"]
    checks = [
        {"name": "LOW_SHARPE", "limit": th["sharpe"], "value": s, "result": "PASS" if s >= th["sharpe"] else "FAIL"},
        {"name": "LOW_FITNESS", "limit": th["fitness"], "value": stats["fitness"],
         "result": "PASS" if stats["fitness"] >= th["fitness"] else "FAIL"},
        {"name": "LOW_TURNOVER", "limit": th["tvr_lo"], "value": stats["turnover"],
         "result": "PASS" if stats["turnover"] >= th["tvr_lo"] else "FAIL"},
        {"name": "HIGH_TURNOVER", "limit": th["tvr_hi"], "value": stats["turnover"],
         "result": "PASS" if stats["turnover"] <= th["tvr_hi"] else "FAIL"},
        {"name": "CONCENTRATED_WEIGHT", "limit": th["weight"], "value": round(maxw, 4),
         "result": "PASS" if maxw <= th["weight"] + 1e-9 else "FAIL"},
        {"name": "LOW_SUB_UNIVERSE_SHARPE", "limit": round(th["sub_ratio"] * abs(s), 2), "value": sub_sharpe,
         "result": "PASS" if sub_sharpe >= th["sub_ratio"] * s or s < 0 else "FAIL"},
        {"name": "LOW_2Y_SHARPE", "limit": lim_2y, "value": last2,
         "result": "PASS" if last2 >= lim_2y else "FAIL"},
    ]
    return Result(stats, train, test, yearly, pnl_s, w_s, checks)
