"""Evaluate FASTEXPR expressions on local numpy data (the offline sandbox).

Purpose: LEARNING and PRE-CHECKING, not replacing BRAIN. You can see what each
operator does to the numbers, what distribution it outputs, how turnover
reacts to smoothing - on synthetic data, for free, on a T470s.

Data layout: every matrix is a float array shaped (T days, N stocks).
Groups are int arrays (T, N) or (N,). VECTOR fields are (T, N, K) with NaN padding.

A few operators are approximations of BRAIN's exact implementation
(hump, jump_decay, ts_target_tvr_*, group_backfill); they are marked APPROX.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd
from scipy.special import ndtri

from .. import fastexpr as fx

GROUP_NAMES = {"market", "sector", "industry", "subindustry", "country", "exchange", "currency"}


class EvalError(ValueError):
    pass


class Data:
    """Container for sandbox data. fields: {name: (T,N)}, groups: {name: (T,N) int},
    vectors: {name: (T,N,K)}; returns: (T,N) daily returns used by the backtester."""

    def __init__(self, fields: Dict[str, np.ndarray], groups: Dict[str, np.ndarray],
                 vectors: Optional[Dict[str, np.ndarray]] = None, dates=None, tickers=None,
                 descriptions: Optional[Dict[str, str]] = None):
        self.fields = fields
        self.groups = groups
        self.vectors = vectors or {}
        any_f = next(iter(fields.values()))
        self.T, self.N = any_f.shape
        self.dates = dates if dates is not None else pd.bdate_range("2018-01-02", periods=self.T)
        self.tickers = tickers if tickers is not None else [f"S{i:04d}" for i in range(self.N)]
        self.descriptions = descriptions or {}

    def get(self, name: str):
        if name in self.fields:
            return self.fields[name]
        if name in self.groups:
            return self.groups[name].astype(float)
        if name in self.vectors:
            return self.vectors[name]
        raise EvalError(f"unknown field '{name}' in sandbox data")

    def catalog_rows(self) -> list:
        """Fields in the same shape as a BRAIN /data-fields response (for the linter/catalog)."""
        rows = []
        for k in self.fields:
            # BRAIN-style coverage: share of stocks with a (recent) value, quarterly data counted as carried
            cov = float(np.isfinite(pd.DataFrame(self.fields[k]).ffill(limit=63).to_numpy()[252:]).mean())
            rows.append({"id": k, "type": "MATRIX", "description": self.descriptions.get(k, k), "coverage": cov,
                         "dataset": k.split("_")[0] if "_" in k else "pv1"})
        for k in self.groups:
            rows.append({"id": k, "type": "GROUP", "description": self.descriptions.get(k, k), "coverage": 1.0,
                         "dataset": "pv1"})
        for k in self.vectors:
            rows.append({"id": k, "type": "VECTOR", "description": self.descriptions.get(k, k), "coverage":
                         float(np.isfinite(self.vectors[k]).any(axis=2).mean()), "dataset": "anl_sandbox"})
        return rows


# ------------------------------------------------------------------ helpers

def _arr(x, shape):
    if np.isscalar(x):
        return np.full(shape, float(x))
    return x


def _shift(x: np.ndarray, d: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if d <= 0:
        return x.astype(float).copy()
    if d < x.shape[0]:
        out[d:] = x[:-d]
    return out


def _df(x):
    return pd.DataFrame(x)


def _minp(d):
    return max(1, int(math.ceil(d * 0.5)))


def _windows(x: np.ndarray, d: int, fn: Callable[[np.ndarray], np.ndarray], fill=np.nan) -> np.ndarray:
    """Apply fn over trailing windows: fn receives (rows, N, d) with the newest value LAST."""
    T, N = x.shape
    pad = np.full((d - 1, N), np.nan)
    xp = np.vstack([pad, x.astype(float)])
    view = np.lib.stride_tricks.sliding_window_view(xp, d, axis=0)  # (T, N, d)
    out = np.full((T, N), fill, dtype=float)
    chunk = max(1, int(1.5e7 // max(1, N * d)))
    for s in range(0, T, chunk):
        out[s:s + chunk] = fn(view[s:s + chunk])
    return out


def _row_rank(x: np.ndarray) -> np.ndarray:
    r = _df(x).rank(axis=1, method="average")
    n = r.count(axis=1).to_numpy()[:, None]
    out = (r.to_numpy() - 1.0) / np.where(n > 1, n - 1, 1.0)
    out[(n == 1).repeat(x.shape[1], axis=1) & np.isfinite(out)] = 0.5
    return out


def _group_keys(x: np.ndarray, g: np.ndarray):
    T, N = x.shape
    if g.ndim == 1:
        g = np.broadcast_to(g, (T, N))
    g = np.nan_to_num(g.astype(float), nan=-1).astype(np.int64)
    gmax = int(g.max()) + 2
    keys = np.arange(T)[:, None] * gmax + (g + 1)
    return keys, g


def _group_apply(x: np.ndarray, g: np.ndarray, how: str, weight: Optional[np.ndarray] = None) -> np.ndarray:
    keys, graw = _group_keys(x, g)
    valid = np.isfinite(x) & (graw >= 0)
    if weight is not None:
        valid &= np.isfinite(weight)
    s = pd.Series(x[valid])
    k = keys[valid]
    out = np.full(x.shape, np.nan)
    if s.empty:
        return out
    grp = s.groupby(k)
    if how == "mean":
        if weight is not None:
            w = pd.Series(weight[valid])
            num = (s * w).groupby(k).transform("sum")
            den = w.groupby(k).transform("sum")
            vals = num / den.replace(0, np.nan)
        else:
            vals = grp.transform("mean")
    elif how == "rank":
        r = grp.rank(method="average")
        n = grp.transform("count")
        vals = (r - 1) / (n - 1).where(n > 1, 1)
        vals = vals.where(n > 1, 0.5)
    elif how == "zscore":
        vals = (s - grp.transform("mean")) / grp.transform("std").replace(0, np.nan)
    elif how == "scale":
        mn, mx = grp.transform("min"), grp.transform("max")
        vals = (s - mn) / (mx - mn).replace(0, np.nan)
    elif how == "max":
        vals = grp.transform("max")
    elif how == "min":
        vals = grp.transform("min")
    else:
        raise EvalError(how)
    out[valid] = vals.to_numpy()
    return out


def _parse_range(spec: str):
    a, b, step = [float(v) for v in str(spec).split(",")]
    return np.arange(a, b + 1e-12, step)


# --------------------------------------------------------------- operators

def _ts_rank(x, d, constant=0.0):
    def f(w):
        last = w[..., -1:]
        valid = np.isfinite(w)
        less = np.sum((w < last) & valid, axis=-1)
        eq = np.sum((w == last) & valid, axis=-1) - 1
        n = valid.sum(axis=-1)
        r = (less + 0.5 * eq) / np.where(n > 1, n - 1, np.nan)
        r[~np.isfinite(last[..., 0])] = np.nan
        return r
    return _windows(x, d, f) + constant


def _ts_argmax(x, d, use_max=True):
    def f(w):
        ww = np.where(np.isfinite(w), w, -np.inf if use_max else np.inf)
        idx = np.argmax(ww, axis=-1) if use_max else np.argmin(ww, axis=-1)
        res = (d - 1 - idx).astype(float)
        res[~np.isfinite(w).any(axis=-1)] = np.nan
        return res
    return _windows(x, d, f)


def _ts_decay_linear(x, d, dense=False):
    """Linearly weighted mean over d days (newest weight d) - O(T) via cumulative sums."""
    x = np.asarray(x, dtype=float)
    m = np.isfinite(x)
    T = x.shape[0]
    t = np.arange(T, dtype=float).reshape((-1,) + (1,) * (x.ndim - 1))

    def wsum(v):
        c1 = np.cumsum(v, axis=0)
        c2 = np.cumsum(v * t, axis=0)
        p1 = np.zeros_like(c1)
        p2 = np.zeros_like(c2)
        p1[d:] = c1[:-d]
        p2[d:] = c2[:-d]
        # sum_{j=t-d+1..t} (d - t + j) v_j
        return (d - t) * (c1 - p1) + (c2 - p2)

    num = wsum(np.where(m, x, 0.0))
    den = wsum(m.astype(float))
    out = num / np.where(den > 1e-9, den, np.nan)
    if not dense:
        out[~m] = np.nan
    return out


def _ts_regression(y, x, d, lag=0, rettype=0):
    x = _shift(x, int(lag))
    Y, X = _df(y), _df(x)
    mp = _minp(d)
    mx, my = X.rolling(d, min_periods=mp).mean(), Y.rolling(d, min_periods=mp).mean()
    cov = (X * Y).rolling(d, min_periods=mp).mean() - mx * my
    var = (X * X).rolling(d, min_periods=mp).mean() - mx * mx
    beta = cov / var.where(var.abs() > 1e-15)
    alpha = my - beta * mx
    fitted = alpha + beta * X
    rt = int(rettype)
    if rt == 0:
        return (Y - fitted).to_numpy()
    if rt == 1:
        return alpha.to_numpy()
    if rt == 2:
        return beta.to_numpy()
    if rt == 3:
        return fitted.to_numpy()
    if rt == 6:
        vy = (Y * Y).rolling(d, min_periods=mp).mean() - my * my
        return (cov * cov / (var * vy)).to_numpy()
    raise EvalError(f"ts_regression rettype={rt} not implemented in the sandbox (0,1,2,3,6 are)")


def _days_from_last_change(x):
    T, N = x.shape
    out = np.full((T, N), np.nan)
    last = np.full(N, np.nan)
    cnt = np.zeros(N)
    for t in range(T):
        v = x[t]
        changed = np.isfinite(v) & ~((v == last) | (np.isnan(v) & np.isnan(last)))
        cnt = np.where(changed, 0, cnt + 1)
        last = np.where(np.isfinite(v), v, last)
        out[t] = np.where(np.isfinite(last), cnt, np.nan)
    return out


def _last_diff_value(x, d):
    T, N = x.shape
    out = np.full((T, N), np.nan)
    for t in range(T):
        cur = x[t]
        res = np.full(N, np.nan)
        found = np.zeros(N, bool)
        for k in range(1, min(d, t) + 1):
            v = x[t - k]
            hit = ~found & np.isfinite(v) & (v != cur)
            res[hit] = v[hit]
            found |= hit
            if found.all():
                break
        out[t] = res
    return out


def _kth_element(x, d, k, ignore="NaN"):
    T, N = x.shape
    k = int(k)
    out = np.full((T, N), np.nan)
    count = np.zeros((T, N))
    for lag in range(d):
        xl = _shift(x, lag)
        valid = np.isfinite(xl) if str(ignore).lower() == "nan" else np.ones_like(xl, bool)
        count = count + valid
        take = valid & (count == k) & np.isnan(out)
        out[take] = xl[take]
    return out


def _hump(x, h=0.01):  # APPROX
    T, N = x.shape
    out = np.full((T, N), np.nan)
    prev = np.full(N, np.nan)
    for t in range(T):
        v = x[t]
        scale = np.nanmean(np.abs(v)) if np.isfinite(v).any() else np.nan
        move = np.abs(v - prev) > h * (scale if scale == scale else 0)
        newv = np.where(np.isnan(prev) | move, v, prev)
        newv = np.where(np.isfinite(v), newv, np.nan)
        out[t] = newv
        prev = np.where(np.isfinite(newv), newv, prev)
    return out


def _trade_when(c, y, z):
    T, N = y.shape
    c, z = _arr(c, (T, N)), _arr(z, (T, N))
    out = np.full((T, N), np.nan)
    prev = np.full(N, np.nan)
    for t in range(T):
        cur = np.where(c[t] > 0, y[t], prev)
        cur = np.where(z[t] > 0, np.nan, cur)
        out[t] = cur
        prev = cur
    return out


def _target_tvr_decay(x, target=0.1, lambda_min=0.0, lambda_max=1.0):  # APPROX: exp smoothing to hit turnover
    best, best_err = x, 1e9
    for lam in np.linspace(max(lambda_min, 0.01), min(lambda_max, 0.99), 12):
        y = _df(x).ewm(alpha=1 - lam, ignore_na=True).mean().to_numpy()
        w = y - np.nanmean(y, axis=1, keepdims=True)
        w = w / np.nansum(np.abs(w), axis=1, keepdims=True)
        tv = np.nanmean(np.nansum(np.abs(np.diff(w, axis=0)), axis=1))
        if abs(tv - target) < best_err:
            best, best_err = y, abs(tv - target)
    return best


class Evaluator:
    def __init__(self, data: Data):
        self.data = data
        self.shape = (data.T, data.N)

    def __call__(self, expression: str) -> np.ndarray:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            return self._run(expression)

    def _run(self, expression: str) -> np.ndarray:
        prog = fx.parse(expression)
        env: Dict[str, np.ndarray] = {}
        val = None
        for st in prog.statements:
            if isinstance(st, fx.Assign):
                env[st.target] = self._ev(st.value, env)
                val = env[st.target]
            else:
                val = self._ev(st, env)
        out = _arr(val, self.shape).astype(float)
        out[~np.isfinite(out)] = np.nan
        return out

    # -------------------------------------------------------------- eval
    def _ev(self, n, env):
        if isinstance(n, fx.Num):
            return n.value
        if isinstance(n, fx.Str):
            return n.value
        if isinstance(n, fx.Name):
            if n.id in env:
                return env[n.id]
            low = n.id.lower()
            if low == "true":
                return 1.0
            if low == "false":
                return 0.0
            if low == "nan":
                return np.nan
            if n.id in GROUP_NAMES and n.id not in self.data.groups:
                if n.id == "market":
                    return np.zeros(self.shape)
                raise EvalError(f"group '{n.id}' not in sandbox data")
            return self.data.get(n.id)
        if isinstance(n, fx.Unary):
            v = self._ev(n.operand, env)
            return -v if n.op == "-" else np.where(np.isnan(v), np.nan, (np.asarray(v) <= 0).astype(float))
        if isinstance(n, fx.BinOp):
            return self._call(fx.INFIX_NAMES[n.op], [n.left, n.right], {}, env)
        if isinstance(n, fx.Ternary):
            return self._call("if_else", [n.cond, n.a, n.b], {}, env)
        if isinstance(n, fx.Call):
            return self._call(n.func, n.args, dict(n.kwargs), env)
        raise EvalError(f"cannot evaluate {type(n).__name__}")

    def _call(self, f, args, kwargs, env):
        S = self.shape
        if f.startswith("vec_"):
            node = args[0]
            if not isinstance(node, fx.Name) or node.id not in self.data.vectors:
                raise EvalError(f"{f} needs a VECTOR field")
            v = self.data.vectors[node.id]
            import warnings
            with warnings.catch_warnings(), np.errstate(all="ignore"):
                warnings.simplefilter("ignore")
                ops = {"vec_avg": lambda z: np.nanmean(z, axis=2), "vec_sum": lambda z: np.nansum(z, axis=2),
                       "vec_max": lambda z: np.nanmax(z, axis=2), "vec_min": lambda z: np.nanmin(z, axis=2),
                       "vec_stddev": lambda z: np.nanstd(z, axis=2),
                       "vec_count": lambda z: np.isfinite(z).sum(axis=2).astype(float),
                       "vec_range": lambda z: np.nanmax(z, axis=2) - np.nanmin(z, axis=2)}
                if f not in ops:
                    raise EvalError(f"unknown vector operator {f}")
                out = ops[f](v)
                if f == "vec_sum":
                    out = np.where(np.isfinite(v).any(axis=2), out, np.nan)
                return out
        a = [self._ev(x, env) for x in args]
        kw = {k: self._ev(v, env) for k, v in kwargs.items()}
        A = [(_arr(x, S) if not isinstance(x, str) else x) for x in a]

        def p(i, name, default):
            if name in kw:
                return kw[name]
            if i < len(a):
                return a[i]
            return default

        with np.errstate(all="ignore"):
            # ---------------------------------------------------- arithmetic
            if f == "add":
                if kw.get("filter"):
                    return sum(np.nan_to_num(x) for x in A)
                out = A[0]
                for x in A[1:]:
                    out = out + x
                return out
            if f == "subtract":
                if kw.get("filter"):
                    out = np.nan_to_num(A[0])
                    for x in A[1:]:
                        out = out - np.nan_to_num(x)
                    return out
                out = A[0]
                for x in A[1:]:
                    out = out - x
                return out
            if f == "multiply":
                out = np.nan_to_num(A[0], nan=1.0) if kw.get("filter") else A[0]
                for x in A[1:]:
                    out = out * (np.nan_to_num(x, nan=1.0) if kw.get("filter") else x)
                return out
            if f == "divide":
                r = A[0] / A[1]
                return np.where(np.isfinite(r), r, np.nan)
            if f == "inverse":
                r = 1.0 / A[0]
                return np.where(np.isfinite(r), r, np.nan)
            if f == "abs":
                return np.abs(A[0])
            if f == "log":
                return np.where(A[0] > 0, np.log(np.where(A[0] > 0, A[0], 1)), np.nan)
            if f == "sqrt":
                return np.where(A[0] >= 0, np.sqrt(np.abs(A[0])), np.nan)
            if f == "sign":
                return np.sign(A[0])
            if f == "reverse":
                return -A[0]
            if f == "power":
                return np.power(A[0], A[1])
            if f == "signed_power":
                return np.sign(A[0]) * np.power(np.abs(A[0]), A[1])
            if f == "max":
                return np.maximum.reduce(A)
            if f == "min":
                return np.minimum.reduce(A)
            if f == "to_nan":
                val = float(kw.get("value", 0))
                if kw.get("reverse"):
                    return np.where(np.isnan(A[0]), val, A[0])
                return np.where(A[0] == val, np.nan, A[0])
            if f == "densify":
                return A[0]
            # ---------------------------------------------------- logical
            cmp = {"less": np.less, "less_equal": np.less_equal, "greater": np.greater,
                   "greater_equal": np.greater_equal, "equal": np.equal, "not_equal": np.not_equal}
            if f in cmp:
                r = cmp[f](A[0], A[1]).astype(float)
                return np.where(np.isnan(A[0]) | np.isnan(A[1]), np.nan, r)
            if f == "and":
                return np.where(np.isnan(A[0]) | np.isnan(A[1]), np.nan, ((A[0] > 0) & (A[1] > 0)).astype(float))
            if f == "or":
                return np.where(np.isnan(A[0]) & np.isnan(A[1]), np.nan, ((A[0] > 0) | (A[1] > 0)).astype(float))
            if f == "not":
                return np.where(np.isnan(A[0]), np.nan, (A[0] <= 0).astype(float))
            if f == "is_nan":
                return np.isnan(A[0]).astype(float)
            if f == "if_else":
                return np.where(np.isnan(A[0]), np.nan, np.where(A[0] > 0, A[1], A[2]))
            # ---------------------------------------------------- time series
            if f == "ts_delay":
                return _shift(A[0], int(a[1]))
            if f == "ts_delta":
                return A[0] - _shift(A[0], int(a[1]))
            if f in ("ts_sum", "ts_mean", "ts_std_dev", "ts_max", "ts_min", "ts_av_diff", "ts_zscore", "ts_scale"):
                d = int(a[1])
                R = _df(A[0]).rolling(d, min_periods=_minp(d))
                if f == "ts_sum":
                    return R.sum().to_numpy()
                if f == "ts_mean":
                    return R.mean().to_numpy()
                if f == "ts_std_dev":
                    return R.std(ddof=0).to_numpy()
                if f == "ts_max":
                    return R.max().to_numpy()
                if f == "ts_min":
                    return R.min().to_numpy()
                if f == "ts_av_diff":
                    return A[0] - R.mean().to_numpy()
                if f == "ts_zscore":
                    return (A[0] - R.mean().to_numpy()) / np.where(R.std(ddof=0).to_numpy() > 0, R.std(ddof=0).to_numpy(), np.nan)
                if f == "ts_scale":
                    mn, mx = R.min().to_numpy(), R.max().to_numpy()
                    return (A[0] - mn) / np.where(mx - mn > 0, mx - mn, np.nan) + float(p(2, "constant", 0))
            if f == "ts_product":
                d = int(a[1])
                return _windows(A[0], d, lambda w: np.where(np.isfinite(w).all(axis=-1), np.prod(w, axis=-1), np.nan))
            if f == "ts_rank":
                return _ts_rank(A[0], int(a[1]), float(p(2, "constant", 0)))
            if f == "ts_quantile":
                r = _ts_rank(A[0], int(a[1]))
                return ndtri(np.clip(r, 0.001, 0.999))
            if f == "ts_arg_max":
                return _ts_argmax(A[0], int(a[1]), True)
            if f == "ts_arg_min":
                return _ts_argmax(A[0], int(a[1]), False)
            if f == "ts_decay_linear":
                return _ts_decay_linear(A[0], int(a[1]), bool(p(2, "dense", False)))
            if f == "ts_backfill":
                d = int(p(1, "lookback", 21))
                return _df(A[0]).ffill(limit=d).to_numpy()
            if f == "ts_count_nans":
                d = int(a[1])
                return _df(np.isnan(A[0]).astype(float)).rolling(d, min_periods=1).sum().to_numpy()
            if f == "ts_corr":
                d = int(a[2])
                return _df(A[0]).rolling(d, min_periods=_minp(d)).corr(_df(A[1])).to_numpy()
            if f == "ts_covariance":
                d = int(a[2])
                return _df(A[0]).rolling(d, min_periods=_minp(d)).cov(_df(A[1])).to_numpy()
            if f == "ts_regression":
                return _ts_regression(A[0], A[1], int(a[2]), int(p(3, "lag", 0)), int(p(4, "rettype", 0)))
            if f == "ts_step":
                return np.broadcast_to(np.arange(1, S[0] + 1, dtype=float)[:, None], S).copy()
            if f == "days_from_last_change":
                return _days_from_last_change(A[0])
            if f == "last_diff_value":
                return _last_diff_value(A[0], int(a[1]))
            if f == "kth_element":
                return _kth_element(A[0], int(a[1]), int(p(2, "k", 1)), kw.get("ignore", "NaN"))
            if f == "hump":
                return _hump(A[0], float(p(1, "hump", 0.01)))
            if f == "jump_decay":  # APPROX
                d = int(a[1])
                sens, force = float(kw.get("sensitivity", 0.5)), float(kw.get("force", 0.1))
                prev = _shift(A[0], 1)
                sd = _df(A[0]).rolling(d, min_periods=_minp(d)).std().to_numpy()
                jump = np.abs(A[0] - prev) > sens * sd
                return np.where(jump, prev + force * (A[0] - prev), A[0])
            if f in ("ts_target_tvr_decay", "ts_target_tvr_delta_limit"):  # APPROX
                return _target_tvr_decay(A[0], float(kw.get("target_tvr", 0.1)), float(kw.get("lambda_min", 0)),
                                         float(kw.get("lambda_max", 1)))
            # ---------------------------------------------------- cross-sectional
            if f == "rank":
                return _row_rank(A[0])
            if f == "zscore":
                m, s = np.nanmean(A[0], 1, keepdims=True), np.nanstd(A[0], 1, keepdims=True)
                return (A[0] - m) / np.where(s > 0, s, np.nan)
            if f == "normalize":
                out = A[0] - np.nanmean(A[0], 1, keepdims=True)
                if kw.get("useStd"):
                    out = out / np.nanstd(A[0], 1, keepdims=True)
                lim = float(kw.get("limit", 0.0))
                return np.clip(out, -lim, lim) if lim > 0 else out
            if f == "quantile":
                r = _row_rank(A[0])
                n = np.isfinite(A[0]).sum(1, keepdims=True)
                u = (r * (n - 1) + 0.5) / np.maximum(n, 1)
                drv = str(kw.get("driver", "gaussian")).lower()
                sig = float(kw.get("sigma", 1.0))
                if drv == "uniform":
                    return (u - 0.5) * sig
                if drv == "cauchy":
                    return np.tan(np.pi * (u - 0.5)) * sig
                return ndtri(np.clip(u, 1e-6, 1 - 1e-6)) * sig
            if f == "scale":
                x = A[0]
                tot = float(kw.get("scale", 1))
                return x / np.nansum(np.abs(x), 1, keepdims=True) * tot
            if f == "scale_down":
                mn, mx = np.nanmin(A[0], 1, keepdims=True), np.nanmax(A[0], 1, keepdims=True)
                return (A[0] - mn) / np.where(mx - mn > 0, mx - mn, np.nan) - float(kw.get("constant", 0))
            if f == "winsorize":
                sd = float(kw.get("std", 4))
                m, s = np.nanmean(A[0], 1, keepdims=True), np.nanstd(A[0], 1, keepdims=True)
                return np.clip(A[0], m - sd * s, m + sd * s)
            if f == "vector_neut":
                x, y = A[0], A[1]
                m = np.isfinite(x) & np.isfinite(y)
                xy = np.nansum(np.where(m, x * y, 0), 1, keepdims=True)
                yy = np.nansum(np.where(m, y * y, 0), 1, keepdims=True)
                return x - xy / np.where(yy > 0, yy, np.nan) * y
            # ---------------------------------------------------- transformational
            if f == "bucket":
                x = A[0]
                if "buckets" in kw:
                    edges = np.array([float(v) for v in str(kw["buckets"]).split(",")])
                else:
                    edges = _parse_range(kw.get("range", "0,1,0.1"))
                ids = np.digitize(x, edges).astype(float)
                ids[np.isnan(x)] = np.nan if not kw.get("NaNGroup") else -1
                return ids
            if f == "trade_when":
                return _trade_when(A[0], A[1], A[2])
            # ---------------------------------------------------- group
            if f == "group_cartesian_product":
                g1, g2 = A[0], A[1]
                return g1 * (np.nanmax(g2) + 1) + g2
            if f in ("group_neutralize", "group_rank", "group_zscore", "group_scale", "group_max", "group_min"):
                x, g = A[0], A[1]
                if f == "group_neutralize":
                    return x - _group_apply(x, g, "mean")
                return _group_apply(x, g, f.split("_")[1])
            if f == "group_mean":
                x, w, g = A[0], A[1], A[2]
                return _group_apply(x, g, "mean", weight=w)
            if f == "group_backfill":  # APPROX
                x, g, d = A[0], A[1], int(a[2])
                gm = _group_apply(_df(x).rolling(d, min_periods=1).mean().to_numpy(), g, "mean")
                return np.where(np.isnan(x), gm, x)
        raise EvalError(f"operator '{f}' not available in the sandbox")
