"""Pyramid planner - built around your "PYRAMIDS GUIDE.pdf".

A pyramid is one (region, delay, data category) cell. Filling many of them is
what moves you up the Genius levels. The guide's plan:

  Tier 1 (low-lying, abundant well-covered fields): Analyst, Fundamental, Model,
          Price Volume, Risk
  Tier 2 (fewer fields, good coverage; "boosters/chasers"): Earnings, Imbalance,
          Other, Macro
  Tier 3 (good but harder): Option (few countries, needs a clear hypothesis),
          News, Sentiment (often very high turnover)
  Regions: USA, GLB, EUR, ASI, IND + one single-country region (KOR/TWN/JPN/AMR/HKG)
  -> 5 tier-1 categories x 6 regions = 30 pyramids ("enough to get you to master")
  -> 9 categories x 5 regions = 45+.

Your submitted-alpha breakdown comes live from BRAIN
(GET /users/self/activities/diversity) or, offline, from your journal.
An alpha counts in EVERY category whose fields it uses (BRAIN API docs), so
an analyst idea that divides by ``close`` also touches Price Volume.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

import pandas as pd

from . import config
from .catalog import CATEGORY_NAMES, _cat_id

TIERS = {
    1: ["analyst", "fundamental", "model", "pv", "risk"],
    2: ["earnings", "imbalance", "other", "macro", "insiders", "institutions", "shortinterest"],
    3: ["option", "news", "sentiment", "socialmedia", "broker"],
}
# BRAIN's Genius grid has 17 categories (2026-Q4); the guide's tiers covered 12. Insiders, Institutions and
# Short Interest are filed with tier 2, Social Media and Broker (ASI only) with tier 3 (BRAIN_RULES S14).

MULTIPLIER_SNAPSHOT = config.BUNDLED_DATA / "pyramid_multipliers_2026Q4.json"


def _snapshot() -> pd.DataFrame:
    try:
        d = json.loads(MULTIPLIER_SNAPSHOT.read_text())
        df = pd.DataFrame(d["rows"])
        df.attrs["source"] = d.get("source", "snapshot")
        return df
    except (OSError, ValueError, KeyError):
        return pd.DataFrame(columns=["region", "delay", "category", "multiplier"])


def multiplier_table(live: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Pyramid theme multiplier per (region, delay, category).

    BRAIN's /activities/pyramid-multipliers answer is parsed when its shape is recognisable; otherwise the
    bundled snapshot of Zacc's 2026-Q4 Genius page is used (cells absent there are not offered by BRAIN).
    """
    if live is not None and not live.empty:
        cols = {c.lower(): c for c in live.columns}
        pick = lambda *names: next((cols[n] for n in names if n in cols), None)  # noqa: E731
        rc, dc = pick("region"), pick("delay")
        cc = pick("category.id", "datacategory.id", "category", "category.name", "datacategory.name")
        mc = pick("multiplier", "value", "pyramidmultiplier")
        if rc and dc and cc and mc:
            df = pd.DataFrame({"region": live[rc], "delay": pd.to_numeric(live[dc], errors="coerce"),
                               "category": live[cc].map(_cat_id), "multiplier": pd.to_numeric(live[mc], errors="coerce")})
            rev = {_cat_id(n): c for c, n in CATEGORY_NAMES.items()}
            df["category"] = df["category"].map(lambda c: rev.get(c, c))
            df = df.dropna()
            if not df.empty:
                df["delay"] = df["delay"].astype(int)
                df.attrs["source"] = "BRAIN (live)"
                return df.reset_index(drop=True)
    return _snapshot()
TIER_BONUS = {1: 1.0, 2: 0.7, 3: 0.4}

