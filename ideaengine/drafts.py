"""Phase 3: hypothesis-card drafts - written in the cockpit or pasted from the Claude Projects team.

A draft IS a HYPOLAB card (same YAML, no second format). This module keeps drafts in ideas.sqlite, checks
them without simulating anything, and on approval appends them to ~/.hypolab/library/my_cards.yaml.

States (design doc): draft -> checked -> approved, or binned at any point (the reason is kept).
  draft     saved, but a check still fails (or it was never checked)
  checked   every check passes: the YAML builds, the linter accepts every rung, the concepts exist
  approved  appended to my_cards.yaml; HYPOLAB loads it with source "mine"
  binned    set aside with a reason; restore puts it back to draft

What the checks do NOT do: choose field ids (the binder does, per region), simulate, or approve.
"""
from __future__ import annotations

import copy
import datetime as dt
import difflib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
import yaml

from hypolab import config
from hypolab import hypotheses as hyp
from hypolab.catalog import CATEGORY_NAMES
from hypolab.concepts import CONCEPTS
from hypolab.ideas import STANDARD_PV, bind_role, build_card
from hypolab.linter import Linter
from hypolab.operators import STANDARD_GROUPS

STATES = ("draft", "checked", "approved", "binned")
HORIZONS = ("fast", "medium", "slow")
REQUIRED = ("id", "title", "category", "family", "horizon", "strength", "sign", "story", "why_persists",
            "references", "roles", "ladder", "settings", "expected_turnover")
KEY_ORDER = REQUIRED[:6] + ("beginner",) + REQUIRED[6:] + ("watch_out",)
ID_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
FAMILY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
NEUTRALIZATIONS = {"NONE", "MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY", "COUNTRY", "STATISTICAL", "CROWDING",
                   "FAST", "SLOW", "SLOW_AND_FAST", "REVERSION_AND_MOMENTUM"}
MAX_RUNGS = 3
MY_CARDS = "my_cards.yaml"
BIN_REASONS = ["weak story - I don't believe it", "duplicate of another card", "known factor in disguise",
               "family is a dead end", "data missing in my regions", "Critic said bin"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY, yaml TEXT, state TEXT, source TEXT DEFAULT '', reason TEXT DEFAULT '',
  verdict TEXT DEFAULT '', decision TEXT DEFAULT '', title TEXT DEFAULT '', family TEXT DEFAULT '',
  created REAL, updated REAL);
"""


def template() -> dict:
    """A blank card to start from (every required field present, sensible defaults)."""
    return {
        "id": "IE_", "title": "", "category": "auto", "family": "", "horizon": "medium", "strength": 2,
        "sign": "+1", "story": "", "why_persists": "", "references": [], "roles": {},
        "ladder": [{"name": "core", "expr": "", "teaches": ""}],
        "settings": {"neutralization": "SUBINDUSTRY", "decay": 0, "truncation": 0.08},
        "expected_turnover": [0.02, 0.2], "watch_out": [],
    }


# --------------------------------------------------------------------------------------------- YAML in and out
class _Folded(str):
    pass


class _Flow(dict):
    pass


class _FlowList(list):
    pass


class _Quoted(str):
    pass


class _Dumper(yaml.SafeDumper):
    pass


_Dumper.add_representer(_Folded, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", str(s), style=">"))
_Dumper.add_representer(_Flow, lambda d, m: d.represent_mapping("tag:yaml.org,2002:map", m.items(), flow_style=True))
_Dumper.add_representer(_Quoted, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", str(s), style='"'))
_Dumper.add_representer(_FlowList, lambda d, s: d.represent_sequence("tag:yaml.org,2002:seq", s, flow_style=True))


def _ordered(card: dict) -> dict:
    out = {k: card[k] for k in KEY_ORDER if k in card}
    out.update({k: v for k, v in card.items() if k not in out})
    return out


def card_yaml(card: dict, source: str = "") -> str:
    """One card as a YAML list item in the library's style (folded story, flow settings), with `# from:`."""
    c = _ordered(copy.deepcopy(card))
    for k in ("story", "why_persists"):
        if isinstance(c.get(k), str) and c[k].strip():
            c[k] = _Folded(" ".join(c[k].split()) + "\n")
    if isinstance(c.get("settings"), dict):
        c["settings"] = _Flow(c["settings"])
    if isinstance(c.get("expected_turnover"), list):
        c["expected_turnover"] = _FlowList(c["expected_turnover"])
    if isinstance(c.get("roles"), dict):
        c["roles"] = {k: (_Flow(v) if isinstance(v, dict) else v) for k, v in c["roles"].items()}
    if isinstance(c.get("ladder"), list):
        # quoted like the library when it fits on one line; a long one stays plain (PyYAML would break a
        # long quoted string with backslashes)
        c["ladder"] = [{**s, "expr": _Quoted(s["expr"])} if isinstance(s, dict) and isinstance(s.get("expr"), str)
                       and len(s["expr"]) <= 96 else s for s in c["ladder"]]
    text = yaml.dump([c], Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=110, default_flow_style=False)
    head = f"# from: {source.strip()}\n" if source and source.strip() else ""
    return head + text


@dataclass
class Parsed:
    card: Optional[dict]
    source: str = ""
    errors: List[str] = field(default_factory=list)


_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*$", re.M)


