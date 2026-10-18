"""Your submitted alphas, read from BRAIN, and what they say about your habits.

    from hypolab.account import sync_account, operator_audit
    sync_account(brain, journal)                  # downloads every submitted alpha + the live operator list
    summary, by_category, used, unused = operator_audit(journal, 2026, 4)

What it gives you:
* the real lifetime count of submitted alphas (feeds the SuperAlpha countdown) and per-quarter counts;
* operators used and NOT used per quarter, by BRAIN's own categories (counting rules as in the
  community "ALPHA_ITERATOR (Unused Ops)" notebook: REGULAR code only, symbols mapped to operator names,
  `ts_backfill` / `group_backfill` left out, `=` in named arguments is not an operator);
* the fields and datasets your submitted alphas lean on (a correlation warning for new ideas).

Stored in journal.sqlite, table `account_alphas` (one row per submitted alpha; re-syncing replaces rows).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

from .operators import LITERALS, STANDARD_GROUPS, regular_operator_catalog, sync_operators

BRAIN_TZ = ZoneInfo("America/New_York")
EXCLUDED_FROM_AUDIT = {"ts_backfill", "group_backfill"}

SYMBOLIC_OPERATOR_NAMES = {
    "+": "add", "-": "subtract", "*": "multiply", "/": "divide", "÷": "divide", "%": "modulo", "^": "power",
    "<": "less", "<=": "less_equal", ">": "greater", ">=": "greater_equal", "==": "equal", "!=": "not_equal",
    "&&": "and", "||": "or", "!": "not", "?": "if_else",
}
_SYMBOL = re.compile(r"&&|\|\||<=|>=|==|!=|[+\-*/÷%^<>!?]")
_FUNC = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_IDENT = re.compile(r"\b([A-Za-z_]\w*)\b")
_NAMED_ARG = re.compile(r"\b([A-Za-z_]\w*)\s*=(?!=)")
_COMMENT = re.compile(r"#[^\n]*")
_NUMBER_IN_E = re.compile(r"\d[eE][+-]?\d")       # 1e-3: the minus is not subtraction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS account_alphas (
  alpha_id TEXT PRIMARY KEY, type TEXT, status TEXT, date_submitted TEXT, date_created TEXT,
  region TEXT, universe TEXT, delay INTEGER, neutralization TEXT, decay INTEGER, truncation REAL,
  code TEXT, sharpe REAL, fitness REAL, turnover REAL, returns REAL, drawdown REAL,
  operators TEXT, fields TEXT, name TEXT, tags TEXT, synced REAL, extra TEXT);
"""
# Keys of BRAIN's alpha JSON kept verbatim in `extra` when present (names vary; matched by substring):
# Pyramid tags, Osmosis points, classifications, themes. Used by quarter_pyramids() / osmosis_check().
_EXTRA_KEYS = ("pyramid", "osmosis", "classification", "theme")


# ------------------------------------------------------------------ parsing
def _clean(code: str) -> str:
    code = _COMMENT.sub("", code or "")
    return re.sub(r"(['\"]).*?\1", "", code)                # drop string literals (e.g. range="0,1,0.1")


def operators_in_code(code: str, known: Iterable[str]) -> Set[str]:
    """Distinct operator names used in one REGULAR expression (symbols mapped to names)."""
    known = set(known)
    text = _clean(code)
    if not text.strip():
        return set()
    funcs = {n for n in _FUNC.findall(text) if n in known}
    text_wo_exp = _NUMBER_IN_E.sub("0", text)
    symbols = {SYMBOLIC_OPERATOR_NAMES[t] for t in _SYMBOL.findall(text_wo_exp)}
    return ((funcs | symbols) & known) - EXCLUDED_FROM_AUDIT


