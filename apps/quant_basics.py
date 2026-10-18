import marimo

__generated_with = "0.23.16"
app = marimo.App(width="medium", app_title="HYPOLAB quant basics", css_file="hypolab.css", html_head_file="head.html")


@app.cell(hide_code=True)
def _():
    import sys

    import marimo as mo

    _root = mo.notebook_dir().parent if mo.notebook_dir() else None
    if _root is not None and str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    import pandas as pd

    from hypolab import playground as pg
    from hypolab.linter import Linter
    from hypolab.overfit import deflated_sharpe, noise_table
    from hypolab.robustness import variants
    from hypolab.sandbox.backtest import backtest
    from hypolab.sandbox.evaluator import Evaluator
    from hypolab.sandbox.market import make_market

    return Evaluator, Linter, backtest, deflated_sharpe, make_market, mo, noise_table, pd, pg, variants


@app.cell(hide_code=True)
def _(mo):
    mo.md("""
    # Quant basics, hands-on (no BRAIN account needed)

    A synthetic market with **known truths** (value, quality, analyst revisions, earnings drift, reversal,
    sentiment) plus **40 pure-noise fields** (`nz_000` ... `nz_039`). Everything runs on your laptop.

    By the end you will understand what an alpha is, what each operator does to the numbers, neutralization,
    Sharpe / turnover / returns / fitness, why the 12.5% turnover floor matters, and - most importantly -
    **how brute-force searching produces impressive-looking garbage**.
    """)
    return


@app.cell(hide_code=True)
def _(Evaluator, make_market, mo, pd):
    with mo.status.spinner(title="Building the practice market (500 stocks x 6 years) ..."):
        data = make_market()
        ev = Evaluator(data)
    mo.vstack([mo.md(f"**{data.T} days x {data.N} stocks, {len(data.fields)} fields.** Some of them:"),
               mo.ui.table(pd.Series(data.descriptions, name="description").head(32).reset_index()
                           .rename(columns={"index": "field"}), selection=None, page_size=8)])
    return data, ev


@app.cell(hide_code=True)
def _(ev, mo, pd):
    _day = -1
    _x = ev("rank(-ts_sum(returns, 5))")[_day]
    _df = pd.DataFrame({"last_week_return": ev("ts_sum(returns, 5)")[_day], "alpha_value": _x}) \
        .sort_values("alpha_value").head(5)
    mo.vstack([mo.md("""
    ## 1. An alpha is a vector of weights, every day

    BRAIN evaluates your expression for every stock each day. Positive values are **bought**, negative values
    are **sold short**, and the platform scales everything to a fixed book. `rank(x)` turns any number into its
    position in the cross-section (0 = lowest, 1 = highest); after neutralization the lowest ranks become shorts.
    Below: the five stocks `rank(-ts_sum(returns, 5))` likes least - last week's biggest winners.
    """), mo.ui.table(_df, selection=None)])
    return


@app.cell(hide_code=True)
def _(data, mo, pd, pg):
    _fig = pg.plot_distribution(["fnd_cfo", "rank(fnd_cfo)", "zscore(ts_backfill(fnd_cfo, 63))",
                                 "ts_rank(close, 63)"], data)
    _desc = pd.DataFrame({e: pg.describe(e, data) for e in ["ts_backfill(fnd_cfo, 63) / cap",
                                                          "rank(ts_backfill(fnd_cfo, 63) / cap)",
                                                          "winsorize(ts_backfill(fnd_cfo, 63) / cap, std=4)"]})
    mo.vstack([mo.md("""
    ## 2. Know the distribution each operator produces

    `rank` gives uniform 0..1. `zscore` gives mean 0, sd 1, and **tails survive**. `ts_rank` is the position
    within the stock's own history. Multiplying a 0..1 rank by an unbounded quantity lets the unbounded one
    dominate. `winsorize` clips the tails.
    """), _fig, mo.ui.table(_desc.reset_index().rename(columns={"index": "statistic"}), selection=None)])
    return


