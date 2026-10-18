"""Small helpers for the learning app (sandbox data)."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

from .sandbox.backtest import backtest
from .sandbox.evaluator import Data, Evaluator


def describe(expr: str, data: Data, day: int = -1) -> pd.Series:
    """Cross-sectional distribution of an expression on one day."""
    x = Evaluator(data)(expr)[day]
    v = x[np.isfinite(x)]
    if v.size == 0:
        return pd.Series({"coverage": 0.0})
    return pd.Series({"coverage": round(v.size / x.size, 3), "min": v.min(), "p05": np.percentile(v, 5),
                      "median": np.median(v), "p95": np.percentile(v, 95), "max": v.max(), "mean": v.mean(),
                      "std": v.std(), "skew": pd.Series(v).skew()}).round(4)


def plot_distribution(exprs: Iterable[str], data: Data, day: int = -1, bins: int = 40):
    import matplotlib.pyplot as plt

    from . import theme
    theme.apply_matplotlib()
    exprs = list(exprs)
    ev = Evaluator(data)
    fig, axes = plt.subplots(1, len(exprs), figsize=(4 * len(exprs), 3))
    axes = np.atleast_1d(axes)
    for ax, e in zip(axes, exprs):
        x = ev(e)[day]
        ax.hist(x[np.isfinite(x)], bins=bins, color=theme.TEAL, alpha=0.85)
        ax.set_title(e if len(e) < 38 else e[:35] + "...", fontsize=9)
    fig.tight_layout()
    return fig


def run(exprs: Dict[str, str] | List[str], data: Data, decay: int = 0, neutralization: str = "SUBINDUSTRY",
        truncation: float = 0.08, test_years: float = 2.0) -> pd.DataFrame:
    """Backtest several expressions and return a comparison table."""
    if not isinstance(exprs, dict):
        exprs = {e: e for e in exprs}
    ev = Evaluator(data)
    rows = []
    for name, e in exprs.items():
        r = backtest(ev(e), data, decay=decay, neutralization=neutralization, truncation=truncation,
                     test_years=test_years)
        rows.append({"name": name, **{k: r.stats[k] for k in ("sharpe", "fitness", "turnover", "returns", "drawdown")},
                     "train_sharpe": r.train.get("sharpe"), "test_sharpe": r.test.get("sharpe"),
                     "failed": ", ".join(r.failed)})
    return pd.DataFrame(rows)


def pnl_plot(exprs: Dict[str, str], data: Data, decay: int = 0, neutralization: str = "SUBINDUSTRY"):
    import matplotlib.pyplot as plt

    from . import theme
    theme.apply_matplotlib()
    ev = Evaluator(data)
    fig, ax = plt.subplots(figsize=(9, 3.5))
    for name, e in exprs.items():
        r = backtest(ev(e), data, decay=decay, neutralization=neutralization)
        ax.plot(r.pnl.cumsum() / 1e6, label=f"{name} (Sharpe {r.stats['sharpe']})")
    ax.set_ylabel("cumulative PnL ($M, synthetic)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def template_sweep(templates: List[str], fields: List[str], data: Data, **kw) -> pd.DataFrame:
    """What the zip's notebooks do: every template x every field. Used to SHOW the overfitting trap."""
    exprs = {f"{t.format(x=f)}": t.format(x=f) for f in fields for t in templates}
    return run(exprs, data, **kw).sort_values("sharpe", ascending=False).reset_index(drop=True)