def fields_in_code(code: str, known_operators: Iterable[str]) -> Set[str]:
    """Data fields an expression uses: identifiers that are not operators, variables, keywords or arguments."""
    ops = set(known_operators)
    text = _clean(code)
    assigned = {m.group(1) for stmt in text.split(";") for m in [re.match(r"\s*([A-Za-z_]\w*)\s*=(?!=)", stmt)] if m}
    named = set(_NAMED_ARG.findall(text)) - assigned
    out = set()
    for m in _IDENT.finditer(text):
        name = m.group(1)
        after = text[m.end():m.end() + 2].lstrip()[:1]
        if after == "(" or name in ops or name in assigned or name in named:
            continue
        if name in LITERALS or name.lower() in LITERALS or name in STANDARD_GROUPS or name.lower() in ("true", "false"):
            continue
        out.add(name)
    return out


# ------------------------------------------------------------------ storage
def _ensure(journal):
    """Create the table when the journal is writable (it normally already exists: see journal._SCHEMA)."""
    if not getattr(journal, "readonly", False):
        journal.db.executescript(_SCHEMA)


def _has_table(journal) -> bool:
    return journal.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_alphas'").fetchone() \
        is not None


def _row(a: dict, op_names: Set[str]) -> tuple:
    st = a.get("settings") or {}
    typ = a.get("type") or "REGULAR"
    code = (a.get("regular") or {}).get("code") if isinstance(a.get("regular"), dict) else a.get("regular")
    if typ == "SUPER":
        combo = a.get("combo") or {}
        code = (combo.get("code") if isinstance(combo, dict) else combo) or code
    is_ = a.get("is") or {}
    ops = sorted(operators_in_code(code or "", op_names)) if typ == "REGULAR" else []
    flds = sorted(fields_in_code(code or "", op_names)) if typ == "REGULAR" else []
    return (a.get("id"), typ, a.get("status"), a.get("dateSubmitted"), a.get("dateCreated"),
            st.get("region"), st.get("universe"), st.get("delay"), st.get("neutralization"), st.get("decay"),
            st.get("truncation"), code, is_.get("sharpe"), is_.get("fitness"), is_.get("turnover"),
            is_.get("returns"), is_.get("drawdown"), json.dumps(ops), json.dumps(flds), a.get("name"),
            json.dumps(a.get("tags") or []), time.time(),
            json.dumps({k: v for k, v in a.items() if any(x in k.lower() for x in _EXTRA_KEYS)}, default=str))


def store_alphas(journal, alphas: Sequence[dict], op_names: Optional[Iterable[str]] = None) -> int:
    _ensure(journal)
    names = set(op_names) if op_names is not None else set(regular_operator_catalog()["name"])
    rows = [_row(a, names) for a in alphas if a.get("id") and a.get("dateSubmitted")]
    journal.db.executemany(f"INSERT OR REPLACE INTO account_alphas VALUES ({','.join('?' * 23)})", rows)
    journal.db.commit()
    return len(rows)


def account_alphas(journal) -> pd.DataFrame:
    _ensure(journal)
    if not _has_table(journal):          # a read-only journal from before this table existed
        return pd.DataFrame(columns=["alpha_id", "type", "date_submitted", "operators", "fields", "submitted"])
    df = pd.read_sql_query("SELECT * FROM account_alphas ORDER BY date_submitted DESC", journal.db)
    if not df.empty:
        df["operators"] = df["operators"].map(lambda s: json.loads(s or "[]"))
        df["fields"] = df["fields"].map(lambda s: json.loads(s or "[]"))
        df["submitted"] = pd.to_datetime(df["date_submitted"], utc=True, errors="coerce").dt.tz_convert(BRAIN_TZ)
    return df


def last_sync(journal) -> Optional[float]:
    _ensure(journal)
    if not _has_table(journal):
        return None
    r = journal.db.execute("SELECT MAX(synced) FROM account_alphas").fetchone()
    return r[0] if r and r[0] else None


def sync_account(brain, journal, operators: bool = True) -> dict:
    """Download the live operator list (optional) and every submitted alpha, and store them."""
    out = {}
    if operators:
        out.update(sync_operators(brain))
        if hasattr(brain, "sync_simulation_options"):
            try:
                opts = brain.sync_simulation_options()
                out["regions_synced"] = int(len(opts))
            except Exception as e:  # noqa: BLE001 - options are a convenience; never block the alpha download
                out["regions_error"] = str(e)[:200]
    alphas = brain.submitted_alphas()
    out["alphas"] = store_alphas(journal, alphas)
    return out


