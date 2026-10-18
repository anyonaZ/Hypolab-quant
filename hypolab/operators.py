"""The operator set you can use (transcribed from your `operators.pdf`).

The PDF is BRAIN's Learn > Operators page as seen by your account on
2026-09-10. Every operator on it (both "base" and "genius" tags) is treated as
available to you at GOLD, as you stated. Anything NOT in this registry is
flagged by the linter: several notebooks in the zip use operators that are not
on your list (arc_sin, sigmoid, s_log_1p, log_diff, ts_returns, ts_skewness,
ts_kurtosis, pasteurize, ts_decay_exp_window, group_median, exp, ...).

If BRAIN later shows you more operators, call
``OperatorRegistry.extend_from_api(brain_client.operators())`` and they are
merged in (flagged ``source="api"``).

Each spec carries what a beginner needs to use the operator *correctly*:

* ``params``  - ordered parameter names; ``required`` how many are mandatory
* ``named_only`` - attributes BRAIN rejects when passed positionally
  (``winsorize(x, 4)`` fails with "Invalid number of inputs"; you must write
  ``winsorize(x, std=4)``)
* ``kinds``   - what each argument must be: ``x`` (matrix), ``vector``,
  ``group``, ``window`` (integer days), ``number``, ``bool``, ``str``
* ``output``  - the value distribution it produces (WorldQuant's webinar
  checklist item 5: "understand the value distribution at each step")
* ``why``     - what it is for in alpha research
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence


@dataclass
class OpSpec:
    name: str
    category: str
    params: List[str]
    required: int
    defaults: Dict[str, object] = field(default_factory=dict)
    named_only: List[str] = field(default_factory=list)
    kinds: Dict[str, str] = field(default_factory=dict)
    variadic: bool = False
    tier: str = "base"          # base | genius (as tagged in the PDF)
    output: str = ""
    why: str = ""
    signature: str = ""
    source: str = "pdf"
    api_category: str = ""

    def kind_of(self, param: str) -> str:
        return self.kinds.get(param, "x")


def _op(name, category, params, required, *, defaults=None, named_only=(), kinds=None,
        variadic=False, tier="base", output="", why="", signature=""):
    return OpSpec(name=name, category=category, params=list(params), required=required,
                  defaults=dict(defaults or {}), named_only=list(named_only),
                  kinds=dict(kinds or {}), variadic=variadic, tier=tier, output=output,
                  why=why, signature=signature or f"{name}({', '.join(params)})")


W = "window"
G = "group"
V = "vector"
N = "number"

_SPECS: List[OpSpec] = [
    # ------------------------------------------------------------ Arithmetic
    _op("abs", "Arithmetic", ["x"], 1, output="same scale as x, >= 0",
        why="Magnitude only (e.g. size of a surprise regardless of sign)."),
    _op("add", "Arithmetic", ["x", "y", "filter"], 2, defaults={"filter": False}, named_only=["filter"],
        kinds={"filter": "bool"}, variadic=True, output="sum of scales - normalise legs first",
        why="Combine legs. Rank/zscore each leg first so one leg cannot dominate. filter=true treats NaN as 0.",
        signature="add(x, y, filter=false)  or  x + y"),
    _op("densify", "Arithmetic", ["x"], 1, kinds={"x": G}, output="group ids",
        why="Compacts a grouping field with many empty buckets."),
    _op("divide", "Arithmetic", ["x", "y"], 2, output="ratio - can explode when y ~ 0",
        why="Ratios: yields (earnings/cap), margins, growth. Guard tiny denominators.",
        signature="divide(x, y)  or  x / y"),
    _op("inverse", "Arithmetic", ["x"], 1, output="1/x - explodes near 0",
        why="Turn price-to-X into X-to-price (e.g. P/E -> earnings yield)."),
    _op("log", "Arithmetic", ["x"], 1, output="compresses large positive values; NaN for x<=0",
        why="Tame skewed positive data (market cap, volume, counts)."),
    _op("max", "Arithmetic", ["x", "y"], 2, variadic=True, output="element-wise max",
        why="'Either leg fires' combination (OR-like)."),
    _op("min", "Arithmetic", ["x", "y"], 2, variadic=True, output="element-wise min",
        why="Conjunction: only takes a position where BOTH legs agree - cuts drawdown."),
    _op("multiply", "Arithmetic", ["x", "y", "filter"], 2, defaults={"filter": False}, named_only=["filter"],
        kinds={"filter": "bool"}, variadic=True, output="product of scales",
        why="Interaction / conditioning: signal * (strength of a second effect).",
        signature="multiply(x, y, ..., filter=false)  or  x * y"),
    _op("power", "Arithmetic", ["x", "y"], 2, kinds={"y": N}, output="loses sign for non-integer y",
        why="Prefer signed_power to keep the sign."),
    _op("reverse", "Arithmetic", ["x"], 1, output="-x", why="Flip the direction of a signal."),
    _op("sign", "Arithmetic", ["x"], 1, output="{-1, 0, +1}", why="Direction only - very high turnover if used raw."),
    _op("signed_power", "Arithmetic", ["x", "y"], 2, kinds={"y": N}, output="keeps sign, reshapes tails",
        why="y>1 sharpens conviction in the extremes, y<1 flattens them."),
    _op("sqrt", "Arithmetic", ["x"], 1, output="NaN for x<0", why="Compress positive data."),
    _op("subtract", "Arithmetic", ["x", "y", "filter"], 2, defaults={"filter": False}, named_only=["filter"],
        kinds={"filter": "bool"}, variadic=True, output="difference",
        why="Spreads, 'actual minus expected', 'stock minus peers'.",
        signature="subtract(x, y, filter=false)  or  x - y"),
    _op("to_nan", "Arithmetic", ["x", "value", "reverse"], 1, defaults={"value": 0, "reverse": False},
        named_only=["value", "reverse"], kinds={"value": N, "reverse": "bool"}, tier="genius",
        why="Turn placeholder zeros into NaN (vendor fields that fill missing with 0)."),
    # ------------------------------------------------------------- Logical
    _op("and", "Logical", ["input1", "input2"], 2, output="{0,1}", why="Both conditions true."),
    _op("or", "Logical", ["input1", "input2"], 2, output="{0,1}", why="Either condition true."),
    _op("not", "Logical", ["x"], 1, output="{0,1}", why="Negate a condition."),
    _op("if_else", "Logical", ["input1", "input2", "input3"], 3, output="branch values",
        why="Regime switching: different behaviour when a condition holds."),
    _op("is_nan", "Logical", ["input"], 1, output="{0,1}", why="Detect missing data (e.g. no news today)."),
    _op("less", "Logical", ["input1", "input2"], 2, output="{0,1}", signature="input1 < input2"),
    _op("less_equal", "Logical", ["input1", "input2"], 2, output="{0,1}", signature="input1 <= input2"),
    _op("greater", "Logical", ["input1", "input2"], 2, output="{0,1}", signature="input1 > input2"),
    _op("greater_equal", "Logical", ["input1", "input2"], 2, output="{0,1}", signature="input1 >= input2"),
    _op("equal", "Logical", ["input1", "input2"], 2, output="{0,1}", signature="input1 == input2"),
    _op("not_equal", "Logical", ["input1", "input2"], 2, output="{0,1}", signature="input1 != input2"),
    # ---------------------------------------------------------- Time Series
    _op("days_from_last_change", "Time Series", ["x"], 1, output="integer days >= 0",
        why="Event timing: days since a field last changed (e.g. since the last earnings update)."),
    _op("hump", "Time Series", ["x", "hump"], 1, defaults={"hump": 0.01}, named_only=["hump"],
        kinds={"hump": N}, output="same as x but changes only when large",
        why="Cuts turnover by ignoring small changes. MUST be written hump(x, hump=0.01)."),
    _op("jump_decay", "Time Series", ["x", "d", "sensitivity", "force"], 2,
        defaults={"sensitivity": 0.5, "force": 0.1}, named_only=["sensitivity", "force"],
        kinds={"d": W, "sensitivity": N, "force": N}, tier="genius",
        why="Damp sudden jumps in noisy data."),
    _op("kth_element", "Time Series", ["x", "d", "k", "ignore"], 3, defaults={"ignore": "NaN"},
        named_only=["ignore"], kinds={"d": W, "k": N, "ignore": "str"},
        why="k-th valid value looking back d days; commonly used for backfilling."),
    _op("last_diff_value", "Time Series", ["x", "d"], 2, kinds={"d": W},
        why="Previous different value - the value before the latest update (e.g. previous estimate)."),
    _op("ts_arg_max", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="0..d-1 days",
        why="How long ago the peak happened (recency of a high)."),
    _op("ts_arg_min", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="0..d-1 days",
        why="How long ago the trough happened."),
    _op("ts_av_diff", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="x minus its own d-day mean",
        why="Deviation from the stock's own normal level - removes level differences between stocks."),
    _op("ts_backfill", "Time Series", ["x", "lookback", "k"], 2, defaults={"k": 1}, named_only=["k"],
        kinds={"lookback": W, "k": N}, output="same as x with gaps filled",
        why="Fill missing values with the last valid one. Essential for quarterly/sparse fields.",
        signature="ts_backfill(x, lookback=d, k=1)"),
    _op("ts_corr", "Time Series", ["x", "y", "d"], 3, kinds={"d": W}, output="[-1, 1]",
        why="Rolling correlation between two series (e.g. price vs volume)."),
    _op("ts_count_nans", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="0..d",
        why="Data availability / event frequency (e.g. how many days had news)."),
    _op("ts_covariance", "Time Series", ["y", "x", "d"], 3, kinds={"d": W},
        why="Rolling covariance; scale depends on both inputs."),
    _op("ts_decay_linear", "Time Series", ["x", "d", "dense"], 2, defaults={"dense": False},
        named_only=["dense"], kinds={"d": W, "dense": "bool"}, output="smoothed x",
        why="Weighted average favouring recent days - smooths and lowers turnover."),
    _op("ts_delay", "Time Series", ["x", "d"], 2, kinds={"d": W}, why="Value d days ago."),
    _op("ts_delta", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="x - x[d days ago]",
        why="Change over d days (momentum/revision). On quarterly data use d >= 63."),
    _op("ts_max", "Time Series", ["x", "d"], 2, kinds={"d": W}, tier="genius", why="Highest value in the window."),
    _op("ts_mean", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="smoothed x", why="Simple moving average."),
    _op("ts_min", "Time Series", ["x", "d"], 2, kinds={"d": W}, tier="genius", why="Lowest value in the window."),
    _op("ts_product", "Time Series", ["x", "d"], 2, kinds={"d": W},
        why="Compounding, e.g. ts_product(1+returns, d) - 1 = d-day return."),
    _op("ts_quantile", "Time Series", ["x", "d", "driver"], 2, defaults={"driver": "gaussian"},
        named_only=["driver"], kinds={"d": W, "driver": "str"}, output="roughly N(0,1)",
        why="Time-series rank mapped to a normal distribution."),
    _op("ts_rank", "Time Series", ["x", "d", "constant"], 2, defaults={"constant": 0},
        named_only=["constant"], kinds={"d": W, "constant": N}, output="[0, 1] (+constant)",
        why="Where today's value sits within the stock's own last d days - removes scale."),
    _op("ts_regression", "Time Series", ["y", "x", "d", "lag", "rettype"], 3,
        defaults={"lag": 0, "rettype": 0}, named_only=["lag", "rettype"],
        kinds={"d": W, "lag": N, "rettype": N},
        output="rettype 0=residual, 1=intercept, 2=slope(beta), 3=fitted, 6=R^2",
        why="Strip out what x explains about y (residual), or measure sensitivity (slope)."),
    _op("ts_scale", "Time Series", ["x", "d", "constant"], 2, defaults={"constant": 0},
        named_only=["constant"], kinds={"d": W, "constant": N}, output="[0, 1]",
        why="Min-max position within the window."),
    _op("ts_std_dev", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="depends on scale of x",
        why="Volatility / instability of a series."),
    _op("ts_step", "Time Series", ["x"], 1, kinds={"x": N}, why="Day counter."),
    _op("ts_sum", "Time Series", ["x", "d"], 2, kinds={"d": W}, why="Rolling sum (e.g. sum of returns = momentum)."),
    _op("ts_target_tvr_decay", "Time Series", ["x", "lambda_min", "lambda_max", "target_tvr"], 1,
        defaults={"lambda_min": 0, "lambda_max": 1, "target_tvr": 0.1},
        named_only=["lambda_min", "lambda_max", "target_tvr"],
        kinds={"lambda_min": N, "lambda_max": N, "target_tvr": N}, tier="genius",
        why="Auto-tunes smoothing to hit a target turnover. Write target_tvr=0.1 by name."),
    _op("ts_target_tvr_delta_limit", "Time Series", ["x", "y", "lambda_min", "lambda_max", "target_tvr"], 2,
        defaults={"lambda_min": 0, "lambda_max": 1, "target_tvr": 0.1},
        named_only=["lambda_min", "lambda_max", "target_tvr"],
        kinds={"lambda_min": N, "lambda_max": N, "target_tvr": N}, tier="genius",
        why="Limits daily position changes to hit a target turnover."),
    _op("ts_zscore", "Time Series", ["x", "d"], 2, kinds={"d": W}, output="~N(0,1) over time",
        why="How unusual today's value is versus the stock's own history."),
    # ------------------------------------------------------ Cross Sectional
    _op("normalize", "Cross Sectional", ["x", "useStd", "limit"], 1, defaults={"useStd": False, "limit": 0.0},
        named_only=["useStd", "limit"], kinds={"useStd": "bool", "limit": N}, output="mean 0 across stocks",
        why="Demean across the market each day."),
    _op("quantile", "Cross Sectional", ["x", "driver", "sigma"], 1, defaults={"driver": "gaussian", "sigma": 1.0},
        named_only=["driver", "sigma"], kinds={"driver": "str", "sigma": N}, output="~N(0, sigma)",
        why="Rank then map to a bell curve - robust to outliers but keeps tails."),
    _op("rank", "Cross Sectional", ["x", "rate"], 1, defaults={"rate": 2}, named_only=["rate"],
        kinds={"rate": N}, output="uniform [0, 1]",
        why="THE default normaliser: robust to outliers, removes scale. Always safe as the outer wrapper."),
    _op("scale", "Cross Sectional", ["x", "scale", "longscale", "shortscale"], 1,
        defaults={"scale": 1, "longscale": 1, "shortscale": 1}, named_only=["scale", "longscale", "shortscale"],
        kinds={"scale": N, "longscale": N, "shortscale": N}, output="sum(|x|) = scale",
        why="Book-size scaling; keeps relative magnitudes (outliers survive)."),
    _op("scale_down", "Cross Sectional", ["x", "constant"], 1, defaults={"constant": 0}, named_only=["constant"],
        kinds={"constant": N}, tier="genius", output="[0, 1] - constant", why="Min-max across stocks."),
    _op("vector_neut", "Cross Sectional", ["x", "y"], 2, tier="genius", output="x with the y-component removed",
        why="Orthogonalise: remove exposure to y (e.g. size, momentum, a crowded alpha)."),
    _op("winsorize", "Cross Sectional", ["x", "std"], 1, defaults={"std": 4}, named_only=["std"],
        kinds={"std": N}, output="x clipped at mean +/- std*sd",
        why="Remove outliers. MUST be written winsorize(x, std=4)."),
    _op("zscore", "Cross Sectional", ["x"], 1, output="mean 0, sd 1 (tails survive)",
        why="Standardise across stocks; wrap in rank/winsorize if tails are extreme."),
    # --------------------------------------------------------------- Vector
    _op("vec_avg", "Vector", ["x"], 1, kinds={"x": V}, why="Mean of a VECTOR field (many values per stock-day) -> matrix."),
    _op("vec_count", "Vector", ["x"], 1, kinds={"x": V}, tier="genius", why="Number of items (e.g. number of news stories)."),
    _op("vec_max", "Vector", ["x"], 1, kinds={"x": V}, tier="genius", why="Max item."),
    _op("vec_min", "Vector", ["x"], 1, kinds={"x": V}, tier="genius", why="Min item."),
    _op("vec_range", "Vector", ["x"], 1, kinds={"x": V}, tier="genius", why="Max - min (disagreement)."),
    _op("vec_stddev", "Vector", ["x"], 1, kinds={"x": V}, tier="genius", why="Dispersion across items."),
    _op("vec_sum", "Vector", ["x"], 1, kinds={"x": V}, why="Sum of items."),
    # ------------------------------------------------------ Transformational
    _op("bucket", "Transformational", ["x", "range", "buckets", "skipBoth", "NaNGroup"], 1,
        defaults={"range": "0,1,0.1", "skipBoth": False, "NaNGroup": False},
        named_only=["range", "buckets", "skipBoth", "NaNGroup"],
        kinds={"range": "str", "buckets": "str", "skipBoth": "bool", "NaNGroup": "bool"}, output="group ids",
        why="Build custom groups (e.g. size deciles) for group_* operators. Feed it rank(x) when range is 0..1.",
        signature='bucket(rank(x), range="0,1,0.1")  or  bucket(rank(x), buckets="2,5,6,7,10")'),
    _op("trade_when", "Transformational", ["x", "y", "z"], 3, output="y when x>0, previous value otherwise, NaN when z>0",
        why="Trade only when a condition holds (z=-1: never force exit). Cuts turnover, targets regimes."),
    # ----------------------------------------------------------------- Group
    _op("group_backfill", "Group", ["x", "group", "d", "std"], 3, defaults={"std": 4.0}, named_only=["std"],
        kinds={"group": G, "d": W, "std": N}, why="Fill a stock's NaN with its group's (winsorised) mean."),
    _op("group_cartesian_product", "Group", ["g1", "g2"], 2, kinds={"g1": G, "g2": G}, tier="genius",
        output="group ids", why="Combine two groupings (e.g. country x sector)."),
    _op("group_max", "Group", ["x", "group"], 2, kinds={"group": G}, tier="genius", why="Group maximum."),
    _op("group_mean", "Group", ["x", "weight", "group"], 3, kinds={"group": G},
        why="(Weighted) peer average; use cap as weight for a cap-weighted benchmark. 3 inputs: x, weight, group."),
    _op("group_min", "Group", ["x", "group"], 2, kinds={"group": G}, tier="genius", why="Group minimum."),
    _op("group_neutralize", "Group", ["x", "group"], 2, kinds={"group": G}, output="mean 0 within each group",
        why="Remove the group effect so only stock-specific signal remains."),
    _op("group_rank", "Group", ["x", "group"], 2, kinds={"group": G}, output="[0, 1] within each group",
        why="Rank against peers - 'cheap for its industry' rather than 'cheap overall'."),
    _op("group_scale", "Group", ["x", "group"], 2, kinds={"group": G}, output="[0, 1] within each group",
        why="Min-max within groups."),
    _op("group_zscore", "Group", ["x", "group"], 2, kinds={"group": G}, output="mean 0, sd 1 within group",
        why="Standardise against peers."),
]

#: Grouping keywords that every region accepts as a group argument.
STANDARD_GROUPS = {"market", "sector", "industry", "subindustry", "country", "exchange", "currency"}

#: Identifiers that are literals, not fields.
LITERALS = {"true", "false", "nan", "NaN", "inf", "gaussian", "uniform", "cauchy"}

#: Operators seen in the zip's notebooks that are NOT on your Gold list.
NOT_ON_YOUR_LIST = {
    "arc_sin", "arc_cos", "arc_tan", "sigmoid", "tanh", "s_log_1p", "log_diff", "exp", "fraction",
    "ts_returns", "ts_skewness", "ts_kurtosis", "ts_ir", "ts_max_diff", "ts_min_max_cps",
    "ts_decay_exp_window", "ts_delta_limit", "ts_entropy", "ts_percentage", "pasteurize",
    "group_median", "group_count", "group_sum", "group_std_dev", "nan_mask", "tail", "left_tail",
    "right_tail", "clamp", "filter", "vec_norm", "vec_percentage", "ts_target_tvr_hump", "ts_count",
    "regression_neut", "group_vector_neut", "vec_ir", "vec_skewness", "vec_kurtosis",
}


class OperatorRegistry:
    def __init__(self, specs: Iterable[OpSpec] = ()):
        self.specs: Dict[str, OpSpec] = {s.name: s for s in specs}

    @classmethod
    def gold(cls) -> "OperatorRegistry":
        return cls(_SPECS)

    def __contains__(self, name: str) -> bool:
        return name in self.specs

    def get(self, name: str) -> Optional[OpSpec]:
        return self.specs.get(name)

    def names(self) -> List[str]:
        return sorted(self.specs)

    def by_category(self) -> Dict[str, List[OpSpec]]:
        out: Dict[str, List[OpSpec]] = {}
        for s in self.specs.values():
            out.setdefault(s.category, []).append(s)
        return out

    def extend_from_api(self, rows: Sequence[dict], scope: str = "REGULAR") -> List[str]:
        """Merge operators returned by GET /operators (only those in `scope`).
        Returns the names that were new. Signatures are taken from `definition`."""
        added = []
        for r in rows:
            scopes = r.get("scope") or []
            if isinstance(scopes, str):
                scopes = [scopes]
            if scope not in scopes or r.get("name") in self.specs:
                continue
            name = r["name"]
            self.specs[name] = OpSpec(name=name, category=r.get("category", "API"), params=["x"], required=1,
                                      variadic=True, signature=r.get("definition", name),
                                      why=(r.get("description") or "")[:200], source="api")
            added.append(name)
        return added

    def table(self):
        """A pandas DataFrame for browsing in a notebook."""
        import pandas as pd
        return pd.DataFrame([{
            "operator": s.name, "category": s.category, "tag": s.tier, "signature": s.signature,
            "named-only args": ", ".join(s.named_only), "output": s.output, "use it for": s.why,
        } for s in sorted(self.specs.values(), key=lambda s: (s.category, s.name))])


GOLD = OperatorRegistry.gold()


# ------------------------------------------------------- your account's live operator list (GET /operators)
# The PDF list above is the starting point. BRAIN's live list for your account is longer (131 REGULAR operators
# in 8 categories in October 2026, against 82 in the PDF), so once it has been downloaded (cockpit, Account tab,
# or sync_operators(brain)) it is cached and merged into GOLD: the linter then accepts everything your account
# really has. Operators known only from the API get light checks (BRAIN reports any argument errors).

def api_cache_path():
    from . import config
    return config.HOME / "operators.json"


def load_api_rows() -> List[dict]:
    import json
    p = api_cache_path()
    if not p.exists():
        return []
    try:
        return list(json.loads(p.read_text()).get("rows", []))
    except (ValueError, OSError):
        return []


def apply_api_operators(rows: Optional[Sequence[dict]] = None) -> List[str]:
    """Merge the cached (or given) live operator list into GOLD. Returns the names added."""
    rows = load_api_rows() if rows is None else rows
    added = GOLD.extend_from_api(rows)
    for r in rows:                          # keep BRAIN's own category names for operators we already know
        spec = GOLD.get(r.get("name"))
        if spec is not None and r.get("category") and spec.source == "pdf":
            spec.api_category = r["category"]
    return added


def sync_operators(brain) -> dict:
    """Download GET /operators for your account, cache it in ~/.hypolab/operators.json, merge it into GOLD."""
    import json
    import time as _time
    rows = brain.operators()
    if isinstance(rows, dict):
        rows = rows.get("results") or rows.get("operators") or []
    from . import config
    config.ensure_home()
    api_cache_path().write_text(json.dumps({"fetched": _time.time(), "rows": rows}))
    added = apply_api_operators(rows)
    regular = [r for r in rows if "REGULAR" in (r.get("scope") if isinstance(r.get("scope"), list)
                                                else [r.get("scope")])]
    return {"operators": len(rows), "regular": len(regular), "added_to_linter": added}


def regular_operator_catalog(rows: Optional[Sequence[dict]] = None):
    """One row per REGULAR operator with BRAIN's category: the live list if downloaded, else the PDF list."""
    import pandas as pd
    rows = load_api_rows() if rows is None else rows
    out = []
    for r in rows:
        scopes = r.get("scope") or []
        scopes = [scopes] if isinstance(scopes, str) else scopes
        if "REGULAR" in scopes and r.get("name"):
            out.append({"name": r["name"], "category": r.get("category") or "Other", "source": "BRAIN"})
    if not out:
        out = [{"name": sp.name, "category": sp.category, "source": "PDF"} for sp in GOLD.specs.values()
               if sp.source == "pdf"]
    return pd.DataFrame(out).drop_duplicates("name").sort_values(["category", "name"]).reset_index(drop=True)


try:                                        # use the cached live list from the start, if there is one
    apply_api_operators()
except Exception:  # noqa: BLE001 - never let a bad cache stop HYPOLAB from importing
    pass
