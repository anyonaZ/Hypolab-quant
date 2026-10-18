"""The weekly layer on top of HYPOLAB's PyramidTracker.

HYPOLAB already knows WHICH Pyramid cells are empty (tracker.plan()). This module decides what to do
THIS week: one region, one or two categories, one dataset to read closely - and measures the week
against the quarter's goals.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional

import pandas as pd

from hypolab import config
from hypolab.catalog import CATEGORY_NAMES
from hypolab.pyramids import GUIDE_DATASETS, TIERS

# Starting from zero Pyramids: two regions x the five tier-1 categories = 10 Pyramids (the Expert bar).
STARTING_PLAN = {
    "2026-W42": ("USA", ["analyst", "fundamental"]),
    "2026-W43": ("USA", ["pv", "model", "risk"]),
    "2026-W44": ("GLB", ["analyst", "fundamental"]),
    "2026-W45": ("GLB", ["pv", "model", "risk"]),
    "2026-W46": ("EUR", ["analyst", "fundamental"]),
}

CATEGORY_IDS = [c for t in (1, 2, 3) for c in TIERS[t]]


def category_name(cid: str) -> str:
    return CATEGORY_NAMES.get(cid, cid)


def iso_week(day: Optional[dt.date] = None) -> str:
    y, w, _ = (day or dt.date.today()).isocalendar()
    return f"{y}-W{w:02d}"


def week_start(week: str) -> dt.date:
    y, w = week.split("-W")
    return dt.date.fromisocalendar(int(y), int(w), 1)


def next_week(week: str) -> str:
    return iso_week(week_start(week) + dt.timedelta(days=7))


def quarter_bounds(quarter: str) -> tuple:
    """'2026-Q4' -> (date(2026,10,1), date(2026,12,31))."""
    y, q = quarter.split("-Q")
    y, q = int(y), int(q)
    start = dt.date(y, 3 * (q - 1) + 1, 1)
    end = (dt.date(y + (q == 4), (3 * q) % 12 + 1, 1)) - dt.timedelta(days=1)
    return start, end


def guide_dataset(category: str) -> str:
    """First dataset the Pyramids guide recommends for a category (without the shape note)."""
    for d in GUIDE_DATASETS.get(category, []):
        if not d.upper().startswith("NOT "):
            return d.split(" (")[0].split(" /")[0].strip()
    return ""


def propose(week: str, tracker=None, saved: Optional[dict] = None) -> dict:
    """A plan for `week`: the saved one if any, else the starting plan, else the top empty cells."""
    if saved:
        return saved
    if week in STARTING_PLAN:
        region, cats = STARTING_PLAN[week]
    else:
        region, cats = config.live_region(), ["analyst", "fundamental"]
        if tracker is not None:
            plan = tracker.plan(n=30)
            if not plan.empty:
                region = plan.iloc[0]["region"]
                names = plan[plan["region"] == region]["category"].tolist()[:2]
                rev = {v: k for k, v in CATEGORY_NAMES.items()}
                cats = [rev.get(n, n.lower()) for n in names]
    universe = config.REGION_DEFAULTS.get(region, {}).get("universe", "TOP3000")
    return {"week": week, "region": region, "universe": universe, "delay": 1, "categories": cats,
            "dataset_focus": guide_dataset(cats[0]) if cats else "", "card_target": 5,
            "submit_target": DEFAULT_WEEKLY_SUBMISSIONS, "review_note": ""}


# ------------------------------------------------------------------- submissions: daily cap + SuperAlpha unlock
# BRAIN expects up to 4 alphas + 1 SuperAlpha a day. 4 is the CEILING. The default weekly target is 2 a working
# day: it unlocks SuperAlphas in about five weeks while leaving room to submit only what clears the gate
# (combined alpha performance is a Genius bar, so weak filler hurts).
DEFAULT_WEEKLY_SUBMISSIONS = 10
WORKDAYS_PER_WEEK = 5


def _workdays_needed(n: int, per_day: float) -> int:
    return 0 if n <= 0 else math.ceil(n / max(per_day, 1e-9))


def _add_workdays(start: dt.date, n: int) -> dt.date:
    d = start
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def lifetime_submitted(store, journal=None) -> int:
    """The count you entered from BRAIN, plus every alpha submitted through HYPOLAB since (live journal only)."""
    lt = store.lifetime()
    extra = 0
    if journal is not None and getattr(journal, "path", None) != ":memory:":
        sub = journal.submissions()
        if not sub.empty:
            extra = int((sub["submitted"] > lt["since"]).sum())
    return int(lt["base"]) + extra


def submission_status(store, journal=None, today: Optional[dt.date] = None,
                      weekly_target: Optional[int] = None) -> Dict[str, object]:
    """Today's submissions against the daily cap, and the road to the SuperAlpha unlock."""
    st = config.settings()
    cap = int(st.get("max_submissions_per_day", 4))
    unlock = int(store.lifetime()["unlock"] or st.get("superalpha_unlock_after", 100))
    today = today or dt.date.today()
    done_today = journal.submissions_today() if journal is not None else 0
    lifetime = lifetime_submitted(store, journal)
    to_unlock = max(0, unlock - lifetime)
    left_today = max(0, cap - done_today)
    weekly = int(weekly_target or DEFAULT_WEEKLY_SUBMISSIONS)

    def unlock_date(per_day: float) -> Optional[dt.date]:
        if to_unlock == 0:
            return today
        rest = to_unlock - min(left_today, per_day) if today.weekday() < 5 else to_unlock
        return today if rest <= 0 else _add_workdays(today, _workdays_needed(rest, per_day))

    return {"cap": cap, "submitted_today": done_today, "left_today": left_today, "lifetime": lifetime,
            "unlock_at": unlock, "to_unlock": to_unlock, "superalpha_unlocked": to_unlock == 0,
            "weekly_target": weekly,
            "unlock_at_cap": unlock_date(cap),
            "unlock_at_target": unlock_date(weekly / WORKDAYS_PER_WEEK)}


