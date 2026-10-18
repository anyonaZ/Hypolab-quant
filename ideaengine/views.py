"""Small, testable helpers that turn HYPOLAB objects into what the cockpit shows.

Keeping them here (not in the marimo file) means they are unit-tested and the cockpit stays thin.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

import pandas as pd

from hypolab.catalog import CATEGORY_NAMES

VERDICT_ORDER = ["PASS", "NEAR", "WEAK", "INVERTED", "NOISE", "ERROR", "BLOCKED", "BUDGET"]


def cards_table(cards: Iterable) -> pd.DataFrame:
    rows = []
    for c in cards:
        h = c.hypothesis
        rows.append({"id": h.id, "title": h.title, "source": h.source,
                     "pyramid": ", ".join(CATEGORY_NAMES.get(x, x) for x in c.categories),
                     "evidence": h.stars, "horizon": h.horizon, "family": h.family,
                     "fields": ", ".join(b.field_id for b in c.bindings.values()) or "price/volume",
                     "rungs": len(c.steps), "score": round(c.score, 2)})
    return pd.DataFrame(rows, columns=["id", "title", "source", "pyramid", "evidence", "horizon", "family",
                                       "fields", "rungs", "score"])


def _num(v, nd=2):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def result_row(t) -> Dict[str, object]:
    """One line of the Lab's history for a TestResult."""
    s = t.summary or {}
    return {"idea": t.card.hypothesis.id if t.card else (getattr(t, "idea_id", None) or "manual"), "rung": t.rung,
            "alpha_id": t.alpha_id,
            "verdict": t.diagnosis.verdict, "sharpe": _num(s.get("is_sharpe")), "fitness": _num(s.get("is_fitness")),
            "turnover": _num(s.get("is_turnover"), 3), "cached": bool(t.cached),
            "next": t.diagnosis.next.title if t.diagnosis.next else "", "expression": t.expression}


def action_choices(t) -> Dict[str, int]:
    """Diagnosis actions that R.follow() can apply automatically (an expression or settings change)."""
    out = {}
    for i, a in enumerate(t.diagnosis.actions or []):
        if a.kind != "stop" and (a.expression or a.settings):
            out[f"{i + 1}. {a.title}"] = i
    return out


def verdict_mix(experiments: pd.DataFrame) -> pd.DataFrame:
    if experiments.empty:
        return pd.DataFrame(columns=["verdict", "simulations"])
    v = experiments["verdict"].replace("", "-").value_counts()
    order = [x for x in VERDICT_ORDER if x in v.index] + [x for x in v.index if x not in VERDICT_ORDER]
    return pd.DataFrame({"verdict": order, "simulations": [int(v[x]) for x in order]})


def tries_per_idea(experiments: pd.DataFrame, budget: int) -> pd.DataFrame:
    if experiments.empty:
        return pd.DataFrame(columns=["idea_id", "tries", "budget_left", "best_sharpe", "best_verdict"])
    ex = experiments[experiments["purpose"].isin(["explore", "boost"])]
    if ex.empty:
        return pd.DataFrame(columns=["idea_id", "tries", "budget_left", "best_sharpe", "best_verdict"])
    rank = {v: i for i, v in enumerate(VERDICT_ORDER)}
    g = ex.groupby("idea_id").agg(tries=("id", "count"), best_sharpe=("sharpe", "max"),
                                  best_verdict=("verdict", lambda s: min(s, key=lambda x: rank.get(x, 99))))
    g["budget_left"] = (budget - g["tries"]).clip(lower=0)
    g["best_sharpe"] = g["best_sharpe"].round(2)
    return g.reset_index()[["idea_id", "tries", "budget_left", "best_sharpe", "best_verdict"]] \
        .sort_values("tries", ascending=False).reset_index(drop=True)


