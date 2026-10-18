"""The Idea Engine's own state: quarter goals, weekly plans and card drafts (~/.hypolab/ideas.sqlite).

Later phases add sources, inbox items, drafts and the model-call cache to the same file.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from hypolab import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
  key TEXT PRIMARY KEY, label TEXT, now REAL, bar REAL, quarter TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS plans (
  week TEXT PRIMARY KEY, region TEXT, universe TEXT, delay INTEGER, categories TEXT, dataset_focus TEXT,
  card_target INTEGER, review_note TEXT DEFAULT '', updated REAL);
"""

# Your Genius page on 2026-10-09 (2026-Q4): the three bars that decide Expert.
DEFAULT_GOALS = [
    {"key": "signals", "label": "Signals (submitted alphas)", "now": 1.0, "bar": 20.0},
    {"key": "pyramids", "label": "Pyramids completed", "now": 0.0, "bar": 10.0},
    {"key": "combined_perf", "label": "Combined alpha performance", "now": -0.01, "bar": 0.5},
]
# Lifetime submitted alphas (not per quarter): SuperAlpha submissions unlock at 100. You had 58 on 2026-10-09.
# The cockpit adds every alpha submitted through HYPOLAB after the date you last entered this number.
LIFETIME_GOAL = {"key": "lifetime_alphas", "label": "Alphas submitted, lifetime (SuperAlpha unlock)",
                 "now": 58.0, "bar": 100.0, "quarter": "lifetime"}
DEFAULT_QUARTER = "2026-Q4"


class IdeaStore:
    def __init__(self, path: Optional[Path] = None):
        config.ensure_home()
        self.path = path if path == ":memory:" else (Path(path) if path else config.HOME / "ideas.sqlite")
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(plans)")}
        if "submit_target" not in cols:                       # added after the first release
            self.db.execute("ALTER TABLE plans ADD COLUMN submit_target INTEGER")
            self.db.commit()
        if "extra" not in cols:                               # 1.5.0: the Reviewer's retry / dead ends / lessons
            self.db.execute("ALTER TABLE plans ADD COLUMN extra TEXT DEFAULT '{}'")
            self.db.commit()
        if not self.db.execute("SELECT COUNT(*) FROM goals WHERE quarter != 'lifetime'").fetchone()[0]:
            for g in DEFAULT_GOALS:
                self.set_goal(g["key"], g["now"], g["bar"], g["label"], DEFAULT_QUARTER)
        if self.db.execute("SELECT COUNT(*) FROM goals WHERE key=?", (LIFETIME_GOAL["key"],)).fetchone()[0] == 0:
            g = LIFETIME_GOAL
            self.set_goal(g["key"], g["now"], g["bar"], g["label"], g["quarter"])

    # ------------------------------------------------------------ goals
    def lifetime(self) -> dict:
        """The lifetime-alphas row: count you entered, the unlock bar, and when you entered it."""
        r = self.db.execute("SELECT now, bar, updated FROM goals WHERE key=?", (LIFETIME_GOAL["key"],)).fetchone()
        return {"base": float(r[0]), "unlock": float(r[1]), "since": float(r[2])}

    def goals(self) -> pd.DataFrame:
        """The quarter's Genius bars (the lifetime count is separate: see lifetime())."""
        df = pd.read_sql_query("SELECT key, label, now, bar, quarter FROM goals WHERE quarter != 'lifetime' "
                               "ORDER BY rowid", self.db)
        df["still_needed"] = (df["bar"] - df["now"]).clip(lower=0).round(2)
        return df

    def set_goal(self, key: str, now: float, bar: float, label: Optional[str] = None,
                 quarter: Optional[str] = None):
        cur = self.db.execute("SELECT label, quarter FROM goals WHERE key=?", (key,)).fetchone()
        label = label or (cur[0] if cur else key)
        quarter = quarter or (cur[1] if cur else DEFAULT_QUARTER)
        self.db.execute("INSERT OR REPLACE INTO goals VALUES (?,?,?,?,?,?)",
                        (key, label, float(now), float(bar), quarter, time.time()))
        self.db.commit()

    # ------------------------------------------------------------ plans
    def plan(self, week: str) -> Optional[dict]:
        cur = self.db.execute("SELECT * FROM plans WHERE week=?", (week,))
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(zip([c[0] for c in cur.description], row))
        d["categories"] = json.loads(d["categories"] or "[]")
        try:
            d["extra"] = json.loads(d.get("extra") or "{}")
        except ValueError:
            d["extra"] = {}
        return d

    def save_plan(self, plan: Dict) -> dict:
        p = dict(plan)
        cats = p.get("categories") or []
        extra = p.get("extra")
        if extra is None:                      # saving from the Week form keeps what the Reviewer added
            old = self.plan(p["week"])
            extra = (old or {}).get("extra") or {}
        self.db.execute("INSERT OR REPLACE INTO plans (week, region, universe, delay, categories, dataset_focus, "
                        "card_target, review_note, updated, submit_target, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (p["week"], p["region"], p.get("universe"), int(p.get("delay", 1)), json.dumps(list(cats)),
                         p.get("dataset_focus", ""), int(p.get("card_target", 5)), p.get("review_note", "") or "",
                         time.time(), p.get("submit_target"), json.dumps(extra)))
        self.db.commit()
        return self.plan(p["week"])

    def plans(self) -> pd.DataFrame:
        df = pd.read_sql_query("SELECT week, region, universe, delay, categories, dataset_focus, card_target, "
                               "submit_target, review_note FROM plans ORDER BY week", self.db)
        if not df.empty:
            df["categories"] = df["categories"].map(lambda s: ", ".join(json.loads(s or "[]")))
        return df

    def weeks_planned(self) -> List[str]:
        return [r[0] for r in self.db.execute("SELECT week FROM plans ORDER BY week")]