# Datasets recommended in your PYRAMIDS GUIDE.pdf (page 2-5), with the data shape noted there.
GUIDE_DATASETS = {
    "analyst": ["analyst11 (matrix)", "analyst15 (matrix)", "analyst69 (vector+matrix)", "analyst4 (matrix)",
                "analyst14 (vector+matrix)", "analyst44 (vector+matrix)", "analyst48 (vector)", "analyst37 (vector)",
                "analyst9 (vector)"],
    "fundamental": ["fundamental6 (matrix)", "fundamental17 (matrix)", "fundamental28 (matrix)",
                    "fundamental72 (vector+matrix)", "fundamental89 (matrix)", "fundamental94 (matrix)", "other466 (matrix)"],
    "model": ["model26 (matrix)", "model38 (matrix)", "model39 (matrix)", "model263 (matrix)", "model109 (vector)",
              "model250 / other176 (matrix)", "NOT model110 (the guide skips it: most crowded)"],
    "pv": ["pv1 (group+matrix)", "pv13 (group+matrix)", "pv47 (group+matrix)"],
    "risk": ["risk70 (matrix)", "risk88 (matrix)", "risk59 (vector; misses 1-2 years of PnL)", "risk62 (matrix)",
             "risk64 (vector)", "risk71 (vector)", "risk65 (matrix)"],
    "earnings": ["earnings3 (matrix)", "earnings4 (vector)", "earnings2 (matrix)"],
    "imbalance": ["imbalance1 (matrix)", "imbalance5 (matrix)"],
    "other": ["other455 (group)", "other143 (matrix)", "other335 (matrix)"],
    "macro": ["macro27 (vector)", "macro38 (matrix)", "other551 (matrix)"],
    "option": ["option datasets - only some countries; needs a clear hypothesis"],
    "news": ["news datasets - watch turnover"], "sentiment": ["sentiment datasets - watch turnover"],
}

GUIDE_NOTES = {
    "news": "The guide warns news/sentiment can have very high turnover: smooth with ts_mean or gate with trade_when.",
    "sentiment": "The guide warns news/sentiment can have very high turnover: smooth with ts_mean or gate with trade_when.",
    "option": "Options exist in few regions; the guide says they need a clear hypothesis (see OPT_* idea cards).",
    "model": "The guide deliberately avoids model110 - it is the most crowded model dataset.",
    "macro": "Macro fields are the same for every stock: use them as a regime gate or via a stock's beta to them "
             "(idea card MAC_MACRO_BETA), never rank them directly.",
}


