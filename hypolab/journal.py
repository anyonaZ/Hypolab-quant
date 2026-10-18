"""Research journal: every idea, every simulation, every lesson - in one SQLite file.

Why: the zip's notebooks forget everything between runs, so the same
expressions get re-simulated, nobody knows how many variants were tried
(which decides how much a Sharpe can be trusted - see overfit.py), and the
lessons of failures are lost. AlphaForge's own notes say it plainly: "the
database is the memory".

File: ~/.hypolab/journal.sqlite
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import pandas as pd

from . import config
from .fastexpr import ParseError, canonical
from .rules import brain_day_start

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ideas (
  id TEXT PRIMARY KEY, hypothesis_id TEXT, region TEXT, family TEXT, title TEXT, categories TEXT,
  created REAL, status TEXT DEFAULT 'open', notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, idea_id TEXT, rung TEXT, purpose TEXT, expression TEXT, canonical TEXT,
  region TEXT, universe TEXT, delay INTEGER, settings TEXT, fingerprint TEXT UNIQUE, created REAL,
  alpha_id TEXT, status TEXT, error TEXT, sharpe REAL, fitness REAL, turnover REAL, returns REAL,
  drawdown REAL, margin REAL, long_count REAL, short_count REAL, train_sharpe REAL, test_sharpe REAL,
  failed TEXT, verdict TEXT, backend TEXT);
CREATE TABLE IF NOT EXISTS submissions (
  alpha_id TEXT PRIMARY KEY, idea_id TEXT, family TEXT, region TEXT, delay INTEGER, categories TEXT,
  submitted REAL, sharpe REAL, fitness REAL);
CREATE TABLE IF NOT EXISTS account_alphas (
  alpha_id TEXT PRIMARY KEY, type TEXT, status TEXT, date_submitted TEXT, date_created TEXT,
  region TEXT, universe TEXT, delay INTEGER, neutralization TEXT, decay INTEGER, truncation REAL,
  code TEXT, sharpe REAL, fitness REAL, turnover REAL, returns REAL, drawdown REAL,
  operators TEXT, fields TEXT, name TEXT, tags TEXT, synced REAL, extra TEXT);
CREATE TABLE IF NOT EXISTS pending (
  location TEXT PRIMARY KEY, created REAL, idea_id TEXT, rung TEXT, purpose TEXT, expression TEXT,
  settings TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS binned (
  hypothesis_id TEXT PRIMARY KEY, created REAL, reason TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS lessons (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, idea_id TEXT, family TEXT, text TEXT);
"""


def fingerprint(expression: str, settings: dict) -> str:
    try:
        expr = canonical(expression)
    except ParseError:
        expr = " ".join(expression.split())
    keys = ("region", "universe", "delay", "decay", "neutralization", "truncation", "maxTrade", "testPeriod",
            "nanHandling", "pasteurization")
    s = {k: settings.get(k) for k in keys}
    return hashlib.sha256((expr + "|" + json.dumps(s, sort_keys=True)).encode()).hexdigest()[:20]


