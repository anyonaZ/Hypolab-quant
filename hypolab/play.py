"""The playground: random alphas for exploring, outside the Pyramid plan.

Two ways to roll (both free - nothing is simulated until you ask):

* random cards  - any idea card (built-in or yours), bound in the chosen region, a random rung, optionally
                  shuffled settings. Ignores the Pyramid plan and the ranking entirely.
* wild          - a random field (or two fields of the SAME dataset) from a random dataset, dropped into a random
                  template (rank of a change, a z-score within a group, a spread of two siblings ...).
                  Two fields from one dataset keep the alpha "single dataset" (BRAIN_RULES T1).

    from hypolab.play import roll, play_stats
    items = roll(R.catalog, "USA", n=5, mode="mix", seed=42)
    results = R.play(items)                    # simulates, journals as purpose "play"

Honesty: random search finds luck as easily as signal. Every play counts as a try for its idea (`play:...`),
so if you later take one to the gate, the deflated Sharpe knows how many dice you threw.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from . import config, rules
from .concepts import NON_NUMERIC
from .hypotheses import load_library
from .linter import Linter

WINDOWS = [5, 10, 21, 63, 126, 252]
GROUPS = ["industry", "subindustry", "sector"]

# One field: {x}; two sibling fields of one dataset: {x}, {y}; window {d}; group {g}.
TEMPLATES_ONE = [
    ("change", "rank(ts_delta({x}, {d}))", "Rank of how much {x} moved over {d} days"),
    ("level vs history", "ts_rank({x}, {d})", "Where {x} sits within its own last {d} days"),
    ("z-score in group", "group_rank(ts_zscore({x}, {d}), {g})", "{x} unusually high for this stock, ranked within its {g}"),
    ("surprise vs average", "rank({x} - ts_mean({x}, {d}))", "{x} above its own {d}-day average"),
    ("neutral level", "group_neutralize(rank({x}), {g})", "{x} level, neutralized within {g}"),
    ("smoothed trend", "rank(ts_decay_linear(ts_delta({x}, {d}), 10))", "Smoothed {d}-day change in {x}"),
    ("relative to group", "group_zscore({x}, {g})", "{x} relative to its {g} peers"),
    ("acceleration", "rank(ts_delta(ts_delta({x}, {d}), {d}))", "Change of the change in {x} (finite differences)"),
]
TEMPLATES_TWO = [
    ("sibling spread", "rank({x}) - rank({y})", "{x} high while its sibling {y} is low"),
    ("sibling ratio", "group_rank({x} / ({y} + 1e-6), {g})", "{x} relative to {y}, ranked within {g}"),
    ("decoupling", "-ts_corr(rank({x}), rank({y}), {d})", "{x} and {y} stop moving together over {d} days"),
]


@dataclass
class PlayItem:
    source: str                     # "card" | "wild"
    name: str                       # what was rolled, in a few words
    expression: str
    settings: dict                  # region, universe, delay, decay, neutralization, truncation
    story: str
    idea_id: str                    # journal idea the try counts against
    title: str = ""
    lint_ok: bool = True
    lint_msg: str = ""
    profile: dict = field(default_factory=dict)
    categories: List[str] = field(default_factory=list)
    card: object = None

    def row(self) -> dict:
        return {"source": self.source, "rolled": self.name, "expression": self.expression,
                "settings": f"D{self.settings.get('delay')} {self.settings.get('neutralization')} "
                            f"decay {self.settings.get('decay')} trunc {self.settings.get('truncation')}",
                "IS test": "single dataset" if self.profile.get("single") else
                           ("datasets unknown" if self.profile.get("single") is None else "IS ladder"),
                "linter": "ok" if self.lint_ok else self.lint_msg[:60], "idea": self.story}


def _settings(region: str, base: dict, rng: random.Random, shuffle: bool) -> dict:
    reg = config.REGION_DEFAULTS.get(region, {})
    s = {"region": region, "universe": base.get("universe") or config.universe_for(region), "delay": 1,
         "decay": int(base.get("decay", 0) or 0), "neutralization": base.get("neutralization") or
         reg.get("neutralization", "SUBINDUSTRY"), "truncation": float(base.get("truncation", 0.08) or 0.08)}
    if shuffle:
        neuts = [n for n in config.region_neutralizations(region) if n != "NONE"]
        s["decay"] = rng.choice([0, 2, 4, 6, 10])
        s["neutralization"] = rng.choice(neuts) if neuts else s["neutralization"]
        s["truncation"] = rng.choice([0.05, 0.08, 0.1])
    return s


def _roll_card(catalog, region: str, rng: random.Random, shuffle: bool, linter: Linter, library) -> Optional[PlayItem]:
    from .ideas import build_card           # local import: ideas imports a lot
    h = rng.choice(library)
    card = build_card(h, catalog, region, linter=linter)
    if card is None or not card.steps:
        return None
    ok_steps = [s for s in card.steps if s.lint.ok] or card.steps
    step = rng.choice(ok_steps)
    st = _settings(region, dict(card.settings, universe=card.universe), rng, shuffle)
    return PlayItem("card", f"{h.id} / {step.name}", step.expression, st, h.title, f"play:{h.id}@{region}",
                    title=h.title, lint_ok=step.lint.ok, lint_msg="; ".join(i.message for i in step.lint.errors()),
                    profile=step.profile, categories=list(card.categories), card=card)


def _usable_fields(catalog, region: str, universe: Optional[str]) -> pd.DataFrame:
    df = catalog.fields(region, universe, 1)
    if df.empty:
        return df
    df = df[df["type"].isin(["MATRIX", "VECTOR"]) & ~df["nature"].isin(NON_NUMERIC)]
    return df[pd.to_numeric(df["coverage"], errors="coerce").fillna(0) >= 0.4]


def _roll_wild(fields: pd.DataFrame, region: str, rng: random.Random, shuffle: bool, linter: Linter,
               dataset_of) -> Optional[PlayItem]:
    if fields.empty:
        return None
    ds = rng.choice(sorted(fields["dataset"].dropna().unique()))
    pool = fields[fields["dataset"] == ds]
    expr_of = lambda r: f"vec_avg({r['id']})" if r["type"] == "VECTOR" else r["id"]  # noqa: E731
    two = len(pool) >= 2 and rng.random() < 0.35
    d, g = rng.choice(WINDOWS), rng.choice(GROUPS)
    if two:
        a, b = pool.sample(2, random_state=rng.randrange(1 << 30)).to_dict("records")
        label, tpl, story = rng.choice(TEMPLATES_TWO)
        x, y = expr_of(a), expr_of(b)
        expr = tpl.format(x=x, y=y, d=d, g=g)
        story = story.format(x=a["id"], y=b["id"], d=d, g=g)
        cats = sorted({str(a.get("category")), str(b.get("category"))})
    else:
        a = pool.sample(1, random_state=rng.randrange(1 << 30)).iloc[0].to_dict()
        label, tpl, story = rng.choice(TEMPLATES_ONE)
        expr = tpl.format(x=expr_of(a), d=d, g=g)
        story = story.format(x=a["id"], d=d, g=g)
        cats = [str(a.get("category"))]
    if rng.random() < 0.5:                  # the dice decide the sign too
        expr = expr[1:] if expr.startswith("-") and expr.count("(") and expr[1:2].isalpha() else f"-({expr})"
        story = "Opposite of: " + story
    lint = linter.lint(expr)
    st = _settings(region, {}, rng, shuffle)
    return PlayItem("wild", f"{ds}: {label}", expr, st, story, f"play:wild:{ds}@{region}",
                    title=f"Wild roll on {ds}", lint_ok=lint.ok,
                    lint_msg="; ".join(i.message for i in lint.errors()),
                    profile=rules.dataset_profile(expr, dataset_of, 1), categories=cats)


def roll(catalog, region: str, n: int = 5, mode: str = "mix", seed: Optional[int] = None,
         shuffle_settings: bool = True, universe: Optional[str] = None, exclude=()) -> List[PlayItem]:
    """Roll ``n`` random alphas. mode: "cards" | "wild" | "mix". Free: nothing is simulated.

    Only expressions that pass the linter are returned (up to n; fewer if the region's catalog is thin).
    The same seed gives the same roll for the same catalog. ``exclude``: card ids never rolled (binned cards).
    """
    rng = random.Random(seed)
    universe = universe or config.universe_for(region)
    has_ctx = catalog.has_context(region, universe, 1)
    linter = Linter.for_context(catalog, region, universe, 1) if has_ctx else Linter()
    library = [h for h in load_library() if h.id not in set(exclude or ())] or load_library()
    fields = _usable_fields(catalog, region, universe) if has_ctx else pd.DataFrame()
    dataset_of = rules.catalog_lookup(catalog, region, universe, 1)
    out, seen = [], set()
    for _ in range(max(1, n) * 8):
        if len(out) >= n:
            break
        pick = mode if mode in ("cards", "wild") else rng.choice(["cards", "wild"])
        item = _roll_card(catalog, region, rng, shuffle_settings, linter, library) if pick == "cards" else \
            _roll_wild(fields, region, rng, shuffle_settings, linter, dataset_of)
        if item is None or not item.lint_ok or item.expression in seen:
            continue
        seen.add(item.expression)
        out.append(item)
    return out


def items_table(items: List[PlayItem]) -> pd.DataFrame:
    return pd.DataFrame([i.row() for i in items], columns=["source", "rolled", "expression", "settings", "IS test",
                                                            "linter", "idea"])


def play_stats(journal) -> dict:
    """Score strip for the Play tab: how many dice thrown, how many hit."""
    try:
        ex = journal.experiments()
    except Exception:  # noqa: BLE001
        ex = pd.DataFrame()
    if ex.empty or "purpose" not in ex.columns:
        return {"plays": 0, "today": 0, "pass": 0, "near": 0, "best_sharpe": None, "best_expression": ""}
    p = ex[ex["purpose"] == "play"]
    if p.empty:
        return {"plays": 0, "today": 0, "pass": 0, "near": 0, "best_sharpe": None, "best_expression": ""}
    sh = pd.to_numeric(p["sharpe"], errors="coerce")
    best = p.loc[sh.idxmax()] if sh.notna().any() else None
    return {"plays": int(len(p)), "today": int((p["created"] >= rules.brain_day_start()).sum()),
            "pass": int((p["verdict"] == "PASS").sum()), "near": int((p["verdict"] == "NEAR").sum()),
            "best_sharpe": float(sh.max()) if sh.notna().any() else None,
            "best_expression": str(best["expression"]) if best is not None else ""}


# ------------------------------------------------------- the last roll survives a restart (1.4.1)
def _roll_path(sandbox: bool):
    config.ensure_home()
    return config.HOME / f"play_last_roll_{'sandbox' if sandbox else 'live'}.json"


def save_roll(items: List[PlayItem], sandbox: bool) -> None:
    import json
    keep = ("source", "name", "expression", "settings", "story", "idea_id", "title", "lint_ok", "lint_msg",
            "profile", "categories")
    try:
        _roll_path(sandbox).write_text(json.dumps([{k: getattr(i, k) for k in keep} for i in items], default=str))
    except OSError:
        pass


def load_roll(sandbox: bool) -> List[PlayItem]:
    """The last roll of this mode (cards are rebound when simulated; the expression is what gets tested)."""
    import json
    try:
        rows = json.loads(_roll_path(sandbox).read_text())
        return [PlayItem(**r) for r in rows]
    except (OSError, ValueError, TypeError):
        return []