def _strip_fences(text: str) -> str:
    """Accept a card pasted with its Markdown code fence (Claude often wraps YAML in ```yaml ... ```)."""
    if "```" not in text:
        return text
    blocks = re.findall(r"```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    return "\n".join(blocks) if blocks else _FENCE.sub("", text)


def parse_cards(text: str) -> List[Parsed]:
    """Cards from pasted text: one card or a list, with optional `# from:` lines and code fences.

    Returns one Parsed per card (or one with errors). A Critic VERDICT or a Reviewer PLAN pasted here by
    mistake is recognised and named."""
    text = (text or "").strip()
    if not text:
        return [Parsed(None, errors=["Nothing pasted."])]
    sources = re.findall(r"(?mi)^\s*#\s*from:\s*(.+?)\s*$", text)
    body = _strip_fences(text)
    try:
        raw = yaml.safe_load(body)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        return [Parsed(None, errors=[f"Not valid YAML{where}: {getattr(e, 'problem', None) or e}. "
                                     "Indentation must use spaces; quote expressions that contain ': '."])]
    if isinstance(raw, dict) and "verdict" in raw:
        return [Parsed(None, errors=["This is a Critic VERDICT, not a card: paste it in the verdict box."])]
    if isinstance(raw, dict) and "plan" in raw:
        return [Parsed(None, errors=["This is a Reviewer PLAN, not a card: paste it on the Week tab."])]
    if isinstance(raw, dict) and "card" in raw and isinstance(raw["card"], dict):
        raw = raw["card"]
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for i, c in enumerate(items):
        src = sources[i] if i < len(sources) else (sources[0] if len(sources) == 1 else "")
        if not isinstance(c, dict) or "id" not in c:
            out.append(Parsed(None, src, [f"Item {i + 1} is not a card (a card is a mapping with an `id:`)."]))
        else:
            out.append(Parsed(c, src))
    return out or [Parsed(None, errors=["No card found in the pasted text."])]


def library_raw() -> Dict[str, Tuple[dict, str]]:
    """Every card in the library as the raw YAML mapping (id -> (mapping, source)), for 'copy a card'."""
    out: Dict[str, Tuple[dict, str]] = {}
    files = [(config.LIBRARY_DIR / "hypotheses.yaml", "library")]
    folder = hyp.user_library_dir()
    if folder.exists():
        files += [(f, "mine") for f in sorted(folder.glob("*.yaml"))]
    for f, src in files:
        try:
            items = yaml.safe_load(f.read_text()) or []
        except Exception:  # noqa: BLE001 - a broken user file is reported by load_library, not here
            continue
        for c in items if isinstance(items, list) else []:
            if isinstance(c, dict) and "id" in c and c["id"] not in out:
                out[c["id"]] = (c, src)
    return out


def copy_of(card_id: str, new_id: Optional[str] = None, taken: Sequence[str] = ()) -> dict:
    """A built-in (or approved) card copied as a new draft: a free id (IE_<id>_V2, _V3 ...), same everything else."""
    raw = library_raw()
    if card_id not in raw:
        raise KeyError(f"no card {card_id!r} in the library")
    c = copy.deepcopy(raw[card_id][0])
    c.pop("beginner", None)
    if new_id:
        c["id"] = new_id
        return c
    base = re.sub(r"_V\d+$", "", re.sub(r"^IE_", "", card_id))
    used = set(raw) | set(taken)
    n = 2
    while f"IE_{base}_V{n}" in used:
        n += 1
    c["id"] = f"IE_{base}_V{n}"
    return c


# ------------------------------------------------------------------------------------------- the form <-> card
ROLE_FORM_KEYS = ("concept", "optional", "note")
NO_CONCEPT = "(none)"
RUNG_FORM_KEYS = ("name", "expr", "teaches")
FORM_ROLES, FORM_RUNGS = 4, 3


def _lines(x) -> str:
    return "\n".join(str(i) for i in x) if isinstance(x, list) else str(x or "")


def form_defaults(card: dict) -> dict:
    """The cockpit form's starting values for a card (any extra keys stay in the card and are merged back)."""
    c = card or {}
    roles = c.get("roles") if isinstance(c.get("roles"), dict) else {}
    lad = c.get("ladder") if isinstance(c.get("ladder"), list) else []
    st = c.get("settings") if isinstance(c.get("settings"), dict) else {}
    et = c.get("expected_turnover") if isinstance(c.get("expected_turnover"), list) else [0.02, 0.2]
    role_rows = []
    for name, spec in roles.items():
        spec = {"concept": spec} if isinstance(spec, str) else (spec or {})
        role_rows.append({"name": str(name), "concept": str(spec.get("concept", "") or ""),
                          "optional": bool(spec.get("optional", False)), "note": str(spec.get("note", "") or "")})
    while len(role_rows) < FORM_ROLES:
        role_rows.append({"name": "", "concept": "", "optional": False, "note": ""})
    rungs = [{"name": str((s or {}).get("name", "") or ""), "expr": str((s or {}).get("expr", "") or ""),
              "teaches": " ".join(str((s or {}).get("teaches", "") or "").split())} for s in lad]
    while len(rungs) < FORM_RUNGS:
        rungs.append({"name": "", "expr": "", "teaches": ""})
    try:
        strength = int(c.get("strength", 2))
    except (TypeError, ValueError):
        strength = 2
    num = lambda x, d: _num(x) if _num(x) is not None else d  # noqa: E731
    return {
        "id": str(c.get("id", "") or ""), "title": str(c.get("title", "") or ""),
        "family": str(c.get("family", "") or ""), "category": str(c.get("category", "auto") or "auto"),
        "horizon": str(c.get("horizon", "medium") or "medium"), "strength": strength,
        "sign": str(c.get("sign", "+1") or "+1"),
        "story": " ".join(str(c.get("story", "") or "").split()),
        "why_persists": " ".join(str(c.get("why_persists", "") or "").split()),
        "references": _lines(c.get("references") or []), "watch_out": _lines(c.get("watch_out") or []),
        "roles": role_rows, "rungs": rungs,
        "neutralization": str(st.get("neutralization", "SUBINDUSTRY") or "SUBINDUSTRY"),
        "decay": int(num(st.get("decay"), 0)), "truncation": float(num(st.get("truncation"), 0.08)),
        "turnover_low": float(num(et[0] if et else None, 0.02)),
        "turnover_high": float(num(et[1] if len(et) > 1 else None, 0.2)),
    }


def card_from_form(v: dict, base: Optional[dict] = None) -> dict:
    """Form values -> card. Keys the form does not show (role categories / pair_with / type / min_coverage,
    a rung's `when`, settings like max_trade, beginner ...) are kept from `base`."""
    base = base or {}
    split = lambda t: [x.strip() for x in str(t or "").splitlines() if x.strip()]  # noqa: E731
    card = {k: val for k, val in base.items() if k not in REQUIRED and k != "watch_out"}
    base_roles = base.get("roles") if isinstance(base.get("roles"), dict) else {}
    roles = {}
    for r in v.get("roles") or []:
        name = str(r.get("name") or "").strip()
        concept = str(r.get("concept") or "").strip()
        concept = "" if concept == NO_CONCEPT else concept
        if not name and not concept:
            continue
        old = base_roles.get(name)
        spec = {k: x for k, x in old.items() if k not in ROLE_FORM_KEYS} if isinstance(old, dict) else {}
        spec = {"concept": concept, **({"optional": True} if r.get("optional") else {}),
                **({"note": str(r["note"]).strip()} if str(r.get("note") or "").strip() else {}), **spec}
        roles[name or "role"] = spec
    base_lad = base.get("ladder") if isinstance(base.get("ladder"), list) else []
    ladder = []
    for i, s in enumerate(v.get("rungs") or []):
        name, expr = str(s.get("name") or "").strip(), " ".join(str(s.get("expr") or "").split())
        if not name and not expr:
            continue
        rung = {"name": name, "expr": expr, "teaches": " ".join(str(s.get("teaches") or "").split())}
        old = base_lad[i] if i < len(base_lad) and isinstance(base_lad[i], dict) else {}
        rung.update({k: x for k, x in old.items() if k not in RUNG_FORM_KEYS})
        ladder.append(rung)
    st = dict(base.get("settings") or {}) if isinstance(base.get("settings"), dict) else {}
    st.update({"neutralization": v.get("neutralization") or "SUBINDUSTRY", "decay": int(v.get("decay") or 0),
               "truncation": float(v.get("truncation") or 0.08)})
    try:
        strength = int(v.get("strength") or 2)
    except (TypeError, ValueError):
        strength = v.get("strength")
    card.update({
        "id": str(v.get("id") or "").strip(), "title": " ".join(str(v.get("title") or "").split()),
        "category": v.get("category") or "auto", "family": str(v.get("family") or "").strip(),
        "horizon": v.get("horizon") or "medium", "strength": strength, "sign": str(v.get("sign") or "").strip(),
        "story": " ".join(str(v.get("story") or "").split()),
        "why_persists": " ".join(str(v.get("why_persists") or "").split()),
        "references": split(v.get("references")), "roles": roles, "ladder": ladder, "settings": st,
        "expected_turnover": [round(float(v.get("turnover_low") or 0), 4), round(float(v.get("turnover_high") or 0), 4)],
    })
    wo = split(v.get("watch_out"))
    if wo:
        card["watch_out"] = wo
    return _ordered(card)


# ----------------------------------------------------------------------------------------------------- checks
@dataclass
class Check:
    level: str          # error | warn | info
    where: str
    message: str


@dataclass
class CheckReport:
    card_id: str
    checks: List[Check] = field(default_factory=list)
    hypothesis: Optional[hyp.Hypothesis] = None
    idea: object = None                 # IdeaCard from the dry-run binding, or None
    region: str = ""
    universe: str = ""
    delay: int = 1
    bindings: List[dict] = field(default_factory=list)
    rungs: List[dict] = field(default_factory=list)
    family_cards: List[str] = field(default_factory=list)
    family_journal: Dict[str, object] = field(default_factory=dict)

    def add(self, level: str, where: str, message: str):
        self.checks.append(Check(level, where, message))

    @property
    def errors(self) -> List[Check]:
        return [c for c in self.checks if c.level == "error"]

    @property
    def warnings(self) -> List[Check]:
        return [c for c in self.checks if c.level == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def state(self) -> str:
        return "checked" if self.ok else "draft"

    def table(self) -> pd.DataFrame:
        order = {"error": 0, "warn": 1, "info": 2}
        rows = sorted(self.checks, key=lambda c: order.get(c.level, 3))
        return pd.DataFrame([{"level": c.level.upper(), "where": c.where, "check": c.message} for c in rows],
                            columns=["level", "where", "check"])

    def summary(self) -> str:
        e, w = len(self.errors), len(self.warnings)
        if e:
            return f"{e} error{'s' * (e != 1)} to fix" + (f", {w} warning{'s' * (w != 1)}" if w else "")
        bound = "binds" if self.idea is not None else "does not bind"
        return (f"All checks pass ({w} warning{'s' * (w != 1)}); {bound} in {self.region} {self.universe} "
                f"D{self.delay}" if self.region else f"All checks pass ({w} warning{'s' * (w != 1)})")

    def dry_run_lines(self) -> List[str]:
        """The dry-run binding as plain lines (used by 'Copy for Critic')."""
        if not self.region:
            return ["no dry run (no field list)"]
        out = [f"dry run in {self.region} {self.universe} D{self.delay}: "
               + ("binds" if self.idea is not None else "does NOT bind")]
        for b in self.bindings:
            out.append(f"role {b['role']} ({b['concept']}) -> {b['field']} | dataset {b['dataset']} | "
                       f"coverage {b['coverage']} | alphas on it {b['alphas']}")
        for r in self.rungs:
            out.append(f"rung {r['rung']}: {r['is_test'] or '-'} | lint {r['lint']}")
        if self.family_cards:
            out.append(f"same family in the library: {', '.join(self.family_cards)}")
        fj = self.family_journal
        if fj.get("tries"):
            out.append(f"journal, family {fj['family']}: {fj['tries']} tries, {fj['signal']} with signal "
                       f"(WEAK or better), best Sharpe {fj['best']}" + (" - DEAD END" if fj.get("dead_end") else ""))
        return out


def _num(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _structure(c: dict, rep: CheckReport, taken_ids: Sequence[str]) -> None:
    for k in REQUIRED:
        if k not in c or c[k] is None or (isinstance(c[k], str) and not c[k].strip()):
            if k == "roles" and c.get("roles") == {}:
                continue
            rep.add("error" if k not in ("references",) else "warn", k, "missing" if k not in c else "empty")
    cid = str(c.get("id", ""))
    if cid and not ID_RE.match(cid):
        rep.add("error", "id", "use capitals, digits and _ only (e.g. IE_TAX_GAP), at least 3 characters")
    elif cid in taken_ids:
        rep.add("error", "id", f"{cid} already exists in the library - pick a new id (built-in and approved ids win)")
    elif cid and not cid.startswith("IE_"):
        rep.add("warn", "id", "cards from the Idea Engine start with IE_ so the journal shows where they came from")
    if c.get("category") not in (None, "auto") and c.get("category") not in CATEGORY_NAMES:
        rep.add("error", "category", f"{c.get('category')!r} is not a category; use auto or one of "
                                     f"{', '.join(CATEGORY_NAMES)}")
    fam = c.get("family")
    if fam and not FAMILY_RE.match(str(fam)):
        rep.add("error", "family", "snake_case, e.g. tax_avoidance")
    if c.get("horizon") and c.get("horizon") not in HORIZONS:
        rep.add("error", "horizon", f"one of {', '.join(HORIZONS)}")
    s = _num(c.get("strength"))
    if c.get("strength") is not None and (s is None or s not in (1, 2, 3)):
        rep.add("error", "strength", "1 (speculative), 2 (solid in papers) or 3 (replicated in many markets)")
    for k, low in (("story", 80), ("why_persists", 50)):
        v = " ".join(str(c.get(k) or "").split())
        if v and len(v) < low:
            rep.add("warn", k, "very short: say who makes the mistake and why prices adjust slowly"
                    if k == "story" else "very short: who is on the other side, and what stops them arbitraging it")
    refs = c.get("references")
    if refs is not None and not isinstance(refs, list):
        rep.add("error", "references", "a list, one source per line")
    et = c.get("expected_turnover")
    if et is not None:
        if not (isinstance(et, list) and len(et) == 2 and all(_num(x) is not None for x in et)):
            rep.add("error", "expected_turnover", "two fractions [low, high], e.g. [0.02, 0.15]")
        else:
            lo, hi = float(et[0]), float(et[1])
            if not (0 <= lo <= hi <= 1.5):
                rep.add("error", "expected_turnover", "fractions with low <= high, e.g. [0.02, 0.15] (not percent)")
    st = c.get("settings")
    if st is not None and not isinstance(st, dict):
        rep.add("error", "settings", "a mapping like {neutralization: SUBINDUSTRY, decay: 0, truncation: 0.08}")
    elif isinstance(st, dict):
        n = str(st.get("neutralization", "")).upper()
        if n and n not in NEUTRALIZATIONS:
            rep.add("warn", "settings", f"neutralization {n} is unusual; BRAIN offers e.g. SUBINDUSTRY, INDUSTRY, "
                                        "SECTOR, MARKET, STATISTICAL and risk sets (SLOW, FAST, SLOW_AND_FAST)")
        d = _num(st.get("decay", 0))
        if d is None or d < 0 or d > 512 or d != int(d):
            rep.add("error", "settings", "decay is a whole number of days, 0-512")
        t = _num(st.get("truncation", 0.08))
        if t is None or not (0 < t <= 1):
            rep.add("error", "settings", "truncation is a fraction, e.g. 0.08")
        elif t > 0.15:
            rep.add("warn", "settings", f"truncation {t} lets one stock hold a big weight; 0.05-0.1 is usual")


def _roles(c: dict, rep: CheckReport) -> None:
    roles = c.get("roles")
    if roles in (None, {}):
        return
    if not isinstance(roles, dict):
        rep.add("error", "roles", "a mapping: role name -> {concept: <name>} ({} when only price/volume is used)")
        return
    for name, spec in roles.items():
        where = f"roles.{name}"
        if not ROLE_RE.match(str(name)):
            rep.add("error", where, "role names are lower_snake_case, e.g. tax")
        concept = spec if isinstance(spec, str) else (spec or {}).get("concept") if isinstance(spec, dict) else None
        if not concept:
            rep.add("error", where, "needs a concept")
            continue
        if concept not in CONCEPTS:
            close = difflib.get_close_matches(str(concept), list(CONCEPTS), n=3, cutoff=0.5)
            rep.add("error", where, f"concept {concept!r} does not exist" +
                    (f" - did you mean {', '.join(close)}?" if close else " - see the Data tab's concept list"))
        if isinstance(spec, dict) and spec.get("pair_with") and spec["pair_with"] not in roles:
            rep.add("error", where, f"pair_with {spec['pair_with']!r} is not a role of this card")
        if isinstance(spec, dict) and spec.get("type") not in (None, "GROUP"):
            rep.add("error", where, "type is only used for GROUP roles")


def _ladder(c: dict, rep: CheckReport) -> None:
    lad = c.get("ladder")
    if not isinstance(lad, list) or not lad:
        rep.add("error", "ladder", "at least one rung: {name, expr, teaches}")
        return
    if len(lad) > MAX_RUNGS:
        rep.add("warn", "ladder", f"{len(lad)} rungs: keep 1-{MAX_RUNGS}, simplest first (more rungs = more tries "
                                  "counted against the idea)")
    names = set()
    roles = c.get("roles") if isinstance(c.get("roles"), dict) else {}
    used = set()
    linter = Linter()
    for i, s in enumerate(lad, 1):
        where = f"rung {i}"
        if not isinstance(s, dict) or not str(s.get("expr") or "").strip():
            rep.add("error", where, "needs an expr")
            continue
        nm = str(s.get("name") or "").strip()
        if not nm:
            rep.add("error", where, "needs a name (e.g. core)")
        elif nm in names:
            rep.add("error", where, f"two rungs are called {nm!r}")
        names.add(nm)
        where = f"rung {i} ({nm or '?'})"
        if not str(s.get("teaches") or "").strip():
            rep.add("warn", where, "teaches is empty: say what this rung tests that the previous one did not")
        expr = str(s["expr"])
        used |= {m.group(2) for m in hyp.PLACEHOLDER.finditer(expr)}
        if re.search(r"\{(?!dir:)[^}]*[^a-zA-Z0-9_}][^}]*\}", expr):
            rep.add("error", where, "a placeholder is written {role} or {dir:role}, letters/digits/_ only")
        dummy = hyp.PLACEHOLDER.sub(lambda m: "1" if m.group(1) else f"field_{m.group(2)}", expr)
        try:
            res = linter.lint(dummy)
        except Exception:  # noqa: BLE001 - syntax errors are reported by validate_library
            continue
        for issue in res.issues:
            if issue.severity != "error":
                rep.add("warn", where, f"{issue.code}: {issue.message}")
        fixed = [f for f in res.fields if not f.startswith("field_") and f not in STANDARD_PV
                 and f not in STANDARD_GROUPS]
        if fixed:
            rep.add("warn", where, f"field id(s) written directly: {', '.join(fixed)}. The card then only works "
                                   "where that field exists; a role with a concept lets HYPOLAB pick per region")
    for r in sorted(set(roles) - used):
        rep.add("warn", f"roles.{r}", "this role is not used by any rung")


def family_journal(journal, family: str, min_tries: int = 5) -> Dict[str, object]:
    """Live tries on a family (explore + boost), how many showed signal, best Sharpe; dead end per 07_dead_ends."""
    out = {"family": family, "tries": 0, "signal": 0, "best": None, "dead_end": False}
    if journal is None or not family:
        return out
    q = """SELECT COUNT(*), SUM(CASE WHEN e.verdict IN ('PASS','NEAR','WEAK') THEN 1 ELSE 0 END), MAX(e.sharpe)
           FROM experiments e JOIN ideas i ON e.idea_id = i.id
           WHERE i.family = ? AND e.purpose IN ('explore','boost')"""
    try:
        n, sig, best = journal.db.execute(q, (family,)).fetchone()
    except Exception:  # noqa: BLE001
        return out
    out.update(tries=int(n or 0), signal=int(sig or 0), best=None if best is None else round(float(best), 2))
    out["dead_end"] = out["tries"] >= min_tries and not out["signal"]
    return out


def check_card(card: dict, catalog=None, region: Optional[str] = None, universe: Optional[str] = None,
               delay: int = 1, journal=None, library: Optional[List[hyp.Hypothesis]] = None,
               allow_id: Optional[str] = None) -> CheckReport:
    """Every check that needs no simulation. `allow_id`: an id that may already exist (re-checking an approved card)."""
    c = card if isinstance(card, dict) else {}
    rep = CheckReport(card_id=str(c.get("id", "")))
    lib = library if library is not None else hyp.load_library()
    taken = [h.id for h in lib if h.id != allow_id]
    _structure(c, rep, taken)
    _roles(c, rep)
    _ladder(c, rep)
    if any(k not in c for k in ("id", "title", "family", "ladder")) or not isinstance(c.get("ladder"), list):
        return rep
    try:
        h = hyp._hypothesis(c, "draft")
    except Exception as e:  # noqa: BLE001
        rep.add("error", "card", f"HYPOLAB cannot build this card: {type(e).__name__}: {e}")
        return rep
    rep.hypothesis = h
    seen = {(x.where, x.message) for x in rep.checks}
    pos = {s.name: i for i, s in enumerate(h.ladder, 1)}
    for p in hyp.validate_library([h]):
        where, _, msg = p.partition(": ")
        name = where.split("/", 1)[1] if "/" in where else ""
        if "empty expression" in msg:
            continue                                   # already reported as "needs an expr"
        where = f"rung {pos[name]} ({name or '?'})" if name in pos else "ladder"
        if (where, msg) not in seen:
            rep.add("error", where, msg)
    # family overlap with the library, and the journal's record for the family
    rep.family_cards = [x.id for x in lib if x.family == h.family and x.id != h.id]
    if rep.family_cards:
        rep.add("info", "family", f"same family as {', '.join(rep.family_cards[:6])}: alphas will correlate; "
                                  "say what is new (data, mechanism or horizon)")
    concepts = {r.concept for r in h.roles.values()}
    if concepts:
        same = [x.id for x in lib if x.id != h.id and {r.concept for r in x.roles.values()} == concepts]
        if same:
            rep.add("warn", "roles", f"uses exactly the same data concepts as {', '.join(same[:5])} - "
                                     "possible duplicate")
    fj = family_journal(journal, h.family)
    rep.family_journal = fj
    if fj["dead_end"]:
        rep.add("warn", "family", f"dead end in your journal: {fj['tries']} tries, none WEAK or better "
                                  f"(best Sharpe {fj['best']}). It needs genuinely new data or mechanism")
    elif fj["tries"]:
        rep.add("info", "family", f"journal: {fj['tries']} tries in this family, {fj['signal']} with signal, "
                                  f"best Sharpe {fj['best']}")
    if catalog is not None and region and rep.ok:
        _dry_run(h, catalog, region, universe, delay, rep)
    return rep


def _dry_run(h: hyp.Hypothesis, catalog, region: str, universe: Optional[str], delay: int, rep: CheckReport):
    universe = universe or config.REGION_DEFAULTS.get(region, {}).get("universe") or "TOP3000"
    rep.region, rep.universe, rep.delay = region, universe, delay
    if h.roles and not catalog.has_context(region, universe, delay):
        rep.add("info", "dry run", f"no field list for {region} {universe} D{delay}: download it on the Cards or "
                                   "Data tab to see which fields the roles bind to")
    try:
        idea = build_card(h, catalog, region, universe, delay)
    except Exception as e:  # noqa: BLE001
        rep.add("warn", "dry run", f"binding failed: {type(e).__name__}: {e}")
        return
    rep.idea = idea
    if idea is not None:
        for r in idea.hypothesis.roles.values():
            b = idea.bindings.get(r.name)
            if b is None:
                rep.bindings.append({"role": r.name, "concept": r.concept, "field": "(optional, not found)",
                                     "dataset": "", "coverage": "", "alphas": "", "why": ""})
                continue
            ac = b.alpha_count
            rep.bindings.append({"role": r.name, "concept": r.concept,
                                 "field": b.field_id + (" (VECTOR)" if b.type == "VECTOR" else ""),
                                 "dataset": b.dataset, "coverage": "?" if b.coverage is None else f"{b.coverage:.0%}",
                                 "alphas": "?" if ac is None or ac != ac else str(int(ac)), "why": b.reason})
        for s in idea.steps:
            rep.rungs.append({"rung": s.name, "is_test": s.is_test, "lint": "ok" if s.lint.ok else "BLOCKED",
                              "expression": s.expression})
        if len(idea.steps) < len(h.ladder):
            rep.add("info", "dry run", f"{len(h.ladder) - len(idea.steps)} rung(s) skipped in {region} (their "
                                       "`when` condition or an optional role)")
        if any(r["is_test"].startswith("single dataset") for r in rep.rungs):
            rep.add("info", "dry run", "single-dataset rung(s): BRAIN asks a higher 2Y Sharpe for them "
                                       "(2.38 at D1, BRAIN_RULES T1)")
        return
    # explain why it does not bind
    missing = []
    for r in h.roles.values():
        b = bind_role(catalog, r, region, universe, delay)
        if b is None and not r.optional:
            missing.append(f"{r.name} ({r.concept})")
    if missing:
        rep.add("warn", "dry run", f"does not bind in {region} {universe} D{delay}: no field for "
                                   f"{', '.join(missing)}. Try another region, or a concept with data here")
    else:
        rep.add("warn", "dry run", f"the roles bind in {region}, but the first rung is blocked by the region's "
                                   "linter (an operator or field not available there)")


# ------------------------------------------------------------------------------------------------ the store
def _now() -> float:
    return time.time()


class Drafts:
    """Drafts in ~/.hypolab/ideas.sqlite (the Idea Engine is its only writer)."""

    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.executescript(_SCHEMA)
        self.db.commit()

    def save(self, card: dict, source: str = "", state: Optional[str] = None, report: Optional[CheckReport] = None,
             old_id: Optional[str] = None) -> str:
        """Create or update a draft. State: from the report (checked/draft) unless given.
        `old_id`: the draft was renamed in the form - the old row is moved to the new id."""
        cid = str(card.get("id", "")).strip()
        if not cid:
            raise ValueError("a draft needs an id")
        if state is None:
            state = report.state if report is not None else "draft"
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        cur = self.get(cid)
        if cur and cur["state"] == "approved":
            raise ValueError(f"{cid} is already approved; copy it to a new id to change it")
        if old_id and old_id != cid and self.get(old_id) and not cur:
            self.db.execute("UPDATE drafts SET id=? WHERE id=? AND state != 'approved'", (cid, old_id))
            cur = self.get(cid)
        created = cur["created"] if cur else _now()
        keep = cur or {}
        self.db.execute(
            "INSERT OR REPLACE INTO drafts (id, yaml, state, source, reason, verdict, decision, title, family, "
            "created, updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, card_yaml(card), state, source or keep.get("source", ""), keep.get("reason", ""), keep.get("verdict", ""), keep.get("decision", ""),
             str(card.get("title", "")), str(card.get("family", "")), created, _now()))
        self.db.commit()
        return cid

    def get(self, cid: str) -> Optional[dict]:
        cur = self.db.execute("SELECT * FROM drafts WHERE id=?", (cid,))
        row = cur.fetchone()
        if row is None:
            return None
        d = dict(zip([c[0] for c in cur.description], row))
        try:
            items = yaml.safe_load(d["yaml"]) or []
            d["card"] = items[0] if isinstance(items, list) and items else None
        except yaml.YAMLError:
            d["card"] = None
        return d

    def list(self, states: Optional[Sequence[str]] = None) -> pd.DataFrame:
        q, args = ("SELECT id, title, family, state, decision AS critic, source, reason, updated FROM drafts", [])
        if states:
            q += f" WHERE state IN ({','.join('?' * len(states))})"
            args = list(states)
        df = pd.read_sql_query(q + " ORDER BY updated DESC", self.db, params=args)
        if not df.empty:
            df["updated"] = pd.to_datetime(df["updated"], unit="s").dt.strftime("%Y-%m-%d %H:%M")
        return df

    def ids(self) -> List[str]:
        return [r[0] for r in self.db.execute("SELECT id FROM drafts")]

    def counts(self) -> Dict[str, int]:
        rows = self.db.execute("SELECT state, COUNT(*) FROM drafts GROUP BY state").fetchall()
        return {s: int(n) for s, n in rows}

    def set_state(self, cid: str, state: str, reason: Optional[str] = None) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        if self.get(cid) is None:
            raise KeyError(cid)
        if reason is None:
            self.db.execute("UPDATE drafts SET state=?, updated=? WHERE id=?", (state, _now(), cid))
        else:
            self.db.execute("UPDATE drafts SET state=?, reason=?, updated=? WHERE id=?", (state, reason, _now(), cid))
        self.db.commit()

    def bin(self, cid: str, reason: str) -> None:
        d = self.get(cid)
        if d is None:
            raise KeyError(cid)
        if d["state"] == "approved":
            raise ValueError(f"{cid} is approved: bin it on the Cards tab instead (that hides it everywhere)")
        self.set_state(cid, "binned", reason or "no reason given")

    def restore(self, cid: str) -> None:
        self.set_state(cid, "draft")

    def delete(self, cid: str) -> None:
        self.db.execute("DELETE FROM drafts WHERE id=? AND state != 'approved'", (cid,))
        self.db.commit()

    # ------------------------------------------------------------------ Critic verdicts
    def attach_verdict(self, text: str, cid: Optional[str] = None) -> dict:
        """Store a Critic VERDICT on its draft. Returns the parsed verdict. The decision is advice: it never
        approves or bins by itself."""
        v = parse_verdict(text)
        vid = cid or v["id"]
        if v.get("id") and cid and v["id"] != cid:
            raise ValueError(f"the verdict is for {v['id']}, not {cid}")
        if self.get(vid) is None:
            raise KeyError(f"no draft {vid!r}: import the card first, then paste its verdict")
        self.db.execute("UPDATE drafts SET verdict=?, decision=?, updated=? WHERE id=?",
                        (yaml.safe_dump({"verdict": v}, sort_keys=False, allow_unicode=True), v["decision"], _now(),
                         vid))
        self.db.commit()
        return v

    # ------------------------------------------------------------------ approve
    def approve(self, cid: str, report: CheckReport) -> Path:
        d = self.get(cid)
        if d is None or d["card"] is None:
            raise KeyError(f"no draft {cid!r}")
        if not report.ok:
            raise ValueError(f"{cid} still has {len(report.errors)} error(s): fix them first")
        if report.card_id != cid:
            raise ValueError("the check report is for another card")
        path = append_to_my_cards(d["card"], d.get("source", ""))
        self.set_state(cid, "approved")
        return path


def parse_verdict(text: str) -> dict:
    body = _strip_fences(text or "")
    # the Critic adds up to five plain lines after the block: keep the YAML part only
    lines, keep = body.splitlines(), []
    started = False
    for ln in lines:
        if ln.strip().startswith("verdict:"):
            started = True
        if started:
            if ln.strip() and not ln.startswith((" ", "\t", "verdict:")) and keep:
                break
            keep.append(ln)
    try:
        raw = yaml.safe_load("\n".join(keep) if keep else body)
    except yaml.YAMLError as e:
        raise ValueError(f"not a VERDICT block (YAML error: {getattr(e, 'problem', e)})")
    if not isinstance(raw, dict) or not isinstance(raw.get("verdict"), dict):
        raise ValueError("expected a block starting with `verdict:` (the Critic's output)")
    v = raw["verdict"]
    dec = str(v.get("decision", "")).strip().lower()
    if dec not in ("keep", "rewrite", "bin"):
        raise ValueError(f"decision must be keep, rewrite or bin (got {v.get('decision')!r})")
    v["decision"] = dec
    v["id"] = str(v.get("id", "")).strip()
    return v


def verdict_markdown(verdict_yaml: str) -> str:
    try:
        v = (yaml.safe_load(verdict_yaml) or {}).get("verdict") or {}
    except yaml.YAMLError:
        return ""
    if not v:
        return ""
    sc = v.get("scores") or {}
    out = [f"**Critic: {str(v.get('decision', '')).upper()}** - {v.get('one_line', '')}",
           "Scores: " + ", ".join(f"{k} {sc[k]}" for k in sc) if sc else ""]
    for k, label in (("duplicate_of", "Duplicate of"), ("known_factor_in_disguise", "Known factor in disguise"),
                     ("most_likely_failure", "Most likely failure"), ("why_it_could_persist", "Why it could persist")):
        if v.get(k) not in (None, "", "null"):
            out.append(f"{label}: {v[k]}")
    fixes = v.get("fixes") or []
    if fixes:
        out.append("Fixes:\n" + "\n".join(f"- {f}" for f in fixes))
    return "\n\n".join(x for x in out if x)


def append_to_my_cards(card: dict, source: str = "") -> Path:
    """Append one card to ~/.hypolab/library/my_cards.yaml: atomic write, previous file kept as .bak.
    Refuses an id that already exists anywhere in the library, and anything that would not load back."""
    folder = config.ensure_home() / "library"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MY_CARDS
    lib_ids = {h.id for h in hyp.load_library()}
    if card.get("id") in lib_ids:
        raise ValueError(f"{card.get('id')} already exists in the library")
    old = path.read_text() if path.exists() else ""
    if old.strip():
        existing = yaml.safe_load(old)
        if existing is not None and not isinstance(existing, list):
            raise ValueError(f"{path} is not a list of cards; fix it by hand first (nothing was written)")
    header = "" if old.strip() else ("# Your own HYPOLAB cards. The cockpit's Drafts tab appends approved cards here.\n"
                                     "# Same format as hypolab/library/hypotheses.yaml.\n\n")
    stamp = f"# approved {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    new = (old.rstrip() + "\n\n" if old.strip() else header) + stamp + card_yaml(card, source)
    items = yaml.safe_load(new) or []
    ids = [c.get("id") for c in items]
    if len(ids) != len(set(ids)):
        raise ValueError("my_cards.yaml would contain a duplicate id (nothing was written)")
    for c in items:
        hyp._hypothesis(c, "mine")          # raises if any card would not load
    if path.exists():
        shutil.copy2(path, path.with_suffix(".yaml.bak"))
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(new)
    os.replace(tmp, path)
    return path


# -------------------------------------------------------------------------------------- hand-offs to the team
def critic_message(card: dict, report: Optional[CheckReport] = None, source: str = "") -> str:
    """'Copy for Critic': the card (valid YAML) plus HYPOLAB's dry-run binding as comment lines."""
    text = card_yaml(card, source)
    if report is not None:
        notes = ["", "# --- HYPOLAB checks (context for the Critic, not part of the card) ---",
                 f"# checks: {report.summary()}"]
        notes += [f"# {c.level}: {c.where}: {c.message}" for c in report.checks if c.level in ("error", "warn")]
        notes += [f"# {line}" for line in report.dry_run_lines()]
        text += "\n".join(notes) + "\n"
    return text


def digest(journal, store, week: str, today: Optional[dt.date] = None) -> str:
    """The Friday DIGEST for the Weekly Reviewer (format in claude_projects/README.md)."""
    from ideaengine import planner
    from ideaengine.views import VERDICT_ORDER
    start = planner.week_start(week)
    t0 = dt.datetime.combine(start, dt.time()).timestamp()
    t1 = t0 + 7 * 86400
    budget = int(config.settings().get("max_sims_per_idea", 10))
    plan = planner.propose(week, None, store.plan(week))
    lines = [f"### DIGEST {week} ({start:%a %d %b} - {start + dt.timedelta(days=6):%a %d %b %Y})", "",
             f"plan: region {plan['region']}, categories {', '.join(plan.get('categories') or []) or '-'}, "
             f"dataset focus {plan.get('dataset_focus') or '-'}, cards to approve {plan.get('card_target')}, "
             f"alphas to submit {plan.get('submit_target')}"
             + ("" if store.plan(week) else " (proposed, never saved)")]
    g = planner.goals_view(store, journal, today)
    if not g.empty:
        parts = []
        for r in g.itertuples(index=False):
            pace = f", needs {r.per_week_needed}/week" if r.per_week_needed == r.per_week_needed and \
                r.per_week_needed is not None else ""
            parts.append(f"{r.key} {r.now:g}/{r.bar:g}{pace}")
        lines.append(f"goals ({g['quarter'].iloc[0]}, {g['weeks_left'].iloc[0]} weeks left): " + "; ".join(parts))
    sub = planner.submission_status(store, journal, weekly_target=plan.get("submit_target"))
    prog = planner.week_progress(journal, week)
    lines.append(f"submissions: this week {prog['submitted']} (target {plan.get('submit_target')}), today "
                 f"{sub['submitted_today']}/{sub['cap']}, lifetime {sub['lifetime']}/{sub['unlock_at']}")
    ex = journal.experiments()
    if not ex.empty:
        ex = ex[(ex["created"] >= t0) & (ex["created"] < t1)]
    backends = ", ".join(f"{k} {v}" for k, v in ex["backend"].value_counts().items()) if not ex.empty else ""
    lines.append(f"simulations: {len(ex)} on {ex['idea_id'].nunique() if not ex.empty else 0} ideas"
                 + (f" ({backends})" if backends else ""))
    if not ex.empty:
        purp = ", ".join(f"{k} {v}" for k, v in ex["purpose"].value_counts().items())
        lines.append(f"by purpose: {purp}")
        v = ex["verdict"].replace("", "-").value_counts()
        order = [x for x in VERDICT_ORDER if x in v.index] + [x for x in v.index if x not in VERDICT_ORDER]
        lines.append("verdicts: " + ", ".join(f"{k} {int(v[k])}" for k in order))
        fails = ex["failed"].fillna("").str.split(",").explode().str.strip()
        fails = fails[fails != ""].value_counts().head(6)
        if not fails.empty:
            lines.append("failed checks: " + ", ".join(f"{k} {int(n)}" for k, n in fails.items()))
    # drafts
    try:
        dr = Drafts(store)
        rows = dr.db.execute("SELECT id, state, reason, decision FROM drafts WHERE updated>=? AND updated<?",
                             (t0, t1)).fetchall()
        app = [r[0] for r in rows if r[1] == "approved"]
        binned = [f"{r[0]} ({r[2]})" for r in rows if r[1] == "binned"]
        waiting = dr.counts()
        lines.append(f"cards: approved this week {len(app)}" + (f" ({', '.join(app)})" if app else "")
                     + f"; drafts waiting {waiting.get('draft', 0) + waiting.get('checked', 0)}"
                     + (f"; binned this week: {', '.join(binned)}" if binned else ""))
        crit = [r for r in rows if r[3]]
        if crit:
            lines.append("critic decisions this week: " + ", ".join(f"{r[0]} {r[3]}" for r in crit))
    except Exception:  # noqa: BLE001
        pass
    if not ex.empty:
        all_ex = journal.experiments()
        tries = all_ex[all_ex["purpose"].isin(["explore", "boost"])].groupby("idea_id").size()
        near = ex[ex["verdict"] == "NEAR"].sort_values("sharpe", ascending=False).drop_duplicates("idea_id")
        lines += ["", "near misses (NEAR):"] + ([
            f"- {r.idea_id} [{r.rung}]: Sharpe {_fmt(r.sharpe)}, fitness {_fmt(r.fitness)}, turnover "
            f"{_fmt(r.turnover)}, failed {r.failed or '-'}; {int(tries.get(r.idea_id, 0))} tries, "
            f"{max(0, budget - int(tries.get(r.idea_id, 0)))} left" for r in near.head(8).itertuples()] or ["- none"])
        inv = ex[ex["verdict"] == "INVERTED"].drop_duplicates("idea_id")
        lines += ["", "inverted (the sign looks wrong):"] + ([
            f"- {r.idea_id} [{r.rung}]: Sharpe {_fmt(r.sharpe)}" for r in inv.head(8).itertuples()] or ["- none"])
        at_budget = [i for i in ex["idea_id"].unique() if int(tries.get(i, 0)) >= budget]
        lines += ["", f"ideas at the trial budget ({budget}):"] + ([f"- {i}" for i in at_budget] or ["- none"])
        best = ex.dropna(subset=["sharpe"]).sort_values("sharpe", ascending=False).head(5)
        lines += ["", "best results this week:"] + ([
            f"- {r.idea_id} [{r.rung}] {r.verdict or '-'}: Sharpe {_fmt(r.sharpe)}, fitness {_fmt(r.fitness)}, "
            f"turnover {_fmt(r.turnover)}" for r in best.itertuples()] or ["- none"])
    les = journal.db.execute("SELECT idea_id, family, text FROM lessons WHERE created>=? AND created<? "
                             "ORDER BY created", (t0, t1)).fetchall()
    lines += ["", "lessons written this week:"] + ([
        f"- {t}" + (f" ({fam or idea})" if (fam or idea) else "") for idea, fam, t in les] or ["- none"])
    return "\n".join(lines) + "\n"


def _fmt(x, nd=2):
    return "-" if x is None or x != x else f"{float(x):.{nd}f}"


WEEK_RE = re.compile(r"^\d{4}-W\d{2}$")


def parse_plan(text: str, regions: Optional[Sequence[str]] = None) -> Tuple[Optional[dict], List[str]]:
    """A Weekly Reviewer PLAN -> (plan dict for IdeaStore.save_plan, problems). Problems that block are
    prefixed 'error:'; others are notes about what was adjusted."""
    body = _strip_fences(text or "")
    keep, started = [], False
    for ln in body.splitlines():
        if ln.strip().startswith("plan:"):
            started = True
        if started:
            if ln.strip() and not ln.startswith((" ", "\t", "plan:")) and keep:
                break
            keep.append(ln)
    try:
        raw = yaml.safe_load("\n".join(keep) if keep else body)
    except yaml.YAMLError as e:
        return None, [f"error: not a PLAN block (YAML error: {getattr(e, 'problem', e)})"]
    if not isinstance(raw, dict) or not isinstance(raw.get("plan"), dict):
        return None, ["error: expected a block starting with `plan:` (the Weekly Reviewer's output)"]
    p, probs = raw["plan"], []
    week = str(p.get("week", "")).strip()
    if not WEEK_RE.match(week):
        probs.append(f"error: week {week!r} must look like 2026-W43")
    region = str(p.get("region", "")).strip().upper()
    known = list(regions or config.account_regions())
    if region not in known:
        probs.append(f"error: region {region!r} is not one of your regions ({', '.join(known)})")
    cats_in = p.get("categories") or []
    cats_in = [cats_in] if isinstance(cats_in, str) else list(cats_in)
    rev = {v.lower(): k for k, v in CATEGORY_NAMES.items()}
    cats = []
    for c in cats_in:
        k = str(c).strip().lower()
        k = k if k in CATEGORY_NAMES else rev.get(k)
        if k:
            cats.append(k)
        else:
            probs.append(f"category {c!r} is unknown and was dropped")
    if not cats:
        probs.append("error: no valid category")

    def _int(k, default, hi):
        v = _num(p.get(k))
        if v is None:
            return default
        if v > hi:
            probs.append(f"{k} {int(v)} is above the ceiling {hi}: set to {hi}")
        return int(max(0, min(v, hi)))
    cap = int(config.settings().get("max_submissions_per_day", 4)) * 5
    lst = lambda k: [str(x) for x in (p.get(k) or [])] if isinstance(p.get(k), list) else \
        ([str(p[k])] if p.get(k) else [])  # noqa: E731
    plan = {"week": week, "region": region,
            "universe": config.REGION_DEFAULTS.get(region, {}).get("universe") or "TOP3000", "delay": 1,
            "categories": cats, "dataset_focus": str(p.get("dataset_focus") or ""),
            "card_target": _int("card_target", 5, 50), "submit_target": _int("submit_target", 10, cap),
            "review_note": " ".join(str(p.get("review_note") or "").split()),
            "extra": {"retry": lst("retry"), "dead_ends": lst("dead_ends"), "lessons": lst("lessons"),
                      "from": "Weekly Reviewer"}}
    if any(x.startswith("error:") for x in probs):
        return None, probs
    return plan, probs


def apply_plan(store, journal, plan: dict) -> Dict[str, int]:
    """Save the plan for its week; lessons and dead ends go to the journal (once, not again on re-apply)."""
    saved = store.save_plan(plan)
    added = 0
    if journal is not None and not getattr(journal, "readonly", False):
        have = {r[0] for r in journal.db.execute("SELECT text FROM lessons").fetchall()}
        ex = plan.get("extra") or {}
        texts = [f"[{plan['week']} review] {t}" for t in ex.get("lessons", [])] + \
                [f"[{plan['week']} review] dead end: stop the family {f}" for f in ex.get("dead_ends", [])]
        for t in texts:
            if t not in have:
                fam = t.split("stop the family ", 1)[1] if "stop the family " in t else ""
                journal.add_lesson(t, family=fam)
                added += 1
    return {"saved": int(saved is not None), "lessons_added": added}


def rebuild_knowledge_pack(journal=None, store=None, out_dir: Optional[Path] = None) -> List[Path]:
    from ideaengine import knowledge_pack
    out = out_dir or (config.PROJECT_DIR / "claude_projects" / "knowledge")
    return knowledge_pack.build(out, journal, store)


def to_json(card: dict) -> str:
    return json.dumps(card, sort_keys=True, default=str)