# ------------------------------------------------------------------ reports
def quarter_bounds(year: int, quarter: int) -> Tuple[dt.datetime, dt.datetime]:
    start = dt.datetime(year, 3 * (quarter - 1) + 1, 1, tzinfo=BRAIN_TZ)
    end = dt.datetime(year + 1, 1, 1, tzinfo=BRAIN_TZ) if quarter == 4 else \
        dt.datetime(year, 3 * quarter + 1, 1, tzinfo=BRAIN_TZ)
    return start, end


def current_quarter() -> Tuple[int, int]:
    now = dt.datetime.now(BRAIN_TZ)
    return now.year, (now.month - 1) // 3 + 1


def counts(journal, year: Optional[int] = None, quarter: Optional[int] = None) -> Dict[str, int]:
    df = account_alphas(journal)
    y, q = (year, quarter) if year else current_quarter()
    if df.empty:
        return {"lifetime_regular": 0, "lifetime_super": 0, "quarter_regular": 0, "quarter_super": 0}
    start, end = quarter_bounds(y, q)
    inq = (df["submitted"] >= start) & (df["submitted"] < end)
    return {"lifetime_regular": int((df["type"] == "REGULAR").sum()), "lifetime_super": int((df["type"] == "SUPER").sum()),
            "quarter_regular": int(((df["type"] == "REGULAR") & inq).sum()),
            "quarter_super": int(((df["type"] == "SUPER") & inq).sum())}


def operator_audit(journal, year: Optional[int] = None, quarter: Optional[int] = None):
    """(summary, by_category, used, unused) for one calendar quarter (BRAIN's time zone, New York)."""
    y, q = (year, quarter) if year else current_quarter()
    start, end = quarter_bounds(y, q)
    cat = regular_operator_catalog()
    cat = cat[~cat["name"].isin(EXCLUDED_FROM_AUDIT)]
    df = account_alphas(journal)
    if not df.empty:
        df = df[(df["submitted"] >= start) & (df["submitted"] < end)]
    reg = df[df["type"] == "REGULAR"] if not df.empty else df
    uses: Counter = Counter()
    for ops in (reg["operators"] if not reg.empty else []):
        uses.update(set(ops) & set(cat["name"]))
    by_cat = []
    for c, g in cat.groupby("category"):
        used = [n for n in g["name"] if uses[n]]
        by_cat.append({"category": c, "used": len(used), "available": len(g),
                       "coverage_%": round(100 * len(used) / len(g), 1) if len(g) else 0.0})
    used_df = pd.DataFrame([{"operator": n, "category": cat.set_index("name").loc[n, "category"],
                             "submissions": k} for n, k in uses.items()],
                           columns=["operator", "category", "submissions"]).sort_values(
        ["category", "submissions"], ascending=[True, False]).reset_index(drop=True)
    unused_df = cat[~cat["name"].isin(uses)].rename(columns={"name": "operator"})[["category", "operator"]] \
        .reset_index(drop=True)
    summary = {"quarter": f"{y} Q{q}", "from": start.date().isoformat(), "to (exclusive)": end.date().isoformat(),
               "submissions": int(len(df)), "regular counted": int(len(reg)),
               "super left out": int(len(df) - len(reg)), "distinct operators used": int(len(uses)),
               "operators available": int(len(cat)), "operator list from": cat["source"].iloc[0] if len(cat) else "-",
               "left out of the count": ", ".join(sorted(EXCLUDED_FROM_AUDIT))}
    return summary, pd.DataFrame(by_cat), used_df, unused_df


def field_usage(journal, top: int = 30) -> pd.DataFrame:
    """Fields your submitted regular alphas use most: new ideas on these will correlate with your own pool."""
    df = account_alphas(journal)
    if df.empty:
        return pd.DataFrame(columns=["field", "submitted alphas", "last used"])
    reg = df[df["type"] == "REGULAR"]
    rows: Dict[str, dict] = {}
    for r in reg.itertuples(index=False):
        for f in r.fields:
            d = rows.setdefault(f, {"field": f, "submitted alphas": 0, "last used": r.date_submitted})
            d["submitted alphas"] += 1
            d["last used"] = max(d["last used"] or "", r.date_submitted or "")
    out = pd.DataFrame(list(rows.values()), columns=["field", "submitted alphas", "last used"])
    return out.sort_values("submitted alphas", ascending=False).head(top).reset_index(drop=True)


