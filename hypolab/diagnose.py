"""Read a simulation result like an experienced researcher and decide the ONE
next step - or decide to stop.

The zip's filter only coloured alphas (and called strongly negative Sharpe
"baddie", although flipping its sign is a strong signal). This module
explains *why* an alpha failed, which constraint binds, and prescribes a
single, economically sensible change. It also tells you when to STOP: tuning
an idea with no signal is how overfit "99% trash" is produced.

Key arithmetic (BRAIN's published definition):
    fitness = sharpe * sqrt(|returns| / max(turnover, 0.125))
so below 12.5% turnover, smoothing CANNOT raise fitness - only more returns
or more Sharpe can. Above it, cutting turnover raises fitness directly.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from . import config, rules

FLOOR = 0.125

ERROR_HINTS = [
    (r"invalid number of inputs", "A parameter must be NAMED (e.g. winsorize(x, std=4), hump(x, hump=0.01))."),
    (r"invalid data field|unknown variable|not found", "A field does not exist in this region/universe/delay - "
                                                       "re-check with the catalog for THIS context."),
    (r"inaccessible or unknown operator|unknown operator", "That operator is not available to your account."),
    (r"must be an event data|vector", "A VECTOR field needs vec_avg()/vec_sum() first (or a matrix field was given to vec_*)."),
    (r"unused variable", "Remove variables you assign but never use."),
    (r"took too much resource|timeout|time out", "Expression too heavy: shorten long windows, reduce nesting, or simulate fewer at once."),
]


@dataclass
class Action:
    title: str
    why: str
    expression: Optional[str] = None
    settings: dict = field(default_factory=dict)
    kind: str = "climb"     # climb | flip | stop | fix | accept


@dataclass
class Diagnosis:
    verdict: str                      # PASS | NEAR | WEAK | NOISE | INVERTED | ERROR
    headline: str
    findings: List[str]
    actions: List[Action]
    metrics: dict

    @property
    def next(self) -> Optional[Action]:
        return self.actions[0] if self.actions else None

    def markdown(self) -> str:
        m = self.metrics
        v = str(self.verdict).lower()
        lines = [f'#### <span class="hl-verdict hl-v-{v}">{self.verdict}</span> {self.headline}']
        if m:
            def f(k, fmt="{:.2f}"):
                v = m.get(k)
                return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else fmt.format(v)
            lab = f" ({m['fitness_label']})" if m.get("fitness_label") else ""
            lines.append(f"Sharpe {f('sharpe')} | Fitness {f('fitness')}{lab} | Turnover {f('turnover', '{:.1%}')} | "
                         f"Returns {f('returns', '{:.1%}')} | Drawdown {f('drawdown', '{:.1%}')} | "
                         f"Train Sharpe {f('train_sharpe')} | Test Sharpe {f('test_sharpe')}")
        if self.findings:
            lines += ["", "**What the numbers say:**"] + [f"- {x}" for x in self.findings]
        if self.actions:
            lines += ["", "**Do this next (in order; do ONE, then re-read):**"]
            for i, a in enumerate(self.actions, 1):
                lines.append(f"{i}. **{a.title}** - {a.why}")
                if a.expression:
                    lines.append(f"   ```\n   {a.expression}\n   ```")
                if a.settings:
                    lines.append(f"   settings change: `{a.settings}`")
        return "\n".join(lines)


# ------------------------------------------------------------- transforms

def split_statements(expr: str) -> List[str]:
    out, depth, buf, quote = [], 0, [], None
    for ch in expr:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ";" and depth == 0:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if "".join(buf).strip():
        out.append("".join(buf).strip())
    return [s for s in out if s]


def wrap_result(expr: str, template: str) -> str:
    """Apply template (with {} for the alpha) to the final value of an expression."""
    parts = split_statements(expr)
    last = parts[-1]
    m = re.match(r"^([A-Za-z_]\w*)\s*=(?!=)\s*(.+)$", last, re.S)
    if m:
        parts[-1] = f"{m.group(1)} = {template.format(m.group(2))}"
    else:
        parts[-1] = template.format(last)
    return ";\n".join(parts)


def flip(expr: str) -> str:
    return wrap_result(expr, "-({})" if len(split_statements(expr)) == 1 else "-1 * ({})")


# ------------------------------------------------------------- diagnosis

def _limit(checks: list, name: str, default: float) -> float:
    for c in checks or []:
        if c.get("name") == name and c.get("limit") is not None:
            try:
                return float(c["limit"])
            except (TypeError, ValueError):
                pass
    return default


def _risk_set(settings: dict, turnover: float) -> Optional[str]:
    """SLOW for low-turnover signals, SLOW_AND_FAST for high-turnover ones (BRAIN_RULES N2), if the region offers it."""
    offered = config.region_neutralizations(settings.get("region", ""))
    want = "SLOW" if (turnover or 0) < 0.2 else "SLOW_AND_FAST"
    current = settings.get("neutralization")
    if want in offered and want != current:
        return want
    return None


def diagnose(summary: dict, expression: str = "", settings: Optional[dict] = None,
             yearly: Optional[pd.DataFrame] = None, expected_turnover=None, delay: int = 1,
             trials_so_far: int = 0) -> Diagnosis:
    settings = settings or {}
    st = config.settings()
    if summary.get("status") in ("ERROR", "REJECTED", "FAIL") or (not summary.get("alpha_id") and summary.get("error")):
        err = str(summary.get("error", ""))
        hint = next((h for p, h in ERROR_HINTS if re.search(p, err, re.I)), "Read the message; run the linter on the expression.")
        return Diagnosis("ERROR", "BRAIN could not simulate this expression", [err[:400]],
                         [Action("Fix the expression", hint, kind="fix")], {})

    checks = summary.get("checks") or []
    s = summary.get("is_sharpe") or 0.0
    fit = summary.get("is_fitness") or 0.0
    tvr = summary.get("is_turnover") or 0.0
    ret = summary.get("is_returns") or 0.0
    dd = summary.get("is_drawdown")
    trs, tes = summary.get("train_sharpe"), summary.get("test_sharpe")
    sharpe_min = _limit(checks, "LOW_SHARPE", st["min_sharpe_d1"] if delay else st["min_sharpe_d0"])
    fit_min = _limit(checks, "LOW_FITNESS", st["min_fitness_d1"] if delay else st["min_fitness_d0"])
    failed = set(summary.get("failed") or [])
    metrics = {"sharpe": s, "fitness": fit, "turnover": tvr, "returns": ret, "drawdown": dd,
               "train_sharpe": trs, "test_sharpe": tes}
    metrics["fitness_label"] = rules.fitness_label(fit, delay)
    findings: List[str] = []
    actions: List[Action] = []
    dec = int(settings.get("decay", 0) or 0)
    prof = summary.get("dataset_profile") or {}
    if prof.get("test"):
        findings.append(f"IS test BRAIN applies: {prof['test']}.")

    # ------------------------------------------------------ direction / signal
    if s <= -0.8 * sharpe_min:
        flipped = flip(expression) if expression else None
        return Diagnosis(
            "INVERTED", f"strong signal in the OPPOSITE direction (Sharpe {s:.2f})",
            ["A large negative Sharpe is information, not garbage: the data rewards the opposite of your stated sign.",
             "Before flipping, ask whether the OPPOSITE mechanism has an economic story (e.g. continuation instead "
             "of reversal). If it does, flip once and log it. If not, the field may be coded the other way round "
             "(e.g. ratings where 1 = Strong Buy)."],
            [Action("Flip the sign once", "costs one trial; record the economic reason in the journal",
                    flipped, kind="flip")], metrics)
    if abs(s) < 0.5:
        return Diagnosis(
            "NOISE", f"no reliable signal (|Sharpe| {abs(s):.2f} < 0.5)",
            ["Tuning windows, decay or neutralization on a signal this weak is exactly how backtest overfitting "
             "happens: some variant will look good by luck.",
             f"After {trials_so_far + 1} trial(s) on this idea, the honest move is to stop."],
            [Action("Stop this rung", "move to the next rung of the ladder (a different mechanism), or to the next "
                    "idea. Write one line in the journal about why you think it failed.", kind="stop")], metrics)

    # ------------------------------------------------------- yearly stability
    if yearly is not None and not yearly.empty and "sharpe" in yearly.columns:
        ys = yearly["sharpe"].astype(float)
        neg = int((ys < 0).sum())
        findings.append(f"Yearly Sharpe: positive in {int((ys > 0).sum())}/{len(ys)} years "
                        f"(worst {ys.min():.2f} in {yearly.loc[ys.idxmin(), 'year'] if 'year' in yearly.columns else '?'}).")
        if neg > len(ys) / 3:
            findings.append("More than a third of years are negative - the signal is regime-dependent.")
    if trs is not None and tes is not None and trs > 0:
        if tes < 0.5 * trs:
            findings.append(f"Test-period Sharpe ({tes:.2f}) is less than half the train Sharpe ({trs:.2f}): "
                            "either decay of the anomaly or overfitting to the train years.")
        else:
            findings.append(f"Train {trs:.2f} vs test {tes:.2f}: holds up out of the selection window - good sign.")

    # --------------------------------------------------------- weak signal
    if s < sharpe_min:
        verdict = "WEAK" if s < 0.75 * sharpe_min else "NEAR"
        findings.append(f"Sharpe {s:.2f} is below the {sharpe_min:.2f} bar.")
        lc, sc = summary.get("is_longCount") or 0, summary.get("is_shortCount") or 0
        if lc and sc and (lc + sc) < 400:
            actions.append(Action("Raise coverage", f"only {lc + sc} names hold positions; sparse data makes Sharpe noisy",
                                  wrap_result(expression, "ts_backfill({}, 63)") if expression else None))
        if tvr > 0.45:
            actions.append(Action("Smooth before judging", f"turnover {tvr:.0%} - daily noise may be hiding the signal; "
                                  "average over a week", wrap_result(expression, "ts_mean({}, 5)") if expression else None))
        actions.append(Action("Climb the ladder", "try the next rung of the idea card: a different, economically "
                              "motivated construction - not a parameter sweep", kind="climb"))
        actions.append(Action("Boost with an independent second signal", "R.boost(result) pairs this alpha with "
                              "signals from a DIFFERENT mechanism/data category (value + quality, revisions + "
                              "sentiment) and predicts the gain before simulating. Same-mechanism legs add "
                              "correlation, not information.", kind="climb"))
        actions.append(Action("Know when to stop", f"you have used {trials_so_far + 1}/{st['max_sims_per_idea']} "
                              "simulations on this idea; stop at the budget.", kind="stop"))
        return Diagnosis(verdict, f"signal exists but is not strong enough (Sharpe {s:.2f})", findings, actions, metrics)

    # ------------------------------------------------------ sharpe OK: fitness
    if fit < fit_min:
        t_req = abs(ret) * (s / fit_min) ** 2 if fit_min > 0 else 0
        if tvr > FLOOR and t_req >= FLOOR:
            target_d = min(15, max(dec + 3, 5))
            findings.append(f"Fitness {fit:.2f} < {fit_min}. Turnover {tvr:.0%} is above the 12.5% floor, so cutting it "
                            f"to about {t_req:.0%} would lift fitness to the bar at the same Sharpe/returns.")
            actions.append(Action("Cut turnover with decay", "raise decay; it averages positions over several days",
                                  settings={"decay": target_d}))
            if expression:
                actions.append(Action("Or smooth inside the expression", "ts_decay_linear keeps the most recent days heavier",
                                      wrap_result(expression, "ts_decay_linear({}, 5)")))
                actions.append(Action("Or only trade meaningful changes", "hump ignores small daily changes",
                                      wrap_result(expression, "hump({}, hump=0.01)")))
        else:
            r_req = fit_min ** 2 * max(tvr, FLOOR) / max(s, 1e-6) ** 2
            findings.append(f"Fitness {fit:.2f} < {fit_min}. Turnover {tvr:.1%} is "
                            f"{'below' if tvr <= FLOOR else 'already near'} the 12.5% floor: smoothing will NOT help "
                            f"(it lowers returns). You need returns of about {r_req:.1%} instead of {ret:.1%}.")
            if dec:
                actions.append(Action("Remove decay", "below the floor, decay only dilutes returns", settings={"decay": 0}))
            actions.append(Action("Sharpen the signal", "shorter (still economic) windows, less backfill, or a more "
                                  "direct field; e.g. use a quarterly change instead of a yearly one", kind="climb"))
            actions.append(Action("Lower truncation pressure / neutralization", "if CONCENTRATED_WEIGHT passes easily, "
                                  "INDUSTRY instead of SUBINDUSTRY keeps more return", settings={"neutralization": "INDUSTRY"}))
        return Diagnosis("NEAR", "Sharpe is good enough; fitness is the binding constraint", findings, actions, metrics)

    # ------------------------------------------------------- remaining checks
    verdict, headline = "PASS", "clears Sharpe and fitness"
    if "HIGH_TURNOVER" in failed:
        actions.append(Action("Turnover above 70%", "raise decay or smooth", settings={"decay": max(dec + 4, 5)}))
    if "LOW_TURNOVER" in failed:
        actions.append(Action("Turnover below 1%", "the signal almost never changes: use a change/revision instead of "
                              "a level, or shorter backfill windows", kind="climb"))
    if "CONCENTRATED_WEIGHT" in failed:
        actions.append(Action("Weight concentrated in few stocks", "rank the output and/or lower truncation",
                              wrap_result(expression, "rank({})") if expression else None, {"truncation": 0.05}))
    if "LOW_SUB_UNIVERSE_SHARPE" in failed:
        # BRAIN: sub_sharpe >= 0.75 * sqrt(sub_size / size) * sharpe (BRAIN_RULES T3/T4)
        actions.append(Action("Signal lives in small/illiquid names", "decay the liquid and illiquid parts separately "
                              "(BRAIN's own tip): liquid names react faster, so they get the shorter decay. Also check "
                              "the expression has no size multiplier such as rank(-assets) or 1-rank(cap).",
                              wrap_result(expression, "ts_decay_linear({0}, 5) * rank(volume * close) + "
                                                      "ts_decay_linear({0}, 10) * (1 - rank(volume * close))")
                              if expression else None))
        actions.append(Action("Or neutralize within size buckets", "so large stocks carry their share",
                              wrap_result(expression, 'group_neutralize({}, bucket(rank(cap), range="0,1,0.1"))')
                              if expression else None))
    if {"LOW_2Y_SHARPE", "IS_LADDER_SHARPE"} & failed:
        why = ("the anomaly may be decaying or crowded. Do not tune it to the last two years - that is fitting "
               "noise. Try the same idea in another region instead.")
        if prof.get("single"):
            why = (f"as a Single Dataset Alpha it must clear a last-2-year Sharpe of {prof.get('cutoff')} (BRAIN may "
                   "lower it by 0.85 when turnover < 30% - not confirmed). " + why)
        actions.append(Action("Recent years are weak", why, kind="stop"))
    if {"SELF_CORRELATION", "PROD_CORRELATION"} & failed:
        # BRAIN's advice, in this order (BRAIN_RULES R1): keep the idea pure, change ONE thing to an equivalent.
        actions.append(Action("Too similar to existing alphas: swap ONE equivalent", "keep the idea, change one piece "
                              "to an equivalent: (1) an equivalent field (close -> vwap/open, a sibling field of the "
                              "same dataset), then (2) a similar operator (ts_mean -> ts_median, subtract -> divide), "
                              "then (3) a meaningful grouping (sector/industry/size bucket). Never change things just "
                              "to lower correlation - that is correlation fitting.", kind="climb"))
        risk = _risk_set(settings, tvr)
        if risk:
            actions.append(Action(f"Or try the {risk} risk set", "BRAIN suggests re-simulating good alphas with risk "
                                  "neutralization: some improve and come out less correlated (BRAIN_RULES N2/N5).",
                                  settings={"neutralization": risk}))
        actions.append(Action("If that fails, change the data", "correlation is mostly a property of the data "
                              "family: move to another dataset or mechanism.", kind="stop"))
    regional = [f for f in failed if f.startswith("LOW_GLB_")]
    if regional:
        actions.append(Action("Fails outside one region", f"{', '.join(regional)}: the data is US-heavy; blend with a "
                              "globally covered leg or use a regional universe", kind="climb"))
    pending = summary.get("pending") or []
    if failed:
        verdict, headline = "NEAR", f"good Sharpe/fitness but fails: {', '.join(sorted(failed))}"
    else:
        findings.append("No failing in-sample checks. Next: robustness battery, then the submission gate "
                        "(self-correlation + platform /check)." + (f" Pending checks: {', '.join(pending)}." if pending else ""))
        actions.append(Action("Run the robustness battery", "rank / binary / winsorize / window-twist tests before "
                              "you believe it", kind="accept"))
    if expected_turnover and (tvr < expected_turnover[0] / 2 or tvr > expected_turnover[1] * 1.5):
        findings.append(f"Turnover {tvr:.0%} is far from what this idea should produce "
                        f"({expected_turnover[0]:.0%}-{expected_turnover[1]:.0%}) - check the data is what you think.")
    return Diagnosis(verdict, headline, findings, actions, metrics)