def experiments_view(experiments: pd.DataFrame, region: Optional[str] = None,
                     verdicts: Optional[List[str]] = None) -> pd.DataFrame:
    if experiments.empty:
        return experiments
    ex = experiments.copy()
    if region:
        ex = ex[ex["region"] == region]
    if verdicts:
        ex = ex[ex["verdict"].isin(verdicts)]
    ex["when"] = pd.to_datetime(ex["created"], unit="s").dt.strftime("%Y-%m-%d %H:%M")
    cols = ["when", "idea_id", "rung", "purpose", "region", "verdict", "sharpe", "fitness", "turnover", "failed",
            "alpha_id", "expression"]
    return ex.sort_values("created", ascending=False)[cols].reset_index(drop=True)


def pnl_figure(pnl: pd.DataFrame, title: str = ""):
    """Cumulative PnL lines (one per column) in the Matrix theme - small, so it renders fast on a laptop."""
    import matplotlib.pyplot as plt

    from hypolab import theme
    theme.apply_matplotlib()
    fig, ax = plt.subplots(figsize=(8.5, 2.9))
    for i, col in enumerate(pnl.columns):
        ax.plot(pnl.index, pnl[col], label=col, linewidth=2.0 if i == 0 else 1.2,
                alpha=1.0 if i == 0 else 0.75, color=theme.SERIES[i % len(theme.SERIES)])
    ax.axhline(0, color=theme.BORDER, linewidth=0.8)
    ax.set_ylabel("cumulative PnL")
    if len(pnl.columns) > 1:
        ax.legend(fontsize=8, loc="upper left")
    if title:
        ax.set_title(title, fontsize=10, loc="left", color=theme.TEXT)
    fig.tight_layout()
    return fig


def pyramid_heatmap(matrix: pd.DataFrame, need: int, title: str = ""):
    """Region x category grid: grey = empty, light = started, strong = complete (>= need alphas)."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap

    from hypolab import theme
    theme.apply_matplotlib()
    vals = matrix.values.astype(float)
    level = (vals > 0).astype(int) + (vals >= need).astype(int)
    fig, ax = plt.subplots(figsize=(max(7, 0.62 * matrix.shape[1] + 2), 0.5 * matrix.shape[0] + 1.4))
    ax.imshow(level, cmap=ListedColormap(theme.PYRAMID_LEVELS), vmin=0, vmax=2, aspect="auto")
    for i in range(vals.shape[0]):
        for j in range(vals.shape[1]):
            ax.text(j, i, f"{int(vals[i, j])}/{need}", ha="center", va="center", fontsize=8,
                    color=("#001a0d" if level[i, j] == 2 else "#d2f5e1") if level[i, j] else theme.MUTED,
                    fontweight="bold" if level[i, j] == 2 else "normal")
    ax.set_xticks(range(matrix.shape[1]))
    ax.set_xticklabels(matrix.columns, rotation=35, ha="right", fontsize=8)
    ax.set_yticks(range(matrix.shape[0]))
    ax.set_yticklabels(matrix.index, fontsize=9)
    ax.set_xticks([x - 0.5 for x in range(1, matrix.shape[1])], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, matrix.shape[0])], minor=True)
    ax.grid(False)
    ax.grid(which="minor", color=theme.SURFACE, linewidth=2)
    ax.tick_params(which="both", length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    if title:
        ax.set_title(title, fontsize=10, loc="left", color=theme.TEXT)
    fig.tight_layout()
    return fig



def html_table(df: pd.DataFrame, code_cols: Iterable[str] = ()) -> str:
    """A read-only table as HTML (no UI element: safe in cells that re-run on every keystroke).
    Wrapped in div.hl-mdtable, which wraps long cells and scrolls sideways instead of overflowing."""
    import html as _html
    if df is None or df.empty:
        return "<p><em>none</em></p>"
    code = set(code_cols)

    def cell(col, v):
        s = "" if v is None or (isinstance(v, float) and math.isnan(v)) else _html.escape(str(v))
        return f"<code>{s}</code>" if col in code and s else s
    head = "".join(f"<th>{_html.escape(str(c))}</th>" for c in df.columns)
    rows = "".join("<tr>" + "".join(f"<td>{cell(c, v)}</td>" for c, v in zip(df.columns, r)) + "</tr>"
                   for r in df.itertuples(index=False))
    return f'<div class="hl-mdtable"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'