# ------------------------------------------------- Genius: quarter, tie-breakers, Osmosis (1.3.2)
def _extra(df: pd.DataFrame) -> pd.Series:
    if "extra" not in df.columns:
        return pd.Series([{}] * len(df), index=df.index)
    return df["extra"].map(lambda s: json.loads(s) if isinstance(s, str) and s else {})


def quarter_alphas(journal, year: Optional[int] = None, quarter: Optional[int] = None,
                   kind: str = "REGULAR") -> pd.DataFrame:
    """Submitted alphas of one calendar quarter (New York time) - what Genius counts [BRAIN_RULES S14]."""
    df = account_alphas(journal)
    if df.empty:
        return df
    y, q = (year, quarter) if year else current_quarter()
    start, end = quarter_bounds(y, q)
    df = df[(df["submitted"] >= start) & (df["submitted"] < end)]
    return df[df["type"] == kind] if kind else df


def tiebreakers(journal, year: Optional[int] = None, quarter: Optional[int] = None) -> Dict[str, float]:
    """Genius tie-breaker numbers computable from your submissions [BRAIN_RULES G5].

    Lower is better for the per-alpha averages, higher for the totals. ts_backfill / group_backfill are not
    counted as operators. The streak and community score come only from BRAIN's Genius page.
    """
    df = quarter_alphas(journal, year, quarter)
    if df.empty:
        return {"alphas": 0, "operators per alpha": 0.0, "fields per alpha": 0.0,
                "distinct operators": 0, "distinct fields": 0}
    ops = [set(o) - EXCLUDED_FROM_AUDIT for o in df["operators"]]
    flds = [set(f) for f in df["fields"]]
    return {"alphas": int(len(df)),
            "operators per alpha": round(sum(map(len, ops)) / len(df), 2),
            "fields per alpha": round(sum(map(len, flds)) / len(df), 2),
            "distinct operators": len(set().union(*ops)), "distinct fields": len(set().union(*flds))}


_GROUPING = {"country", "exchange", "market", "sector", "industry", "subindustry"}


def _norm_cat(v) -> str:
    from .catalog import CATEGORY_NAMES, _cat_id
    rev = {_cat_id(name): cid for cid, name in CATEGORY_NAMES.items()}
    c = _cat_id(v)
    return rev.get(c, c)


def _pyramids_from_extra(extra: dict) -> List[Tuple[str, int, str]]:
    """BRAIN may tag an alpha with its Pyramids (e.g. 'USA/D1/ANALYST'); parse whatever shape it has."""
    out = []
    for k, v in (extra or {}).items():
        if "pyramid" not in k.lower():
            continue
        for item in (v if isinstance(v, list) else [v]):
            name = item.get("name") or item.get("id") if isinstance(item, dict) else item
            parts = str(name or "").replace("-", "/").split("/")
            if len(parts) == 3 and parts[1].upper().startswith("D") and parts[1][1:].isdigit():
                out.append((parts[0].upper(), int(parts[1][1:]), _norm_cat(parts[2])))
    return out


