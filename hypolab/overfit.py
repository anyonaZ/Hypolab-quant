"""How much of a Sharpe ratio is luck? (multiple-testing arithmetic)

The zip's notebooks simulate hundreds or thousands of template x field
combinations and keep the best ones. Every extra try raises the Sharpe you
expect from PURE NOISE. This module puts a number on it.

References
* Bailey & Lopez de Prado (2014) "The Deflated Sharpe Ratio", Journal of
  Portfolio Management - corrects for the number of trials and non-normal returns.
* Harvey, Liu & Zhu (2016) "...and the Cross-Section of Expected Returns",
  Review of Financial Studies - a t-statistic of 2 is not enough after data mining.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

EULER = 0.5772156649


def expected_max_sharpe(n_trials: int, years: float = 5.0, sr_std: Optional[float] = None) -> float:
    """Expected best ANNUALISED Sharpe among n_trials strategies with zero true skill.

    Under the null, the annualised Sharpe of one backtest has standard deviation
    ~ 1/sqrt(years). The expected maximum of N such draws is approximately
    std * ((1-g) * z(1-1/N) + g * z(1-1/(N e))), g = Euler-Mascheroni.
    """
    if n_trials <= 1:
        return 0.0
    s = sr_std if sr_std is not None else 1.0 / math.sqrt(years)
    return s * ((1 - EULER) * norm.ppf(1 - 1.0 / n_trials) + EULER * norm.ppf(1 - 1.0 / (n_trials * math.e)))


def noise_bar(n_trials: int, sharpes=None, years: float = 5.0, q: float = 0.95) -> float:
    """|Sharpe| that the best of n_trials skill-less probes exceeds only (1-q) of the time.

    The spread of a noise Sharpe is at least 1/sqrt(years); when a scan's own Sharpes are given,
    their robust spread (1.4826 x median absolute deviation) is used if larger - real data has
    autocorrelated, fat-tailed noise that makes luck look bigger than the textbook formula says.
    """
    s = 1.0 / math.sqrt(years)
    if sharpes is not None:
        v = np.asarray([x for x in sharpes if x is not None and np.isfinite(x)], dtype=float)
        if v.size >= 8:
            s = max(s, 1.4826 * float(np.median(np.abs(v - np.median(v)))))
    n = max(int(n_trials), 1)
    # two-sided: the best |Sharpe| of n draws
    return float(s * norm.ppf(1 - (1 - q ** (1.0 / n)) / 2))


def noise_table(years: float = 5.0) -> pd.DataFrame:
    """'If I try N alphas that have no skill, how good will the best one look?'"""
    rows = []
    for n in (1, 10, 50, 100, 300, 1000, 5000):
        rows.append({"alphas tried": n, "best Sharpe expected from pure luck": round(expected_max_sharpe(n, years), 2)})
    return pd.DataFrame(rows)


def deflated_sharpe(daily_pnl, n_trials: int, sr_std_annual: Optional[float] = None) -> dict:
    """Probability that the true Sharpe is > 0 after accounting for n_trials tries.

    daily_pnl: daily PnL (any scale). sr_std_annual: dispersion of annualised Sharpe
    across the trials you ran (if unknown, the null-hypothesis value is used).
    Returns dict with sharpe (annual), sr0 (luck benchmark), dsr (probability, 0..1).
    """
    x = pd.Series(daily_pnl).dropna().to_numpy(float)
    if x.size < 60 or x.std() == 0:
        return {"sharpe": 0.0, "sr0": 0.0, "dsr": 0.0, "n": int(x.size)}
    T = x.size
    sr_d = x.mean() / x.std()
    g3 = float(skew(x))
    g4 = float(kurtosis(x, fisher=False))
    sr_std_d = (sr_std_annual / math.sqrt(252)) if sr_std_annual else math.sqrt(1.0 / T)
    sr0_d = expected_max_sharpe(max(n_trials, 1), sr_std=sr_std_d) if n_trials > 1 else 0.0
    denom = math.sqrt(max(1e-12, 1 - g3 * sr_d + (g4 - 1) / 4.0 * sr_d ** 2))
    z = (sr_d - sr0_d) * math.sqrt(T - 1) / denom
    return {"sharpe": round(float(sr_d * math.sqrt(252)), 2), "sr0": round(float(sr0_d * math.sqrt(252)), 2),
            "dsr": round(float(norm.cdf(z)), 3), "skew": round(g3, 2), "kurtosis": round(g4, 2), "n": T,
            "trials": int(n_trials)}


def verdict(dsr: float) -> str:
    if dsr >= 0.95:
        return "very unlikely to be luck"
    if dsr >= 0.80:
        return "probably real, but keep testing"
    if dsr >= 0.50:
        return "coin flip - your search effort explains most of this Sharpe"
    return "most likely luck from trying many variants"
