"""Pre-simulation checks: catch the mistakes that waste simulations.

Severity
--------
* ``error``   - BRAIN will reject it, or it is economically meaningless
                (e.g. ranking a currency ISO code). Never simulate.
* ``warning`` - legal but a known cause of failing checks or overfitting.
* ``info``    - teaching notes.

Every rule here comes from something observed in your zip or from
WorldQuant's own guidance:

* operators not on your Gold list (several zip notebooks use them)
* named-only parameters passed positionally -> "Invalid number of inputs"
  and, in a multi-simulation, ONE such error cancels all ten alphas
* VECTOR fields used without a vec_* reducer, or vec_* on a MATRIX field
* a non-GROUP value passed where a group is required
* unused variables in multi-statement expressions ("Found unused variables")
* identifiers/dates used as numbers (the ITERATOR templates did this)
* windows that mean nothing economically (WQ webinar: "days should reflect
  the alpha idea"), short ts_delta on quarterly data, bucket() on raw cap,
  unbounded outputs (CONCENTRATED_WEIGHT), too many fields/operators
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from . import fastexpr as fx
from .concepts import NON_NUMERIC
from .config import ECONOMIC_WINDOWS
from .operators import GOLD, LITERALS, NOT_ON_YOUR_LIST, STANDARD_GROUPS, OperatorRegistry

# Wrappers whose output is bounded / outlier-safe (help pass CONCENTRATED_WEIGHT)
BOUNDED = {"rank", "group_rank", "ts_rank", "ts_scale", "group_scale", "scale_down", "quantile",
           "ts_quantile", "winsorize", "sign", "zscore", "group_zscore", "ts_zscore", "normalize",
           "if_else", "trade_when", "greater", "less", "and", "or", "not", "bucket", "min", "max"}
# Operators that do NOT bound their input (the output scale is the input scale)
PASSTHROUGH = {"ts_decay_linear", "ts_mean", "ts_backfill", "group_neutralize", "ts_delay", "hump",
               "reverse", "multiply", "add", "subtract", "signed_power", "vector_neut", "ts_target_tvr_decay"}
SLOW_NATURES = {"stock", "flow", "estimate"}


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    fix: str = ""

    def __str__(self):
        s = f"[{self.severity.upper()}] {self.code}: {self.message}"
        return s + (f"\n        fix: {self.fix}" if self.fix else "")


@dataclass
class LintResult:
    expression: str
    issues: List[Issue] = field(default_factory=list)
    fields: List[str] = field(default_factory=list)
    operators: List[str] = field(default_factory=list)
    depth: int = 0
    canonical: str = ""

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]

    def report(self) -> str:
        head = "OK - safe to simulate" if self.ok else "BLOCKED - fix the errors before simulating"
        lines = [head, f"  fields: {', '.join(self.fields) or '-'} | operators: {len(self.operators)} "
                       f"| depth: {self.depth}"]
        lines += [f"  {i}" for i in self.issues]
        return "\n".join(lines)


class Linter:
    def __init__(self, registry: OperatorRegistry = GOLD, field_info: Optional[Dict[str, dict]] = None,
                 strict_fields: bool = False):
        """field_info: {field_id: {"type": MATRIX|VECTOR|GROUP, "nature": ..., "coverage": ...}}.
        strict_fields: unknown identifiers become errors (use when the catalog covers the context)."""
        self.reg = registry
        self.fields = field_info or {}
        self.strict = strict_fields

    @classmethod
    def for_context(cls, catalog, region: str, universe: Optional[str] = None, delay: int = 1,
                    registry: OperatorRegistry = GOLD) -> "Linter":
        df = catalog.fields(region, universe, delay)
        info = {}
        if not df.empty:
            for r in df[["id", "type", "nature", "coverage", "description"]].itertuples(index=False):
                info[r.id] = {"type": r.type, "nature": r.nature, "coverage": r.coverage,
                              "description": r.description or ""}
        return cls(registry, info, strict_fields=bool(info))

    # ---------------------------------------------------------------- api
    def lint(self, expression: str) -> LintResult:
        res = LintResult(expression=expression)
        try:
            prog = fx.parse(expression)
        except fx.ParseError as e:
            res.issues.append(Issue("error", "SYNTAX", str(e), "check brackets, commas and quotes"))
            return res
        res.canonical = fx.to_string(prog)
        res.depth = fx.depth(prog)
        res.operators = fx.operators_used(prog)
        assigned: Dict[str, fx.Node] = {}
        used_vars: Set[str] = set()
        all_fields: List[str] = []

        for idx, stmt in enumerate(prog.statements):
            node = stmt.value if isinstance(stmt, fx.Assign) else stmt
            for n in fx.walk(node):
                if isinstance(n, fx.Name) and n.id in assigned:
                    used_vars.add(n.id)
            self._check_node(node, res, assigned, all_fields)
            if isinstance(stmt, fx.Assign):
                if stmt.target in self.reg:
                    res.issues.append(Issue("error", "SHADOWS_OPERATOR",
                                            f"variable '{stmt.target}' has the name of an operator",
                                            "rename the variable"))
                assigned[stmt.target] = stmt.value
            elif idx < len(prog.statements) - 1:
                res.issues.append(Issue("warning", "DEAD_STATEMENT",
                                        f"statement {idx + 1} is not assigned and not last - it has no effect"))
        if isinstance(prog.statements[-1], fx.Assign):
            res.issues.append(Issue("info", "LAST_IS_ASSIGNMENT",
                                    "the last statement is an assignment; BRAIN uses its value as the alpha",
                                    "end with the variable name, e.g. '...; alpha'"))
        unused = [v for v in assigned if v not in used_vars and
                  not (isinstance(prog.statements[-1], fx.Assign) and prog.statements[-1].target == v)]
        for v in unused:
            res.issues.append(Issue("error", "UNUSED_VARIABLE", f"variable '{v}' is assigned but never used",
                                    "BRAIN rejects this ('Found unused variables'); delete it or use it"))

        res.fields = sorted(set(all_fields))
        self._structure_checks(prog, res, assigned)
        return res

    # ------------------------------------------------------ node checks
    def _check_node(self, node: fx.Node, res: LintResult, assigned: Dict[str, fx.Node], all_fields: List[str]):
        reduced = {id(a) for n in fx.walk(node) if isinstance(n, fx.Call) and
                   (self.reg.get(n.func) and self.reg.get(n.func).category == "Vector") for a in n.args}
        for n in fx.walk(node):
            if isinstance(n, fx.Name) and id(n) not in reduced and \
                    self.fields.get(n.id, {}).get("type") == "VECTOR" and n.id not in assigned:
                res.issues.append(Issue("error", "VECTOR_NEEDS_REDUCER",
                                        f"'{n.id}' is a VECTOR field (several values per stock per day) used as a matrix",
                                        f"reduce it first: vec_avg({n.id}) (or vec_sum / vec_count / vec_max ...)"))
        for n in fx.walk(node):
            if isinstance(n, fx.Call):
                self._check_call(n, res, assigned)
            elif isinstance(n, fx.Name):
                self._check_name(n, res, assigned, all_fields)

    def _check_name(self, n: fx.Name, res: LintResult, assigned, all_fields):
        name = n.id
        if name in assigned or name in LITERALS or name in STANDARD_GROUPS:
            return
        if name in self.reg:
            res.issues.append(Issue("error", "OPERATOR_AS_FIELD", f"'{name}' is an operator used without ()"))
            return
        all_fields.append(name)
        info = self.fields.get(name)
        if info is None:
            if self.strict:
                near = difflib.get_close_matches(name, list(self.fields), n=3, cutoff=0.75)
                res.issues.append(Issue("error", "UNKNOWN_FIELD",
                                        f"'{name}' is not a field in this region/universe/delay",
                                        f"did you mean: {', '.join(near)}" if near else
                                        "search the catalog; fields differ by region"))
            return
        nature = info.get("nature")
        if nature in ("identifier", "date"):
            res.issues.append(Issue("error", "NOT_A_SIGNAL",
                                    f"'{name}' is a {nature} field ({info.get('description', '')[:60]}); "
                                    "its numeric value means nothing economically",
                                    "pick a field that measures something about the company"))
        cov = info.get("coverage")
        if cov is not None and cov == cov and cov < 0.3:
            res.issues.append(Issue("warning", "LOW_COVERAGE", f"'{name}' covers only {cov:.0%} of the universe",
                                    "wrap in ts_backfill(x, 63) or pick a better-covered field"))

    def _check_call(self, c: fx.Call, res: LintResult, assigned):
        spec = self.reg.get(c.func)
        if spec is None:
            if c.func in NOT_ON_YOUR_LIST:
                res.issues.append(Issue("error", "NOT_ON_YOUR_LIST",
                                        f"'{c.func}' is not in your operator list (operators.pdf)",
                                        "if your account has it, download BRAIN's live operator list "
                                        "(cockpit, Account tab) and the linter will accept it"))
            else:
                near = difflib.get_close_matches(c.func, self.reg.names(), n=3, cutoff=0.6)
                res.issues.append(Issue("error", "UNKNOWN_OPERATOR", f"'{c.func}' is not a known operator",
                                        f"did you mean: {', '.join(near)}" if near else ""))
            return
        npos, nkw = len(c.args), len(c.kwargs)
        if spec.variadic:
            if npos < spec.required:
                res.issues.append(Issue("error", "ARITY", f"{c.func} needs at least {spec.required} inputs, got {npos}",
                                        spec.signature))
        else:
            if npos < spec.required:
                res.issues.append(Issue("error", "ARITY", f"{c.func} needs {spec.required} inputs, got {npos}",
                                        spec.signature))
            if npos > len(spec.params):
                res.issues.append(Issue("error", "ARITY", f"{c.func} takes at most {len(spec.params)} inputs, got {npos}",
                                        spec.signature))
            for i in range(spec.required, min(npos, len(spec.params))):
                p = spec.params[i]
                if p in spec.named_only:
                    res.issues.append(Issue("error", "NAMED_PARAMETER",
                                            f"{c.func}: '{p}' must be passed by name - positional fails with "
                                            "'Invalid number of inputs' and cancels a whole multi-simulation",
                                            f"write {c.func}(..., {p}={fx.to_string(c.args[i])})"))
        for k, v in c.kwargs:
            if k not in spec.params and not spec.variadic:
                res.issues.append(Issue("error", "UNKNOWN_PARAMETER", f"{c.func} has no parameter '{k}'", spec.signature))
        # argument kinds
        bound = list(zip(spec.params, c.args)) + [(k, v) for k, v in c.kwargs]
        for pname, arg in bound:
            kind = spec.kind_of(pname)
            if kind == "window":
                self._check_window(c.func, arg, res)
            elif kind == "group":
                self._check_group_arg(c.func, arg, res, assigned)
            elif kind == "vector":
                self._check_vector_arg(c.func, arg, res)
        # specific semantic checks
        if c.func == "bucket" and c.args:
            inner = c.args[0]
            if not (isinstance(inner, fx.Call) and inner.func in ("rank", "group_rank", "ts_rank", "scale_down", "quantile")):
                if not any(k == "buckets" for k, _ in c.kwargs):
                    res.issues.append(Issue("warning", "BUCKET_SCALE",
                                            "bucket(range='0,1,...') expects values in [0,1]; the input is not ranked",
                                            "use bucket(rank(x), range=\"0,1,0.1\") (WorldQuant webinar example)"))
        if c.func in ("ts_delta", "ts_av_diff", "ts_zscore", "ts_std_dev") and len(c.args) >= 2:
            fld = self._root_field(c.args[0])
            d = self._num(c.args[1])
            if fld and d is not None and d < 63 and self.fields.get(fld, {}).get("nature") in ("stock", "flow"):
                res.issues.append(Issue("warning", "QUARTERLY_SHORT_WINDOW",
                                        f"{c.func}({fld}, {int(d)}): '{fld}' updates quarterly, so a {int(d)}-day "
                                        "change is zero most days", "use d >= 63 (a quarter) or 252 (a year)"))
        if c.func in ("divide", "inverse") and c.args:
            den = c.args[-1]
            if isinstance(den, fx.Name) and self.fields.get(den.id, {}).get("nature") == "count":
                res.issues.append(Issue("warning", "DIVIDE_BY_COUNT", f"dividing by count field '{den.id}' "
                                        "explodes when it is 0", f"use ({fx.to_string(den)} + 1)"))

    def _check_window(self, func: str, arg: fx.Node, res: LintResult):
        d = self._num(arg)
        if d is None:
            if not isinstance(arg, fx.Name):
                res.issues.append(Issue("error", "WINDOW_NOT_NUMBER", f"{func}: the window must be a number of days"))
            return
        if d != int(d) or d < 1:
            res.issues.append(Issue("error", "BAD_WINDOW", f"{func}: window {d} must be a positive integer"))
        elif int(d) not in ECONOMIC_WINDOWS and d > 3:
            nearest = min(ECONOMIC_WINDOWS, key=lambda w: abs(w - d))
            res.issues.append(Issue("info", "ARBITRARY_WINDOW",
                                    f"{func}: {int(d)} days does not correspond to a calendar period",
                                    f"prefer {nearest} ({ECONOMIC_WINDOWS[nearest]}) unless the idea says otherwise"))
        if d > 756:
            res.issues.append(Issue("warning", "LONG_WINDOW", f"{func}: {int(d)} days eats most of the backtest's history"))

    def _check_group_arg(self, func: str, arg: fx.Node, res: LintResult, assigned):
        if isinstance(arg, fx.Name):
            if arg.id in STANDARD_GROUPS or arg.id in assigned:
                return
            t = self.fields.get(arg.id, {}).get("type")
            if t and t != "GROUP":
                res.issues.append(Issue("error", "NOT_A_GROUP", f"{func}: '{arg.id}' is a {t} field, not a GROUP",
                                        "use subindustry/industry/sector or bucket(rank(x), range=\"0,1,0.1\")"))
            return
        if isinstance(arg, fx.Call) and arg.func in ("bucket", "densify", "group_cartesian_product"):
            return
        res.issues.append(Issue("error", "NOT_A_GROUP", f"{func}: group argument must be a grouping, "
                                f"got {fx.to_string(arg)}", "use a GROUP field or bucket(...)"))

    def _check_vector_arg(self, func: str, arg: fx.Node, res: LintResult):
        if isinstance(arg, fx.Name):
            t = self.fields.get(arg.id, {}).get("type")
            if t and t != "VECTOR":
                res.issues.append(Issue("error", "NOT_A_VECTOR", f"{func}() needs a VECTOR field; '{arg.id}' is {t}",
                                        f"use {arg.id} directly"))
        elif isinstance(arg, fx.Call):
            res.issues.append(Issue("error", "NOT_A_VECTOR", f"{func}() must be applied directly to a VECTOR field"))

    # ---------------------------------------------------- whole-alpha checks
    def _structure_checks(self, prog: fx.Program, res: LintResult, assigned: Dict[str, fx.Node]):
        n_fields = len(set(res.fields))
        n_ops = len(res.operators)
        if res.depth > 6:
            res.issues.append(Issue("warning", "DEEP_NESTING", f"nesting depth {res.depth} > 6 can time out "
                                    "and is hard to explain", "split into named steps or simplify"))
        if n_fields > 3:
            res.issues.append(Issue("warning", "TOO_MANY_FIELDS", f"{n_fields} fields - an ensemble with vendor "
                                    "risk; each field must earn its place", "start with the core 1-2 fields"))
        if n_ops > 10:
            res.issues.append(Issue("warning", "TOO_MANY_OPERATORS", f"{n_ops} operator applications - high "
                                    "fitting power (WQ webinar rule 3)", "remove steps you cannot explain"))
        if not res.fields:
            res.issues.append(Issue("error", "NO_DATA", "the expression uses no data field"))
        # bounded output?
        result = prog.result
        top = self._resolve(result, assigned)
        if not self._is_bounded(top, assigned):
            res.issues.append(Issue("warning", "UNBOUNDED_OUTPUT",
                                    "the final output is not ranked/standardised - a few extreme stocks can "
                                    "dominate (CONCENTRATED_WEIGHT check)",
                                    "wrap the outside in rank(...) or group_rank(..., subindustry)"))
        # raw price level as the signal
        if isinstance(top, fx.Name) and self.fields.get(top.id, {}).get("nature") == "price":
            res.issues.append(Issue("warning", "RAW_PRICE", "a raw price level is not comparable across stocks",
                                    "use returns, ratios, or a time-series rank"))

    def _resolve(self, node, assigned, _seen=None):
        _seen = _seen or set()
        while isinstance(node, fx.Name) and node.id in assigned and node.id not in _seen:
            _seen.add(node.id)
            node = assigned[node.id]
        return node

    def _is_bounded(self, node, assigned, _d=0) -> bool:
        if _d > 20:
            return True
        node = self._resolve(node, assigned)
        if isinstance(node, fx.Num):
            return True
        if isinstance(node, fx.Unary):
            return self._is_bounded(node.operand, assigned, _d + 1)
        if isinstance(node, fx.Ternary):
            return True
        if isinstance(node, fx.BinOp):
            if node.op in ("<", "<=", ">", ">=", "==", "!=", "&&", "||"):
                return True
            return self._is_bounded(node.left, assigned, _d + 1) and self._is_bounded(node.right, assigned, _d + 1)
        if isinstance(node, fx.Call):
            if node.func in BOUNDED:
                if node.func in ("min", "max"):
                    return all(self._is_bounded(a, assigned, _d + 1) for a in node.args)
                if node.func == "trade_when" and len(node.args) >= 2:
                    return self._is_bounded(node.args[1], assigned, _d + 1)
                if node.func == "if_else" and len(node.args) == 3:
                    return self._is_bounded(node.args[1], assigned, _d + 1) and self._is_bounded(node.args[2], assigned, _d + 1)
                return True
            if node.func in PASSTHROUGH and node.args:
                return all(self._is_bounded(a, assigned, _d + 1) for a in node.args
                           if not isinstance(a, fx.Num))
            return False
        return False

    @staticmethod
    def _num(node) -> Optional[float]:
        if isinstance(node, fx.Num):
            return node.value
        return None

    def _root_field(self, node) -> Optional[str]:
        """Field at the bottom of a chain like ts_backfill(field, d)."""
        while isinstance(node, fx.Call) and node.args:
            node = node.args[0]
        return node.id if isinstance(node, fx.Name) and node.id in self.fields else None


def lint(expression: str, catalog=None, region: str = "USA", universe: Optional[str] = None,
         delay: int = 1) -> LintResult:
    """Convenience: lint with field checks when a catalog for the context is available."""
    if catalog is not None and catalog.has_context(region, universe, delay):
        return Linter.for_context(catalog, region, universe, delay).lint(expression)
    return Linter().lint(expression)