def quarter_pyramids(journal, catalog, year: Optional[int] = None, quarter: Optional[int] = None):
    """(counts, notes): alphas per (region, delay, category) for the quarter - Genius' Pyramid grid.

    Category of each alpha = BRAIN's own Pyramid tags when present, else the categories of the fields it uses
    (looked up in HYPOLAB's catalog for that region and delay). One alpha counts in every category it touches.
    """
    df = quarter_alphas(journal, year, quarter)
    rows, notes, unmapped = [], [], Counter()
    maps: Dict[tuple, dict] = {}
    for r, extra in zip(df.itertuples(index=False), _extra(df)):
        tagged = _pyramids_from_extra(extra)
        if tagged:
            rows += [{"region": a, "delay": b, "category": c, "alphas": 1} for a, b, c in set(tagged)]
            continue
        key = (r.region, int(r.delay or 1))
        if key not in maps:
            try:
                f = catalog.fields(r.region, None, key[1], enrich=False)
                maps[key] = dict(zip(f["id"], f["category"])) if not f.empty else {}
            except Exception:  # noqa: BLE001
                maps[key] = {}
        cats = {_norm_cat(maps[key][x]) for x in r.fields if x in maps[key] and x not in _GROUPING}
        if not cats:
            unmapped[f"{r.region} D{key[1]}"] += 1
            continue
        rows += [{"region": r.region, "delay": key[1], "category": c, "alphas": 1} for c in cats]
    for k, n in unmapped.items():
        notes.append(f"{n} alpha(s) in {k} could not be placed: download {k.split()[0]}'s field list on the "
                     f"Data tab (or BRAIN gave no Pyramid tags).")
    out = pd.DataFrame(rows, columns=["region", "delay", "category", "alphas"])
    if not out.empty:
        out = out.groupby(["region", "delay", "category"], as_index=False)["alphas"].sum()
    return out, notes


def osmosis_check(journal, regions: Optional[Sequence[str]] = None, min_alphas: int = 10,
                  min_scopes: int = 3) -> Tuple[pd.DataFrame, List[str]]:
    """Which region x delay scopes can carry an Osmosis allocation [BRAIN_RULES O2, O6].

    Valid allocation: >= 3 scopes, each exactly 100,000 points over >= 10 alphas (any submission date).
    Uses ACTIVE submitted alphas (decommissioned ones earn nothing). Turnover buckets follow BRAIN's tips:
    < 10%, 10-20%, > 20% (avoid > 20% unless the investability-constrained Sharpe holds).
    """
    df = account_alphas(journal)
    cols = ["scope", "alphas (active)", "eligible", "points (if BRAIN sent them)", "turnover <10%",
            "10-20%", ">20%", "median Sharpe"]
    if df.empty:
        return pd.DataFrame(columns=cols), ["Download your submitted alphas first (button above)."]
    df = df[df["status"].fillna("ACTIVE").str.upper() != "DECOMMISSIONED"]
    ex = _extra(df)
    pts = ex.map(lambda e: next((v for k, v in e.items() if "osmosis" in k.lower() and isinstance(v, (int, float))),
                                None))
    df = df.assign(points=pts)
    rows = []
    for (reg, d), g in df.groupby([df["region"], df["delay"].fillna(1).astype(int)]):
        if regions and reg not in regions:
            continue
        t = pd.to_numeric(g["turnover"], errors="coerce")
        p = pd.to_numeric(g["points"], errors="coerce")
        rows.append({"scope": f"{reg} / D{d}", "alphas (active)": int(len(g)), "eligible": len(g) >= min_alphas,
                     "points (if BRAIN sent them)": int(p.sum()) if p.notna().any() else None,
                     "turnover <10%": int((t < 0.10).sum()), "10-20%": int(((t >= 0.10) & (t <= 0.20)).sum()),
                     ">20%": int((t > 0.20).sum()),
                     "median Sharpe": round(float(pd.to_numeric(g["sharpe"], errors="coerce").median()), 2)})
    out = pd.DataFrame(rows, columns=cols).sort_values("alphas (active)", ascending=False).reset_index(drop=True)
    n_ok = int(out["eligible"].sum()) if len(out) else 0
    notes = [f"{n_ok} scope(s) have >= {min_alphas} active alphas; Osmosis needs at least {min_scopes}."]
    if n_ok < min_scopes and len(out):
        short = out[~out["eligible"]].head(4)
        notes.append("Closest to eligible: " + ", ".join(f"{r.scope} needs {min_alphas - r._2} more"
                                                         for r in short.itertuples()) + ".")
    bad = out[out["points (if BRAIN sent them)"].notna() & (out["points (if BRAIN sent them)"] != 100_000)]
    for r in bad.itertuples():
        notes.append(f"{r.scope}: {int(r._4):,} points - each scope must total exactly 100,000 "
                     f"(BRAIN's 'Osmosis Scale' button on Alphas > Submitted fixes it).")
    return out, notes
