"""BRAIN's own rules, in one place (see docs/BRAIN_RULES.md for the source of every number).

* Single Dataset Alphas  - fields from one dataset only (grouping fields don't count) skip the
  IS-ladder Sharpe test and must instead clear a last-2-year Sharpe cutoff.        [S1]
* Sub-universe test      - sub_sharpe >= 0.75 * sqrt(sub_size / size) * sharpe.     [S9]
* Fitness rating labels  - Spectacular / Excellent / Good / Average / Needs Improvement. [S18]
* BRAIN's day            - simulation quota and daily counts reset at midnight New York time. [S2]
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Callable, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from . import fastexpr as fx

BRAIN_TZ = ZoneInfo("America/New_York")

_KEYWORDS = {"true", "false", "nan", "NaN", "inf"}

# Grouping fields a Single Dataset Alpha may use on top of its one dataset [S1].
GROUPING_FIELDS = {"country", "exchange", "market", "sector", "industry", "subindustry"}
# Operators that read pv1 data under the hood [S1].
PV1_OPERATORS = {"inst_pnl", "convert"}
# Last-2-year IS Sharpe a Single Dataset Alpha must clear, by delay [S1].
SINGLE_DATASET_2Y_SHARPE = {1: 2.38, 0: 3.96}
# BRAIN multiplies IS-ladder thresholds by 0.85 when turnover < 30%. Whether that also applies to the
# single-dataset cutoffs is not stated (BRAIN_RULES T2), so we only mention it.
LOW_TURNOVER_FACTOR = 0.85
LOW_TURNOVER_BELOW = 0.30

FITNESS_LABELS = {  # (label, D1 lower bound, D0 lower bound) - strictly greater than [S18]
    "Spectacular": (2.5, 3.25),
    "Excellent": (2.0, 2.6),
    "Good": (1.5, 1.95),
    "Average": (1.0, 1.3),
}


# ----------------------------------------------------------- single dataset
def fields_in(expression: str) -> List[str]:
    """Identifiers in an expression that are data fields (not operators, not assigned variables)."""
    try:
        prog = fx.parse(expression)
    except fx.ParseError:
        return []
    assigned = {n.target for n in fx.walk(prog) if isinstance(n, fx.Assign)} | _KEYWORDS
    out = []
    for n in fx.walk(prog):
        if isinstance(n, fx.Name) and n.id not in assigned and n.id not in out:
            out.append(n.id)
    return out


def dataset_profile(expression: str, dataset_of: Callable[[str], Optional[str]], delay: int = 1) -> Dict:
    """Which datasets an expression draws on, and which IS Sharpe test applies.

    ``dataset_of(field_id)`` returns the field's dataset id, or None if unknown (e.g. no catalog yet).
    Returns {"datasets": [...], "unknown": [...], "single": bool | None, "test": str, "cutoff": float | None}.
    ``single`` is None when some fields could not be looked up.
    """
    try:
        ops = set(fx.operators_used(fx.parse(expression)))
    except fx.ParseError:
        ops = set()
    datasets, unknown = set(), []
    for f in fields_in(expression):
        if f in GROUPING_FIELDS:
            continue
        ds = dataset_of(f)
        if ds:
            datasets.add(ds)
        else:
            unknown.append(f)
    if ops & PV1_OPERATORS:
        datasets.add("pv1")
    if unknown:
        single = None
    else:
        single = len(datasets) == 1
    cutoff = SINGLE_DATASET_2Y_SHARPE.get(int(delay)) if single else None
    if single:
        test = f"single dataset ({next(iter(datasets))}): last-2-year Sharpe >= {cutoff} instead of the IS ladder"
    elif single is None:
        test = f"unknown - no catalog entry for {', '.join(unknown)}"
    else:
        test = f"{len(datasets)} datasets ({', '.join(sorted(datasets))}): regular IS-ladder Sharpe test"
    return {"datasets": sorted(datasets), "unknown": unknown, "single": single, "test": test, "cutoff": cutoff}


def catalog_lookup(catalog, region: str, universe: Optional[str], delay: int) -> Callable[[str], Optional[str]]:
    """dataset_of() backed by HYPOLAB's catalog (one query, then a dict)."""
    try:
        if hasattr(catalog, "lookup_map"):
            return catalog.lookup_map(region, universe, delay).get      # cached per context (1.4.3)
        df = catalog.fields(region, universe, delay, enrich=False)
    except Exception:  # noqa: BLE001
        df = None
    m = {} if df is None or df.empty else dict(zip(df["id"], df["dataset"]))
    return m.get


# ------------------------------------------------------------ other tests
def sub_universe_cutoff(alpha_sharpe: float, sub_size: float, size: float) -> float:
    """BRAIN's sub-universe threshold [S9], e.g. TOP3000 -> TOP1000: 0.433 x Sharpe."""
    if not size:
        return 0.0
    return 0.75 * math.sqrt(sub_size / size) * alpha_sharpe


def fitness_label(fitness: Optional[float], delay: int = 1) -> str:
    if fitness is None or (isinstance(fitness, float) and math.isnan(fitness)):
        return ""
    col = 0 if int(delay) == 1 else 1
    for label, bounds in FITNESS_LABELS.items():
        if fitness > bounds[col]:
            return label
    return "Needs Improvement"


# --------------------------------------------------------------- BRAIN day
def brain_day_start(now: Optional[_dt.datetime] = None) -> float:
    """Unix time of the last midnight in New York - when BRAIN's daily simulation quota resets [S2]."""
    now = now or _dt.datetime.now(tz=_dt.timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_dt.timezone.utc)
    ny = now.astimezone(BRAIN_TZ)
    midnight = _dt.datetime.combine(ny.date(), _dt.time(), tzinfo=BRAIN_TZ)
    return midnight.timestamp()


def quarter_bounds(day: Optional[_dt.date] = None) -> tuple:
    """(start, end) dates of the calendar quarter - Genius counts signals and Pyramids per quarter [S14]."""
    day = day or _dt.date.today()
    q0 = 3 * ((day.month - 1) // 3) + 1
    start = _dt.date(day.year, q0, 1)
    end = _dt.date(day.year + (q0 == 10), 1 if q0 == 10 else q0 + 3, 1) - _dt.timedelta(days=1)
    return start, end


def osmosis_lock_deadline(quarter_end: _dt.date, weeks_needed: int = 6) -> _dt.date:
    """Last Sunday whose locked allocation still gives ``weeks_needed`` used weeks by quarter end [S10].

    Points lock Sunday 23:59 New York time and are used from the Monday 8 days later.
    """
    d = quarter_end
    while d.weekday() != 6:
        d -= _dt.timedelta(days=1)
    while True:
        first_used = d + _dt.timedelta(days=8)
        weeks = (quarter_end - first_used).days // 7 + 1
        if weeks >= weeks_needed:
            return d
        d -= _dt.timedelta(days=7)


def split_names(items: Iterable[str]) -> str:
    return ", ".join(sorted(set(items)))
