"""Paths and research defaults. Override anything with environment variables
or by editing ``~/.hypolab/settings.json`` (created on first run)."""
from __future__ import annotations

import json
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
BUNDLED_DATA = PROJECT_DIR / "data"
LIBRARY_DIR = PACKAGE_DIR / "library"

HOME = Path(os.environ.get("HYPOLAB_HOME", Path.home() / ".hypolab"))

DEFAULTS = {
    # "sandbox" = offline practice market; "live" = your BRAIN account. Every marimo app follows this switch.
    # Change it on the cockpit's Setup tab, or `python -m hypolab live` / `python -m hypolab sandbox`.
    "mode": "sandbox",
    "live_region": "USA",             # the region the apps use in live mode (change per session if you like)
    # Simulation discipline. BRAIN wants VOLUME (1000+ simulations is normal for a consultant who builds
    # ideas from scratch). Volume is not the problem; picking the best of many variants of ONE idea is.
    # So: spend freely ACROSS ideas and datasets, stay disciplined WITHIN one idea, and let the journal
    # count every try so the gate can deflate the Sharpe honestly.
    "max_sims_per_idea": 10,          # per hypothesis: past this, rethink the idea (force=True overrides)
    "max_sims_per_day": 500,          # only a runaway-loop guard; raise it freely
    # Submissions. BRAIN expects up to 4 regular alphas and 1 SuperAlpha a day; SuperAlphas unlock after
    # 100 submitted alphas (lifetime). The 4 is a ceiling, not a quota: weak submissions pull down your
    # combined alpha performance, which is one of the Genius bars.
    "max_submissions_per_day": 4,
    "superalpha_unlock_after": 100,
    # How long an app keeps running after the browser loses its connection (laptop asleep, Wi-Fi blip). marimo's own
    # default is 120 s, after which the tab shows "kernel not found". Each kept session holds ~0.8 GB on a T470s.
    "session_ttl_seconds": 3600,
    "scan_max_fields": 40,            # fields probed per dataset scan (R.scan)
    "concurrent_simulations": 2,      # gentle on a T470s and on the API; 3 is the safe maximum
    "multi_sim_batch": 5,             # alphas per multi-simulation request (BRAIN allows 2..10)
    # Submission gate used for "is this worth your time" - BRAIN's own /check is the authority,
    # and its limits are read live from each simulation's checks.
    "min_sharpe_d1": 1.58, "min_fitness_d1": 1.0,
    "min_sharpe_d0": 2.69, "min_fitness_d0": 1.5,
    "max_self_corr": 0.7,
    "max_prod_corr": 0.7,             # vs BRAIN's production pool = "is this idea already taken?"
    "target_turnover": [0.05, 0.40],
    # Pyramids: alphas you must submit in one (region, delay, category) cell for it to count.
    # Check the Genius page on BRAIN and set the number you see there.
    # Confirmed by BRAIN's Genius page: a Pyramid needs 3 submitted alphas in the cell (BRAIN_RULES G3).
    "alphas_per_pyramid": 3,
    # Regions YOUR account can simulate (BRAIN's Simulate > Region dropdown; Zacc, 10 Oct 2026).
    # The Pyramid planner, Osmosis check and region pickers use this list. Edit it if BRAIN changes yours.
    "account_regions": ["USA", "GLB", "EUR", "ASI", "CHN", "JPN", "AMR", "IND", "DEU", "GBR"],
    # Older settings (before 1.3.2); no longer used - account_regions replaces them.
    "pyramid_regions": ["USA", "GLB", "EUR", "ASI", "IND"],
    "single_country_region": "KOR",
}


def ensure_home() -> Path:
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(HOME, 0o700)
    except OSError:
        pass
    return HOME


def settings() -> dict:
    ensure_home()
    path = HOME / "settings.json"
    if not path.exists():
        path.write_text(json.dumps(DEFAULTS, indent=2))
        return dict(DEFAULTS)
    try:
        user = json.loads(path.read_text())
    except json.JSONDecodeError:
        user = {}
    merged = dict(DEFAULTS)
    merged.update(user)
    return merged


def save_settings(**changes) -> dict:
    """Update ~/.hypolab/settings.json (keeps everything else)."""
    cur = settings()
    cur.update(changes)
    (HOME / "settings.json").write_text(json.dumps(cur, indent=2))
    return cur


def sandbox_mode() -> bool:
    """True unless you switched to live mode. The apps use: SANDBOX = config.sandbox_mode()."""
    return settings().get("mode", "sandbox") != "live"


def live_region() -> str:
    return settings().get("live_region", "USA")


