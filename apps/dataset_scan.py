import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full", app_title="HYPOLAB dataset scan", css_file="hypolab.css", html_head_file="head.html")


@app.cell(hide_code=True)
def _():
    import sys

    import marimo as mo

    _root = mo.notebook_dir().parent if mo.notebook_dir() else None
    if _root is not None and str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    import pandas as pd

    from hypolab import config
    from ideaengine import views
    from ideaengine.connection import LOGIN_HELP, open_researcher

    return LOGIN_HELP, config, mo, open_researcher, pd, views


@app.cell(hide_code=True)
def _(config, open_researcher):
    # A separate app on purpose: a live scan of 40 fields can take 10-30 minutes, and while it runs this
    # app is busy. The cockpit stays free; scan results reach it through the journal.
    SANDBOX = config.sandbox_mode()
    R, live_problem = open_researcher()
    return R, SANDBOX, live_problem


@app.cell(hide_code=True)
def _(LOGIN_HELP, R, SANDBOX, config, live_problem, mo):
    _mode = ('<span class="hl-pill hl-sandbox">SANDBOX</span> offline practice market (region SBX).' if SANDBOX
             else f'<span class="hl-pill hl-live">LIVE</span> your BRAIN account (region {config.live_region()}).')
    _parts = [mo.md(f"# Learn a dataset: explore, then scan\n{_mode} Switch on the cockpit's Setup tab, then "
                    "reload this page.\n\n"
                    "1. **Explore** (free): each usable field gets only the *lenses* that make sense for its nature - "
                    "a cash-flow amount becomes a yield, an estimate becomes a revision, a count a relative change.\n"
                    "2. **Scan** (one simulation per field, in batches, all journaled): every field probed once. "
                    "The **noise bar** is the |Sharpe| the luckiest pure-noise field would reach; only fields above "
                    "it are candidates.\n\n"
                    "A scan finds *where to look*, not alphas. If you later build an alpha from a scanned field, the "
                    "gate counts every field you scanned as a try: choosing the best of 40 *is* a 40-way selection.")]
    if live_problem:
        _parts.append(mo.callout(mo.md(f"{live_problem}\n\n{LOGIN_HELP}"), kind="warn"))
    header = mo.vstack(_parts)
    header
    return


@app.cell(hide_code=True)
def _(R, SANDBOX, config, mo):
    mo.stop(R is None)
    _region = "SBX" if SANDBOX else config.live_region()
    _u = config.REGION_DEFAULTS.get(_region, {}).get("universe", "TOP3000")
    _ds = R.catalog.datasets(_region, _u, 1)
    _opts = sorted(_ds["id"].tolist()) if not _ds.empty else []
    _default = ("sbx_analyst" if SANDBOX else "analyst15")
    region = _region
    dataset_dd = mo.ui.dropdown(options=_opts, value=_default if _default in _opts else (_opts[0] if _opts else None),
                                searchable=True, label=f"Dataset in {_region} {_u}")
    explore_n = mo.ui.number(start=1, stop=30, step=1, value=6, label="Fields to explore")
    scan_n = mo.ui.number(start=2, stop=int(config.settings()["scan_max_fields"]) * 3, step=1,
                          value=int(config.settings()["scan_max_fields"]), label="Fields to scan")
    min_cov = mo.ui.slider(start=0.1, stop=0.9, step=0.05, value=0.5, label="Minimum coverage", show_value=True)
    scan_btn = mo.ui.run_button(label="Scan (one simulation per field)", kind="warn")
    _note = mo.md("") if _opts else mo.callout(mo.md(
        f"No field list for {_region} yet: download it on the cockpit's Data tab."), kind="warn")
    mo.vstack([_note, mo.hstack([dataset_dd, explore_n, scan_n, min_cov], justify="start", gap=1.5, wrap=True)])
    return dataset_dd, explore_n, min_cov, region, scan_btn, scan_n


@app.cell(hide_code=True)
def _(R, dataset_dd, explore_n, min_cov, mo, region, views):
    mo.stop(R is None or not dataset_dd.value)
    lens_cards = R.explore(dataset_dd.value, region, max_fields=int(explore_n.value), min_coverage=float(min_cov.value))
    explore_table = mo.ui.table(views.cards_table(lens_cards), selection="single", page_size=8,
                                label="Lens cards (no simulations). Tick one to read it")
    return explore_table, lens_cards


@app.cell(hide_code=True)
def _(explore_table, lens_cards, mo):
    _sel = explore_table.value
    _card = None
    if _sel is not None and len(_sel):
        _card = next((c for c in lens_cards if c.hypothesis.id == _sel.iloc[0]["id"]), None)
    mo.vstack([mo.md("## 1. Explore"), explore_table,
               mo.md(_card.markdown()) if _card else mo.md("_Tick a lens card to read it._")])
    return


@app.cell(hide_code=True)
def _(R, SANDBOX, config, dataset_dd, min_cov, mo, region, scan_btn, scan_n):
    mo.stop(R is None or not dataset_dd.value)
    _left = config.settings()["max_sims_per_day"] - R.journal.sims_today()
    _intro = mo.md(f"## 2. Scan\nUp to **{int(scan_n.value)} simulations** on `{dataset_dd.value}`"
                   + ("" if SANDBOX else f" ({_left} left under today's runaway guard)")
                   + ". Fields already scanned are served from the journal, not simulated again.")
    scan_result = None
    if scan_btn.value:
        with mo.status.spinner(title=f"Scanning {dataset_dd.value} ... (live scans can take a while)"):
            scan_result = R.scan(dataset_dd.value, region, max_fields=int(scan_n.value),
                                 min_coverage=float(min_cov.value))
    mo.vstack([_intro, scan_btn])
    return (scan_result,)


@app.cell(hide_code=True)
def _(mo, scan_result):
    mo.stop(scan_result is None)
    if scan_result.empty:
        _out = mo.callout(mo.md("No usable numeric fields in this dataset at this coverage."), kind="warn")
    else:
        _bar = scan_result.attrs.get("noise_bar")
        _above = int(scan_result["above_noise_bar"].sum())
        _cols = ["field", "description", "nature", "lens", "sharpe", "fitness", "turnover", "above_noise_bar", "cached"]
        _out = mo.vstack([
            mo.callout(mo.md(f"**Noise bar for {len(scan_result)} probes: |Sharpe| > {_bar}.** {_above} field(s) "
                             "clear it. A negative Sharpe means the field works with the opposite sign. Below the "
                             "bar is not proof of nothing: a field with a clear mechanism may still deserve a card."),
                       kind="success" if _above else "neutral"),
            mo.ui.table(scan_result[_cols], selection=None, page_size=15),
            mo.md("**Next:** for each candidate, write one sentence on *why* it should predict returns, then turn "
                  "it into a card (cockpit, Cards tab; the card form arrives in phase 3). In live mode the probes are "
                  "in your journal, so the cockpit's Journal tab shows them too (the sandbox keeps a separate "
                  "practice journal per app)."),
        ])
    _out
    return


if __name__ == "__main__":
    app.run()