class PyramidTracker:
    def __init__(self, counts: Optional[pd.DataFrame] = None, alphas_per_pyramid: Optional[int] = None,
                 regions: Optional[List[str]] = None, multipliers: Optional[pd.DataFrame] = None):
        """counts: DataFrame with columns region, delay, category, alphas.
        multipliers: region, delay, category, multiplier (see multiplier_table()); also tells which cells exist."""
        st = config.settings()
        self.multipliers = multipliers if multipliers is not None else pd.DataFrame(
            columns=["region", "delay", "category", "multiplier"])
        self._mult = {(r.region, int(r.delay), r.category): float(r.multiplier)
                      for r in self.multipliers.itertuples(index=False)}
        self.k = alphas_per_pyramid or st["alphas_per_pyramid"]
        self.regions = regions or config.account_regions()
        df = counts if counts is not None else pd.DataFrame(columns=["region", "delay", "category", "alphas"])
        self.notes: List[str] = []          # what was cleaned up in BRAIN's counts (shown on the Pyramids tab)
        self.totals = pd.DataFrame(columns=["region", "delay", "alphas"])   # BRAIN's per-region subtotals
        if not df.empty:
            df = self._clean(df)
        self.counts = df

    def _clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """BRAIN's diversity counts can carry missing values (seen live on 2026-10-10: rows without a delay).
        Never crash on them: missing delay -> 1 (where nearly all alphas are), missing count -> 0, and say so."""
        df = df.copy()
        for col in ("region", "delay", "category", "alphas"):
            if col not in df.columns:
                df[col] = None
        # Rows without a category are BRAIN's subtotals (a region+delay, or a whole region), not cells.
        # Counting them as "Other" would double every region's total; keep them aside instead.
        no_cat = df["category"].isna() | (df["category"].astype(str).str.strip() == "")
        if "kind" in df.columns:
            no_cat = no_cat | (df["kind"].fillna("cell") != "cell")
        if no_cat.any():
            tot = df[no_cat & df["region"].notna()].copy()
            tot["alphas"] = pd.to_numeric(tot["alphas"], errors="coerce").fillna(0).astype(int)
            tot["delay"] = pd.to_numeric(tot["delay"], errors="coerce").map(
                lambda d: "all" if pd.isna(d) else str(int(d)))
            self.totals = tot[["region", "delay", "alphas"]].drop_duplicates().reset_index(drop=True)
            df = df[~no_cat]
        delay = pd.to_numeric(df["delay"], errors="coerce")
        n_nodelay = int(delay.isna().sum())
        if n_nodelay:
            self.notes.append(f"{n_nodelay} row(s) from BRAIN had no delay; counted as delay 1.")
        df["delay"] = delay.fillna(1).astype(int)
        alphas = pd.to_numeric(df["alphas"], errors="coerce")
        if alphas.isna().any():
            self.notes.append(f"{int(alphas.isna().sum())} row(s) had no alpha count; counted as 0.")
        df["alphas"] = alphas.fillna(0).astype(int)
        no_region = df["region"].isna() | (df["region"].astype(str).str.strip() == "")
        if no_region.any():
            self.notes.append(f"{int(no_region.sum())} row(s) had no region and were left out.")
            df = df[~no_region]
        df["category"] = df["category"].map(_cat_id)
        return df[["region", "delay", "category", "alphas"]].reset_index(drop=True)

    @classmethod
    def from_brain(cls, brain, **kw) -> "PyramidTracker":
        return cls(brain.diversity(), **kw)

    @classmethod
    def from_journal(cls, journal, **kw) -> "PyramidTracker":
        sub = journal.submissions()
        rows = []
        for r in sub.itertuples(index=False):
            for c in (r.categories or "").split(","):
                if c:
                    rows.append({"region": r.region, "delay": r.delay, "category": c, "alphas": 1})
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.groupby(["region", "delay", "category"], as_index=False)["alphas"].sum()
        return cls(df, **kw)

    def matrix(self, delay: int = 1) -> pd.DataFrame:
        cats = [c for t in (1, 2, 3) for c in TIERS[t]]
        m = pd.DataFrame(0, index=self.regions, columns=cats)
        if not self.counts.empty:
            d = self.counts[self.counts["delay"] == delay]
            for r in d.itertuples(index=False):
                if r.region in m.index and r.category in m.columns:
                    m.loc[r.region, r.category] += int(r.alphas)
        m.columns = [CATEGORY_NAMES.get(c, c) for c in m.columns]
        return m

    def filled(self, delay: int = 1) -> int:
        return int((self.matrix(delay) >= self.k).sum().sum())

    def need(self, region: str, delay: int = 1) -> Dict[str, float]:
        """Bonus per category for the idea ranker: unfilled tier-1 cells first."""
        m = self.matrix(delay)
        out = {}
        for tier, cats in TIERS.items():
            for c in cats:
                col = CATEGORY_NAMES.get(c, c)
                have = int(m.loc[region, col]) if region in m.index else 0
                if have < self.k:
                    out[c] = TIER_BONUS[tier] * (1.0 if have == 0 else 0.6)
        return out

    def multiplier(self, region: str, delay: int, category: str) -> Optional[float]:
        return self._mult.get((region, int(delay), category))

    def offered(self, region: str, delay: int, category: str) -> bool:
        """False only when the multiplier table is known and has no such cell (BRAIN doesn't offer it)."""
        if not self._mult or not any(k[0] == region for k in self._mult):
            return True
        return (region, int(delay), category) in self._mult

    def plan(self, n: int = 8, delay: int = 1, by: str = "guide") -> pd.DataFrame:
        """Next pyramid cells to work on.

        by="guide": tier 1 across all regions first, then cells you have started (the guide's order).
        by="multiplier": highest Pyramid theme multiplier first within each tier (pays more per alpha, but the
        high-multiplier regions - DEU, GBR, JPN, AMR, CHN, all D0 - are usually harder to pass).
        Cells BRAIN doesn't offer (absent from the multiplier table) are left out.
        """
        m = self.matrix(delay)
        rows = []
        for tier in (1, 2, 3):
            for c in TIERS[tier]:
                col = CATEGORY_NAMES.get(c, c)
                for reg in self.regions:
                    if delay not in config.REGION_DEFAULTS.get(reg, {}).get("delays", [1]) or \
                            not self.offered(reg, delay, c):
                        continue
                    have = int(m.loc[reg, col]) if reg in m.index else 0
                    if have < self.k:
                        rows.append({"tier": tier, "region": reg, "delay": delay, "category": col, "have": have,
                                     "need": self.k - have, "multiplier": self.multiplier(reg, delay, c),
                                     "datasets (guide)": ", ".join(GUIDE_DATASETS.get(c, [])[:4]),
                                     "note": GUIDE_NOTES.get(c, "")})
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        if by == "multiplier":
            df["_m"] = df["multiplier"].fillna(0)
            df = df.sort_values(["tier", "_m", "need"], ascending=[True, False, True], kind="stable").drop(columns="_m")
        else:
            # prefer cells you have started (closer to done), then guide order
            df = df.sort_values(["tier", "need", "region"], kind="stable")
        return df.head(n).reset_index(drop=True)

    def summary(self, delay: int = 1) -> str:
        f = self.filled(delay)
        total = len(self.regions) * len(TIERS[1])
        return (f"{f} pyramid(s) filled (>= {self.k} alphas) at delay {delay}. "
                f"Tier-1 grid of the guide: {len(TIERS[1])} categories x {len(self.regions)} regions = {total}.")