# Default universes and simulation constraints per region (documented / measured).
# These are starting points; `BrainClient.simulation_options()` reads the live truth.
REGION_DEFAULTS = {
    "USA": {"universe": "TOP3000", "delays": [1, 0], "max_trade": "OFF", "neutralization": "SUBINDUSTRY"},
    "GLB": {"universe": "MINVOL1M", "delays": [1], "max_trade": "OFF", "neutralization": "STATISTICAL"},
    "EUR": {"universe": "TOP2500", "delays": [1, 0], "max_trade": "OFF", "neutralization": "SUBINDUSTRY"},
    "ASI": {"universe": "MINVOL1M", "delays": [1], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "CHN": {"universe": "TOP2000U", "delays": [1, 0], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "KOR": {"universe": "TOP600", "delays": [1], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "TWN": {"universe": "TOP500", "delays": [1], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "HKG": {"universe": "TOP800", "delays": [1], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "JPN": {"universe": "TOP1600", "delays": [1, 0], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "AMR": {"universe": "TOP600", "delays": [1, 0], "max_trade": "OFF", "neutralization": "SUBINDUSTRY"},
    # DEU and GBR: offered on Zacc's account with D1 and D0 (Genius page). Their universe names are not
    # documented anywhere we have; they are filled in from BRAIN by sync_simulation_options() (Account tab).
    "DEU": {"universe": None, "delays": [1, 0], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "GBR": {"universe": None, "delays": [1, 0], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    "IND": {"universe": "TOP500", "delays": [1], "max_trade": "ON", "neutralization": "SUBINDUSTRY"},
    # offline sandbox (synthetic data, see hypolab/sandbox)
    "SBX": {"universe": "SANDBOX", "delays": [1], "max_trade": "OFF", "neutralization": "SUBINDUSTRY"},
}

# Economically meaningful look-back windows in trading days (WorldQuant webinar:
# "days should reflect the alpha idea").
ECONOMIC_WINDOWS = {
    1: "one day", 2: "two days", 3: "three days", 5: "one week", 10: "two weeks", 21: "one month",
    42: "two months", 63: "one quarter", 126: "half a year", 189: "three quarters", 252: "one year",
    504: "two years", 756: "three years",
}


def account_regions() -> list:
    """Regions this account can simulate, in the order of the setting."""
    regs = settings().get("account_regions") or DEFAULTS["account_regions"]
    return [r for r in regs if r != "SBX"]


def universe_for(region: str):
    """Default universe for a region, or None if unknown (sync the simulation options first)."""
    return REGION_DEFAULTS.get(region, {}).get("universe")


def region_neutralizations(region: str) -> list:
    """Neutralizations BRAIN offers in this region (from the synced options), else the classic five."""
    return REGION_DEFAULTS.get(region, {}).get("neutralizations") or \
        ["MARKET", "SECTOR", "INDUSTRY", "SUBINDUSTRY", "NONE"]


def _pick_universe(current, universes):
    if current in universes or not universes:
        return current
    tops = [u for u in universes if u.startswith("TOP") and u[3:].isdigit()]
    return max(tops, key=lambda u: int(u[3:])) if tops else universes[0]


def apply_sim_options(rows=None) -> int:
    """Merge BRAIN's OPTIONS /simulations answer (cached in ~/.hypolab/sim_options.json) into REGION_DEFAULTS.

    BRAIN is the authority on which delays, universes and neutralizations each region offers.
    """
    if rows is None:
        try:
            rows = json.loads((HOME / "sim_options.json").read_text())
        except (OSError, ValueError):
            return 0
    n = 0
    for r in rows or []:
        reg = r.get("region")
        if not reg:
            continue
        e = REGION_DEFAULTS.setdefault(reg, {"universe": None, "delays": [1], "max_trade": "OFF",
                                             "neutralization": "SUBINDUSTRY"})
        delays = [int(d) for d in (r.get("delays") or []) if str(d).lstrip("-").isdigit()]
        if delays:
            e["delays"] = sorted(set(delays), reverse=True)
        univs = list(r.get("universes") or [])
        if univs:
            e["universes"] = univs
            e["universe"] = _pick_universe(e.get("universe"), univs)
        neuts = list(r.get("neutralizations") or [])
        if neuts:
            e["neutralizations"] = neuts
            if e.get("neutralization") not in neuts:
                e["neutralization"] = "SUBINDUSTRY" if "SUBINDUSTRY" in neuts else neuts[0]
        n += 1
    return n


def save_sim_options(rows) -> int:
    ensure_home()
    (HOME / "sim_options.json").write_text(json.dumps(rows, indent=1))
    return apply_sim_options(rows)


apply_sim_options()
