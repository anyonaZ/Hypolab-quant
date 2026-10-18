"""Local catalog of datasets and datafields, enriched with economics.

Sources
-------
1. ``data/catalog_GLB_MINVOL1M_D1.json.gz`` - built from the ``ace-catalog.json``
   in your zip (137 datasets, 27,114 fields for GLB / MINVOL1M / delay 1).
   Lets you explore ideas offline on day one.
2. ``Catalog.sync_from_brain(client, region, universe, delay)`` - pulls every
   field for your account, page by page (the ``get_datafields`` in the zip's
   Gold ``ace_lib`` fetched only the FIRST page when no search term was given,
   so beginners only ever saw a sliver of each dataset).

Everything is stored in ``~/.hypolab/catalog.sqlite`` so later sessions start
instantly and do not spend API requests.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import pickle
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from . import config
from .concepts import CONCEPTS, NON_NUMERIC, classify_nature, direction_hint, match_concepts

# BRAIN data category id -> pyramid / display name
CATEGORY_NAMES = {
    "analyst": "Analyst", "fundamental": "Fundamental", "model": "Model", "pv": "Price Volume",
    "risk": "Risk", "earnings": "Earnings", "imbalance": "Imbalance", "other": "Other", "macro": "Macro",
    "option": "Option", "news": "News", "sentiment": "Sentiment", "shortinterest": "Short Interest",
    "institutions": "Institutions", "insiders": "Insiders", "socialmedia": "Social Media", "broker": "Broker",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
  region TEXT, universe TEXT, delay INTEGER, id TEXT, name TEXT, category TEXT, description TEXT,
  coverage REAL, value_score REAL, user_count REAL, alpha_count REAL, field_count REAL,
  pyramid_multiplier REAL, updated REAL, PRIMARY KEY (region, universe, delay, id));
CREATE TABLE IF NOT EXISTS fields (
  region TEXT, universe TEXT, delay INTEGER, id TEXT, dataset TEXT, category TEXT, type TEXT,
  description TEXT, coverage REAL, date_coverage REAL, user_count REAL, alpha_count REAL,
  pyramid_multiplier REAL, updated REAL, PRIMARY KEY (region, universe, delay, id));
CREATE TABLE IF NOT EXISTS sync_log (region TEXT, universe TEXT, delay INTEGER, dataset TEXT,
  n_fields INTEGER, ts REAL, PRIMARY KEY (region, universe, delay, dataset));
"""


def _rules_hash() -> str:
    """Changes whenever the concept or nature/direction rules change, so stale disk caches are ignored."""
    from . import concepts as _c
    sig = repr([(c.name, c.include, c.exclude, c.natures, c.canonical) for c in CONCEPTS.values()]) + \
        repr(_c._NATURE_RULES) + repr(_c._POS) + repr(_c._NEG)
    return hashlib.sha1(sig.encode()).hexdigest()[:10]


def _num(v):
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _cat_id(v) -> str:
    if isinstance(v, dict):
        v = v.get("id") or v.get("name")
    return str(v or "other").lower().replace(" ", "").replace("_", "")


