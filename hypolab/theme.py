"""HYPOLAB's "Matrix" colours, shared by the apps' CSS (apps/hypolab.css) and every chart.

    from hypolab import theme
    theme.apply_matplotlib()          # dark figures that sit on the app background
"""
from __future__ import annotations

BG = "#010604"
SURFACE = "#04120b"
SURFACE_2 = "#071c11"
BORDER = "#123a22"
TEXT = "#d2f5e1"
MUTED = "#7fb196"
CODE = "#00ff9c"          # the code-rain green: primary
CODE_DIM = "#0a7a4c"
CYAN = "#5ef2ff"
PASS = "#00ff9c"          # PASS / READY / LIVE (solid, dark text)
WARN = "#c3a6ff"          # warnings: soft violet (1.4.1 - yellow did not sit with green)
MAGENTA = "#ff7ad9"       # INVERTED
LIME, AMBER = PASS, WARN  # older names kept so nothing breaks
RED = "#ff4f6e"
VIOLET = "#c69bff"
# older names (1.3.3) kept so nothing breaks
TEAL, TEAL_DIM, BLUE, GREEN = CODE, CODE_DIM, CYAN, LIME

# series order for line/bar charts
SERIES = [CODE, CYAN, VIOLET, MAGENTA, "#7dffbf", RED]

# Pyramid grid: empty / started / complete
PYRAMID_LEVELS = ["#071c11", "#0b5a37", "#00d482"]


def apply_matplotlib() -> None:
    """Dark matplotlib defaults matching the apps (call before drawing)."""
    import matplotlib as mpl
    from cycler import cycler
    mpl.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": BORDER, "axes.labelcolor": TEXT, "axes.titlecolor": TEXT,
        "axes.grid": True, "grid.color": BORDER, "grid.linewidth": 0.6, "grid.alpha": 0.8,
        "axes.prop_cycle": cycler(color=SERIES),
        "xtick.color": MUTED, "ytick.color": MUTED, "text.color": TEXT,
        "legend.facecolor": SURFACE_2, "legend.edgecolor": BORDER, "legend.labelcolor": TEXT,
        "font.family": ["JetBrains Mono", "DejaVu Sans Mono", "monospace"], "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "lines.linewidth": 1.8,
    })


# Spinner titles while BRAIN (or the sandbox) works: something to read instead of a bare "Simulating ...".
LOADING_LINES = [
    "Jacking in ... routing your expression through the market",
    "Decoding 3,000 stocks x 2,500 days ...",
    "Following the white rabbit through the order book ...",
    "Compiling the signal, one cross-section at a time ...",
    "Asking the market whether it agrees with you ...",
    "Neutralizing the noise ... the signal is in there somewhere",
    "Rebalancing the simulated book, day after day ...",
    "Back-propagating through ten years of tape ...",
    "There is no spoon. There is only Sharpe ...",
    "Reading the code in the rain ...",
    "Measuring turnover, hunting drawdowns ...",
    "Checking whether this edge is real or luck ...",
]


def loading_line(what: str = "") -> str:
    """A random spinner title, e.g. theme.loading_line("3 alphas")."""
    import random
    line = random.choice(LOADING_LINES)
    return f"{line}  [{what}]" if what else line
