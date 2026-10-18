"""A synthetic stock market with KNOWN truths, for learning.

What is planted (so you can check whether your research process finds it):

* value       - cheap stocks (high cash-flow / market cap) drift up slowly
* quality     - profitable, low-accrual firms drift up slowly
* revisions   - analyst estimate revisions predict the next ~2 months
* surprise    - earnings surprises are followed by ~60 days of drift (PEAD)
* reversal    - one-week idiosyncratic moves partly revert
* low risk    - high-volatility stocks earn a little less
* sentiment   - news sentiment has a short, small drift

What is NOT planted: 40 "nz_*" noise fields with ZERO predictive power.
Throw templates at them and some will still show a respectable Sharpe -
that is the overfitting lesson in the learning app (apps/quant_basics.py).

Sizes default to 500 stocks x 6 years (runs in seconds on a T470s).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .evaluator import Data


def _ar1(rng, T, N, phi, scale=1.0, init=None):
    x = np.empty((T, N))
    x[0] = init if init is not None else rng.standard_normal(N) * scale
    eps = rng.standard_normal((T, N)) * scale * np.sqrt(1 - phi ** 2)
    for t in range(1, T):
        x[t] = phi * x[t - 1] + eps[t]
    return x


def _quarterly(x: np.ndarray, offsets: np.ndarray, period: int = 63, noise=None) -> np.ndarray:
    """Sample a daily latent series once per quarter per stock (staggered report dates), NaN elsewhere."""
    T, N = x.shape
    out = np.full((T, N), np.nan)
    for i in range(N):
        days = np.arange(offsets[i], T, period)
        out[days, i] = x[days, i] + (noise[days, i] if noise is not None else 0)
    return out


def make_market(n_stocks: int = 500, n_days: int = 1512, seed: int = 7, signal_scale: float = 0.22) -> Data:
    rng = np.random.default_rng(seed)
    T, N = n_days, n_stocks
    dates = pd.bdate_range("2019-01-02", periods=T)

    # ----- groups (nested): 6 sectors > 18 industries > 48 subindustries
    sub = rng.integers(0, 48, N)
    industry = sub // 3 % 18
    sector = industry // 3 % 6
    country = rng.choice([0, 1, 2], N, p=[0.6, 0.25, 0.15])

    # ----- slow characteristics (AR(1) with ~1-2 year half-lives)
    value = _ar1(rng, T, N, 0.998)
    quality = _ar1(rng, T, N, 0.999)
    size = np.cumsum(rng.standard_normal((T, N)) * 0.002, axis=0) + rng.normal(8.0, 1.2, N)  # log cap (millions)
    vol_level = np.exp(rng.normal(np.log(0.02), 0.35, N))   # daily vol per stock
    beta = np.clip(rng.normal(1.0, 0.3, N), 0.2, 2.0)

    # ----- analyst estimate revisions: persistent AR(1) shocks
    rev_shock = _ar1(rng, T, N, 0.985)
    k = signal_scale
    # ----- earnings surprise events (quarterly, staggered)
    offs = rng.integers(0, 63, N)
    surprise_raw = rng.standard_normal((T, N))
    surprise = _quarterly(surprise_raw + 0.6 * rev_shock, offs)   # surprises partly anticipated by revisions
    days_since = np.full(N, 999.0)
    last_s = np.zeros(N)
    pead = np.zeros((T, N))
    for t in range(T):
        hit = np.isfinite(surprise[t])
        last_s = np.where(hit, surprise[t], last_s)
        days_since = np.where(hit, 0.0, days_since + 1)
        pead[t] = np.where(days_since < 60, last_s, 0.0)

    # ----- news: sparse sentiment events
    news_on = rng.random((T, N)) < 0.08
    sent_true = rng.standard_normal((T, N))
    sentiment = np.where(news_on, sent_true, np.nan)
    sent_carry = pd.DataFrame(np.where(news_on, sent_true, 0)).ewm(halflife=3).mean().to_numpy()

    # ----- returns
    mkt = rng.standard_normal(T) * 0.010 + 0.0003
    ind_f = rng.standard_normal((T, 18)) * 0.006
    idio = rng.standard_normal((T, N)) * vol_level
    # reversal: subtract a fraction of last week's idiosyncratic move
    idio_lag = pd.DataFrame(idio).rolling(5, min_periods=1).sum().shift(1).fillna(0).to_numpy()
    drift = k * (0.00025 * value + 0.00030 * quality + 0.00045 * rev_shock + 0.00060 * pead / 1.0
                 + 0.00050 * sent_carry - 0.12 * idio_lag / 5.0
                 - 0.00020 * (np.log(vol_level / 0.02))[None, :])
    ret = beta[None, :] * mkt[:, None] + ind_f[:, industry] + idio + drift
    ret = np.clip(ret, -0.5, 1.0)

    close = 30 * np.exp(np.cumsum(np.log1p(ret), axis=0)) * np.exp(rng.normal(0, 0.8, N))
    open_ = close / (1 + ret) * np.exp(rng.standard_normal((T, N)) * 0.004)
    high = np.maximum(open_, close) * (1 + np.abs(rng.standard_normal((T, N))) * 0.006)
    low = np.minimum(open_, close) * (1 - np.abs(rng.standard_normal((T, N))) * 0.006)
    vwap = (high + low + close) / 3
    cap = np.exp(size) * (close / close[0])
    sharesout = cap / close
    volume = np.exp(np.log(cap) - 4 + 0.6 * np.abs(idio) / vol_level + rng.standard_normal((T, N)) * 0.3)
    adv20 = pd.DataFrame(volume).rolling(20, min_periods=1).mean().to_numpy()

    # ----- fundamentals (quarterly), consistent with the latent characteristics
    assets = np.exp(np.log(cap) + 0.5 + 0.3 * rng.standard_normal(N))
    sales = assets * np.exp(-0.3 + 0.2 * quality)
    cogs = sales * (0.65 - 0.08 * np.tanh(quality))
    cfo = cap * 0.06 * np.exp(0.5 * value) * (1 + 0.1 * quality)
    accr = -0.04 * quality + 0.02 * rng.standard_normal((T, N))
    net_income = cfo + accr * assets
    debt = assets * (0.3 - 0.05 * quality).clip(0.05)
    equity = assets - debt - 0.2 * assets
    inventory = assets * 0.1 * np.exp(-0.2 * quality)
    receivables = sales * 0.15
    capex = assets * 0.05 * np.exp(0.1 * rng.standard_normal((T, N)))
    qn = rng.standard_normal((T, N)) * 0.03

    def q(x):
        return _quarterly(x, offs, noise=qn * np.abs(x))

    fields = {
        "open": open_, "high": high, "low": low, "close": close, "vwap": vwap, "volume": volume, "adv20": adv20,
        "returns": ret, "cap": cap, "sharesout": sharesout,
        "fnd_sales": q(sales), "fnd_cogs": q(cogs), "fnd_net_income": q(net_income), "fnd_cfo": q(cfo),
        "fnd_assets": q(assets), "fnd_debt": q(debt), "fnd_equity": q(equity), "fnd_inventory": q(inventory),
        "fnd_receivables": q(receivables), "fnd_capex": q(capex),
    }
    eps_level = net_income / sharesout
    est = eps_level * (1 + 0.15 * np.tanh(np.cumsum(rev_shock * 0.03, axis=0) / 3))
    fields["anl_est_eps"] = est
    fields["anl_est_eps_std"] = np.abs(est) * (0.05 + 0.05 * np.abs(rng.standard_normal((T, N))))
    up = np.clip(np.round(3 + 1.0 * rev_shock + 1.5 * rng.standard_normal((T, N))), 0, None)
    dn = np.clip(np.round(3 - 1.0 * rev_shock + 1.5 * rng.standard_normal((T, N))), 0, None)
    fields["anl_rev_up_30d"], fields["anl_rev_down_30d"] = up, dn
    fields["anl_num_est"] = np.clip(np.round(np.exp(np.log(cap) / 3)), 1, 40)
    fields["ern_eps_surprise"] = surprise
    fields["mdl_value_score"] = pd.DataFrame(value + 0.8 * _ar1(rng, T, N, 0.98)).rank(axis=1, pct=True).to_numpy() * 100
    fields["mdl_quality_score"] = pd.DataFrame(quality + 0.8 * _ar1(rng, T, N, 0.98)).rank(axis=1, pct=True).to_numpy() * 100
    fields["snt_news_sentiment"] = sentiment
    fields["snt_news_count"] = news_on.astype(float) + rng.poisson(0.2, (T, N))
    for j in range(40):
        fields[f"nz_{j:03d}"] = _ar1(rng, T, N, rng.uniform(0.9, 0.999))

    # one VECTOR field: individual analyst EPS estimates (K=6 analysts, some missing)
    K = 6
    vec = est[:, :, None] * (1 + 0.05 * rng.standard_normal((T, N, K)))
    vec[rng.random((T, N, K)) < 0.3] = np.nan
    groups = {"sector": np.broadcast_to(sector, (T, N)).copy(), "industry": np.broadcast_to(industry, (T, N)).copy(),
              "subindustry": np.broadcast_to(sub, (T, N)).copy(), "country": np.broadcast_to(country, (T, N)).copy(),
              "market": np.zeros((T, N), int)}
    desc = {
        "returns": "Daily returns", "close": "Daily close price", "open": "Daily open price", "high": "Daily high price",
        "low": "Daily low price", "vwap": "Volume weighted average price", "volume": "Daily volume",
        "adv20": "Average daily volume in past 20 days", "cap": "Daily market capitalization (in millions)",
        "sharesout": "Shares outstanding",
        "fnd_sales": "Total revenue (sales), quarterly", "fnd_cogs": "Cost of goods sold, quarterly",
        "fnd_net_income": "Net income, quarterly", "fnd_cfo": "Cash flow from operating activities, quarterly",
        "fnd_assets": "Total assets, quarterly", "fnd_debt": "Total debt, quarterly",
        "fnd_equity": "Total shareholders equity (book value), quarterly", "fnd_inventory": "Inventory, quarterly",
        "fnd_receivables": "Receivables, quarterly", "fnd_capex": "Capital expenditure, quarterly",
        "anl_est_eps": "Consensus mean EPS estimate for next fiscal year (FY1)",
        "anl_est_eps_std": "Standard deviation of analyst EPS estimates (FY1)",
        "anl_rev_up_30d": "Number of analysts revising up FY1 EPS estimates in the past 30 days",
        "anl_rev_down_30d": "Number of analysts revising down FY1 EPS estimates in the past 30 days",
        "anl_num_est": "Number of analysts estimates (FY1 EPS)",
        "ern_eps_surprise": "Earnings surprise: actual EPS minus consensus estimate, scaled",
        "mdl_value_score": "Relative valuation score, 1-100 percentile, higher = better value",
        "mdl_quality_score": "Earnings quality score, 1-100 percentile, higher = better quality",
        "snt_news_sentiment": "News sentiment score of stories published today (NaN if no news)",
        "snt_news_count": "Number of news stories today (buzz)",
        "anl_est_eps_vec": "Individual analyst EPS estimates (VECTOR)",
        "sector": "Sector grouping", "industry": "Industry grouping", "subindustry": "Subindustry grouping",
        "country": "Country grouping", "market": "Market grouping",
    }
    for j in range(40):
        desc[f"nz_{j:03d}"] = f"Synthetic model output #{j} (pure noise - planted for the overfitting lesson)"
    return Data(fields, groups, {"anl_est_eps_vec": vec}, dates=dates, descriptions=desc)