class Catalog:
    def __init__(self, path: Optional[Path] = None):
        config.ensure_home()
        self.path = Path(path) if path else config.HOME / "catalog.sqlite"
        self.db = sqlite3.connect(str(self.path))
        self.db.executescript(_SCHEMA)
        self._cache: Dict[tuple, pd.DataFrame] = {}
        # 1.4.3: enriched fields and concept matches are kept on disk between restarts (a slow laptop otherwise
        # re-reads 27k field descriptions with regexes every time the cockpit starts). Never for :memory:.
        self._disk = str(path) != ":memory:"
        self._concepts_disk: Dict[tuple, dict] = {}

    # ------------------------------------------------------------ disk cache (1.4.3)
    def _cache_file(self, kind: str, region, universe, delay) -> Optional[Path]:
        if not self._disk:
            return None
        try:
            q = "SELECT COUNT(*), MAX(updated) FROM fields WHERE region=? AND delay=?"
            args: list = [region, delay]
            if universe:
                q += " AND universe=?"
                args.append(universe)
            n, mx = self.db.execute(q, args).fetchone()
        except sqlite3.Error:
            return None
        if not n:
            return None
        folder = self.path.parent / "cache"
        stem = f"{kind}_{region}_{universe or 'ALL'}_D{delay}_"
        name = f"{stem}{n}_{int((mx or 0) * 1000)}_{_rules_hash()}.pkl"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for old in folder.glob(stem + "*.pkl"):
                if old.name != name:
                    old.unlink(missing_ok=True)        # superseded by a newer sync
        except OSError:
            return None
        return folder / name

    @staticmethod
    def _load(path: Optional[Path]):
        if path is None or not path.exists():
            return None
        try:
            with open(path, "rb") as fh:
                return pickle.load(fh)
        except Exception:  # noqa: BLE001 - a broken cache file is simply rebuilt
            return None

    @staticmethod
    def _save(path: Optional[Path], obj) -> None:
        if path is None:
            return
        try:
            tmp = path.with_suffix(".tmp")
            with open(tmp, "wb") as fh:
                pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(path)
        except OSError:
            pass

    # ------------------------------------------------------------ loading
    def load_bundled(self) -> int:
        """Load the GLB/MINVOL1M/D1 snapshot shipped in data/ (from your zip)."""
        n = 0
        for path in sorted(config.BUNDLED_DATA.glob("catalog_*.json.gz")):
            with gzip.open(path, "rt") as fh:
                snap = json.load(fh)
            n += self._ingest(snap["region"], snap["universe"], int(snap["delay"]),
                              snap["datasets"], snap["fields"], bundled=True)
        return n

    def ingest_payload(self, payload: dict) -> int:
        """Load a {region, universe, delay, datasets, fields} snapshot (e.g. the sandbox market)."""
        return self._ingest(payload["region"], payload["universe"], int(payload["delay"]), payload["datasets"],
                            payload["fields"])

    def _ingest(self, region, universe, delay, datasets: Iterable[dict], fields: Iterable[dict],
                bundled: bool = False) -> int:
        now = time.time()
        ds_rows, cat_of = [], {}
        for d in datasets:
            cat = _cat_id(d.get("category"))
            did = d.get("id")
            cat_of[did] = cat
            ds_rows.append((region, universe, delay, did, d.get("name"), cat, d.get("description"),
                            _num(d.get("coverage")), _num(d.get("value_score", d.get("valueScore"))),
                            _num(d.get("user_count", d.get("userCount"))),
                            _num(d.get("alpha_count", d.get("alphaCount"))),
                            _num(d.get("field_count", d.get("fieldCount"))),
                            _num(d.get("pyramid_multiplier", d.get("pyramidMultiplier"))), now))
        self.db.executemany("INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ds_rows)
        f_rows = []
        for f in fields:
            ds = f.get("dataset")
            if isinstance(ds, dict):
                ds = ds.get("id")
            cat = f.get("category")
            cat = _cat_id(cat) if cat else cat_of.get(ds, "other")
            f_rows.append((region, universe, delay, f.get("id"), ds, cat, f.get("type", "MATRIX"),
                           f.get("description"), _num(f.get("coverage")), _num(f.get("date_coverage", f.get("dateCoverage"))),
                           _num(f.get("user_count", f.get("userCount"))), _num(f.get("alpha_count", f.get("alphaCount"))),
                           _num(f.get("pyramid_multiplier", f.get("pyramidMultiplier"))), now))
        self.db.executemany("INSERT OR REPLACE INTO fields VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", f_rows)
        self.db.commit()
        self._cache.clear()
        self._concepts_disk.clear()
        return len(f_rows)

    def sync_from_brain(self, client, region: str, universe: str, delay: int = 1,
                        datasets: Optional[Sequence[str]] = None, categories: Optional[Sequence[str]] = None,
                        max_age_days: float = 7.0, progress=print) -> int:
        """Fetch datasets + ALL their fields (paginated) for one context.

        Only datasets older than ``max_age_days`` are re-fetched, so re-running is cheap.
        """
        ds_list = client.datasets(region=region, universe=universe, delay=delay)
        self._ingest(region, universe, delay, ds_list, [])
        wanted = []
        for d in ds_list:
            cat = _cat_id(d.get("category"))
            if datasets and d["id"] not in datasets:
                continue
            if categories and cat not in {_cat_id(c) for c in categories}:
                continue
            wanted.append(d["id"])
        total = 0
        for i, ds in enumerate(wanted, 1):
            row = self.db.execute("SELECT ts FROM sync_log WHERE region=? AND universe=? AND delay=? AND dataset=?",
                                  (region, universe, delay, ds)).fetchone()
            if row and time.time() - row[0] < max_age_days * 86400:
                continue
            fields = client.datafields(region=region, universe=universe, delay=delay, dataset_id=ds)
            n = self._ingest(region, universe, delay, [], fields)
            self.db.execute("INSERT OR REPLACE INTO sync_log VALUES (?,?,?,?,?,?)",
                            (region, universe, delay, ds, n, time.time()))
            self.db.commit()
            total += n
            if progress:
                progress(f"[{i}/{len(wanted)}] {ds}: {n} fields")
        return total

    # ------------------------------------------------------------- views
    def contexts(self) -> pd.DataFrame:
        return pd.read_sql_query("SELECT region, universe, delay, COUNT(*) AS fields FROM fields "
                                 "GROUP BY region, universe, delay", self.db)

    def datasets(self, region: str, universe: Optional[str] = None, delay: int = 1) -> pd.DataFrame:
        q = "SELECT * FROM datasets WHERE region=? AND delay=?"
        args: list = [region, delay]
        if universe:
            q += " AND universe=?"
            args.append(universe)
        df = pd.read_sql_query(q, self.db, params=args)
        if not df.empty:
            df["category_name"] = df["category"].map(lambda c: CATEGORY_NAMES.get(c, c))
            fc = self.fields(region, universe, delay).groupby("dataset").size()
            df["fields_known"] = df["id"].map(fc).fillna(0).astype(int)
        return df

    def fields(self, region: str, universe: Optional[str] = None, delay: int = 1,
               enrich: bool = True) -> pd.DataFrame:
        key = (region, universe, delay, enrich)
        if key in self._cache:
            return self._cache[key]
        q = "SELECT * FROM fields WHERE region=? AND delay=?"
        args: list = [region, delay]
        if universe:
            q += " AND universe=?"
            args.append(universe)
        disk = self._cache_file("fields", region, universe, delay) if enrich else None
        hit = self._load(disk)
        if isinstance(hit, pd.DataFrame):
            self._cache[key] = hit
            return hit
        df = pd.read_sql_query(q, self.db, params=args)
        if enrich and not df.empty:
            df["nature"] = [classify_nature(i, d or "", t) for i, d, t in zip(df["id"], df["description"], df["type"])]
            dirs = [direction_hint(i, d or "") for i, d in zip(df["id"], df["description"])]
            df["direction"] = [x[0] for x in dirs]
            df["direction_reason"] = [x[1] for x in dirs]
            df["category_name"] = df["category"].map(lambda c: CATEGORY_NAMES.get(c, c))
            ac = df["alpha_count"].fillna(0)
            df["crowding"] = (ac + 1).map(math.log10).round(2)   # 0 = untouched, 4 = 10k alphas
            self._save(disk, df)
        self._cache[key] = df
        return df

    def has_context(self, region: str, universe: Optional[str] = None, delay: int = 1) -> bool:
        return not self.fields(region, universe, delay, enrich=False).empty

    def lookup(self, field_id: str, region: str, universe: Optional[str] = None, delay: int = 1) -> Optional[dict]:
        df = self.fields(region, universe, delay)
        hit = df[df["id"] == field_id]
        return None if hit.empty else hit.iloc[0].to_dict()

    def search(self, text: str, region: str, universe: Optional[str] = None, delay: int = 1,
               limit: int = 30) -> pd.DataFrame:
        df = self.fields(region, universe, delay)
        t = text.lower()
        mask = df["id"].str.lower().str.contains(t, regex=False) | \
            df["description"].fillna("").str.lower().str.contains(t, regex=False)
        cols = ["id", "dataset", "category_name", "type", "nature", "coverage", "alpha_count", "description"]
        return df.loc[mask, cols].sort_values("coverage", ascending=False).head(limit)

    def find_concept(self, concept: str, region: str, universe: Optional[str] = None, delay: int = 1,
                     allowed_types: Sequence[str] = ("MATRIX", "VECTOR"), min_coverage: float = 0.3,
                     categories: Optional[Sequence[str]] = None, limit: int = 15) -> pd.DataFrame:
        """Fields that represent an economic concept, best first.

        Ranking = match strength x coverage, mildly penalising crowded fields
        (crowded fields correlate with alphas that already exist).
        """
        if concept not in CONCEPTS:
            raise KeyError(f"unknown concept {concept!r}; known: {sorted(CONCEPTS)}")
        ckey = ("concept", concept, region, universe, delay, tuple(allowed_types), min_coverage,
                tuple(categories or ()), limit)
        if ckey in self._cache:
            return self._cache[ckey].copy()
        ctx = (region, universe, delay)
        if ctx not in self._concepts_disk:
            path = self._cache_file("concepts", region, universe, delay)
            self._concepts_disk[ctx] = {"path": path, "data": self._load(path) or {}}
        store = self._concepts_disk[ctx]
        out = store["data"].get(ckey)
        if not isinstance(out, pd.DataFrame):
            out = self._find_concept(concept, region, universe, delay, allowed_types, min_coverage, categories,
                                     limit)
            store["data"][ckey] = out
            self._save(store["path"], store["data"])
        self._cache[ckey] = out
        return out.copy()

    def _rows(self, region, universe, delay) -> list:
        key = ("rows", region, universe, delay)
        if key not in self._cache:
            df = self.fields(region, universe, delay)
            out = []
            if not df.empty:
                cols = ["id", "dataset", "category", "type", "nature", "coverage", "alpha_count", "description"]
                for rec in df[cols].to_dict("records"):
                    desc = rec["description"] if isinstance(rec["description"], str) else ""
                    fid = str(rec["id"]).lower()
                    cov, ac = rec["coverage"], rec["alpha_count"]
                    rec["description"] = rec["description"] if isinstance(rec["description"], str) else None
                    rec["coverage"] = 0.5 if cov is None or pd.isna(cov) else float(cov)
                    rec["crowd"] = 0.0 if ac is None or pd.isna(ac) else math.log10(1 + ac)
                    rec["fid"], rec["text"] = fid, f"{fid.replace('_', ' ')} | {desc.lower()}"
                    out.append(rec)
            self._cache[key] = out
        return self._cache[key]

    def lookup_map(self, region: str, universe: Optional[str] = None, delay: int = 1) -> dict:
        """{field id: dataset id} for one context, built once (rules.catalog_lookup uses it)."""
        key = ("dsmap", region, universe, delay)
        if key not in self._cache:
            df = self.fields(region, universe, delay, enrich=False)
            self._cache[key] = {} if df.empty else dict(zip(df["id"].tolist(), df["dataset"].tolist()))
        return self._cache[key]

    def _find_concept(self, concept, region, universe, delay, allowed_types, min_coverage, categories, limit):
        df = self.fields(region, universe, delay)
        if df.empty:
            return df
        c = CONCEPTS[concept]
        cats = {_cat_id(x) for x in categories} if categories else None
        allowed = set(allowed_types)
        rows = []
        # plain Python rows built once per region (1.4.3): iterating the DataFrame for each of ~50 concepts
        # was most of the Cards tab's start-up time on a big catalog (27k GLB fields: 18 s -> under 1 s)
        for r in self._rows(region, universe, delay):
            if r["type"] not in allowed or (cats is not None and r["category"] not in cats):
                continue
            if r["nature"] in NON_NUMERIC:
                continue
            if r["nature"] == "flag" and not (c.natures and "flag" in c.natures):
                continue          # 0/1 indicators are gates, not signals
            s, why = c.match_text(r["fid"], r["text"])
            if s <= 0:
                continue
            if c.natures and r["nature"] not in c.natures:
                s *= 0.5
            cov = r["coverage"]
            if cov < min_coverage:
                continue
            score = s * (0.4 + cov) * (1.0 - 0.06 * r["crowd"])
            rows.append({"id": r["id"], "dataset": r["dataset"], "category": r["category"], "type": r["type"],
                         "nature": r["nature"], "coverage": cov, "alpha_count": r["alpha_count"],
                         "score": round(score, 3), "why": why, "description": r["description"]})
        out = pd.DataFrame(rows)
        if out.empty:
            # standard fields (close, returns, cap ...) exist in every region even if the catalog lacks them
            if c.canonical:
                return pd.DataFrame([{"id": c.canonical[0], "dataset": "pv1", "category": "pv", "type": "MATRIX",
                                      "nature": "level", "coverage": 1.0, "alpha_count": None, "score": 1.0,
                                      "why": "standard BRAIN field (not in local catalog - verify it exists)",
                                      "description": c.note}])
            return out
        return out.sort_values("score", ascending=False).head(limit).reset_index(drop=True)

    def concept_map(self, dataset: str, region: str, universe: Optional[str] = None, delay: int = 1) -> pd.DataFrame:
        """What each field of a dataset measures - the first thing to read about a new dataset."""
        df = self.fields(region, universe, delay)
        sub = df[df["dataset"] == dataset]
        rows = []
        for r in sub.itertuples(index=False):
            ms = match_concepts(r.id, r.description or "", r.nature)
            rows.append({"id": r.id, "type": r.type, "nature": r.nature, "coverage": r.coverage,
                         "alpha_count": r.alpha_count, "concepts": ", ".join(m.concept for m in ms[:3]),
                         "direction": r.direction, "description": r.description})
        return pd.DataFrame(rows)

    def dataset_summary(self, region: str, universe: Optional[str] = None, delay: int = 1) -> pd.DataFrame:
        """One row per dataset: size, coverage, crowding, how much is numeric/usable."""
        f = self.fields(region, universe, delay)
        if f.empty:
            return f
        f = f.assign(usable=~f["nature"].isin(NON_NUMERIC))
        g = f.groupby(["dataset", "category"]).agg(
            fields=("id", "count"), usable=("usable", "sum"), matrix=("type", lambda s: (s == "MATRIX").sum()),
            vector=("type", lambda s: (s == "VECTOR").sum()), median_coverage=("coverage", "median"),
            median_alpha_count=("alpha_count", "median")).reset_index()
        ds = self.datasets(region, universe, delay)
        if not ds.empty:
            g = g.merge(ds[["id", "name", "value_score", "alpha_count"]].rename(
                columns={"id": "dataset", "alpha_count": "dataset_alpha_count"}), on="dataset", how="left")
        g["category_name"] = g["category"].map(lambda c: CATEGORY_NAMES.get(c, c))
        return g.sort_values(["category", "median_coverage"], ascending=[True, False])