@app.cell(hide_code=True)
def _(backtest, data, ev, mo, pd):
    slow = "group_rank(ts_backfill(fnd_cfo, 252) / cap, subindustry)"      # value: slow, low turnover
    fast = "group_rank(-ts_sum(returns, 5), subindustry)"                   # reversal: fast, high turnover
    _rows = []
    for _d in (0, 3, 6, 10, 15):
        for _name, _e in (("slow value", slow), ("fast reversal", fast)):
            _r = backtest(ev(_e), data, decay=_d)
            _rows.append({"signal": _name, "decay": _d,
                          **{k: _r.stats[k] for k in ("sharpe", "turnover", "returns", "fitness")}})
    _piv = pd.DataFrame(_rows).pivot(index="decay", columns="signal", values=["turnover", "fitness"])
    _piv.columns = [f"{a} - {b}" for a, b in _piv.columns]
    mo.vstack([mo.md("""
    ## 3. The four numbers BRAIN judges

    * **Sharpe** = mean daily PnL / std daily PnL x sqrt(252): consistency of profits.
    * **Turnover** = share of the book traded per day.
    * **Returns** = annualised PnL / half the book.
    * **Fitness** = Sharpe x sqrt(|Returns| / max(Turnover, 0.125)).

    Below **12.5% turnover the divisor stops shrinking**: smoothing a slow signal further cannot raise fitness;
    it only lowers returns. Above 12.5%, cutting turnover raises fitness directly. For the **fast** signal below,
    decay cuts turnover and lifts fitness; for the **slow** one it does nothing useful. The Lab's diagnosis
    applies exactly this rule.
    """), mo.ui.table(_piv.round(3).reset_index(), selection=None)])
    return fast, slow


@app.cell(hide_code=True)
def _(data, mo, pd, pg, slow):
    _t = pd.concat([pg.run({"value, NONE": slow}, data, neutralization="NONE"),
                    pg.run({"value, SECTOR": slow}, data, neutralization="SECTOR"),
                    pg.run({"value, SUBINDUSTRY": slow}, data, neutralization="SUBINDUSTRY")])
    mo.vstack([mo.md("""
    ## 4. Neutralization: compare with peers, not with the market

    Without neutralization an alpha can just be a bet on one sector. `group_rank(x, subindustry)` and the
    neutralization setting remove those common bets, so only stock-specific skill remains.
    """), mo.ui.table(_t, selection=None)])
    return


@app.cell(hide_code=True)
def _(data, mo, pg):
    ideas = {
        "value (cash yield)": "group_rank(ts_backfill(fnd_cfo, 252) / cap, subindustry)",
        "quality score": "group_rank(ts_backfill(mdl_quality_score, 21), subindustry)",
        "revision breadth (rung 1)": "group_rank((anl_rev_up_30d - anl_rev_down_30d) / "
                                     "(anl_rev_up_30d + anl_rev_down_30d + 1), subindustry)",
        "revision breadth (rung 2)": "ts_mean(group_rank((anl_rev_up_30d - anl_rev_down_30d) / "
                                     "(anl_rev_up_30d + anl_rev_down_30d + 1), subindustry), 21)",
        "earnings drift (PEAD)": "group_rank(ts_backfill(ern_eps_surprise, 63), subindustry)",
        "1-week reversal": "group_rank(-ts_sum(returns, 5), subindustry)",
    }
    _fig = pg.pnl_plot({k: ideas[k] for k in ["revision breadth (rung 2)", "earnings drift (PEAD)",
                                              "value (cash yield)"]}, data, decay=2)
    mo.vstack([mo.md("""
    ## 5. Ideas with a mechanism - and the ladder

    Each planted truth matches an idea card. Notice **revision breadth**: rung 1 has a good Sharpe but fails
    fitness (too much turnover); rung 2 (a month of smoothing - an economic choice, analysts update monthly)
    passes. That is climbing the ladder, not parameter fishing.
    """), mo.ui.table(pg.run(ideas, data, decay=2), selection=None), _fig])
    return (ideas,)


@app.cell(hide_code=True)
def _(mo):
    sweep_btn = mo.ui.run_button(label="Run the brute-force sweep on 40 noise fields (1-2 minutes)", kind="warn")
    mo.vstack([mo.md("""
    ## 6. THE lesson: brute force manufactures luck

    This is what template-sweep notebooks do: many templates x many fields, keep the best. We run it on the
    **40 noise fields that predict NOTHING**.
    """), sweep_btn])
    return (sweep_btn,)


