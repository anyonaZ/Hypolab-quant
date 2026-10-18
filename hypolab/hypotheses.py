"""Load and validate the hypothesis library (library/hypotheses.yaml)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from . import config
from .fastexpr import ParseError, parse
from .linter import Linter

PLACEHOLDER = re.compile(r"\{(dir:)?([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class Role:
    name: str
    concept: str
    optional: bool = False
    categories: Optional[List[str]] = None
    type: Optional[str] = None          # "GROUP" for grouping roles
    note: str = ""
    min_coverage: float = 0.3
    pair_with: Optional[str] = None     # choose the field that mirrors another role's field (up/down, buy/sell)


@dataclass
class Step:
    name: str
    expr: str
    teaches: str = ""
    when: Optional[Dict[str, List[str]]] = None   # {role: [allowed natures]}

    def roles(self) -> List[str]:
        return sorted({m.group(2) for m in PLACEHOLDER.finditer(self.expr)})


@dataclass
class Hypothesis:
    id: str
    title: str
    category: str
    family: str
    horizon: str
    strength: int
    story: str
    why_persists: str
    references: List[str]
    roles: Dict[str, Role]
    ladder: List[Step]
    settings: dict = field(default_factory=dict)
    expected_turnover: List[float] = field(default_factory=lambda: [0.02, 0.4])
    watch_out: List[str] = field(default_factory=list)
    sign: str = "+1"
    beginner: bool = False
    source: str = "library"

    @property
    def stars(self) -> str:
        return "*" * int(self.strength) + "." * (3 - int(self.strength))


def _role(name: str, spec) -> Role:
    if isinstance(spec, str):
        return Role(name=name, concept=spec)
    return Role(name=name, concept=spec["concept"], optional=bool(spec.get("optional", False)),
                categories=spec.get("categories"), type=spec.get("type"), note=spec.get("note", ""),
                min_coverage=float(spec.get("min_coverage", 0.3)), pair_with=spec.get("pair_with"))


def user_library_dir() -> Path:
    """Your own cards live here (one or more *.yaml files, same format as library/hypotheses.yaml).
    The Idea Engine writes approved cards to my_cards.yaml in this folder."""
    return config.HOME / "library"


# Problems met while loading YOUR card files (bad YAML, a clash with a built-in id ...).
# Loading never fails because of your files; read this list (the cockpit shows it).
LOAD_WARNINGS: List[str] = []


def _hypothesis(c: dict, source: str) -> Hypothesis:
    return Hypothesis(
        id=c["id"], title=c["title"], category=str(c.get("category", "auto")), family=c["family"],
        horizon=c.get("horizon", "medium"), strength=int(c.get("strength", 2)),
        story=" ".join(str(c.get("story", "")).split()), why_persists=" ".join(str(c.get("why_persists", "")).split()),
        references=list(c.get("references", []) or []),
        roles={k: _role(k, v) for k, v in (c.get("roles") or {}).items()},
        ladder=[Step(s["name"], s["expr"], " ".join(str(s.get("teaches", "")).split()), s.get("when"))
                for s in c["ladder"]],
        settings=dict(c.get("settings", {}) or {}), expected_turnover=list(c.get("expected_turnover", [0.02, 0.4])),
        watch_out=list(c.get("watch_out", []) or []), sign=str(c.get("sign", "+1")), beginner=bool(c.get("beginner", False)),
        source=source,
    )


def load_cards(path: Path, source: str = "library") -> List[Hypothesis]:
    """Cards from one YAML file (raises on a broken file)."""
    raw = yaml.safe_load(Path(path).read_text()) or []
    if not isinstance(raw, list):
        raise ValueError(f"{path}: expected a list of cards")
    return [_hypothesis(c, source) for c in raw]


def load_library(path: Optional[Path] = None, include_user: bool = True) -> List[Hypothesis]:
    """The built-in library plus your own cards (~/.hypolab/library/*.yaml, marked source="mine").

    path: load exactly that one file instead (used by tests and by `validate_library` on a single file).
    A card of yours whose id clashes with a built-in card is skipped (see LOAD_WARNINGS) - built-in ids win,
    so a typo can never silently replace a tested card.
    """
    if path is not None:
        return load_cards(path)
    # 1.4.3: parsed once and reused until a card file changes (the cockpit asks for the library many times)
    files = [config.LIBRARY_DIR / "hypotheses.yaml"]
    folder = user_library_dir()
    if include_user and folder.exists():
        files += sorted(folder.glob("*.yaml"))
    sig = (include_user, tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files if f.exists()))
    if _LIB_CACHE.get("sig") == sig:
        LOAD_WARNINGS[:] = _LIB_CACHE["warnings"]
        return list(_LIB_CACHE["cards"])
    cards = _load_library_uncached(include_user)
    _LIB_CACHE.update(sig=sig, cards=list(cards), warnings=list(LOAD_WARNINGS))
    return cards


_LIB_CACHE: dict = {}


def _load_library_uncached(include_user: bool) -> List[Hypothesis]:
    cards = load_cards(config.LIBRARY_DIR / "hypotheses.yaml")
    LOAD_WARNINGS.clear()
    if not include_user:
        return cards
    seen = {h.id for h in cards}
    folder = user_library_dir()
    for f in sorted(folder.glob("*.yaml")) if folder.exists() else []:
        try:
            mine = load_cards(f, source="mine")
        except Exception as e:  # noqa: BLE001 - one bad file must not hide the whole library
            LOAD_WARNINGS.append(f"{f.name}: not loaded ({e})")
            continue
        for h in mine:
            if h.id in seen:
                LOAD_WARNINGS.append(f"{f.name}: card {h.id} skipped - that id already exists")
                continue
            seen.add(h.id)
            cards.append(h)
    return cards


def validate_library(library: List[Hypothesis]) -> List[str]:
    """Problems found in the library itself (run after you add your own cards)."""
    problems = []
    seen = set()
    linter = Linter()
    for h in library:
        if h.id in seen:
            problems.append(f"{h.id}: duplicate id")
        seen.add(h.id)
        for step in h.ladder:
            missing = [r for r in step.roles() if r not in h.roles]
            if missing:
                problems.append(f"{h.id}/{step.name}: placeholder(s) {missing} have no role")
            dummy = PLACEHOLDER.sub(lambda m: "1" if m.group(1) else f"field_{m.group(2)}", step.expr)
            try:
                parse(dummy)
            except ParseError as e:
                problems.append(f"{h.id}/{step.name}: syntax: {e}")
                continue
            for issue in linter.lint(dummy).errors():
                problems.append(f"{h.id}/{step.name}: {issue.code}: {issue.message}")
    return problems