class Journal:
    def __init__(self, path: Optional[Path] = None, readonly: bool = False):
        """readonly=True opens the file without the right to write (the cockpit and the Idea Engine read the
        journal this way while a notebook writes to it). WAL mode lets readers and one writer work at once."""
        config.ensure_home()
        self.path = path if path == ":memory:" else (Path(path) if path else config.HOME / "journal.sqlite")
        self.readonly = bool(readonly) and self.path != ":memory:"
        if self.readonly:
            if not Path(self.path).exists():
                # create an empty journal once so a fresh install can still be browsed
                Journal(self.path).db.close()
            self.db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            return
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self):
        """Columns added after a journal was created (1.3.2: account_alphas.extra)."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(account_alphas)")}
        if "extra" not in cols:
            self.db.execute("ALTER TABLE account_alphas ADD COLUMN extra TEXT")
            self.db.commit()

    @classmethod
    def open_readonly(cls, path: Optional[Path] = None) -> "Journal":
        return cls(path, readonly=True)

    # ------------------------------------------------------------- binned cards (1.4.3)
    def bin_card(self, hypothesis_id: str, reason: str = "") -> None:
        """Put an idea card in the bin: hidden from the Cards ranking, the Lab list, Play and boosters.
        Nothing is deleted - restore_card() brings it back, and its simulations stay in the journal."""
        self.db.execute("INSERT OR REPLACE INTO binned VALUES (?,?,?)", (hypothesis_id, time.time(), reason or ""))
        self.db.commit()

    def restore_card(self, hypothesis_id: str) -> None:
        self.db.execute("DELETE FROM binned WHERE hypothesis_id=?", (hypothesis_id,))
        self.db.commit()

    def binned(self) -> pd.DataFrame:
        try:
            return pd.read_sql_query("SELECT hypothesis_id, created, reason FROM binned ORDER BY created DESC",
                                     self.db)
        except Exception:  # noqa: BLE001 - an old read-only journal without the table
            return pd.DataFrame(columns=["hypothesis_id", "created", "reason"])

    def binned_ids(self) -> set:
        try:
            return {r[0] for r in self.db.execute("SELECT hypothesis_id FROM binned")}
        except sqlite3.Error:            # an old read-only journal without the table
            return set()

    # ------------------------------------------------------------- ideas
    def log_idea(self, card) -> str:
        self.db.execute("INSERT OR IGNORE INTO ideas (id, hypothesis_id, region, family, title, categories, created) "
                        "VALUES (?,?,?,?,?,?,?)", (card.id, card.hypothesis.id, card.region, card.family,
                                                  card.hypothesis.title, ",".join(card.categories), time.time()))
        self.db.commit()
        return card.id

    def log_manual_idea(self, idea_id: str, region: str, family: str, title: str, categories=()) -> str:
        """An idea row without a card (e.g. re-runs of submitted alphas), so submit() knows its family."""
        self.db.execute("INSERT OR IGNORE INTO ideas (id, hypothesis_id, region, family, title, categories, created) "
                        "VALUES (?,?,?,?,?,?,?)", (idea_id, idea_id, region, family, title, ",".join(categories),
                                                  time.time()))
        self.db.commit()
        return idea_id

    # ------------------------------------------------- in-flight simulations (1.4.1 resume)
    def add_pending(self, location: str, idea_id: str, rung: str, purpose: str, expression: str, settings: dict,
                    payload: dict) -> None:
        """A simulation BRAIN accepted but HYPOLAB has not read back yet (survives a shutdown)."""
        self.db.execute("INSERT OR REPLACE INTO pending VALUES (?,?,?,?,?,?,?,?)",
                        (location, time.time(), idea_id, rung, purpose, expression, json.dumps(settings),
                         json.dumps(payload)))
        self.db.commit()

    def pending(self) -> List[dict]:
        if getattr(self, "readonly", False):
            try:
                rows = self.db.execute("SELECT * FROM pending ORDER BY created").fetchall()
            except sqlite3.OperationalError:
                return []
        else:
            rows = self.db.execute("SELECT * FROM pending ORDER BY created").fetchall()
        cols = ["location", "created", "idea_id", "rung", "purpose", "expression", "settings", "payload"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["settings"], d["payload"] = json.loads(d["settings"] or "{}"), json.loads(d["payload"] or "{}")
            out.append(d)
        return out

    def clear_pending(self, location: str) -> None:
        self.db.execute("DELETE FROM pending WHERE location=?", (location,))
        self.db.commit()

    def idea(self, idea_id: str) -> Optional[dict]:
        """The stored row of one idea (family, categories, title ...) - survives a kernel restart."""
        cur = self.db.execute("SELECT * FROM ideas WHERE id=?", (idea_id,))
        row = cur.fetchone()
        return None if row is None else dict(zip([d[0] for d in cur.description], row))

    def set_idea_status(self, idea_id: str, status: str, note: str = ""):
        self.db.execute("UPDATE ideas SET status=?, notes=notes || ? WHERE id=?", (status, f"\n{note}" if note else "", idea_id))
        self.db.commit()

    # ------------------------------------------------------- experiments
    def already_run(self, expression: str, settings: dict) -> Optional[dict]:
        fp = fingerprint(expression, settings)
        row = self.db.execute("SELECT * FROM experiments WHERE fingerprint=? AND status IN ('COMPLETE','WARNING')",
                              (fp,)).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self.db.execute("SELECT * FROM experiments LIMIT 0").description]
        return dict(zip(cols, row))

    def record(self, idea_id: str, rung: str, purpose: str, expression: str, settings: dict, summary: dict,
               verdict: str = "", backend: str = "brain") -> int:
        try:
            canon = canonical(expression)
        except ParseError:
            canon = expression
        fp = fingerprint(expression, settings)
        vals = dict(idea_id=idea_id, rung=rung, purpose=purpose, expression=expression, canonical=canon,
                    region=settings.get("region"), universe=settings.get("universe"), delay=settings.get("delay"),
                    settings=json.dumps(settings), fingerprint=fp, created=time.time(),
                    alpha_id=summary.get("alpha_id"), status=summary.get("status", "COMPLETE"),
                    error=summary.get("error", ""), sharpe=summary.get("is_sharpe"), fitness=summary.get("is_fitness"),
                    turnover=summary.get("is_turnover"), returns=summary.get("is_returns"),
                    drawdown=summary.get("is_drawdown"), margin=summary.get("is_margin"),
                    long_count=summary.get("is_longCount"), short_count=summary.get("is_shortCount"),
                    train_sharpe=summary.get("train_sharpe"), test_sharpe=summary.get("test_sharpe"),
                    failed=",".join(summary.get("failed", []) or []), verdict=verdict, backend=backend)
        cols = ",".join(vals)
        q = ",".join("?" * len(vals))
        cur = self.db.execute(f"INSERT OR REPLACE INTO experiments ({cols}) VALUES ({q})", tuple(vals.values()))
        self.db.commit()
        return cur.lastrowid

    def experiments(self, idea_id: Optional[str] = None, region: Optional[str] = None) -> pd.DataFrame:
        q, args = "SELECT * FROM experiments WHERE 1=1", []
        if idea_id:
            q += " AND idea_id=?"
            args.append(idea_id)
        if region:
            q += " AND region=?"
            args.append(region)
        return pd.read_sql_query(q + " ORDER BY created", self.db, params=args)

    def simulated_expressions(self, region: str) -> Set[str]:
        rows = self.db.execute("SELECT canonical FROM experiments WHERE region=? AND status IN ('COMPLETE','WARNING')",
                               (region,)).fetchall()
        return {r[0] for r in rows}

    def trials(self, idea_id: str, purpose=("explore", "boost", "play")) -> int:
        """Tries that count against an idea: exploring rungs, searching for boosters and playground rolls
        (all are selection, so the gate's deflated Sharpe must know about every one)."""
        q, args = "SELECT COUNT(*) FROM experiments WHERE idea_id=?", [idea_id]
        if purpose:
            purposes = [purpose] if isinstance(purpose, str) else list(purpose)
            q += f" AND purpose IN ({','.join('?' * len(purposes))})"
            args.extend(purposes)
        return int(self.db.execute(q, args).fetchone()[0])

    def sims_today(self) -> int:
        # BRAIN's day: the quota resets at midnight New York time (07:00/08:00 in Nairobi) - BRAIN_RULES S-2
        start = brain_day_start()
        return int(self.db.execute("SELECT COUNT(*) FROM experiments WHERE created>=? AND backend='brain'",
                                   (start,)).fetchone()[0])

    def family_status(self, family: str, region: str) -> Dict[str, int]:
        sim = self.db.execute("SELECT COUNT(*) FROM experiments e JOIN ideas i ON e.idea_id=i.id "
                              "WHERE i.family=? AND e.region=?", (family, region)).fetchone()[0]
        sub = self.db.execute("SELECT COUNT(*) FROM submissions WHERE family=? AND region=?", (family, region)).fetchone()[0]
        return {"simulated": int(sim), "submitted": int(sub)}

    # ------------------------------------------------------- submissions
    def record_submission(self, alpha_id: str, idea_id: str, family: str, region: str, delay: int,
                          categories: Iterable[str], sharpe=None, fitness=None):
        self.db.execute("INSERT OR REPLACE INTO submissions VALUES (?,?,?,?,?,?,?,?,?)",
                        (alpha_id, idea_id, family, region, delay, ",".join(categories), time.time(), sharpe, fitness))
        self.set_idea_status(idea_id, "submitted", f"submitted {alpha_id}")
        self.db.commit()

    def submissions_today(self) -> int:
        """Alphas submitted since BRAIN's midnight (New York time); BRAIN expects at most 4 a day."""
        start = brain_day_start()
        return int(self.db.execute("SELECT COUNT(*) FROM submissions WHERE submitted>=?", (start,)).fetchone()[0])

    def submissions(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT * FROM submissions ORDER BY submitted", self.db)

    # ------------------------------------------------------------ lessons
    def add_lesson(self, text: str, idea_id: str = "", family: str = ""):
        self.db.execute("INSERT INTO lessons (created, idea_id, family, text) VALUES (?,?,?,?)",
                        (time.time(), idea_id, family, text))
        self.db.commit()

    def lessons(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT datetime(created,'unixepoch') AS date, idea_id, family, text FROM lessons "
                                 "ORDER BY created DESC", self.db)

    # ------------------------------------------------------------ reports
    def scoreboard(self) -> pd.DataFrame:
        """Per family: tries, best Sharpe, how many passed, submitted - your research map."""
        q = """SELECT i.family, e.region, COUNT(*) AS sims, MAX(e.sharpe) AS best_sharpe, MAX(e.fitness) AS best_fitness,
               SUM(CASE WHEN e.failed='' AND e.status IN ('COMPLETE','WARNING') THEN 1 ELSE 0 END) AS clean,
               (SELECT COUNT(*) FROM submissions s WHERE s.family=i.family AND s.region=e.region) AS submitted
               FROM experiments e JOIN ideas i ON e.idea_id=i.id GROUP BY i.family, e.region ORDER BY best_sharpe DESC"""
        return pd.read_sql_query(q, self.db)