@app.cell(hide_code=True)
def _(data, mo, pg, sweep_btn):
    mo.stop(not sweep_btn.value, mo.md("_Press the button to run it._"))
    _templates = ["rank(ts_rank({x}, 126))", "rank(ts_decay_linear({x}, 126))", "rank(-ts_delta({x}, 21))",
                  "-rank({x})"]
    with mo.status.spinner(title="160 noise alphas ..."):
        sweep = pg.template_sweep(_templates, [f"nz_{j:03d}" for j in range(40)], data, decay=4)
    return (sweep,)


@app.cell(hide_code=True)
def _(backtest, data, deflated_sharpe, ev, ideas, mo, noise_table, pd, sweep):
    best = sweep.iloc[0]
    _r_noise = backtest(ev(best["name"]), data, decay=4)
    _r_real = backtest(ev(ideas["revision breadth (rung 2)"]), data, decay=2)
    _dsr = pd.DataFrame({"best noise alpha": deflated_sharpe(_r_noise.pnl, n_trials=len(sweep)),
                         "revision breadth (2 tries)": deflated_sharpe(_r_real.pnl, n_trials=2)})
    mo.vstack([
        mo.ui.table(sweep.head(10), selection=None),
        mo.md(f"**Best of {len(sweep)} noise alphas: Sharpe {best.sharpe}** (train {best.train_sharpe}, "
              f"test {best.test_sharpe}). How good the best one looks from pure luck, by number of tries:"),
        mo.ui.table(noise_table(years=5), selection=None),
        mo.md("""
    The best noise alpha looks like a real signal. Its *test-period* Sharpe usually collapses, and the
    **deflated Sharpe** (which accounts for how many things you tried) says it is luck:
    """),
        mo.ui.table(_dsr.reset_index().rename(columns={"index": "statistic"}), selection=None),
        mo.md("""
    **Volume itself is not the problem.** BRAIN expects 1000+ simulations - that is how you learn the data. The
    problem is *picking the best of many variants of one idea* and believing it. Simulate a lot **across** ideas
    and datasets, stay disciplined **within** one idea (a ladder of 2-4 rungs, about 10 tries), and let the
    journal count every try so the gate can deflate the Sharpe honestly.
    """)])
    return (best,)


@app.cell(hide_code=True)
def _(backtest, best, data, ev, ideas, mo, pd, variants):
    def _battery(expr, decay):
        _rows = []
        for _v in variants(expr, {"neutralization": "SUBINDUSTRY", "region": "SBX"}):
            _r = backtest(ev(_v.expression), data, decay=decay, neutralization=_v.settings["neutralization"])
            _rows.append({"variant": _v.name, "sharpe": _r.stats["sharpe"]})
        return pd.DataFrame(_rows).set_index("variant")["sharpe"]

    _t = pd.DataFrame({"best noise alpha": _battery(best["name"], 4),
                       "revision breadth": _battery(ideas["revision breadth (rung 2)"], 2)})
    mo.vstack([mo.md("""
    ## 7. Robustness tests (WorldQuant's own checklist)

    A real signal survives `rank()`, a binary version, winsorizing and small window changes. A lucky one often
    does not.
    """), mo.ui.table(_t.reset_index(), selection=None)])
    return


@app.cell(hide_code=True)
def _(mo):
    my_expr = mo.ui.text_area(value="group_rank(ts_delta(ts_backfill(anl_est_eps, 63), 63) / close, subindustry)",
                              rows=3, full_width=True, label="Your expression (practice market fields)")
    my_decay = mo.ui.number(start=0, stop=30, step=1, value=3, label="Decay")
    try_btn = mo.ui.run_button(label="Lint and backtest")
    mo.vstack([mo.md("""
    ## 8. Try operators yourself

    The linter tells you about mistakes before anything is evaluated, exactly as it does before a real
    simulation.
    """), my_expr, mo.hstack([my_decay, try_btn], justify="start")])
    return my_decay, my_expr, try_btn


@app.cell(hide_code=True)
def _(Linter, data, mo, my_decay, my_expr, pg, try_btn):
    mo.stop(not try_btn.value)
    _lint = Linter().lint(my_expr.value)
    _out = [mo.md(f"```\n{_lint.report()}\n```")]
    if _lint.ok:
        try:
            _out.append(mo.ui.table(pg.run({"my alpha": my_expr.value}, data, decay=int(my_decay.value)),
                                    selection=None))
        except Exception as _e:  # noqa: BLE001
            _out.append(mo.callout(mo.md(f"Could not evaluate: {_e}"), kind="danger"))
    mo.vstack(_out)
    return


if __name__ == "__main__":
    app.run()
