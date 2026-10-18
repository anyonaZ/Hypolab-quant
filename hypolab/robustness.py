"""Robustness battery - WorldQuant's own pre-submission tests.

From the BRAIN webinar on robust alphas (captured in your zip's AlphaForge
knowledge base): a robust alpha is not sensitive to small changes.

* rank test        rank(alpha)            - does the ORDER carry the signal?
* binary test      rank(alpha) > 0.5      - collapse means a few names' magnitudes drive PnL
* outlier test     winsorize(alpha, std=4)- disappearing PnL means outliers drove it
* window twist     every window x0.85 / x1.15 - "63 -> 60 must not do large damage"
* neutralization   one neighbouring neutralization
* universe         a more liquid universe (where defined)

These are VALIDATION runs, not a search: you do not pick the best variant,
you check that none of them collapses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

import pandas as pd

from . import fastexpr as fx
from .diagnose import wrap_result
from .operators import GOLD

NEIGHBOUR_NEUT = {"SUBINDUSTRY": "INDUSTRY", "INDUSTRY": "SUBINDUSTRY", "SECTOR": "INDUSTRY", "MARKET": "SECTOR",
                  "STATISTICAL": "MARKET", "NONE": "MARKET", "COUNTRY": "MARKET"}
LIQUID_UNIVERSE = {"USA": "TOP1000", "EUR": "TOP1200"}


def twist_windows(expression: str, factor: float) -> Optional[str]:
    prog = fx.parse(expression)
    changed = False
    for n in fx.walk(prog):
        if isinstance(n, fx.Call):
            spec = GOLD.get(n.func)
            if not spec:
                continue
            for i, a in enumerate(n.args):
                if i < len(spec.params) and spec.kind_of(spec.params[i]) == "window" and isinstance(a, fx.Num):
                    new = max(2, int(round(a.value * factor)))
                    if new != a.value:
                        a.value = float(new)
                        changed = True
    return fx.to_string(prog) if changed else None


@dataclass
class Variant:
    name: str
    expression: str
    settings: dict
    test: str


def variants(expression: str, settings: dict) -> List[Variant]:
    out = [Variant("rank test", wrap_result(expression, "rank({})"), dict(settings), "order carries the signal"),
           Variant("binary test", wrap_result(expression, "rank({}) > 0.5"), dict(settings), "not a few large bets"),
           Variant("outlier test", wrap_result(expression, "winsorize({}, std=4)"), dict(settings), "not outlier-driven")]
    for f, label in ((0.85, "windows -15%"), (1.15, "windows +15%")):
        e = twist_windows(expression, f)
        if e:
            out.append(Variant(label, e, dict(settings), "parameters not fitted"))
    neut = settings.get("neutralization", "SUBINDUSTRY")
    if neut in NEIGHBOUR_NEUT:
        s2 = dict(settings, neutralization=NEIGHBOUR_NEUT[neut])
        out.append(Variant(f"neutralization {NEIGHBOUR_NEUT[neut]}", expression, s2, "not a neutralization artefact"))
    reg = settings.get("region")
    if reg in LIQUID_UNIVERSE and settings.get("universe") != LIQUID_UNIVERSE[reg]:
        out.append(Variant(f"universe {LIQUID_UNIVERSE[reg]}", expression, dict(settings, universe=LIQUID_UNIVERSE[reg]),
                           "works in liquid names"))
    return out


def score(base_sharpe: float, rows: pd.DataFrame) -> dict:
    """rows: DataFrame with columns variant, sharpe. Pass = same sign and >= 70% of base (50% for binary)."""
    if rows.empty or not base_sharpe:
        return {"score": 0.0, "verdict": "no data"}
    ok = []
    for r in rows.itertuples(index=False):
        need = 0.5 if r.variant == "binary test" else 0.7
        ok.append((r.sharpe or 0) * (1 if base_sharpe > 0 else -1) >= need * abs(base_sharpe))
    frac = sum(ok) / len(ok)
    verdict = ("robust" if frac >= 0.8 else "fragile in places - read which test failed" if frac >= 0.5
               else "fragile - likely fitted to noise or a few names")
    return {"score": round(frac, 2), "verdict": verdict, "passed": ok}


def run(expression: str, settings: dict, base_sharpe: float,
        simulate: Callable[[List[Variant]], List[dict]]) -> pd.DataFrame:
    """simulate(variants) -> list of summary dicts (is_sharpe, is_fitness, ...). Returns a report table."""
    vs = variants(expression, settings)
    res = simulate(vs)
    rows = []
    for v, r in zip(vs, res):
        rows.append({"variant": v.name, "tests": v.test, "sharpe": r.get("is_sharpe"), "fitness": r.get("is_fitness"),
                     "turnover": r.get("is_turnover"), "vs_base": round((r.get("is_sharpe") or 0) / base_sharpe, 2)
                     if base_sharpe else None, "expression": v.expression})
    df = pd.DataFrame(rows)
    sc = score(base_sharpe, df)
    if "passed" in sc:
        df["pass"] = sc["passed"]
    df.attrs["score"] = sc
    return df