def submission_summary(status: Dict[str, object]) -> str:
    s = status
    head = (f"**Today:** {s['submitted_today']}/{s['cap']} alphas submitted ({s['left_today']} left). ")
    if s["superalpha_unlocked"]:
        return head + "**SuperAlpha: unlocked** - one a day."
    fmt = lambda d: d.strftime("%a %d %b") if d else "-"   # noqa: E731
    return (head + f"**SuperAlpha: locked** - {s['lifetime']}/{s['unlock_at']} lifetime alphas, "
            f"{s['to_unlock']} to go. At this week's target ({s['weekly_target']} a week) it unlocks around "
            f"{fmt(s['unlock_at_target'])}; at the full {s['cap']} a day (working days) around "
            f"{fmt(s['unlock_at_cap'])}. The cap is a ceiling: submit only what clears the gate.")


def week_progress(journal, week: str) -> Dict[str, object]:
    """What happened in the journal during one ISO week (simulations, ideas, verdicts)."""
    start = dt.datetime.combine(week_start(week), dt.time())
    end = start + dt.timedelta(days=7)
    sub = journal.submissions()
    submitted = 0 if sub.empty else int(((sub["submitted"] >= start.timestamp()) &
                                         (sub["submitted"] < end.timestamp())).sum())
    ex = journal.experiments()
    if ex.empty:
        return {"simulations": 0, "ideas_tested": 0, "verdicts": {}, "best_sharpe": None, "submitted": submitted}
    ex = ex[(ex["created"] >= start.timestamp()) & (ex["created"] < end.timestamp())]
    return {"simulations": int(len(ex)), "ideas_tested": int(ex["idea_id"].nunique()),
            "verdicts": ex["verdict"].replace("", "-").value_counts().to_dict(),
            "best_sharpe": None if ex["sharpe"].dropna().empty else round(float(ex["sharpe"].max()), 2),
            "submitted": submitted}


def submissions_in_quarter(journal, quarter: str) -> int:
    start, end = quarter_bounds(quarter)
    sub = journal.submissions()
    if sub.empty:
        return 0
    t0 = dt.datetime.combine(start, dt.time()).timestamp()
    t1 = dt.datetime.combine(end + dt.timedelta(days=1), dt.time()).timestamp()
    return int(((sub["submitted"] >= t0) & (sub["submitted"] < t1)).sum())


def weeks_left(quarter: str, today: Optional[dt.date] = None) -> float:
    _, end = quarter_bounds(quarter)
    return max(0.0, round(((end - (today or dt.date.today())).days + 1) / 7, 1))


def goals_view(store, journal=None, today: Optional[dt.date] = None) -> pd.DataFrame:
    """Goals with the weekly pace needed to reach each bar by the end of the quarter."""
    g = store.goals()
    if g.empty:
        return g
    left = weeks_left(g["quarter"].iloc[0], today)
    g["weeks_left"] = left
    g["per_week_needed"] = (g["still_needed"] / left).round(2) if left else None
    # a pace only makes sense for counts; combined performance is a level, not something you add weekly
    g.loc[g["key"] == "combined_perf", "per_week_needed"] = None
    if journal is not None:
        g["journal_hint"] = ""
        g.loc[g["key"] == "signals", "journal_hint"] = (
            f"{submissions_in_quarter(journal, g['quarter'].iloc[0])} submitted through HYPOLAB this quarter")
    return g
