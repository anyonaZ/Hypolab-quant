"""The idea engine: turn economic hypotheses into concrete, testable alpha ideas
for YOUR region, using the fields that actually exist there.

Two ways to get ideas
---------------------
1. ``generate_ideas(...)`` - start from the hypothesis library (economics first).
   Each hypothesis's roles ("operating cash flow", "analyst EPS estimate") are
   bound to real fields in the catalog; the result is an ``IdeaCard`` with the
   story, the bound data and a short ladder of expressions.
2. ``explore_dataset(...)`` - start from a dataset you know nothing about
   (data first). Each usable field is classified by its NATURE and passed
   through the "lenses" that make economic sense for that nature (a yield for
   a cash-flow amount, a revision for an estimate, a level for a vendor score,
   a breadth ratio for counts ...). This replaces the zip's approach of
   pushing every field through the same four templates.

Ideas are ranked by evidence strength, data fit, coverage, crowding (alphas
already built on the field), whether they fill a pyramid you still need, and
your journal (families you already submitted are pushed down; expressions you
already simulated are removed).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from . import config, rules
from .catalog import CATEGORY_NAMES, Catalog, _cat_id
from .concepts import CONCEPTS, NON_NUMERIC, direction_hint
from .hypotheses import PLACEHOLDER, Hypothesis, Role, Step, load_library
from .linter import Linter, LintResult

STANDARD_PV = {"open", "high", "low", "close", "vwap", "volume", "returns", "adv20", "cap", "sharesout",
               "dividend", "split", "adjfactor"}


@dataclass
class Binding:
    role: str
    field_id: str
    dataset: str
    category: str
    type: str
    nature: str
    coverage: Optional[float]
    alpha_count: Optional[float]
    direction: int
    reason: str
    score: float
    alternatives: List[str] = field(default_factory=list)
    description: str = ""

    @property
    def expr(self) -> str:
        return f"vec_avg({self.field_id})" if self.type == "VECTOR" else self.field_id


@dataclass
class LadderStep:
    name: str
    expression: str
    teaches: str
    lint: LintResult
    profile: dict = field(default_factory=dict)   # rules.dataset_profile(): datasets used + which IS test applies

    @property
    def single_dataset(self) -> Optional[bool]:
        return self.profile.get("single")

    @property
    def is_test(self) -> str:
        """Short label: which in-sample Sharpe test BRAIN will apply (BRAIN_RULES T1)."""
        p = self.profile
        if not p:
            return ""
        if p.get("single"):
            return f"single dataset: 2Y Sharpe >= {p['cutoff']}"
        if p.get("single") is None:
            return "datasets unknown"
        return f"IS ladder ({len(p['datasets'])} datasets)"


@dataclass
class IdeaCard:
    hypothesis: Hypothesis
    region: str
    universe: str
    delay: int
    bindings: Dict[str, Binding]
    steps: List[LadderStep]
    categories: List[str]
    settings: dict
    score: float = 0.0
    score_notes: List[str] = field(default_factory=list)
    unbound: List[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.hypothesis.id}@{self.region}"

    @property
    def family(self) -> str:
        return self.hypothesis.family

    def expressions(self) -> List[str]:
        return [s.expression for s in self.steps]

    def summary_row(self) -> dict:
        return {
            "idea": self.hypothesis.id, "title": self.hypothesis.title, "family": self.family,
            "pyramid": ", ".join(CATEGORY_NAMES.get(c, c) for c in self.categories),
            "evidence": self.hypothesis.stars, "horizon": self.hypothesis.horizon,
            "fields": ", ".join(b.field_id for b in self.bindings.values()) or "price/volume",
            "first_expression": self.steps[0].expression if self.steps else "", "score": round(self.score, 2),
        }

    def markdown(self) -> str:
        h = self.hypothesis
        pyr = ", ".join(CATEGORY_NAMES.get(c, c) for c in self.categories)
        out = [f"### {h.title}  `{h.id}`",
               f"**Pyramid:** {pyr} | **Region:** {self.region} {self.universe} D{self.delay} | "
               f"**Evidence:** {h.stars} | **Horizon:** {h.horizon} | **Family:** `{h.family}`", "",
               f"**The idea.** {h.story}", "", f"**Why it can persist.** {h.why_persists}", "",
               f"**Expected sign:** {h.sign}"]
        if self.bindings:
            out += ["", "**Data bound to the idea** (check the descriptions - you are the final judge):", "",
                    "| role | field | dataset | coverage | alphas already on it | why chosen |",
                    "|---|---|---|---|---|---|"]
            for b in self.bindings.values():
                cov = "?" if b.coverage is None else f"{b.coverage:.0%}"
                ac = "?" if b.alpha_count is None or (isinstance(b.alpha_count, float) and math.isnan(b.alpha_count)) \
                    else f"{int(b.alpha_count)}"
                out.append(f"| {b.role} | `{b.field_id}`{' (VECTOR)' if b.type == 'VECTOR' else ''} | {b.dataset} | "
                           f"{cov} | {ac} | {b.reason} |")
            alts = [f"`{b.role}`: {', '.join(b.alternatives)}" for b in self.bindings.values() if b.alternatives]
            if alts:
                out += ["", "Alternatives if a field looks wrong: " + "; ".join(alts)]
        out += ["", "**Ladder - simulate rung 1 first, then climb only if the diagnosis says so:**", ""]
        for i, s in enumerate(self.steps, 1):
            flag = "" if s.lint.ok else "  <- BLOCKED by linter"
            test = f"  \n   _IS test: {s.profile['test']}_" if s.profile else ""
            out += [f"{i}. *{s.name}* - {s.teaches}{flag}{test}", f"   ```\n   {s.expression}\n   ```"]
        st = self.settings
        out += ["", f"**Settings:** neutralization `{st.get('neutralization')}`, decay `{st.get('decay')}`, "
                    f"truncation `{st.get('truncation')}`, universe `{self.universe}`"
                    + (", maxTrade `ON`" if st.get("max_trade") == "ON" else ""),
                f"**Expected turnover:** {h.expected_turnover[0]:.0%}-{h.expected_turnover[1]:.0%}"]
        if h.watch_out:
            out += ["", "**Watch out:**"] + [f"- {w}" for w in h.watch_out]
        if h.references:
            out += ["", "**Read:** " + "; ".join(h.references)]
        if self.score_notes:
            out += ["", "_Ranking notes: " + "; ".join(self.score_notes) + "_"]
        return "\n".join(out)


# --------------------------------------------------------------- settings

def settings_for(region: str, hyp_settings: dict) -> dict:
    reg = config.REGION_DEFAULTS.get(region, {})
    s = {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08, "max_trade": reg.get("max_trade", "OFF")}
    s.update(hyp_settings or {})
    if region == "GLB" and s["neutralization"] in ("SUBINDUSTRY", "INDUSTRY"):
        # measured in the zip's AlphaForge campaign: in GLB, STATISTICAL neutralization kept Sharpe while
        # SUBINDUSTRY/INDUSTRY collapsed it; the expression's own group_rank still compares peers.
        s["neutralization"] = "STATISTICAL"
    return s


# ---------------------------------------------------------------- binding

def _short_reason(reason: str) -> str:
    if reason.startswith("matched /") and len(reason) > 48:
        return reason[:45] + ".../"
    return reason


def _binding_from_row(role: str, row: dict, reason: str, score: float, alternatives: List[str]) -> Binding:
    d, why = direction_hint(row["id"], row.get("description") or "")
    reason = _short_reason(reason)
    return Binding(role=role, field_id=row["id"], dataset=row.get("dataset") or "?",
                   category=_cat_id(row.get("category") or "other"), type=row.get("type") or "MATRIX",
                   nature=row.get("nature") or "level", coverage=row.get("coverage"),
                   alpha_count=row.get("alpha_count"), direction=d, reason=reason, score=score,
                   alternatives=alternatives, description=(row.get("description") or "")[:160])


_MIRROR = [("up", "down"), ("raise", "lower"), ("raised", "lowered"), ("upward", "downward"), ("buy", "sell"),
           ("buyers", "sellers"), ("bought", "sold"), ("acquired", "disposed"), ("purchased", "sold"),
           ("call", "put"), ("pos", "neg"), ("positive", "negative"), ("upgrades", "downgrades"),
           ("raising", "lowering"), ("raise", "cut"), ("increase", "decrease"), ("increased", "decreased"),
           ("upward", "downward"), ("ups", "downs"), ("top", "bottom")]


def _mirror_key(field_id: str) -> str:
    toks = re.split(r"[_\W]+", field_id.lower())
    out = []
    for t in toks:
        for a, b in _MIRROR:
            if t in (a, b):
                t = "<dir>"
                break
        out.append(t)
    return "_".join(out)


def bind_role(catalog: Catalog, role: Role, region: str, universe: Optional[str], delay: int,
              avoid_fields: Iterable[str] = (), partner: Optional[str] = None) -> Optional[Binding]:
    avoid = set(avoid_fields)
    if role.type == "GROUP":
        df = catalog.fields(region, universe, delay)
        if df.empty:
            return None
        c = CONCEPTS[role.concept]
        g = df[df["type"] == "GROUP"]
        if role.categories:
            g = g[g["category"].isin([_cat_id(x) for x in role.categories])]
        rows = []
        for r in g.itertuples(index=False):
            s, why = c.match(r.id, r.description or "")
            if s > 0 and r.id not in avoid and (r.coverage or 0) >= role.min_coverage:
                rows.append((s * (0.4 + (r.coverage or 0.5)), r._asdict(), why))
        if not rows:
            return None
        rows.sort(key=lambda x: -x[0])
        best = rows[0]
        return _binding_from_row(role.name, best[1], best[2], best[0], [x[1]["id"] for x in rows[1:4]])
    found = catalog.find_concept(role.concept, region, universe, delay, categories=role.categories,
                                 min_coverage=role.min_coverage, limit=60 if partner else 8)
    if found is None or found.empty:
        return None
    found = found[~found["id"].isin(avoid)]
    if found.empty:
        return None
    if partner:
        import difflib
        key = _mirror_key(partner)
        sims = found["id"].map(lambda i: difflib.SequenceMatcher(None, _mirror_key(i), key).ratio())
        found = found.assign(_sim=sims).sort_values(["_sim", "score"], ascending=False)
        if found["_sim"].iloc[0] < 0.85:
            return None   # no mirror field: mixing e.g. FQ2-earnings ups with FY1-revenue downs is meaningless
        found = found.drop(columns="_sim")
    best = found.iloc[0].to_dict()
    return _binding_from_row(role.name, best, best.get("why", ""), float(best.get("score", 1.0)),
                             found["id"].iloc[1:4].tolist())


def _fill(expr: str, bindings: Dict[str, Binding]) -> Optional[str]:
    missing = False

    def sub(m):
        nonlocal missing
        b = bindings.get(m.group(2))
        if b is None:
            missing = True
            return m.group(0)
        if m.group(1):           # {dir:role}
            return "-1" if b.direction < 0 else "1"
        return b.expr

    out = PLACEHOLDER.sub(sub, expr)
    # tidy the direction multiplier: "1 * x" -> "x", "-1 * x" -> "-x"
    out = re.sub(r"(?<![\w.])-1 \* ", "-", out)
    out = re.sub(r"(?<![\w.])1 \* ", "", out)
    return None if missing else out


def _categories_used(bindings: Dict[str, Binding], expressions: Sequence[str], fixed: str) -> List[str]:
    if fixed and fixed != "auto":
        cats = {fixed}
    else:
        cats = {b.category for b in bindings.values()}
    names = set()
    for e in expressions:
        names |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", e))
    if names & STANDARD_PV:
        cats.add("pv")
    return sorted(cats)


def build_card(h: Hypothesis, catalog: Catalog, region: str, universe: Optional[str] = None, delay: int = 1,
               linter: Optional[Linter] = None, avoid_fields: Iterable[str] = ()) -> Optional[IdeaCard]:
    universe = universe or config.REGION_DEFAULTS.get(region, {}).get("universe", "TOP3000")
    has_ctx = catalog.has_context(region, universe, delay)
    linter = linter or (Linter.for_context(catalog, region, universe, delay) if has_ctx else Linter())
    bindings: Dict[str, Binding] = {}
    unbound = []
    ordered = sorted(h.roles.values(), key=lambda r: r.pair_with is not None)
    for role in ordered:
        partner = bindings[role.pair_with].field_id if role.pair_with and role.pair_with in bindings else None
        b = bind_role(catalog, role, region, universe, delay, avoid_fields, partner) if has_ctx else None
        if b is None:
            c = CONCEPTS.get(role.concept)
            if c and c.canonical and not has_ctx:
                b = Binding(role.name, c.canonical[0], "?", "fundamental", "MATRIX", "level", None, None, 0,
                            "standard field name (no catalog for this region yet - verify it exists)", 0.5)
        if b is None:
            unbound.append(role.name)
            if not role.optional:
                return None
            continue
        bindings[role.name] = b
    _cat_ds = rules.catalog_lookup(catalog, region, universe, delay) if has_ctx else (lambda f: None)
    _bound_ds = {b.field_id: b.dataset for b in bindings.values() if b.dataset and b.dataset != "?"}

    def _dataset_of(f):
        return _bound_ds.get(f) or _cat_ds(f)

    steps = []
    for st in h.ladder:
        if st.when and any(r in bindings and bindings[r].nature not in allowed for r, allowed in st.when.items()):
            continue
        expr = _fill(st.expr, bindings)
        if expr is None:
            continue
        steps.append(LadderStep(st.name, expr, st.teaches, linter.lint(expr),
                                rules.dataset_profile(expr, _dataset_of, delay)))
    steps = [s for s in steps if s.lint.ok] + [s for s in steps if not s.lint.ok]
    if not steps or not steps[0].lint.ok:
        return None
    cats = _categories_used(bindings, [s.expression for s in steps], h.category)
    return IdeaCard(hypothesis=h, region=region, universe=universe, delay=delay, bindings=bindings,
                    steps=steps, categories=cats, settings=settings_for(region, h.settings), unbound=unbound)


# ----------------------------------------------------------------- ranking

def _score(card: IdeaCard, need: Dict[str, float], journal=None, beginner: bool = False) -> None:
    h = card.hypothesis
    notes = []
    score = 1.0 * h.strength
    if card.bindings:
        fit = sum(min(b.score, 3.0) for b in card.bindings.values()) / len(card.bindings)
        score += 0.5 * fit
        covs = [b.coverage for b in card.bindings.values() if b.coverage is not None]
        if covs:
            score += 1.0 * (sum(covs) / len(covs) - 0.5)
        crowd = [math.log10(1 + b.alpha_count) for b in card.bindings.values()
                 if b.alpha_count is not None and not (isinstance(b.alpha_count, float) and math.isnan(b.alpha_count))]
        if crowd:
            c = sum(crowd) / len(crowd)
            score -= 0.35 * c
            if c > 3:
                notes.append("crowded fields (thousands of alphas)")
    else:
        score -= 0.4    # pure price-volume ideas are the most crowded on the platform
        notes.append("price-volume only: crowded but always available")
    bonus = max((need.get(c, 0.0) for c in card.categories), default=0.0)
    if bonus:
        score += bonus
        notes.append("fills a pyramid you still need")
    if beginner and h.beginner:
        score += 0.75
    if journal is not None:
        fam = journal.family_status(card.family, card.region)
        if fam.get("submitted", 0):
            score -= 1.5 * fam["submitted"]
            notes.append(f"you already submitted {fam['submitted']} alpha(s) in this family here - correlation risk")
        if fam.get("simulated", 0) >= config.settings()["max_sims_per_idea"]:
            score -= 1.0
            notes.append("simulation budget for this family already spent")
        seen = journal.simulated_expressions(card.region)
        before = len(card.steps)
        card.steps = [s for s in card.steps if s.lint.canonical not in seen]
        if len(card.steps) < before:
            notes.append(f"{before - len(card.steps)} rung(s) already simulated - removed")
    card.score = score
    card.score_notes = notes


def generate_ideas(catalog: Catalog, region: str, universe: Optional[str] = None, delay: int = 1,
                   categories: Optional[Sequence[str]] = None, n: int = 10, journal=None,
                   pyramid_need: Optional[Dict[str, float]] = None, beginner: bool = False,
                   library: Optional[List[Hypothesis]] = None, one_per_family: bool = True,
                   avoid_fields: Iterable[str] = ()) -> List[IdeaCard]:
    """Ranked idea cards for one region.

    categories: restrict to ideas whose data falls in these BRAIN categories
                (e.g. ["analyst"] to work on the Analyst pyramid).
    pyramid_need: {category: bonus} from pyramids.PyramidTracker.need() - unfilled pyramids rank higher.
    """
    library = library or load_library()
    universe = universe or config.REGION_DEFAULTS.get(region, {}).get("universe", "TOP3000")
    has_ctx = catalog.has_context(region, universe, delay)
    linter = Linter.for_context(catalog, region, universe, delay) if has_ctx else Linter()
    want = {_cat_id(c) for c in categories} if categories else None
    cards = []
    for h in library:
        card = build_card(h, catalog, region, universe, delay, linter, avoid_fields)
        if card is None:
            continue
        if want and not (set(card.categories) & want):
            continue
        _score(card, pyramid_need or {}, journal, beginner)
        if card.steps:
            cards.append(card)
    cards.sort(key=lambda c: -c.score)
    if one_per_family:
        seen, first, rest = set(), [], []
        for c in cards:
            (rest if c.family in seen else first).append(c)
            seen.add(c.family)
        cards = first + rest
    return cards[:n]


def ideas_table(cards: List[IdeaCard]) -> pd.DataFrame:
    return pd.DataFrame([c.summary_row() for c in cards])


# ------------------------------------------------------------------ lenses
# Data-first exploration: what can a field of a given NATURE sensibly say?

LENSES = {
    "rank_score": [
        ("level", "group_rank({d}ts_backfill({x}, 21), subindustry)",
         "The vendor score itself, direction-corrected, against sub-industry peers."),
        ("improvement", "group_rank({d}ts_delta(ts_backfill({x}, 21), 63), subindustry)",
         "Is the score improving over the quarter? Changes are often less crowded than levels."),
    ],
    "estimate": [
        ("revision", "group_rank({d}ts_delta(ts_backfill({x}, 63), 63) / close, subindustry)",
         "Revision of a forward-looking estimate, scaled by price (analysts update slowly -> drift)."),
        ("yield", "group_rank({d}ts_backfill({x}, 63) / close, subindustry)",
         "Estimate per dollar of price - a forward-looking value measure (if the estimate is per share)."),
    ],
    "flow": [
        ("yield", "group_rank({d}ts_backfill({x}, 252) / cap, subindustry)",
         "Income/cash amount per dollar of market value - a value lens."),
        ("growth", "group_rank({d}ts_delta(ts_backfill({x}, 252), 252) / ts_backfill(cap, 21), subindustry)",
         "Year-on-year change scaled by size - improving fundamentals lens."),
    ],
    "stock": [
        ("growth", "-group_rank(ts_backfill({x}, 252) / ts_delay(ts_backfill({x}, 252), 252) - 1, subindustry)",
         "Balance-sheet items that grow fast tend to precede LOWER returns (investment/asset-growth effect)."),
        ("intensity", "group_rank({d}ts_backfill({x}, 252) / cap, subindustry)",
         "Item per dollar of market value (only meaningful for assets you believe are under-priced)."),
    ],
    "ratio": [
        ("level", "group_rank({d}ts_backfill({x}, 63), subindustry)", "The ratio against peers."),
        ("trend", "group_rank({d}ts_delta(ts_backfill({x}, 63), 252), subindustry)", "One-year change of the ratio."),
    ],
    "change": [
        ("level", "group_rank({d}ts_backfill({x}, 21), subindustry)", "The change/revision as reported."),
        ("persistent", "group_rank({d}ts_mean(ts_backfill({x}, 21), 63), subindustry)",
         "Quarter-average: only persistent changes count."),
    ],
    "count": [
        ("relative-change", "group_rank({d}ts_delta(ts_backfill({x}, 21), 63) / (ts_backfill({x}, 21) + 1), subindustry)",
         "Counts scale with company size; a relative change removes that."),
    ],
    "level": [
        ("unusual-vs-own-history", "group_rank({d}ts_zscore(ts_backfill({x}, 21), 252), subindustry)",
         "How unusual today's value is versus the stock's own year - removes level differences between stocks."),
    ],
    "price": [
        ("vs-close", "group_rank({d}ts_backfill({x}, 21) / close - 1, subindustry)",
         "A price-type field relative to the actual price (e.g. a target price -> implied upside)."),
    ],
}


def explore_dataset(catalog: Catalog, dataset: str, region: str, universe: Optional[str] = None,
                    delay: int = 1, max_fields: int = 8, min_coverage: float = 0.5,
                    prefer_uncrowded: bool = True, journal=None, dedupe_siblings: bool = True) -> List[IdeaCard]:
    """Data-first ideas for one dataset: best-covered, least-crowded numeric fields x sensible lenses.

    dedupe_siblings=False keeps every field (used by Researcher.scan, which probes each field once)."""
    universe = universe or config.REGION_DEFAULTS.get(region, {}).get("universe", "TOP3000")
    df = catalog.fields(region, universe, delay)
    sub = df[(df["dataset"] == dataset) & (~df["nature"].isin(NON_NUMERIC | {"flag"}))
             & (df["type"].isin(["MATRIX", "VECTOR"]))]
    sub = sub[sub["coverage"].fillna(0.5) >= min_coverage]
    if sub.empty:
        return []
    sub = sub.assign(_crowd=sub["alpha_count"].fillna(0).map(lambda v: math.log10(1 + v)))
    sub = sub.sort_values(["_crowd", "coverage"] if prefer_uncrowded else ["coverage"],
                          ascending=[True, False] if prefer_uncrowded else [False])
    # one field per (nature, first word) to avoid 8 near-identical siblings
    picked, keys = [], set()
    for r in sub.itertuples(index=False):
        key = (r.nature, re.sub(r"[_\d]+", " ", r.id).split()[0] if r.id else "")
        if dedupe_siblings and key in keys:
            continue
        keys.add(key)
        picked.append(r._asdict())
        if len(picked) >= max_fields:
            break
    linter = Linter.for_context(catalog, region, universe, delay)
    _lens_ds = rules.catalog_lookup(catalog, region, universe, delay)
    cards = []
    for row in picked:
        nature = row["nature"]
        d, dwhy = direction_hint(row["id"], row.get("description") or "")
        b = _binding_from_row("x", row, f"{nature}; {dwhy}", 1.0, [])
        xexpr = b.expr
        sign = "-" if d < 0 else ""
        steps = []
        for name, tmpl, teaches in LENSES.get(nature, LENSES["level"]):
            # {d} carries the direction prior; the balance-sheet growth lens has its own fixed sign
            e = tmpl.replace("{d}", sign).replace("{x}", xexpr)
            steps.append(LadderStep(name, e, teaches, linter.lint(e),
                                    rules.dataset_profile(e, _lens_ds, delay)))
        steps = [s for s in steps if s.lint.ok]
        if not steps:
            continue
        desc = (row.get("description") or "").strip()
        h = Hypothesis(
            id=f"LENS_{row['id']}", title=f"{row['id']} - {desc[:70]}", category="auto",
            family=f"lens_{dataset}", horizon="medium" if nature in ("estimate", "change", "rank_score") else "slow",
            strength=1,
            story=(f"Data-first idea. `{row['id']}` ({desc}) is a **{nature}** field: "
                   f"{NATURE_STORY.get(nature, '')} Direction prior: {dwhy}. "
                   "Before simulating, write ONE sentence on why this number should predict returns; "
                   "if you cannot, skip the field."),
            why_persists="Unknown until you state the mechanism - that is your job for this card.",
            references=["Your Pyramids guide: start with datasets that have good coverage"],
            roles={"x": Role("x", "vendor_score")}, ladder=[Step(s.name, s.expression, s.teaches) for s in steps],
            settings={"neutralization": "SUBINDUSTRY", "decay": 2, "truncation": 0.08},
            expected_turnover=[0.02, 0.3], watch_out=["Lens ideas are hypotheses-to-be, not hypotheses. Budget 2 simulations."],
            sign="+1" if d >= 0 else "-1", source="lens")
        card = IdeaCard(hypothesis=h, region=region, universe=universe, delay=delay, bindings={"x": b},
                        steps=steps, categories=_categories_used({"x": b}, [s.expression for s in steps], "auto"),
                        settings=settings_for(region, h.settings))
        _score(card, {}, journal)
        if card.steps:
            cards.append(card)
    return sorted(cards, key=lambda c: -c.score)


NATURE_STORY = {
    "rank_score": "a finished vendor score - someone else's research; use it cleanly against peers.",
    "estimate": "a forward-looking estimate - the information is in how it CHANGES and how it compares with price.",
    "flow": "an income-statement/cash-flow amount - must be scaled by size before comparing stocks.",
    "stock": "a balance-sheet amount - scale by size; fast growth in balance-sheet items is usually bad news.",
    "ratio": "a ratio that is already comparable across stocks.",
    "change": "already a change/revision number.",
    "count": "a count, which grows with company size - use relative changes.",
    "level": "a numeric level of unclear type - compare it with the stock's own history.",
    "price": "a price-type number - only meaningful relative to the stock's actual price.",
}
