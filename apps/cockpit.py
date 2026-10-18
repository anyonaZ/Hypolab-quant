import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full", app_title="HYPOLAB cockpit", css_file="hypolab.css", html_head_file="head.html")


@app.cell(hide_code=True)
def _():
    import sys

    import marimo as mo

    _root = mo.notebook_dir().parent if mo.notebook_dir() else None
    if _root is not None and str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    import pandas as pd

    import hypolab
    from hypolab import config, connect, play, rules, theme
    from hypolab import hypotheses as hyp
    from hypolab.brain import AuthError, BrainClient, quota as brain_quota
    from hypolab import account as acct
    from hypolab.concepts import CONCEPTS
    from hypolab.operators import GOLD
    from hypolab.catalog import CATEGORY_NAMES, Catalog
    from hypolab.ideas import generate_ideas
    from hypolab.journal import Journal
    from hypolab.pyramids import GUIDE_DATASETS, GUIDE_NOTES, TIERS, PyramidTracker, multiplier_table
    from ideaengine import drafts as idea_drafts
    from ideaengine import planner, views
    from ideaengine.connection import LOGIN_HELP, open_researcher
    from ideaengine.store import IdeaStore

    pd.set_option("display.max_colwidth", 200)
    return (acct, AuthError, BrainClient, CATEGORY_NAMES, CONCEPTS, Catalog, GOLD, GUIDE_DATASETS, GUIDE_NOTES, IdeaStore,
            idea_drafts, Journal, LOGIN_HELP, PyramidTracker, TIERS, config, connect, generate_ideas, hyp, hypolab, mo,
            brain_quota, multiplier_table, open_researcher, pd, planner, play, rules, theme, views)


@app.cell(hide_code=True)
def _(mo):
    # bumped after a mode switch, a login or a logout: the Researcher below is opened again
    get_conn, set_conn = mo.state(0)
    get_login, set_login = mo.state(None)
    return get_conn, get_login, set_conn, set_login


@app.cell(hide_code=True)
def _(config, get_conn, open_researcher):
    # One Researcher for the whole app: sandbox (offline practice) or your BRAIN account,
    # following the switch on the Setup tab (or `python -m hypolab live USA` / `sandbox`).
    get_conn()
    SANDBOX = config.sandbox_mode()
    R, live_problem = open_researcher()
    return R, SANDBOX, live_problem


@app.cell(hide_code=True)
def _(IdeaStore, Journal, R, planner):
    store = IdeaStore()
    this_week = planner.iso_week()
    # the journal the cockpit shows: the Researcher's (sandbox = in-memory practice journal), else read-only file
    J = R.journal if R is not None else Journal.open_readonly()
    return J, store, this_week


@app.cell(hide_code=True)
def _(mo):
    # shared state: Lab results, the card sent to the Lab, and a counter that refreshes views after saves
    get_results, set_results = mo.state([])
    get_lab_card, set_lab_card = mo.state(None)
    get_version, set_version = mo.state(0)
    get_boost, set_boost = mo.state(None)
    get_robust, set_robust = mo.state({})
    get_gate, set_gate = mo.state(None)
    get_submitted, set_submitted = mo.state([])
    # 1.4.3: which result the Lab shows (None = the newest), PnL/yearly per alpha id, and the bin
    get_focus, set_focus = mo.state(None)
    get_perf, set_perf = mo.state({})
    get_bins, set_bins = mo.state(0)
    get_bin_msg, set_bin_msg = mo.state(None)
    NO_CARD = "(no card: write your own expression)"

    def add_results(new):
        """Append results to the Lab list and show the newest (or the last of `new`)."""
        set_results(get_results() + list(new))
        set_focus(None)
    return (NO_CARD, add_results, get_bin_msg, get_bins, get_boost, get_focus, get_gate, get_lab_card, get_perf,
            get_results, get_robust, get_submitted, get_version, set_bin_msg, set_bins, set_boost, set_focus,
            set_gate, set_lab_card, set_perf, set_results, set_robust, set_submitted, set_version)


@app.cell(hide_code=True)
def _(R, SANDBOX, config, hyp, live_problem, mo):
    _mode = ('<span class="hl-pill hl-sandbox">SANDBOX</span> offline practice market (region SBX); nothing here '
             "touches your BRAIN account." if SANDBOX else
             f'<span class="hl-pill hl-live">LIVE</span> your BRAIN account (default region {config.live_region()}).')
    _parts = [mo.md(f"# HYPOLAB cockpit\n{_mode}  Switch and log in on the **Setup** tab.")]
    if live_problem:
        _parts.append(mo.callout(mo.md(f"{live_problem}\n\nLog in on the **Setup** tab. Until then: Pyramids and "
                                       "Journal show your journal; the Lab is off."), kind="warn"))
    hyp.load_library()
    if hyp.LOAD_WARNINGS:
        _parts.append(mo.callout(mo.md("**Your card files:**\n\n" + "\n".join(f"- {w}" for w in hyp.LOAD_WARNINGS)),
                                 kind="warn"))
    header = mo.vstack(_parts)
    return (header,)


@app.cell(hide_code=True)
def _(R, SANDBOX, config, mo, store, this_week):
    # The region the Cards and Lab tabs work in. Default: this week's plan.
    _plan = store.plan(this_week)
    _regions = ["SBX"] if SANDBOX else config.account_regions()
    _default = "SBX" if SANDBOX else ((_plan or {}).get("region") or (R.region if R else config.live_region()))
    region_dd = mo.ui.dropdown(options=_regions, value=_default if _default in _regions else _regions[0],
                               label="Region for Cards and Lab")
    return (region_dd,)


# =============================================================================================== PYRAMIDS
@app.cell(hide_code=True)
def _(mo):
    refresh_pyr = mo.ui.button(label="Refresh counts", value=0, on_click=lambda v: (v or 0) + 1)
    return (refresh_pyr,)


@app.cell(hide_code=True)
def _(J, PyramidTracker, R, SANDBOX, acct, get_submitted, get_version, multiplier_table, refresh_pyr):
    # Genius counts Pyramids PER QUARTER (BRAIN_RULES S14). Order of sources:
    # 1. this quarter's submitted alphas (Account tab download) placed in categories by their fields,
    # 2. BRAIN's diversity counts (ALL TIME - they overstate the quarter), 3. HYPOLAB's own journal.
    refresh_pyr.value, get_submitted(), get_version()
    pyr_source, pyr_notes, pyr_raw, pyr_totals, pyr_mult = "journal", [], [], None, multiplier_table()
    if R is not None and SANDBOX:
        pyr_counts, pyr_regions, pyr_source = R.brain.diversity(), ["SBX"], "sandbox"
    else:
        _base = None
        _yq = acct.current_quarter()
        if R is not None:
            try:
                pyr_mult = multiplier_table(R.brain.pyramid_multipliers())
            except Exception:  # noqa: BLE001
                pass
        if acct.last_sync(J):
            _qc, pyr_notes = acct.quarter_pyramids(J, R.catalog if R is not None else None, *_yq)
            _base, pyr_source = PyramidTracker(_qc), f"your {_yq[0]} Q{_yq[1]} submissions (Account tab download)"
        elif R is not None:
            try:
                _div = R.brain.diversity()
                pyr_raw = _div.attrs.get("raw_sample", [])
                _base = PyramidTracker(_div)
                pyr_source = "BRAIN, ALL TIME - Genius counts the quarter only: download on the Account tab"
            except Exception as _e:  # noqa: BLE001
                pyr_source = f"journal (BRAIN unavailable: {_e})"
        _base = _base or PyramidTracker.from_journal(J)
        pyr_counts, pyr_regions, pyr_totals = _base.counts, _base.regions, _base.totals
        pyr_notes = list(pyr_notes) + list(_base.notes)
    return pyr_counts, pyr_mult, pyr_notes, pyr_raw, pyr_regions, pyr_source, pyr_totals


@app.cell(hide_code=True)
def _(config, mo):
    k_input = mo.ui.number(start=1, stop=50, step=1, value=int(config.settings()["alphas_per_pyramid"]),
                           label="Alphas needed per Pyramid (check the Pyramids page on BRAIN)")
    return (k_input,)


@app.cell(hide_code=True)
def _(PyramidTracker, config, k_input, pyr_counts, pyr_mult, pyr_regions):
    if int(k_input.value) != int(config.settings()["alphas_per_pyramid"]):
        config.save_settings(alphas_per_pyramid=int(k_input.value))
    tracker = PyramidTracker(pyr_counts, alphas_per_pyramid=int(k_input.value), regions=pyr_regions,
                             multipliers=pyr_mult)
    return (tracker,)


@app.cell(hide_code=True)
def _(mo):
    plan_sort = mo.ui.radio(options={"Guide order (tier 1 first, easiest regions)": "guide",
                                     "Highest multiplier first (pays more, usually harder)": "multiplier"},
                            value="Guide order (tier 1 first, easiest regions)", inline=True)
    return (plan_sort,)


@app.cell(hide_code=True)
def _(GUIDE_DATASETS, GUIDE_NOTES, R, SANDBOX, k_input, mo, pd, plan_sort, pyr_mult, pyr_notes, pyr_raw,
      pyr_source, pyr_totals, refresh_pyr, tracker, views):
    _m = tracker.matrix()
    _fig = views.pyramid_heatmap(_m, tracker.k, title=f"Alphas per cell (counts from {pyr_source})")
    _notes = pd.DataFrame([{"category": c, "guide datasets": ", ".join(GUIDE_DATASETS.get(c, [])),
                            "note": GUIDE_NOTES.get(c, "")} for c in GUIDE_DATASETS])
    _mult = mo.md("")
    if not SANDBOX and len(pyr_mult):
        _mt = pyr_mult.pivot_table(index="category", columns=["region", "delay"], values="multiplier")
        _mt.columns = [f"{r} D{d}" for r, d in _mt.columns]
        _mult = mo.accordion({f"Pyramid theme multipliers (source: {pyr_mult.attrs.get('source', '?')})":
                              mo.ui.table(_mt.reset_index(), selection=None, page_size=20)})
    pyramids_view = mo.vstack([
        mo.hstack([mo.md(f"**{tracker.summary()}**"), refresh_pyr], justify="space-between"),
        k_input,
        mo.callout(mo.md("**Cleaned up in BRAIN's counts:** " + " ".join(pyr_notes)), kind="neutral")
        if pyr_notes else mo.md(""),
        _fig,
        mo.vstack([
            mo.md("**Alphas per region (BRAIN's totals).** One alpha counts in every category whose data it uses, "
                  "so the cells above can add up to more than these totals."),
            mo.ui.table(pyr_totals, selection=None, page_size=12, show_column_summaries=False),
        ]) if pyr_totals is not None and len(pyr_totals) else mo.md(""),
        mo.md("### Next cells to work on"), plan_sort,
        mo.ui.tabs({"Delay 1": mo.ui.table(tracker.plan(n=15, delay=1, by=plan_sort.value), selection=None,
                                           page_size=15),
                    "Delay 0": mo.ui.table(tracker.plan(n=15, delay=0, by=plan_sort.value), selection=None,
                                           page_size=15)}),
        mo.accordion({"Datasets the Pyramids guide recommends": mo.ui.table(_notes, selection=None, page_size=12),
                      **({"BRAIN's raw Pyramid rows (first 20, for checking)": mo.json(pyr_raw)} if pyr_raw else {})}),
        _mult,
    ])
    return (pyramids_view,)


# =================================================================================================== WEEK
@app.cell(hide_code=True)
def _(mo, planner, store, this_week):
    _weeks = [this_week]
    for _ in range(6):
        _weeks.append(planner.next_week(_weeks[-1]))
    _weeks = sorted(set(_weeks) | set(store.weeks_planned()))
    _default = this_week if store.plan(this_week) or this_week in planner.STARTING_PLAN else \
        next((w for w in _weeks if w > this_week), this_week)
    week_dd = mo.ui.dropdown(options=_weeks, value=_default, label="Week")
    return (week_dd,)


@app.cell(hide_code=True)
def _(CATEGORY_NAMES, config, get_version, mo, planner, store, tracker, week_dd):
    get_version()
    _p = planner.propose(week_dd.value, tracker, store.plan(week_dd.value))
    _regions = list(dict.fromkeys(config.account_regions() + [_p["region"]]))
    _cat_opts = {f"{CATEGORY_NAMES.get(c, c)} ({c})": c for c in planner.CATEGORY_IDS}
    _cat_vals = [k for k, v in _cat_opts.items() if v in _p["categories"]]
    plan_form = mo.md(
        "**Region** {region}  **Categories** {categories}\n\n"
        "**Dataset to read closely** {dataset_focus}  **Cards to approve** {card_target}  "
        "**Alphas to submit this week** {submit_target}\n\n"
        "**Friday review note** {review_note}"
    ).batch(
        region=mo.ui.dropdown(options=_regions, value=_p["region"]),
        categories=mo.ui.multiselect(options=_cat_opts, value=_cat_vals),
        dataset_focus=mo.ui.text(value=_p.get("dataset_focus") or ""),
        card_target=mo.ui.number(start=0, stop=50, value=int(_p.get("card_target") or 5)),
        submit_target=mo.ui.number(start=0, stop=28, value=int(_p.get("submit_target") or
                                                               planner.DEFAULT_WEEKLY_SUBMISSIONS)),
        review_note=mo.ui.text_area(value=_p.get("review_note") or "", rows=3, full_width=True),
    ).form(submit_button_label="Save this week's plan")
    plan_is_saved = store.plan(week_dd.value) is not None
    return plan_form, plan_is_saved


@app.cell(hide_code=True)
def _(config, get_version, mo, plan_form, set_version, store, week_dd):
    mo.stop(plan_form.value is None)
    _v = plan_form.value
    _region = _v["region"]
    store.save_plan({"week": week_dd.value, "region": _region,
                     "universe": config.REGION_DEFAULTS.get(_region, {}).get("universe", "TOP3000"), "delay": 1,
                     "categories": list(_v["categories"]), "dataset_focus": _v["dataset_focus"],
                     "card_target": int(_v["card_target"] or 0), "submit_target": int(_v["submit_target"] or 0),
                     "review_note": _v["review_note"]})
    set_version(get_version() + 1)
    return


@app.cell(hide_code=True)
def _(get_version, mo, store):
    get_version()
    _g = store.goals().set_index("key")
    _lt = store.lifetime()
    goal_form = mo.md(
        "| | now | Expert bar |\n|---|---|---|\n"
        "| Signals (submitted alphas) | {signals_now} | {signals_bar} |\n"
        "| Pyramids completed | {pyramids_now} | {pyramids_bar} |\n"
        "| Combined alpha performance | {perf_now} | {perf_bar} |\n"
        "| Alphas submitted, lifetime (SuperAlpha unlock) | {life_now} | {life_bar} |"
    ).batch(
        signals_now=mo.ui.number(value=float(_g.loc["signals", "now"]), step=1),
        signals_bar=mo.ui.number(value=float(_g.loc["signals", "bar"]), step=1),
        pyramids_now=mo.ui.number(value=float(_g.loc["pyramids", "now"]), step=1),
        pyramids_bar=mo.ui.number(value=float(_g.loc["pyramids", "bar"]), step=1),
        perf_now=mo.ui.number(value=float(_g.loc["combined_perf", "now"]), step=0.01),
        perf_bar=mo.ui.number(value=float(_g.loc["combined_perf", "bar"]), step=0.01),
        life_now=mo.ui.number(value=float(_lt["base"]), step=1),
        life_bar=mo.ui.number(value=float(_lt["unlock"]), step=1),
    ).form(submit_button_label="Update from my Genius page")
    return (goal_form,)


@app.cell(hide_code=True)
def _(get_version, goal_form, mo, set_version, store):
    mo.stop(goal_form.value is None)
    _v = goal_form.value
    store.set_goal("signals", _v["signals_now"], _v["signals_bar"])
    store.set_goal("pyramids", _v["pyramids_now"], _v["pyramids_bar"])
    store.set_goal("combined_perf", _v["perf_now"], _v["perf_bar"])
    _lt = store.lifetime()
    if (_v["life_now"], _v["life_bar"]) != (_lt["base"], _lt["unlock"]):
        store.set_goal("lifetime_alphas", _v["life_now"], _v["life_bar"])   # restarts the auto-count from now
    set_version(get_version() + 1)
    return


@app.cell(hide_code=True)
def _(mo):
    # Friday hand-off (1.5.0): DIGEST out to the Weekly Reviewer, its PLAN back in
    wk_plan_area = mo.ui.text_area(placeholder="plan:\n  week: 2026-W43\n  region: USA\n  categories: [pv, model]\n"
                                               "  ...", rows=10, full_width=True,
                                   label="Paste the Weekly Reviewer's PLAN (the `plan:` block; text around it is ignored)")
    wk_plan_btn = mo.ui.run_button(label="Check and save this plan", kind="success")
    get_wk_msg, set_wk_msg = mo.state(None)
    return get_wk_msg, set_wk_msg, wk_plan_area, wk_plan_btn


@app.cell(hide_code=True)
def _(J, SANDBOX, config, get_version, idea_drafts, mo, set_version, set_wk_msg, store, wk_plan_area,
      wk_plan_btn):
    mo.stop(not wk_plan_btn.value)
    _regions = (["SBX"] if SANDBOX else []) + config.account_regions()
    _plan, _probs = idea_drafts.parse_plan(wk_plan_area.value, _regions)
    if _plan is None:
        set_wk_msg(("danger", "**Plan not saved.**\n\n" + "\n".join(f"- {p.replace('error: ', '')}" for p in _probs)))
    else:
        _res = idea_drafts.apply_plan(store, J, _plan)
        _ex = _plan["extra"]
        _n = len(_ex["lessons"]) + len(_ex["dead_ends"])
        _les = (f"{_res['lessons_added']} lesson(s) added to the journal" if _res["lessons_added"] or not _n else
                ("lessons already in the journal" if not getattr(J, "readonly", False) else
                 "lessons NOT stored: log in on the Setup tab (the journal is read-only now), then save again"))
        set_wk_msg(("success", f"Saved the plan for **{_plan['week']}** ({_plan['region']}, "
                               f"{', '.join(_plan['categories'])}); {_les}. Pick {_plan['week']} in the Week menu to "
                               "see it." + ("\n\n" + "\n".join(f"- {p}" for p in _probs) if _probs else "")))
        set_version(get_version() + 1)
    return


@app.cell(hide_code=True)
def _(CATEGORY_NAMES, J, get_results, get_submitted, get_version, get_wk_msg, goal_form, idea_drafts, mo,
      plan_form, plan_is_saved, planner, store, this_week, tracker, week_dd, wk_plan_area, wk_plan_btn):
    get_version(), get_results(), get_submitted()
    _g = planner.goals_view(store, J)
    _cols = ["label", "now", "bar", "still_needed", "per_week_needed", "journal_hint"]
    _prog = planner.week_progress(J, week_dd.value)
    _p = planner.propose(week_dd.value, tracker, store.plan(week_dd.value))
    _cells = ", ".join(f"{_p['region']} {CATEGORY_NAMES.get(c, c)}" for c in _p["categories"])
    _status = "saved" if plan_is_saved else "proposed - not saved yet"
    _verd = ", ".join(f"{k} {v}" for k, v in _prog["verdicts"].items()) or "none yet"
    _this = planner.propose(this_week, tracker, store.plan(this_week))
    _sub = planner.submission_status(store, J, weekly_target=_this.get("submit_target"))
    _sub_week = planner.week_progress(J, week_dd.value).get("submitted", 0)
    _wm = get_wk_msg()
    try:
        _digest = idea_drafts.digest(J, store, week_dd.value)
    except Exception as _e:  # noqa: BLE001
        _digest = f"(digest failed: {_e})"
    _x = (store.plan(week_dd.value) or {}).get("extra") or {}
    _extra = []
    if _x.get("retry") or _x.get("dead_ends") or _x.get("lessons"):
        _extra.append(mo.callout(mo.md(
            f"**From the {_x.get('from', 'review')}:** "
            + (f"retry {', '.join(f'`{i}`' for i in _x['retry'])}. " if _x.get("retry") else "")
            + (f"Stop these families: {', '.join(f'`{f}`' for f in _x['dead_ends'])}. " if _x.get("dead_ends") else "")
            + ("\n\n" + "\n".join(f"- {l}" for l in _x["lessons"]) if _x.get("lessons") else "")), kind="info"))
    week_view = mo.vstack([
        mo.callout(mo.md(planner.submission_summary(_sub)),
                   kind="success" if _sub["left_today"] else "warn"),
        mo.md(f"## Quarter goal: Expert by {_g['quarter'].iloc[0]} "
              f"({_g['weeks_left'].iloc[0]} weeks left)"),
        mo.ui.table(_g[_cols], selection=None),
        mo.md("Combined alpha performance is the bar that punishes weak submissions: submit only what clears "
              "the gate, never alphas made just to fill a Pyramid."),
        mo.accordion({"Update the numbers from your Genius page": goal_form}),
        mo.hstack([mo.md(f"## Plan for {week_dd.value} ({_status})"), week_dd], justify="space-between"),
        mo.md(f"**Cells this week:** {_cells}. **Dataset to read:** {_p.get('dataset_focus') or '-'}. "
              f"**Cards to approve:** {_p.get('card_target')}. "
              f"**Alphas to submit:** {_p.get('submit_target')} ({_sub_week} so far)."),
        plan_form,
        mo.md(f"**This week so far:** {_prog['simulations']} simulations on {_prog['ideas_tested']} ideas; "
              f"verdicts: {_verd}; best Sharpe {_prog['best_sharpe'] if _prog['best_sharpe'] is not None else '-'}."),
        *_extra,
        mo.md("## Friday review"),
        mo.md("1. Copy the **DIGEST** of the selected week into the **Weekly Reviewer** project. "
              "2. Paste its **PLAN** below: it is saved for its week, its lessons and dead ends go to the journal."),
        *([mo.callout(mo.md(_wm[1]), kind=_wm[0])] if _wm else []),
        mo.accordion({f"DIGEST for {week_dd.value} (copy this)":
                      mo.ui.code_editor(value=_digest, language="markdown", disabled=True, show_copy_button=True,
                                        theme="dark"),
                      "Paste the Reviewer's PLAN": mo.vstack([wk_plan_area, wk_plan_btn])}),
    ])
    return (week_view,)


# ================================================================================================== CARDS
@app.cell(hide_code=True)
def _(CATEGORY_NAMES, SANDBOX, mo, planner, store, this_week):
    _plan = store.plan(this_week) or planner.propose(this_week)
    _cat_opts = {f"{CATEGORY_NAMES.get(c, c)} ({c})": c for c in planner.CATEGORY_IDS}
    cards_cats = mo.ui.multiselect(options=_cat_opts, label="Pyramid categories (empty = all)",
                                   value=[] if SANDBOX else [k for k, v in _cat_opts.items() if v in _plan["categories"]])
    cards_source = mo.ui.radio(options={"all": "all", "built-in": "library", "mine": "mine"}, value="all",
                               inline=True, label="Cards")
    cards_n = mo.ui.number(start=5, stop=100, step=5, value=30, label="How many")
    return cards_cats, cards_n, cards_source


@app.cell(hide_code=True)
def _(mo):
    sync_btn = mo.ui.run_button(label="Download the field list for this region (metadata only, a few minutes)")
    return (sync_btn,)


@app.cell(hide_code=True)
def _(Catalog, R, SANDBOX, config, mo, region_dd, sync_btn):
    # The data catalog for the chosen region (the sandbox has its own synthetic one).
    catalog = R.catalog if R is not None else Catalog()
    _uni = config.REGION_DEFAULTS.get(region_dd.value, {}).get("universe", "TOP3000")
    if sync_btn.value and R is not None and not SANDBOX:
        with mo.status.spinner(title=f"Syncing {region_dd.value} {_uni} ..."):
            catalog.sync_from_brain(R.brain, region_dd.value, _uni, 1, progress=None)
    catalog_ok = catalog.has_context(region_dd.value, _uni, 1)
    return catalog, catalog_ok


@app.cell(hide_code=True)
def _(J, catalog, cards_cats, cards_n, cards_source, generate_ideas, get_bins, get_version, hyp, region_dd,
      tracker, views):
    get_version(), get_bins()
    _binned = J.binned_ids()
    _lib = [h for h in hyp.load_library() if h.id not in _binned]      # binned (noise) cards stay out (1.4.3)
    if cards_source.value != "all":
        _lib = [h for h in _lib if h.source == cards_source.value]
    try:
        _need = tracker.need(region_dd.value)
    except Exception:  # noqa: BLE001
        _need = {}
    ranked_cards = generate_ideas(catalog, region_dd.value, categories=list(cards_cats.value) or None,
                                  n=int(cards_n.value), journal=J, pyramid_need=_need, beginner=True,
                                  library=_lib, one_per_family=True) if _lib else []
    cards_df = views.cards_table(ranked_cards)
    return cards_df, ranked_cards


@app.cell(hide_code=True)
def _(cards_df, mo):
    cards_table = mo.ui.table(cards_df, selection="single", page_size=12,
                              label="Tick a card to read it and send it to the Lab")
    return (cards_table,)


@app.cell(hide_code=True)
def _(R, cards_table, mo, ranked_cards, set_lab_card):
    import time as _time
    _sel = cards_table.value
    selected_card = None
    if _sel is not None and len(_sel):
        _id = _sel.iloc[0]["id"]
        selected_card = next((c for c in ranked_cards if c.hypothesis.id == _id), None)
    # (id, time) so sending the same card again after changing the Lab's dropdown still switches back
    send_btn = mo.ui.button(label="Send this card to the Lab",
                            on_click=lambda _: set_lab_card((selected_card.hypothesis.id, _time.time())
                                                            if selected_card else None),
                            disabled=selected_card is None, kind="success")
    bin_reason = mo.ui.dropdown(options=["noise - no real signal", "data missing or too thin here",
                                         "weak story - I don't believe it", "duplicate of another card",
                                         "crowded - everyone trades it"],
                                value="noise - no real signal", label="Why bin it")
    bin_btn = mo.ui.run_button(label="Bin this card", kind="danger", disabled=selected_card is None or R is None)
    return bin_btn, bin_reason, selected_card, send_btn


@app.cell(hide_code=True)
def _(NO_CARD, R, bin_btn, bin_reason, config, get_bins, mo, selected_card, set_bin_msg, set_bins, set_lab_card):
    # Bin a noise card (1.4.3): hidden from Cards, the Lab list, Play and boosters. Nothing is deleted.
    mo.stop(not bin_btn.value or R is None or selected_card is None)
    import time as _time
    _id = selected_card.hypothesis.id
    R.bin(_id, bin_reason.value)
    if config.settings().get("last_lab_card") == _id:
        config.save_settings(last_lab_card="")
        set_lab_card((NO_CARD, _time.time()))
    set_bin_msg(("cards", f"Binned **{_id}** ({bin_reason.value}). Restore it any time from **The bin** below."))
    set_bins(get_bins() + 1)
    return


@app.cell(hide_code=True)
def _(J, get_bins, mo, pd):
    get_bins()
    _b = J.binned()
    if not _b.empty:
        _b = _b.assign(binned=pd.to_datetime(_b["created"], unit="s").dt.strftime("%Y-%m-%d %H:%M"))[
            ["hypothesis_id", "reason", "binned"]].rename(columns={"hypothesis_id": "card", "binned": "binned (UTC)"})
    bin_table = mo.ui.table(_b, selection="multi", page_size=10, show_download=False,
                            label="Tick the cards to bring back")
    restore_btn_bin = mo.ui.run_button(label="Restore the ticked cards", kind="success", disabled=_b.empty)
    n_binned = len(_b)
    return bin_table, n_binned, restore_btn_bin


@app.cell(hide_code=True)
def _(R, bin_table, get_bins, mo, restore_btn_bin, set_bin_msg, set_bins):
    mo.stop(not restore_btn_bin.value or R is None)
    _sel = bin_table.value
    _ids = list(_sel["card"]) if _sel is not None and len(_sel) else []
    for _i in _ids:
        R.restore(_i)
    set_bin_msg(("cards", f"Restored {', '.join(f'**{i}**' for i in _ids)}." if _ids else "Tick a card first."))
    set_bins(get_bins() + 1)
    return


@app.cell(hide_code=True)
def _(R, SANDBOX, bin_btn, bin_reason, bin_table, cards_cats, cards_n, cards_source, cards_table, catalog_ok,
      get_bin_msg, mo, n_binned, region_dd, restore_btn_bin, selected_card, send_btn, sync_btn):
    _top = [mo.hstack([region_dd, cards_cats, cards_source, cards_n], justify="start", gap=1.5, wrap=True)]
    if not catalog_ok and not SANDBOX:
        _top.append(mo.callout(mo.vstack([
            mo.md(f"No field list for **{region_dd.value}** yet, so cards cannot be bound to real fields. "
                  "Download it once (it is reused for 7 days)."),
            sync_btn if R is not None else mo.md("_Log in first to download it._")]), kind="warn"))
    _detail = mo.md("_Select a card to read it._")
    if selected_card is not None:
        _detail = mo.vstack([
            mo.hstack([send_btn, mo.hstack([bin_reason, bin_btn], justify="end", gap=0.75, align="end")],
                      justify="space-between", align="end", wrap=True),
            mo.md(selected_card.markdown())])
    _bm = get_bin_msg()
    _msg = [mo.callout(mo.md(_bm[1]), kind="neutral")] if isinstance(_bm, tuple) and _bm[0] == "cards" else []
    cards_view = mo.vstack(_top + [
        mo.md("Ranked by evidence, data fit, coverage, crowding, the Pyramids you still need, and your journal "
              "(one card per family). Read the story before you simulate anything. **Noise?** Bin it - it "
              "leaves the ranking, the Lab list, Play and the boosters, and you can restore it later."),
        *_msg, cards_table, _detail,
        mo.accordion({f"The bin ({n_binned} card{'s' if n_binned != 1 else ''})":
                      mo.vstack([bin_table, restore_btn_bin]) if n_binned else
                      mo.md("_Empty. Bin a card above when it turns out to be noise._")})])
    return (cards_view,)


# ================================================================================================= DRAFTS
@app.cell(hide_code=True)
def _(idea_drafts, mo, store):
    # Phase 3 (1.5.0): write your own cards, or import the Claude Projects team's. Drafts live in ideas.sqlite.
    drafts = idea_drafts.Drafts(store)
    get_dr_src, set_dr_src = mo.state({"card": idea_drafts.template(), "source": "", "n": 0})
    get_dr_open, set_dr_open = mo.state(None)        # id of the saved draft open in the form (None = unsaved)
    get_dr_msg, set_dr_msg = mo.state(None)          # (callout kind, markdown)
    get_dr_v, set_dr_v = mo.state(0)                 # bumped after every change to the drafts table
    get_dr_approved, set_dr_approved = mo.state(None)
    import itertools as _it
    dr_view_runs = _it.count(1)                      # numbers the Drafts view's runs (fresh element ids)
    return (dr_view_runs, drafts, get_dr_approved, get_dr_msg, get_dr_open, get_dr_src, get_dr_v, set_dr_approved, set_dr_msg,
            set_dr_open, set_dr_src, set_dr_v)


@app.cell(hide_code=True)
def _(get_dr_v, idea_drafts, mo):
    # controls that must keep what you type: they never depend on the form
    get_dr_v()
    _raw = idea_drafts.library_raw()
    _opts = {"Blank card": ""}
    _opts.update({f"Copy {k} ({_s}) - {str(_c.get('title', ''))[:60]}": k for k, (_c, _s) in _raw.items()})
    dr_start = mo.ui.dropdown(options=_opts, value="Blank card", searchable=True, label="Start from")
    dr_start_btn = mo.ui.run_button(label="Load into the form", kind="neutral")
    dr_import = mo.ui.text_area(placeholder="# from: B-20261012-1\n- id: IE_...\n  title: ...", rows=8,
                                full_width=True, label="Paste one or more CARDs from Scout & Writer "
                                                       "(the `# from:` line and ```yaml fences are fine)")
    dr_import_btn = mo.ui.run_button(label="Import as draft(s) and open the first", kind="success")
    dr_filter = mo.ui.radio(options={"waiting (draft + checked)": "waiting", "approved": "approved",
                                     "binned": "binned", "all": "all"},
                            value="waiting (draft + checked)", inline=True, label="Show")
    dr_save_btn = mo.ui.run_button(label="Save draft", kind="neutral")
    dr_approve_btn = mo.ui.run_button(label="Approve: add to my_cards.yaml", kind="success")
    dr_bin_reason = mo.ui.dropdown(options=idea_drafts.BIN_REASONS, value=idea_drafts.BIN_REASONS[0],
                                   label="Why bin it")
    dr_bin_btn = mo.ui.run_button(label="Bin draft", kind="danger")
    dr_verdict = mo.ui.text_area(placeholder="verdict:\n  id: IE_...\n  decision: keep | rewrite | bin\n  ...",
                                 rows=7, full_width=True, label="Paste the Critic's VERDICT")
    dr_verdict_btn = mo.ui.run_button(label="Attach the verdict to its draft", kind="neutral")
    dr_pack_btn = mo.ui.run_button(label="Rebuild the knowledge pack", kind="neutral")
    return (dr_approve_btn, dr_bin_btn, dr_bin_reason, dr_filter, dr_import, dr_import_btn, dr_pack_btn,
            dr_save_btn, dr_start, dr_start_btn, dr_verdict, dr_verdict_btn)


@app.cell(hide_code=True)
def _(dr_start, dr_start_btn, drafts, get_dr_src, idea_drafts, mo, set_dr_msg, set_dr_open, set_dr_src):
    mo.stop(not dr_start_btn.value)
    if dr_start.value:
        _c = idea_drafts.copy_of(dr_start.value, taken=drafts.ids())
        _src = f"copy of {dr_start.value}"
        _m = (f"Copied **{dr_start.value}** as **{_c['id']}**. Change ONE thing for an economic reason (data, "
              "mechanism or horizon) - otherwise it is the same card twice.")
    else:
        _c, _src, _m = idea_drafts.template(), "", "Blank card loaded. Start with the story: who is wrong, and why."
    set_dr_src({"card": _c, "source": _src, "n": get_dr_src()["n"] + 1})
    set_dr_open(None)
    set_dr_msg(("neutral", _m))
    return


@app.cell(hide_code=True)
def _(J, catalog, dr_import, dr_import_btn, drafts, get_dr_src, get_dr_v, hyp, idea_drafts, mo, region_dd,
      set_dr_msg, set_dr_open, set_dr_src, set_dr_v):
    mo.stop(not dr_import_btn.value)
    _lib = hyp.load_library()
    _ok, _bad = [], []
    for _p in idea_drafts.parse_cards(dr_import.value):
        if _p.card is None:
            _bad += _p.errors
            continue
        _rep = idea_drafts.check_card(_p.card, catalog, region_dd.value, journal=J, library=_lib)
        try:
            drafts.save(_p.card, _p.source or "imported", report=_rep)
            _ok.append((_p, _rep))
        except Exception as _e:  # noqa: BLE001
            _bad.append(f"{_p.card.get('id')}: {_e}")
    if _ok:
        _first = _ok[0][0]
        set_dr_src({"card": _first.card, "source": _first.source or "imported", "n": get_dr_src()["n"] + 1})
        set_dr_open(str(_first.card["id"]))
    _lines = [f"- **{_p.card['id']}** ({_r.state}): {_r.summary()}" for _p, _r in _ok] + [f"- {_b}" for _b in _bad]
    set_dr_msg(("success" if _ok and not _bad else "warn", "**Import**\n\n" + "\n".join(_lines)))
    set_dr_v(get_dr_v() + 1)
    return


@app.cell(hide_code=True)
def _(dr_filter, drafts, get_dr_v, mo):
    get_dr_v()
    _st = {"waiting": ["draft", "checked"], "approved": ["approved"], "binned": ["binned"], "all": None}
    _df = drafts.list(_st[dr_filter.value])
    dr_table = mo.ui.table(_df, selection="single", page_size=5, show_download=False,
                           label="Your drafts - tick one, then open or restore it")
    dr_open_btn = mo.ui.run_button(label="Open in the form", kind="neutral", disabled=_df.empty)
    dr_restore_btn = mo.ui.run_button(label="Restore (back to draft)", kind="success",
                                      disabled=dr_filter.value not in ("binned", "all") or _df.empty)
    dr_counts = drafts.counts()
    return dr_counts, dr_open_btn, dr_restore_btn, dr_table


@app.cell(hide_code=True)
def _(dr_open_btn, dr_restore_btn, dr_table, drafts, get_dr_src, get_dr_v, mo, set_dr_msg, set_dr_open,
      set_dr_src, set_dr_v):
    mo.stop(not (dr_open_btn.value or dr_restore_btn.value))
    _sel = dr_table.value
    _id = str(_sel.iloc[0]["id"]) if _sel is not None and len(_sel) else None
    _row = drafts.get(_id) if _id else None
    if _row is None or _row["card"] is None:
        set_dr_msg(("warn", "Tick a draft in the list first."))
    elif dr_restore_btn.value:
        if _row["state"] == "binned":
            drafts.restore(_id)
            set_dr_src({"card": _row["card"], "source": _row["source"] or "", "n": get_dr_src()["n"] + 1})
            set_dr_open(_id)
            set_dr_msg(("success", f"**{_id}** is back as a draft and open in the form."))
        else:
            set_dr_msg(("warn", f"**{_id}** is not binned ({_row['state']})."))
        set_dr_v(get_dr_v() + 1)
    else:
        set_dr_src({"card": _row["card"], "source": _row["source"] or "", "n": get_dr_src()["n"] + 1})
        set_dr_open(_id)
        _note = " It is approved, so the form is read-only: copy it to a new id to change it." \
            if _row["state"] == "approved" else ""
        set_dr_msg(("neutral", f"Opened **{_id}** ({_row['state']}).{_note}"))
    return


@app.cell(hide_code=True)
def _(CATEGORY_NAMES, CONCEPTS, get_dr_src, idea_drafts, mo):
    # The form. Rebuilt only when another card is loaded (get_dr_src), never while you type - and never when the
    # region changes, which would wipe unsaved edits (so it depends on nothing else).
    _src = get_dr_src()
    _d = idea_drafts.form_defaults(_src["card"])
    # The browser keeps a value per element id and showed the OLD card's text when the rebuilt form reused the
    # same ids (checked with Playwright, marimo 0.23.16). So every load gets ids never used before in the session.
    try:
        from marimo._runtime.context import get_context as _ctx
        _ctx()._id_provider._counter += 1000 * _src["n"]
    except Exception:  # noqa: BLE001 - private API; without it a reload of the page shows the new card
        pass
    _NC = idea_drafts.NO_CONCEPT

    def _with(opts, cur):
        return list(opts) + ([cur] if cur not in opts else [])

    _concepts = [_NC] + sorted(CONCEPTS)
    _cats = {"auto (from the data used)": "auto", **{f"{v} ({k})": k for k, v in CATEGORY_NAMES.items()}}
    if _d["category"] not in _cats.values():
        _cats[_d["category"]] = _d["category"]
    _strength = {"1 - speculative": 1, "2 - solid in papers": 2, "3 - replicated in many markets": 3}
    _neut = list(dict.fromkeys(sorted(idea_drafts.NEUTRALIZATIONS) + [_d["neutralization"]]))

    def _role(r):
        return mo.ui.dictionary({
            "name": mo.ui.text(value=r["name"], placeholder="role, e.g. tax"),
            "concept": mo.ui.dropdown(options=_with(_concepts, r["concept"] or _NC), value=r["concept"] or _NC,
                                      searchable=True),
            "optional": mo.ui.checkbox(value=r["optional"], label="optional"),
            "note": mo.ui.text(value=r["note"], placeholder="what the field should be (helps you check the binding)",
                               full_width=True)})

    def _rung(s, i):
        return mo.ui.dictionary({
            "name": mo.ui.text(value=s["name"], placeholder="core" if i == 0 else "one change, e.g. smoothed"),
            "expr": mo.ui.text_area(value=s["expr"], rows=2, full_width=True,
                                    placeholder="group_rank(ts_backfill({tax}, 63) / cap, subindustry)" if i == 0
                                    else "optional: rung 1 with ONE change (leave empty if not needed)"),
            "teaches": mo.ui.text(value=s["teaches"], full_width=True,
                                  placeholder="what this rung tests that the previous one did not")})

    _hz = _with(list(idea_drafts.HORIZONS), _d["horizon"])
    dr_form = mo.ui.dictionary({
        "id": mo.ui.text(value=_d["id"], placeholder="IE_MY_IDEA", label="id"),
        "title": mo.ui.text(value=_d["title"], full_width=True, placeholder="the idea in plain words", label="Title"),
        "family": mo.ui.text(value=_d["family"], placeholder="snake_case, e.g. tax_avoidance", label="Family"),
        "category": mo.ui.dropdown(options=_cats, value=next(k for k, v in _cats.items() if v == _d["category"]),
                                   label="Pyramid category"),
        "horizon": mo.ui.dropdown(options=_hz, value=_d["horizon"], label="Horizon"),
        "strength": mo.ui.dropdown(options=_strength, label="Evidence",
                                   value=next((k for k, v in _strength.items() if v == _d["strength"]),
                                              "2 - solid in papers")),
        "sign": mo.ui.text(value=_d["sign"], placeholder="+1", label="Expected sign"),
        "story": mo.ui.text_area(value=_d["story"], rows=4, full_width=True, label="The story (mechanism)",
                                 placeholder="Who makes the mistake, and why do prices adjust slowly?"),
        "why_persists": mo.ui.text_area(value=_d["why_persists"], rows=3, full_width=True, label="Why it persists",
                                        placeholder="Who is on the other side, and what stops them arbitraging it?"),
        "references": mo.ui.text_area(value=_d["references"], rows=2, full_width=True,
                                      label="References (one per line)"),
        "watch_out": mo.ui.text_area(value=_d["watch_out"], rows=2, full_width=True,
                                     label="Watch out (one trap per line, optional)"),
        "roles": mo.ui.array([_role(r) for r in _d["roles"]]),
        "rungs": mo.ui.array([_rung(s, i) for i, s in enumerate(_d["rungs"])]),
        "neutralization": mo.ui.dropdown(options=_neut, value=_d["neutralization"], label="Neutralization"),
        "decay": mo.ui.number(start=0, stop=512, step=1, value=min(max(_d["decay"], 0), 512), label="Decay"),
        "truncation": mo.ui.number(start=0.01, stop=1.0, step=0.01, value=min(max(_d["truncation"], 0.01), 1.0),
                                   label="Truncation"),
        "turnover_low": mo.ui.number(start=0, stop=1.5, step=0.01, value=min(max(_d["turnover_low"], 0), 1.5),
                                     label="Turnover from"),
        "turnover_high": mo.ui.number(start=0, stop=1.5, step=0.01, value=min(max(_d["turnover_high"], 0), 1.5),
                                      label="to"),
    })
    return (dr_form,)


@app.cell(hide_code=True)
def _(J, catalog, dr_form, drafts, get_dr_open, get_dr_src, get_dr_v, get_version, hyp, idea_drafts, region_dd):
    # live checks on every change - nothing is simulated
    get_dr_v(), get_version()
    dr_card = idea_drafts.card_from_form(dr_form.value, get_dr_src()["card"])
    _open = get_dr_open()
    dr_row = drafts.get(_open) if _open else None
    _allow = _open if dr_row and dr_row["state"] == "approved" else None
    dr_report = idea_drafts.check_card(dr_card, catalog, region_dd.value, journal=J, library=hyp.load_library(),
                                       allow_id=_allow)
    return dr_card, dr_report, dr_row


@app.cell(hide_code=True)
def _(dr_approve_btn, dr_bin_btn, dr_bin_reason, dr_card, dr_report, dr_row, dr_save_btn, drafts, get_dr_open,
      get_dr_src, get_dr_v, get_version, idea_drafts, mo, set_dr_approved, set_dr_msg, set_dr_open, set_dr_src,
      set_dr_v, set_version):
    mo.stop(not (dr_save_btn.value or dr_approve_btn.value or dr_bin_btn.value))
    _src = get_dr_src()
    _blank = {"card": idea_drafts.template(), "source": "", "n": _src["n"] + 1}
    if dr_row is not None and dr_row["state"] == "approved":
        set_dr_msg(("warn", f"**{dr_row['id']}** is approved and read-only. To change it, start from "
                            f"*Copy {dr_row['id']}* (a new id), or bin it on the Cards tab."))
    elif dr_approve_btn.value and not dr_report.ok:
        set_dr_msg(("danger", f"Not approved: {dr_report.summary()}. The checks on the right say what to fix."))
    else:
        try:
            _id = drafts.save(dr_card, _src["source"], report=dr_report, old_id=get_dr_open())
            if dr_approve_btn.value:
                _had = (idea_drafts.hyp.user_library_dir() / idea_drafts.MY_CARDS).exists()
                _path = drafts.approve(_id, dr_report)
                set_version(get_version() + 1)          # Cards ranking and the Lab list pick it up
                set_dr_approved(_id)
                set_dr_src(_blank)
                set_dr_open(None)
                _bind = "" if dr_report.idea is not None or not dr_report.region else \
                    f" Note: it does not bind in {dr_report.region}; pick a region where its data exists."
                set_dr_msg(("success", f"**{_id}** approved and added to `{_path}`"
                                       + (" (previous file kept as `my_cards.yaml.bak`)" if _had else "")
                                       + ". It is on the Cards tab (source *mine*) and in the Lab's card list. "
                                       "The form is blank again." + _bind))
            elif dr_bin_btn.value:
                drafts.bin(_id, dr_bin_reason.value)
                set_dr_src(_blank)
                set_dr_open(None)
                set_dr_msg(("neutral", f"Binned **{_id}** ({dr_bin_reason.value}). It stays in the list under "
                                       "*binned*; restore it any time."))
            else:
                set_dr_open(_id)
                set_dr_msg(("success" if dr_report.ok else "warn",
                            f"Saved **{_id}** as *{dr_report.state}*. {dr_report.summary()}."))
        except Exception as _e:  # noqa: BLE001
            set_dr_msg(("danger", f"Not saved: {_e}"))
    set_dr_v(get_dr_v() + 1)
    return


@app.cell(hide_code=True)
def _(dr_verdict, dr_verdict_btn, drafts, get_dr_v, mo, set_dr_msg, set_dr_v):
    mo.stop(not dr_verdict_btn.value)
    _next = {"keep": "Approve it when the checks pass, then test rung 1 in the Lab.",
             "rewrite": "Paste the fixes into Scout & Writer, then import the rewritten card here.",
             "bin": "If you agree, bin it with the reason *Critic said bin* (the decision stays yours)."}
    try:
        _v = drafts.attach_verdict(dr_verdict.value)
        set_dr_msg(("success", f"Verdict **{_v['decision']}** attached to **{_v['id']}**. {_next[_v['decision']]}"))
    except Exception as _e:  # noqa: BLE001
        set_dr_msg(("danger", f"Verdict not attached: {_e}"))
    set_dr_v(get_dr_v() + 1)
    return


@app.cell(hide_code=True)
def _(get_dr_approved, mo):
    dr_lab_btn = mo.ui.run_button(label=f"Send {get_dr_approved() or 'it'} to the Lab", kind="success",
                                  disabled=get_dr_approved() is None)
    return (dr_lab_btn,)


@app.cell(hide_code=True)
def _(dr_lab_btn, get_dr_approved, mo, set_lab_card):
    mo.stop(not dr_lab_btn.value or get_dr_approved() is None)
    import time as _time
    set_lab_card((get_dr_approved(), _time.time()))
    return


@app.cell(hide_code=True)
def _(Journal, dr_pack_btn, idea_drafts, mo, set_dr_msg, store):
    mo.stop(not dr_pack_btn.value)
    try:
        try:
            _j = Journal.open_readonly()                # your real journal, also in sandbox mode
        except Exception:  # noqa: BLE001
            _j = None
        _files = idea_drafts.rebuild_knowledge_pack(_j, store)
        set_dr_msg(("success", f"Knowledge pack rebuilt in `{_files[0].parent}` ({len(_files)} files). Re-upload "
                               "the ones that changed (03, 04, 06, 07, 08) to the Claude Projects."))
    except Exception as _e:  # noqa: BLE001
        set_dr_msg(("danger", f"Knowledge pack not rebuilt: {_e}"))
    return


@app.cell(hide_code=True)
def _(SANDBOX, catalog_ok, dr_approve_btn, dr_bin_btn, dr_bin_reason, dr_card, dr_counts, dr_filter, dr_form,
      dr_import, dr_import_btn, dr_lab_btn, dr_open_btn, dr_pack_btn, dr_report, dr_restore_btn, dr_row,
      dr_save_btn, dr_start, dr_start_btn, dr_table, dr_verdict, dr_verdict_btn, dr_view_runs, get_dr_approved,
      get_dr_msg, get_dr_src, idea_drafts, mo, pd, region_dd, views):
    _f = dr_form
    _msg = get_dr_msg()
    try:                                     # fresh element ids on every run (see the form cell)
        from marimo._runtime.context import get_context as _ctx
        _ctx()._id_provider._counter += 100 * next(dr_view_runs)
    except Exception:  # noqa: BLE001
        pass
    _list = mo.vstack([mo.hstack([mo.md("### Your drafts"), dr_filter], justify="start", gap=2, align="center"),
                       dr_table if len(dr_table.data) else mo.md("_Nothing here yet._"),
                       mo.hstack([dr_open_btn, dr_restore_btn], justify="start", gap=1)])
    _top = [mo.md("Write a hypothesis card, or import one from the **Scout & Writer** project. Every change is "
                  "checked at once - format, Gold operators, concepts, a dry-run binding to real fields in the "
                  "region below, the same family in the library, and your journal's dead ends. **Nothing is "
                  "simulated here.** Approve adds the card to your library; then test it in the Lab."),
            mo.md(f"Drafts: waiting **{dr_counts.get('draft', 0) + dr_counts.get('checked', 0)}** "
                  f"(checked {dr_counts.get('checked', 0)}) | approved **{dr_counts.get('approved', 0)}** | "
                  f"binned {dr_counts.get('binned', 0)}")]
    if _msg:
        _top.append(mo.callout(mo.md(_msg[1]), kind=_msg[0]))
    if get_dr_approved():
        _top.append(dr_lab_btn)
    _top += [mo.hstack([dr_start, dr_start_btn, region_dd], justify="start", gap=1.5, align="end", wrap=True),
             mo.accordion({"Import from Scout & Writer": mo.vstack([dr_import, dr_import_btn])}), _list]
    if not catalog_ok and not SANDBOX:
        _top.append(mo.callout(mo.md(f"No field list for **{region_dd.value}** yet: the dry-run binding needs it "
                                     "(download it on the Cards or Data tab)."), kind="warn"))

    # ---- left: the form
    _roles = [mo.hstack([_r["name"], _r["concept"], _r["optional"], _r["note"]], widths=[2, 3, 1, 5],
                        align="center", gap=0.5) for _r in _f["roles"].elements]
    _rungs = []
    for _i, _s in enumerate(_f["rungs"].elements):
        _rungs += [mo.hstack([mo.md(f"**Rung {_i + 1}**"), _s["name"], _s["teaches"]], widths=[1, 2, 6],
                             align="center", gap=0.5), _s["expr"]]
    _src = get_dr_src()["source"]
    _state = f"draft **{dr_row['id']}** - {dr_row['state']}" if dr_row else "not saved yet"
    _left = mo.vstack([
        mo.md(f"### The card  <small>({_state}{'; from: ' + _src if _src else ''})</small>"),
        mo.hstack([_f["id"], _f["family"], _f["category"]], justify="start", gap=1, wrap=True),
        mo.hstack([_f["horizon"], _f["strength"], _f["sign"]], justify="start", gap=1, wrap=True),
        _f["title"], _f["story"], _f["why_persists"],
        mo.md("**Data roles** - concepts, never field ids (HYPOLAB binds them per region). Leave empty if the "
              "card uses only price/volume (close, returns, volume, adv20, cap ...)."),
        *_roles,
        mo.md("**Ladder** - rung 1 is the plainest test; each later rung changes ONE thing. Write data as "
              "`{role}`; `{dir:role}` becomes +1/-1 from the field's description."),
        *_rungs,
        mo.hstack([_f["neutralization"], _f["decay"], _f["truncation"], _f["turnover_low"], _f["turnover_high"]],
                  justify="start", gap=1, wrap=True),
        _f["references"], _f["watch_out"],
    ], gap=0.6)

    # ---- right: checks, dry run, actions, hand-offs
    _rep = dr_report
    _kind = "danger" if _rep.errors else ("warn" if _rep.idea is None and _rep.region else "success")
    _right = [mo.md("### Checks"), mo.callout(mo.md(f"**{_rep.summary()}**"), kind=_kind)]
    # read-only tables as Markdown: this cell re-runs on every keystroke, and marimo's browser side mixes up
    # UI elements whose ids shift between runs (a table appearing or not) - Markdown has no id
    if _rep.checks:
        _right.append(mo.md(views.html_table(_rep.table())))
    if _rep.bindings:
        _right.append(mo.md(f"**Dry-run binding in {_rep.region} {_rep.universe} D{_rep.delay}** - read the "
                            "descriptions: you are the final judge\n\n"
                            + views.html_table(pd.DataFrame(_rep.bindings).drop(columns=["why"]),
                                               code_cols=["field"])))
    if _rep.rungs:
        _right.append(mo.md("**Rungs as they would be simulated**\n\n"
                            + views.html_table(pd.DataFrame(_rep.rungs), code_cols=["expression"])))
    _right += [mo.hstack([dr_save_btn, dr_approve_btn], justify="start", gap=1),
               mo.hstack([dr_bin_reason, dr_bin_btn], justify="start", gap=1, align="end")]
    _ver = idea_drafts.verdict_markdown(dr_row["verdict"]) if dr_row and dr_row.get("verdict") else ""
    if _ver:
        _right.append(mo.callout(mo.md(_ver), kind="info"))
    _critic = idea_drafts.critic_message(dr_card, _rep, _src)
    _handoff = mo.accordion({
        "Copy for the Critic (card + dry run)": mo.vstack([
            mo.md("Copy this into the **Critic** project; paste its VERDICT below."),
            mo.ui.code_editor(value=_critic, language="yaml", disabled=True, show_copy_button=True, theme="dark")]),
        "Paste the Critic's VERDICT": mo.vstack([dr_verdict, dr_verdict_btn]),
        "The card as YAML": mo.ui.code_editor(value=idea_drafts.card_yaml(dr_card, _src), language="yaml",
                                              disabled=True, show_copy_button=True, theme="dark"),
        "Rebuild the knowledge pack": mo.vstack([
            mo.md("The Writer, Critic and Reviewer read the knowledge files. Rebuild them after you approve cards "
                  "or download your account, then re-upload the changed files (see `claude_projects/README.md`)."),
            dr_pack_btn]),
    })
    _body = mo.hstack([_left.style({"min-width": "0"}),
                       mo.vstack(_right, gap=0.6).style({"min-width": "0", "max-width": "100%", "overflow-x": "auto"})],
                      widths=[3, 2], gap=2, align="start")
    drafts_view = mo.vstack(_top + [_body, mo.md("### Hand-offs to the Claude Projects team"), _handoff], gap=1)
    return (drafts_view,)


# ==================================================================================================== LAB
@app.cell(hide_code=True)
def _(J, NO_CARD, config, get_bins, get_lab_card, hyp, mo, ranked_cards):
    get_bins()
    _binned = J.binned_ids()
    _ids = [NO_CARD] + [h.id for h in hyp.load_library() if h.id not in _binned]
    # the card you last worked on comes back after a restart (settings.json: last_lab_card; "" = no card)
    _sent = get_lab_card()
    _sent = _sent[0] if isinstance(_sent, tuple) else _sent
    _saved = config.settings().get("last_lab_card")
    _first = _sent or (NO_CARD if _saved == "" else _saved) or \
        (ranked_cards[0].hypothesis.id if ranked_cards else NO_CARD)
    lab_card_dd = mo.ui.dropdown(options=_ids, value=_first if _first in _ids else NO_CARD, searchable=True,
                                 label="Idea card")
    return (lab_card_dd,)


@app.cell(hide_code=True)
def _(NO_CARD, R, config, lab_card_dd, region_dd):
    lab_card, lab_card_error = None, ""
    _keep = "" if lab_card_dd.value in (None, NO_CARD) else lab_card_dd.value
    if config.settings().get("last_lab_card") != _keep:
        config.save_settings(last_lab_card=_keep)
    if R is not None and _keep:
        try:
            lab_card = R.card(lab_card_dd.value, region=region_dd.value)
        except Exception as _e:  # noqa: BLE001
            lab_card_error = str(_e)
    return lab_card, lab_card_error


@app.cell(hide_code=True)
def _(config, lab_card, mo, region_dd):
    _steps = lab_card.steps if lab_card is not None else []
    rung_dd = mo.ui.dropdown(options={f"{i + 1}. {s.name}": i for i, s in enumerate(_steps)},
                             value=f"1. {_steps[0].name}" if _steps else None, label="Rung")
    _st = lab_card.settings if lab_card is not None else {}
    custom_expr = mo.ui.text_area(value="", rows=3, full_width=True,
                                  label="Or your own expression (leave empty to use the rung; still linted, "
                                        "budgeted and counted against this idea)" if lab_card is not None else
                                        "Your expression (linted before it costs a simulation)")
    decay_in = mo.ui.number(start=0, stop=60, step=1, value=int(_st.get("decay", 0) or 0), label="Decay")
    # Every neutralization BRAIN offers in this region (incl. the risk sets SLOW / FAST / SLOW_AND_FAST /
    # REVERSION_AND_MOMENTUM / STATISTICAL / CROWDING once the simulation options are synced) - BRAIN_RULES N1.
    _reg = lab_card.region if lab_card is not None else region_dd.value
    _neut = _st.get("neutralization", "SUBINDUSTRY")
    neut_dd = mo.ui.dropdown(options=list(dict.fromkeys(config.region_neutralizations(_reg) + [_neut])),
                             value=_neut, label="Neutralization")
    _delays = config.REGION_DEFAULTS.get(_reg, {}).get("delays", [1])
    _d0 = int(lab_card.delay) if lab_card is not None else 1
    delay_dd = mo.ui.dropdown(options={f"D{d}": d for d in dict.fromkeys(_delays + [_d0])}, value=f"D{_d0}",
                              label="Delay")
    trunc_in = mo.ui.number(start=0.01, stop=1.0, step=0.01, value=float(_st.get("truncation", 0.08) or 0.08),
                            label="Truncation")
    sim_btn = mo.ui.run_button(label="Simulate", kind="success")
    lab_remove_btn = mo.ui.run_button(label="Remove card from the Lab", kind="neutral", disabled=lab_card is None)
    lab_bin_btn = mo.ui.run_button(label="Bin card (noise)", kind="danger", disabled=lab_card is None)
    return (custom_expr, decay_in, delay_dd, lab_bin_btn, lab_remove_btn, neut_dd, rung_dd, sim_btn, trunc_in)


@app.cell(hide_code=True)
def _(NO_CARD, R, config, get_bins, lab_bin_btn, lab_card, lab_remove_btn, mo, set_bin_msg, set_bins,
      set_lab_card):
    # 1.4.3: take the card out of the Lab (results stay in the list and the journal), or bin it as noise
    mo.stop(not (lab_remove_btn.value or lab_bin_btn.value) or lab_card is None)
    import time as _time
    _id = lab_card.hypothesis.id
    if lab_bin_btn.value and R is not None:
        R.bin(_id, "noise - binned from the Lab")
        set_bin_msg(("lab", f"Binned **{_id}** from the Lab. Restore it from **Cards > The bin**."))
        set_bins(get_bins() + 1)
    config.save_settings(last_lab_card="")
    set_lab_card((NO_CARD, _time.time()))
    return


@app.cell(hide_code=True)
def _(R, add_results, config, custom_expr, decay_in, delay_dd, lab_card, mo, neut_dd, region_dd, rung_dd,
      sim_btn, trunc_in, theme):
    # Spends ONE simulation, and only when you click Simulate (changing a control never simulates).
    _expr = custom_expr.value.strip() or None
    mo.stop(not sim_btn.value or R is None or (lab_card is None and not _expr),
            mo.callout(mo.md("No card in the Lab: write your own expression first."), kind="warn")
            if sim_btn.value and lab_card is None and not _expr else None)
    _settings = {"decay": int(decay_in.value), "neutralization": neut_dd.value, "truncation": float(trunc_in.value),
                 "delay": int(delay_dd.value)}
    if lab_card is None:          # your own expression, no card: counted as manual@<region>
        _settings.update(region=region_dd.value, universe=config.universe_for(region_dd.value))
    with mo.status.spinner(title=theme.loading_line("1 simulation")):
        _t = R.test(lab_card, rung=int(rung_dd.value or 0), expression=_expr, settings=_settings)
    add_results([_t])
    return


@app.cell(hide_code=True)
def _(get_focus, get_results, mo, pd, views):
    _res = get_results()
    _f = get_focus()
    _pick = _f if isinstance(_f, int) and 0 <= _f < len(_res) else len(_res) - 1
    lab_history = mo.ui.table(pd.DataFrame([{"#": i, "": "\u25b6" if i == _pick else "", **views.result_row(t)}
                                            for i, t in enumerate(_res)]),
                              selection="single",
                              initial_selection=[_pick] if _res else None, page_size=8,
                              label="Results this session (select one to work on; \u25b6 = shown below)")
    lab_remove_res = mo.ui.run_button(label="Remove the selected result from this list", kind="neutral",
                                      disabled=not _res)
    lab_clear_res = mo.ui.run_button(label="Clear the list", kind="neutral", disabled=not _res)
    return lab_clear_res, lab_history, lab_remove_res


@app.cell(hide_code=True)
def _(get_focus, get_results, lab_history):
    _res = get_results()
    current = None
    if _res:
        _f = get_focus()
        _idx = _f if isinstance(_f, int) and 0 <= _f < len(_res) else len(_res) - 1
        _sel = lab_history.value
        if _sel is not None and len(_sel):
            _idx = int(_sel.iloc[0]["#"])
        current = _res[_idx]
    return (current,)


@app.cell(hide_code=True)
def _(current, mo, views):
    _choices = views.action_choices(current) if current is not None else {}
    follow_dd = mo.ui.dropdown(options=_choices, value=next(iter(_choices), None), label="Suggested action")
    follow_btn = mo.ui.run_button(label="Apply it (1 simulation)", disabled=not _choices)
    boost_k = mo.ui.number(start=1, stop=8, step=1, value=4, label="Boosters to try")
    boost_mode = mo.ui.dropdown(options={"add: rank(a) + rank(b)": "add", "and: min(rank(a), rank(b))": "and"},
                                value="add: rank(a) + rank(b)", label="Combine")
    boost_btn = mo.ui.run_button(label="Boost (up to 2 x k simulations)")
    robust_btn = mo.ui.run_button(label="Run the robustness battery (about 7 simulations)")
    gate_btn = mo.ui.run_button(label="Gate report")
    return boost_btn, boost_k, boost_mode, follow_btn, follow_dd, gate_btn, robust_btn


@app.cell(hide_code=True)
def _(R, add_results, current, follow_btn, follow_dd, mo, theme):
    mo.stop(not follow_btn.value or current is None or follow_dd.value is None)
    with mo.status.spinner(title=theme.loading_line("the suggested change")):
        _t = R.follow(current, int(follow_dd.value))
    add_results([_t])
    return


@app.cell(hide_code=True)
def _(current, get_results, lab_clear_res, lab_remove_res, mo, set_focus, set_results):
    # 1.4.3: tidy the Lab's list (the journal keeps everything; "Restore results" brings them back)
    mo.stop(not (lab_remove_res.value or lab_clear_res.value))
    if lab_clear_res.value:
        set_results([])
    elif current is not None:
        set_results([t for t in get_results() if t is not current])
    set_focus(None)
    return


@app.cell(hide_code=True)
def _(R, add_results, boost_btn, boost_k, boost_mode, boost_compare, current, get_perf, mo, set_boost,
      set_perf, theme):
    mo.stop(not boost_btn.value or current is None)
    try:
        with mo.status.spinner(title=theme.loading_line("boosters")):
            _rep = R.boost(current, k=int(boost_k.value), mode=boost_mode.value)
            _perf = dict(get_perf())
            if _rep.best is not None and _rep.best.alpha_id:      # the boosted alpha's PnL, drawn right away
                _perf[_rep.best.alpha_id] = R.performance(_rep.best, compare=boost_compare(_rep, _rep.best))
        set_boost(_rep)
        set_perf(_perf)
        # each booster alone, then the combinations, the best one LAST so it is selected and shown below
        add_results(_rep.lab_results())
    except ValueError as _e:
        set_boost(str(_e))
    return


@app.cell(hide_code=True)
def _():
    def boost_compare(rep, t):
        """Lines drawn next to a boost result: the base alpha and the booster alone."""
        if rep is None or isinstance(rep, str):
            return {}
        for _k, _r in rep.results.items():
            if _r is t or (_r.alpha_id and _r.alpha_id == t.alpha_id):
                _b = rep.boosters.get(_k)
                return {"base": rep.base.alpha_id, "booster " + _k: _b.alpha_id if _b is not None else None}
        return {}
    return (boost_compare,)


@app.cell(hide_code=True)
def _(get_boost, get_results, mo, set_focus):
    # 1.4.3: jump to any alpha the last boost made (each booster alone and every combination)
    _b = get_boost()
    _opts = {}
    if _b is not None and not isinstance(_b, str):
        _res = get_results()
        for _t in _b.lab_results():
            _i = next((i for i, r in enumerate(_res) if r is _t), None)
            if _i is not None:
                _s = _t.summary.get("is_sharpe")
                _who = _t.card.hypothesis.id if _t.card is not None else (_t.idea_id or "manual")
                _opts[f"#{_i}  {_who} / {_t.rung}  -  Sharpe {_s if _s is not None else '-'}  "
                      f"{_t.diagnosis.verdict}"] = _i
    open_boost_dd = mo.ui.dropdown(options=_opts, label="Open a boosted alpha", on_change=set_focus,
                                   full_width=True)
    return (open_boost_dd,)


@app.cell(hide_code=True)
def _(current, mo):
    perf_btn = mo.ui.run_button(label="Show its performance (PnL chart + yearly table, no simulation)",
                                disabled=current is None or not current.alpha_id)
    return (perf_btn,)


@app.cell(hide_code=True)
def _(R, boost_compare, current, get_boost, get_perf, mo, perf_btn, set_perf):
    mo.stop(not perf_btn.value or R is None or current is None or not current.alpha_id)
    with mo.status.spinner(title="Reading the PnL from BRAIN ..."):
        _p = R.performance(current, compare=boost_compare(get_boost(), current))
    set_perf({**get_perf(), current.alpha_id: _p})
    return


@app.cell(hide_code=True)
def _(current, get_perf, mo, pd, views):
    # the performance panel for the result shown in the Lab
    perf_view = None
    _p = get_perf().get(current.alpha_id) if current is not None and current.alpha_id else None
    if _p is not None:
        if _p["error"]:
            perf_view = mo.callout(mo.md(_p["error"]), kind="warn")
        else:
            import matplotlib.pyplot as _plt
            _parts = []
            if not _p["pnl"].empty:
                _fig = views.pnl_figure(_p["pnl"], title=f"Cumulative PnL - {current.rung}")
                _parts.append(mo.as_html(_fig))
                _plt.close(_fig)
            _y = _p["yearly"]
            if _y is not None and not _y.empty:
                if not isinstance(_y.index, pd.RangeIndex):
                    _y = _y.reset_index()
                if "year" in _y.columns:
                    _y = _y.assign(year=_y["year"].astype(str))
                _parts.append(mo.ui.table(_y, selection=None, page_size=12, show_download=False,
                                          show_column_summaries=False, label="Year by year"))
            perf_view = mo.vstack(_parts) if _parts else mo.md("_BRAIN returned no PnL for this alpha._")
    return (perf_view,)


@app.cell(hide_code=True)
def _(R, current, get_robust, mo, robust_btn, set_robust, theme):
    mo.stop(not robust_btn.value or current is None or not current.alpha_id)
    with mo.status.spinner(title=theme.loading_line("robustness battery")):
        _rb = R.robustness(current)
    set_robust({**get_robust(), current.alpha_id: _rb})
    return


@app.cell(hide_code=True)
def _(R, current, gate_btn, get_robust, mo, set_gate):
    mo.stop(not gate_btn.value or current is None or not current.alpha_id)
    with mo.status.spinner(title="Platform checks, correlations, deflated Sharpe ..."):
        set_gate(R.gate(current, get_robust().get(current.alpha_id)))
    return


@app.cell(hide_code=True)
def _(J, SANDBOX, config, current, get_gate, get_submitted, mo):
    get_submitted()
    _g = get_gate()
    _ready = _g is not None and current is not None and _g.alpha_id == current.alpha_id and _g.ready
    _cap = int(config.settings().get("max_submissions_per_day", 4))
    submissions_today = J.submissions_today()
    _ready = _ready and submissions_today < _cap
    confirm_in = mo.ui.text(value="", placeholder=f"SUBMIT {_g.alpha_id}" if _ready else "",
                            label="Type SUBMIT and the alpha id to confirm", full_width=True)
    submit_btn = mo.ui.run_button(label="Submit to BRAIN (permanent)" if not SANDBOX else "Submit (sandbox practice)",
                                  kind="danger", disabled=not _ready)
    return confirm_in, submissions_today, submit_btn


@app.cell(hide_code=True)
def _(R, confirm_in, get_gate, get_submitted, mo, set_submitted, submit_btn):
    mo.stop(not submit_btn.value)
    _g = get_gate()
    try:
        _res = R.submit(_g, confirm=confirm_in.value.strip())
        set_submitted(get_submitted() + [(_g.alpha_id, str(_res))])
    except Exception as _e:  # noqa: BLE001
        set_submitted(get_submitted() + [(_g.alpha_id, f"NOT submitted: {_e}")])
    return


@app.cell(hide_code=True)
def _(mo):
    # Pick up where you left off (1.4.1): results come back from the journal, interrupted simulations from BRAIN.
    restore_btn = mo.ui.run_button(label="Restore results", kind="neutral")
    recover_btn = mo.ui.run_button(label="Fetch them from BRAIN (no new simulation)", kind="success")
    get_resume_msg, set_resume_msg = mo.state(None)
    return get_resume_msg, recover_btn, restore_btn, set_resume_msg


@app.cell(hide_code=True)
def _(R, get_results, mo, restore_btn, set_focus, set_results):
    mo.stop(not restore_btn.value or R is None)
    set_results(R.recent_results(10) + list(get_results()))
    set_focus(None)
    return


@app.cell(hide_code=True)
def _(R, add_results, mo, recover_btn, set_resume_msg, theme):
    mo.stop(not recover_btn.value or R is None)
    with mo.status.spinner(title=theme.loading_line("collecting interrupted simulations")):
        _r = R.recover_pending()
    add_results(_r["recovered"])
    set_resume_msg(f"Recovered {len(_r['recovered'])} result(s) without simulating again"
                   + (f"; {_r['running']} still running on BRAIN - try again in a few minutes" if _r["running"] else "")
                   + (f"; {_r['gone']} no longer on BRAIN (simulate again if you still want them)" if _r["gone"]
                      else "") + ".")
    return


@app.cell(hide_code=True)
def _(R, SANDBOX, get_play, get_results, get_resume_msg, mo, pd, recover_btn, restore_btn):
    get_play()                      # re-check the journal after Play simulations too
    _parts = []
    if R is not None:
        _pend = R.pending() if not SANDBOX else []
        if _pend:
            _parts.append(mo.callout(mo.vstack([
                mo.md(f"**{len(_pend)} simulation(s) were still running when HYPOLAB last closed.** BRAIN finished "
                      "them (and counted them), so collect the results instead of paying again:"),
                mo.ui.table(pd.DataFrame([{"idea": p["idea_id"], "rung": p["rung"], "expression": p["expression"],
                                           "sent": pd.Timestamp(p["created"], unit="s").strftime("%Y-%m-%d %H:%M")}
                                          for p in _pend]), selection=None, show_download=False),
                recover_btn]), kind="info"))
        if not get_results():
            _ex = R.journal.experiments()
            _n = int(_ex["purpose"].isin(["explore", "boost", "play"]).sum()) if not _ex.empty else 0
            if _n:
                _last = pd.Timestamp(_ex["created"].max(), unit="s").strftime("%a %d %b %H:%M")
                _parts.append(mo.callout(mo.hstack([
                    mo.md(f"**Pick up where you left off:** {_n} simulation(s) in your journal, the last on {_last} "
                          "(UTC). Restoring brings back their diagnoses without simulating anything."),
                    restore_btn], justify="space-between", align="center"), kind="neutral"))
        if get_resume_msg():
            _parts.append(mo.callout(mo.md(get_resume_msg()), kind="success"))
    resume_view = mo.vstack(_parts) if _parts else mo.md("")
    return (resume_view,)


@app.cell(hide_code=True)
def _(R, SANDBOX, boost_btn, boost_k, boost_mode, config, confirm_in, current, custom_expr, decay_in, follow_btn,
      follow_dd, gate_btn, get_boost, get_gate, get_robust, get_submitted, lab_card, lab_card_dd, lab_card_error,
      lab_history, mo, neut_dd, pd, region_dd, robust_btn, rung_dd, sim_btn, submit_btn, trunc_in, submissions_today,
      delay_dd, brain_quota, resume_view, lab_remove_btn, lab_bin_btn, lab_remove_res, lab_clear_res, open_boost_dd,
      perf_btn, perf_view, get_bin_msg):
    if R is None:
        lab_view = mo.callout(mo.md("The Lab needs a BRAIN session (or sandbox mode). See the message at the top."),
                              kind="warn")
    else:
        _parts = [resume_view, mo.hstack([lab_card_dd, region_dd, lab_remove_btn, lab_bin_btn], justify="start",
                                         gap=1.5, align="center", wrap=True)]
        _bm = get_bin_msg()
        if isinstance(_bm, tuple) and _bm[0] == "lab":
            _parts.append(mo.callout(mo.md(_bm[1]), kind="neutral"))
        if not SANDBOX:
            _q = brain_quota()
            _parts.append(mo.md(
                f"_BRAIN quota today: **{_q['remaining']:,}** of {_q['limit']:,} simulations left (resets at midnight "
                f"New York = 07:00/08:00 Nairobi). Simulations HYPOLAB counted today: {R.journal.sims_today()}._"
                if _q else f"_Simulations HYPOLAB counted today (BRAIN's day, New York time): "
                           f"{R.journal.sims_today()}. BRAIN's own remaining count appears after the next simulation._"))
        if lab_card_error:
            _parts.append(mo.callout(mo.md(lab_card_error), kind="danger"))
        if lab_card is not None:
            _ladder = pd.DataFrame([{"rung": f"{i + 1}. {s.name}", "expression": s.expression,
                                     "linter": "ok" if s.lint.ok else "BLOCKED", "IS test": s.is_test,
                                     "teaches": s.teaches}
                                    for i, s in enumerate(lab_card.steps)])
            _h = lab_card.hypothesis
            _parts += [mo.md(f"**{_h.title}** - {_h.story}\n\n_Why it can persist:_ {_h.why_persists}  "
                             f"**Expected sign:** {_h.sign}"),
                       mo.ui.table(_ladder, selection=None),
                       mo.hstack([rung_dd, delay_dd, decay_in, neut_dd, trunc_in], justify="start", gap=1.5,
                                 wrap=True),
                       custom_expr, sim_btn]
        else:
            _parts += [mo.md("**No card in the Lab.** Pick one above (or send one from **Cards**), or test your own "
                             "expression - it is linted, budgeted and journaled as `manual@" + str(region_dd.value)
                             + "`."),
                       mo.hstack([delay_dd, decay_in, neut_dd, trunc_in], justify="start", gap=1.5, wrap=True),
                       custom_expr, sim_btn]
        _parts += [lab_history, mo.hstack([lab_remove_res, lab_clear_res], justify="start", gap=0.75)]
        if current is not None:
            _parts.append(mo.md(current.markdown()))
            if current.alpha_id:
                _parts.append(mo.md("### Performance"))
                _parts.append(perf_view if perf_view is not None else perf_btn)
            _parts.append(mo.accordion({
                "Follow ONE suggested action": mo.vstack([follow_dd, follow_btn]),
                "Boost a weak-but-real alpha with an independent second signal": mo.vstack([
                    mo.md("Predicted combined Sharpe = (S1 + S2) / sqrt(2 x (1 + correlation)). Every combination "
                          "counts as a try on this idea."), mo.hstack([boost_k, boost_mode]), boost_btn]),
            }))
            _b = get_boost()
            if isinstance(_b, str):
                _parts.append(mo.callout(mo.md(_b), kind="warn"))
            elif _b is not None and current.alpha_id in _b.alpha_ids():
                # the boost report stays visible while you look at the base, a booster or any combination
                _parts += [mo.md(_b.markdown()), mo.ui.table(_b.table, selection=None, show_download=False)]
                if open_boost_dd.options:
                    _parts.append(open_boost_dd)
            if current.alpha_id:
                _parts.append(mo.md("### Validate before you submit"))
                _parts.append(mo.hstack([robust_btn, gate_btn], justify="start"))
                _rb = get_robust().get(current.alpha_id)
                if _rb is not None:
                    _sc = _rb.attrs.get("score", {})
                    _parts += [mo.md(f"**Robustness:** {_sc.get('score', 0):.0%} - {_sc.get('verdict', '')}"),
                               mo.ui.table(_rb.drop(columns=["expression"], errors="ignore"), selection=None)]
                _g = get_gate()
                if _g is not None and _g.alpha_id == current.alpha_id:
                    _parts.append(mo.md(_g.markdown()))
                    if _g.ready:
                        _parts.append(mo.callout(mo.vstack([
                            mo.md(f"**Submitted today: {submissions_today}/{config.settings().get('max_submissions_per_day', 4)}.** "
                                  + ("Daily limit reached - keep this one for tomorrow. " if submissions_today >=
                                     int(config.settings().get("max_submissions_per_day", 4)) else "")),
                            mo.md("**Your decision.** " + ("Sandbox: practice submission only." if SANDBOX else
                                  "This is a real, permanent submission. One alpha per idea family per region is "
                                  "usually right.")), confirm_in, submit_btn]), kind="warn"))
            for _aid, _msg in get_submitted():
                if _aid == current.alpha_id:
                    _parts.append(mo.callout(mo.md(f"`{_aid}`: {_msg}"),
                                             kind="danger" if _msg.startswith("NOT") else "success"))
        lab_view = mo.vstack(_parts)
    return (lab_view,)


# ================================================================================================ JOURNAL
@app.cell(hide_code=True)
def _(J, mo):
    lesson_form = mo.md("{text}\n\n{idea}").batch(
        text=mo.ui.text_area(placeholder="What did this idea teach you? One or two sentences.", rows=2,
                             full_width=True),
        idea=mo.ui.text(placeholder="idea id (optional), e.g. ANL_EPS_REVISION@USA"),
    ).form(submit_button_label="Add lesson", clear_on_submit=True)
    journal_writable = not getattr(J, "readonly", False)
    return journal_writable, lesson_form


@app.cell(hide_code=True)
def _(J, get_version, journal_writable, lesson_form, mo, set_version):
    mo.stop(lesson_form.value is None or not journal_writable or not lesson_form.value["text"].strip())
    J.add_lesson(lesson_form.value["text"].strip(), idea_id=lesson_form.value["idea"].strip())
    set_version(get_version() + 1)
    return


@app.cell(hide_code=True)
def _(J, mo):
    _ex = J.experiments()
    _regions = sorted(r for r in _ex["region"].dropna().unique()) if not _ex.empty else []
    jr_region = mo.ui.dropdown(options=["all"] + _regions, value="all", label="Region")
    jr_verdicts = mo.ui.multiselect(options=["PASS", "NEAR", "WEAK", "INVERTED", "NOISE", "ERROR"], label="Verdicts")
    return jr_region, jr_verdicts


@app.cell(hide_code=True)
def _(J, config, get_boost, get_results, get_robust, get_submitted, get_version, journal_writable, jr_region,
      jr_verdicts, lesson_form, mo, views):
    get_results(), get_version(), get_submitted(), get_robust(), get_boost()
    _ex = J.experiments()
    _budget = int(config.settings()["max_sims_per_idea"])
    _real = _ex[_ex["backend"] != "sandbox"] if not _ex.empty and not getattr(J, "path", "") == ":memory:" else _ex
    journal_view = mo.vstack([
        mo.md(f"**{len(_ex)} simulation{'' if len(_ex) == 1 else 's'} recorded.** If most verdicts are NOISE, choose ideas more carefully; "
              "if one idea has used its whole budget, stop and write a lesson."),
        mo.hstack([
            mo.vstack([mo.md("### Verdict mix"), mo.ui.table(views.verdict_mix(_real), selection=None)]),
            mo.vstack([mo.md(f"### Tries per idea (budget {_budget})"),
                       mo.ui.table(views.tries_per_idea(_ex, _budget), selection=None, page_size=8)]),
        ], widths=[1, 2], gap=2),
        mo.md("### Scoreboard by family"),
        mo.ui.table(J.scoreboard(), selection=None, page_size=8),
        mo.md("### Experiments"),
        mo.hstack([jr_region, jr_verdicts], justify="start", gap=1.5),
        mo.ui.table(views.experiments_view(_ex, None if jr_region.value == "all" else jr_region.value,
                                           list(jr_verdicts.value) or None), selection=None, page_size=10),
        mo.md("### Submissions"),
        mo.ui.table(J.submissions(), selection=None),
        mo.md("### Lessons"),
        lesson_form if journal_writable else mo.md("_Read-only until you log in._"),
        mo.ui.table(J.lessons(), selection=None, page_size=8),
    ])
    return (journal_view,)


# ================================================================================================== SETUP
@app.cell(hide_code=True)
def _(config, get_conn, mo):
    get_conn()
    _st = config.settings()
    _regions = config.account_regions()
    mode_form = mo.md("{mode}\n\n{region}").batch(
        mode=mo.ui.radio(options={"Sandbox - offline practice market": "sandbox",
                                  "Live - my BRAIN account": "live"},
                         value="Sandbox - offline practice market" if config.sandbox_mode()
                         else "Live - my BRAIN account"),
        region=mo.ui.dropdown(options=_regions, value=config.live_region() if config.live_region() in _regions
                              else _regions[0], label="Live region"),
    ).form(submit_button_label="Apply")
    return (mode_form,)


@app.cell(hide_code=True)
def _(connect, get_conn, mo, mode_form, set_conn):
    mo.stop(mode_form.value is None)
    if mode_form.value["mode"] == "live":
        connect.go_live(mode_form.value["region"])
    else:
        connect.go_sandbox()
    set_conn(get_conn() + 1)
    return


@app.cell(hide_code=True)
def _(mo):
    login_form = mo.md("{email}\n\n{password}\n\n{save}").batch(
        email=mo.ui.text(kind="email", label="BRAIN email", full_width=True),
        password=mo.ui.text(kind="password", label="BRAIN password", full_width=True),
        save=mo.ui.checkbox(value=True, label="Remember on this laptop (~/.hypolab/credentials.json, readable only by you)"),
    ).form(submit_button_label="Log in", clear_on_submit=True)
    scan_done_btn = mo.ui.run_button(label="I finished the face scan", kind="success")
    logout_btn = mo.ui.run_button(label="Log out and forget my credentials", kind="danger")
    return login_form, logout_btn, scan_done_btn


@app.cell(hide_code=True)
def _(AuthError, connect, get_conn, login_form, mo, set_conn, set_login):
    mo.stop(login_form.value is None or not login_form.value["email"] or not login_form.value["password"])
    try:
        with mo.status.spinner(title="Checking your credentials with BRAIN ..."):
            _res = connect.begin_login(login_form.value["email"], login_form.value["password"],
                                       save=bool(login_form.value["save"]))
    except (AuthError, Exception) as _e:  # noqa: BLE001
        _res = {"status": "error", "detail": str(_e)}
    set_login(_res)
    if _res["status"] == "ok":
        set_conn(get_conn() + 1)
    return


@app.cell(hide_code=True)
def _(connect, get_conn, mo, scan_done_btn, set_conn, set_login):
    mo.stop(not scan_done_btn.value)
    try:
        _res = connect.finish_login()
    except Exception as _e:  # noqa: BLE001
        _res = {"status": "error", "detail": str(_e)}
    set_login(_res)
    if _res["status"] == "ok":
        set_conn(get_conn() + 1)
    return


@app.cell(hide_code=True)
def _(connect, get_conn, logout_btn, mo, set_conn, set_login):
    mo.stop(not logout_btn.value)
    connect.logout()
    set_login({"status": "logged_out"})
    set_conn(get_conn() + 1)
    return


@app.cell(hide_code=True)
def _(BrainClient, GOLD, R, SANDBOX, config, connect, get_conn, get_login, hypolab, login_form, logout_btn, mo,
      mode_form, pd, scan_done_btn):
    get_conn()
    import sys as _sys
    _left = BrainClient(verbose=False).seconds_left()
    if R is not None and not SANDBOX:
        _left = max(_left, R.brain.seconds_left())
    _status = pd.DataFrame([
        {"item": "mode", "value": "sandbox (practice)" if SANDBOX else "live"},
        {"item": "live region", "value": config.live_region()},
        {"item": "credentials", "value": connect._creds_source()},
        {"item": "BRAIN session", "value": f"about {_left / 3600:.1f} h left" if _left > 0 else "none or expired"},
        {"item": "data folder", "value": str(config.HOME)},
        {"item": "versions", "value": f"hypolab {hypolab.__version__}, marimo {mo.__version__}, "
                                      f"python {_sys.version.split()[0]}"},
    ])
    _l = get_login() or connect.pending() or {}
    _msg = mo.md("")
    if _l.get("status") == "biometric" or _l.get("status") == "waiting":
        _msg = mo.callout(mo.vstack([
            mo.md(("**BRAIN has not registered the scan yet.** Wait until the page says it is done. "
                   if _l["status"] == "waiting" else "**Face scan required.** ")
                  + f"Open [this link]({_l['url']}) in your browser, complete the scan, then press the button."),
            scan_done_btn]), kind="warn")
    elif _l.get("status") == "ok":
        _msg = mo.callout(mo.md(f"**Logged in.** Session valid for about {_l.get('hours_left', '?')} h"
                                + ("; credentials saved." if _l.get("saved") else "; credentials not saved.")
                                + (" Switch to **Live** above to use your account." if SANDBOX else "")),
                          kind="success")
    elif _l.get("status") == "error":
        _msg = mo.callout(mo.md(f"**Login failed:** {_l['detail']}\n\nNothing was saved."), kind="danger")
    elif _l.get("status") == "logged_out":
        _msg = mo.callout(mo.md("Logged out; saved credentials and session deleted."), kind="neutral")
    setup_view = mo.vstack([
        mo.md("## Where you stand"),
        mo.ui.table(_status, selection=None, show_column_summaries=False, show_download=False),
        mo.md("## Sandbox or live\nEvery tab, the scan app and the learning app follow this switch."),
        mode_form,
        mo.md("## Log in to BRAIN\nYour password goes only to BRAIN and, if you tick the box, to a file only you "
              "can read. If BRAIN asks for a face scan, a link appears here; nothing waits on a terminal."),
        login_form, _msg,
        mo.accordion({
            "Log out": logout_btn,
            "Operators you may use (Gold list)": mo.ui.table(GOLD.table(), selection=None, page_size=15),
            "A sensible daily routine (about 2 hours)": mo.md(
                "1. **20 min - read.** One paper abstract from a card's references, or one BRAIN Learn page.\n"
                "2. **10 min - plan.** Week and Pyramids tabs: which cells this week, how many alphas today.\n"
                "3. **60 min - research.** Cards -> pick 2-3 for this week's cells -> Lab: rung 1, read the "
                "diagnosis, climb at most a few rungs. Respect the stop signs.\n"
                "4. **20 min - validate.** Lab: robustness and gate on anything that passed. Submit only what "
                "clears the gate (at most 4 a day).\n"
                "5. **10 min - write.** One lesson per idea in the Journal tab."),
        }),
    ])
    return (setup_view,)


# =================================================================================================== DATA
@app.cell(hide_code=True)
def _(catalog, get_version, mo):
    get_version()
    _ctx = catalog.contexts()
    _opts = {f"{r.region} {r.universe} D{r.delay} ({r.fields} fields)": (r.region, r.universe, int(r.delay))
             for r in _ctx.itertuples(index=False)}
    data_ctx = mo.ui.dropdown(options=_opts, value=next(iter(_opts), None), label="Region in your catalog")
    return (data_ctx,)


@app.cell(hide_code=True)
def _(config, mo):
    _st = config.settings()
    _regions = config.account_regions()
    sync_region = mo.ui.dropdown(options=_regions, value=config.live_region() if config.live_region() in _regions
                                 else _regions[0], label="Region to download")
    sync_region_btn = mo.ui.run_button(label="Download its field list (metadata only; a few minutes)")
    return sync_region, sync_region_btn


@app.cell(hide_code=True)
def _(R, SANDBOX, catalog, config, get_version, mo, set_version, sync_region, sync_region_btn):
    mo.stop(not sync_region_btn.value or R is None or SANDBOX)
    _u = config.universe_for(sync_region.value)
    mo.stop(_u is None, mo.callout(mo.md(f"HYPOLAB doesn't know {sync_region.value}'s universes yet: press "
                                         "**Download operators + simulation options** on the Account tab first."),
                                   kind="warn"))
    with mo.status.spinner(title=f"Downloading {sync_region.value} {_u} ..."):
        catalog.sync_from_brain(R.brain, sync_region.value, _u, 1, progress=None,
                                categories=["analyst", "fundamental", "model", "pv", "risk", "earnings", "other",
                                            "macro", "imbalance", "option", "news", "sentiment"])
    set_version(get_version() + 1)
    return


@app.cell(hide_code=True)
def _(catalog, data_ctx, mo):
    data_summary = None
    if data_ctx.value:
        _r, _u, _d = data_ctx.value
        data_summary = catalog.dataset_summary(_r, _u, _d).round(3).reset_index(drop=True)
    _cols = ["category_name", "dataset", "name", "fields", "usable", "matrix", "vector", "median_coverage",
             "median_alpha_count", "value_score"]
    ds_table = mo.ui.table(data_summary[[c for c in _cols if c in data_summary.columns]]
                           if data_summary is not None and not data_summary.empty else [],
                           selection="single", page_size=10, label="Tick a dataset to see what each field measures")
    return data_summary, ds_table


@app.cell(hide_code=True)
def _(CONCEPTS, CATEGORY_NAMES, mo):
    concept_dd = mo.ui.dropdown(options=sorted(CONCEPTS), value="cfo", searchable=True, label="Economic concept")
    concept_cats = mo.ui.multiselect(options={CATEGORY_NAMES.get(c, c): c for c in CATEGORY_NAMES},
                                     label="Only these categories")
    search_box = mo.ui.text(placeholder="e.g. short interest", label="Free-text search", debounce=True)
    return concept_cats, concept_dd, search_box


@app.cell(hide_code=True)
def _(GUIDE_DATASETS, R, SANDBOX, catalog, concept_cats, concept_dd, data_ctx, data_summary, ds_table, mo, pd,
      search_box, sync_region, sync_region_btn):
    _parts = [mo.md("Every field is classified by **nature** (balance-sheet stock, income flow, estimate, count, "
                    "vendor score, date, code ...) and matched to **economic concepts**, with **coverage** and "
                    "**crowding** (how many alphas already use it). High coverage and moderate crowding is the "
                    "sweet spot; thousands of alphas on a dataset means yours will correlate with the pool.")]
    if not SANDBOX:
        _parts.append(mo.accordion({"Download another region from BRAIN": mo.vstack(
            [sync_region, sync_region_btn] if R is not None else [mo.md("_Log in first (Setup tab)._")])}))
    if not data_ctx.value:
        _parts.append(mo.callout(mo.md("No catalog yet. Download a region above."), kind="warn"))
        data_view = mo.vstack(_parts)
    else:
        _r, _u, _d = data_ctx.value
        _have = set(data_summary["dataset"]) if data_summary is not None and not data_summary.empty else set()
        _guide = pd.DataFrame([{"category": c, "guide dataset": d, "available here": d.split(" ")[0] in _have}
                               for c, lst in GUIDE_DATASETS.items() for d in lst])
        _detail = mo.md("")
        _sel = ds_table.value
        if _sel is not None and len(_sel):
            _ds = _sel.iloc[0]["dataset"]
            _cm = catalog.concept_map(_ds, _r, _u, _d).sort_values("coverage", ascending=False) \
                .reset_index(drop=True).round(3)
            _detail = mo.vstack([mo.md(f"### What each field of `{_ds}` measures"),
                                 mo.ui.table(_cm, selection=None, page_size=10)])
        _found = catalog.find_concept(concept_dd.value, _r, _u, _d, categories=list(concept_cats.value) or None)
        _search = catalog.search(search_box.value, _r, _u, _d) if search_box.value.strip() else None
        _parts += [data_ctx, mo.md("### Datasets in this region"), ds_table, _detail,
                   mo.md("### Find fields by economic concept"), mo.hstack([concept_dd, concept_cats], justify="start"),
                   mo.ui.table(_found, selection=None, page_size=8),
                   search_box]
        if _search is not None:
            _parts.append(mo.ui.table(_search, selection=None, page_size=8))
        _parts.append(mo.accordion({"Datasets your Pyramids guide recommends - are they here?":
                                    mo.ui.table(_guide, selection=None, page_size=15)}))
        data_view = mo.vstack(_parts)
    return (data_view,)


# ================================================================================================ ACCOUNT
@app.cell(hide_code=True)
def _(mo):
    acct_btn = mo.ui.run_button(label="Download my submitted alphas, operators + simulation options from BRAIN",
                                kind="success")
    get_acct_msg, set_acct_msg = mo.state(None)
    return acct_btn, get_acct_msg, set_acct_msg


@app.cell(hide_code=True)
def _(J, R, SANDBOX, acct, acct_btn, get_version, mo, set_acct_msg, set_version, store):
    mo.stop(not acct_btn.value or R is None or SANDBOX)
    try:
        with mo.status.spinner(title="Downloading your submitted alphas (a few pages of 100) ..."):
            _res = acct.sync_account(R.brain, J)
        _c = acct.counts(J)
        # BRAIN's own count replaces the number typed by hand; HYPOLAB adds its own submissions from here on
        store.set_goal("lifetime_alphas", _c["lifetime_regular"], store.lifetime()["unlock"])
        _opt = (f" Simulation options for {_res['regions_synced']} regions saved (universes, delays, risk "
                f"neutralizations)." if _res.get("regions_synced") else
                f" Simulation options not saved: {_res['regions_error']}" if _res.get("regions_error") else "")
        set_acct_msg(("ok", f"Downloaded {_res['alphas']} submitted alphas and {_res.get('regular', 0)} REGULAR "
                               f"operators ({len(_res.get('added_to_linter', []))} new to the linter). The SuperAlpha countdown now "
                                f"uses BRAIN's count.{_opt}"))
    except Exception as _e:  # noqa: BLE001
        set_acct_msg(("error", f"Download failed: {_e}"))
    set_version(get_version() + 1)
    return


@app.cell(hide_code=True)
def _(J, R, SANDBOX, acct, get_version, mo, pd):
    # Re-run a submitted alpha with BRAIN's risk-neutralization sets or at delay 0 (BRAIN_RULES N5, S-8).
    get_version()
    _df = acct.account_alphas(J)
    _reg = _df[_df["type"] == "REGULAR"] if not _df.empty else _df
    _cols = ["alpha_id", "date_submitted", "region", "delay", "neutralization", "sharpe", "fitness", "turnover",
             "code"]
    rerun_table = mo.ui.table(_reg[[c for c in _cols if c in _reg.columns]].reset_index(drop=True)
                              if len(_reg) else pd.DataFrame(columns=_cols),
                              selection="single", page_size=8, label="Pick ONE submitted alpha")
    return (rerun_table,)


@app.cell(hide_code=True)
def _(R, mo, rerun_table):
    _sel = rerun_table.value
    _row = _sel.iloc[0].to_dict() if _sel is not None and len(_sel) else None
    _vars = R.rerun_variants(_row) if (R is not None and _row) else []
    rerun_choices = mo.ui.multiselect(options={v["label"]: i for i, v in enumerate(_vars)},
                                      label="Variants to simulate (each costs one simulation and one try)")
    rerun_btn = mo.ui.run_button(label="Simulate the chosen variants", kind="success")
    rerun_row, rerun_vars = _row, _vars
    return rerun_btn, rerun_choices, rerun_row, rerun_vars


@app.cell(hide_code=True)
def _(J, R, SANDBOX, acct, get_results, mo, rerun_btn, rerun_choices, rerun_row, rerun_vars, set_results, theme):
    mo.stop(not rerun_btn.value or R is None or rerun_row is None or not rerun_choices.value)
    _full = acct.account_alphas(J)
    _full = _full[_full["alpha_id"] == rerun_row["alpha_id"]]
    _alpha = _full.iloc[0].to_dict() if len(_full) else rerun_row
    with mo.status.spinner(title=theme.loading_line(f"{len(rerun_choices.value)} variant(s)")):
        _res = R.rerun(_alpha, [rerun_vars[i] for i in rerun_choices.value])
    set_results(get_results() + _res)
    return


@app.cell(hide_code=True)
def _(J, acct, get_version, mo):
    get_version()
    _df = acct.account_alphas(J)
    _y, _q = acct.current_quarter()
    _qs = {f"{_y} Q{_q}": (_y, _q)}
    if not _df.empty:
        for _t in _df["submitted"].dropna():
            _qs.setdefault(f"{_t.year} Q{(_t.month - 1) // 3 + 1}", (_t.year, (_t.month - 1) // 3 + 1))
    acct_quarter = mo.ui.dropdown(options=dict(sorted(_qs.items(), reverse=True)), value=f"{_y} Q{_q}",
                                  label="Quarter (BRAIN's calendar, New York time)")
    return (acct_quarter,)


@app.cell(hide_code=True)
def _(J, SANDBOX, acct, acct_btn, acct_quarter, config, get_acct_msg, get_version, mo, pd, rerun_btn,
      rerun_choices, rerun_table, rules):
    get_version()
    _y, _q = acct_quarter.value
    _last = acct.last_sync(J)
    _parts = [mo.md("Your **submitted** alphas as BRAIN records them: the real lifetime count (it feeds the SuperAlpha "
                    "countdown), operators used and unused per quarter by BRAIN's categories, and the fields you "
                    "lean on most. Download again whenever you have submitted on the BRAIN website.")]
    if SANDBOX:
        _parts.append(mo.callout(mo.md("Your account data comes from BRAIN: switch to **Live** on the Setup tab."),
                                 kind="neutral"))
    else:
        _parts.append(mo.hstack([acct_btn, mo.md(
            f"_Last download: {pd.Timestamp(_last, unit='s').strftime('%Y-%m-%d %H:%M')} UTC_" if _last
            else "_Not downloaded yet._")], justify="start", gap=1.5))
    _m = get_acct_msg()
    if _m:
        _parts.append(mo.callout(mo.md(_m[1]), kind="success" if _m[0] == "ok" else "danger"))
    _c = acct.counts(J, _y, _q)
    _summary, _bycat, _used, _unused = acct.operator_audit(J, _y, _q)
    _cat_views = {}
    for _row in _bycat.itertuples(index=False):
        _u = _used[_used["category"] == _row.category][["operator", "submissions"]]
        _n = _unused[_unused["category"] == _row.category]["operator"].tolist()
        _cat_views[f"{_row.category}: {_row.used}/{_row.available} used"] = mo.vstack([
            mo.ui.table(_u, selection=None, show_download=False) if len(_u) else mo.md("_None used this quarter._"),
            mo.md("**Not used yet:** " + (", ".join(f"`{x}`" for x in _n) if _n else "all used"))])
    _subs = acct.account_alphas(J)
    _cols = ["date_submitted", "type", "region", "delay", "sharpe", "fitness", "turnover", "status", "code"]
    _tb = acct.tiebreakers(J, _y, _q)
    _osm, _osm_notes = acct.osmosis_check(J, config.account_regions())
    _qs, _qe = rules.quarter_bounds()
    _lock = rules.osmosis_lock_deadline(_qe)
    _parts += [
        mo.md(f"### Genius tie-breakers, {_y} Q{_q} (from your submissions)\n"
              f"Per alpha: **{_tb['operators per alpha']}** operators, **{_tb['fields per alpha']}** fields (lower is "
              f"better). Distinct this quarter: **{_tb['distinct operators']}** operators, **{_tb['distinct fields']}** "
              f"fields (higher is better). Simple alphas built from many different fields win both. The simulation "
              f"streak counts too: simulate something every day (one free missed day per quarter)."),
        mo.md(f"### Osmosis check\nA valid allocation needs at least 3 region x delay scopes, each with exactly "
              f"100,000 points over at least 10 alphas. Combined Osmosis Performance needs 6 valid weeks in the "
              f"quarter: the last Sunday to lock one is **{_lock:%a %d %b}** (earlier is safer - BRAIN refreshes the "
              f"number only every 4-6 weeks). Points lock Sunday 23:59 New York time = Monday 06:59/07:59 Nairobi."),
        mo.callout(mo.md("\n\n".join(_osm_notes)), kind="info") if _osm_notes else mo.md(""),
        mo.ui.table(_osm, selection=None, page_size=12, show_column_summaries=False) if len(_osm) else mo.md(""),
        mo.md("Prefer alphas with turnover below 20% for Osmosis, and drop ones whose Sharpe falls ~60% or more with "
              "MaxTrade ON unless they are unique (BRAIN's Osmosis tips)."),
        mo.md("### Re-run a submitted alpha with a risk set or at delay 0\nBRAIN suggests re-simulating good alphas "
              "with risk neutralization (SLOW for low turnover, FAST / SLOW_AND_FAST for high turnover, "
              "REVERSION_AND_MOMENTUM for ratios over price) and re-running D1 alphas at D0. Some come out better and "
              "less correlated - candidate new signals. Results appear on the **Lab** tab, where the gate checks "
              "self-correlation with the original before you can submit."),
        rerun_table, rerun_choices, rerun_btn,
    ]
    _parts += [
        mo.md(f"### Counts\nLifetime: **{_c['lifetime_regular']}** regular and **{_c['lifetime_super']}** super "
              f"alphas submitted. {_y} Q{_q}: **{_c['quarter_regular']}** regular, **{_c['quarter_super']}** super."),
        mo.md("### Operators by category"), acct_quarter,
        mo.ui.table(_bycat, selection=None, show_download=False),
        mo.accordion(_cat_views) if _cat_views else mo.md(""),
        mo.md("Use an unused operator only when it fits the idea's mechanism; operators added just to raise "
              "coverage make weaker alphas."),
        mo.md("### Fields your submitted alphas use most\nNew ideas built on these will correlate with your own alphas."),
        mo.ui.table(acct.field_usage(J), selection=None, page_size=10),
        mo.md("### Submitted alphas"),
        mo.ui.table(_subs[[c for c in _cols if c in _subs.columns]] if not _subs.empty else [], selection=None,
                    page_size=10),
        mo.accordion({"How operators are counted": mo.ui.table(
            pd.DataFrame([{"item": k, "value": str(v)} for k, v in _summary.items()]), selection=None,
            show_download=False)}),
    ]
    account_view = mo.vstack(_parts)
    return (account_view,)


# ==================================================================================================== PLAY
@app.cell(hide_code=True)
def _(R, SANDBOX, config, mo, play):
    # The playground: random alphas from random cards or random fields. Ignores the Pyramid plan on purpose.
    _regions = ["SBX"] if SANDBOX else config.account_regions()
    _default = "SBX" if SANDBOX else (R.region if R is not None and R.region in _regions else _regions[0])
    play_mode = mo.ui.radio(options={"Mix": "mix", "Random idea cards": "cards",
                                     "Wild: random field x random template": "wild"},
                            value="Mix", inline=True, label="Dice")
    play_n = mo.ui.slider(start=1, stop=10, step=1, value=4, label="How many", show_value=True)
    play_region = mo.ui.dropdown(options=_regions, value=_default, label="Region")
    play_shuffle = mo.ui.checkbox(value=True, label="Shuffle settings too (decay, neutralization, truncation)")
    play_seed = mo.ui.number(start=0, stop=999999, step=1, value=0, label="Seed (0 = surprise me)")
    roll_btn = mo.ui.run_button(label="Roll the dice (free)", kind="neutral")
    get_roll, set_roll = mo.state(play.load_roll(SANDBOX))      # the last roll survives a restart
    get_play, set_play = mo.state([])
    return (get_play, get_roll, play_mode, play_n, play_region, play_seed, play_shuffle, roll_btn, set_play,
            set_roll)


@app.cell(hide_code=True)
def _(R, SANDBOX, mo, play, play_mode, play_n, play_region, play_seed, play_shuffle, roll_btn, set_roll):
    mo.stop(not roll_btn.value or R is None)
    _seed = int(play_seed.value) or None
    _items = R.roll(n=int(play_n.value), mode=play_mode.value, region=play_region.value, seed=_seed,
                    shuffle_settings=bool(play_shuffle.value))
    play.save_roll(_items, SANDBOX)
    set_roll(_items)
    return


@app.cell(hide_code=True)
def _(get_roll, mo, play):
    _items = get_roll()
    _t = play.items_table(_items)
    _t.insert(0, "#", range(len(_t)))
    roll_table = mo.ui.table(_t, selection="multi", page_size=10,
                             label="Rolled alphas - tick some to simulate only those, or none to simulate them all")
    play_sim_btn = mo.ui.run_button(label="Simulate (all rolled, or only the ticked ones)", kind="success")
    return play_sim_btn, roll_table


@app.cell(hide_code=True)
def _(R, get_play, get_roll, mo, play_sim_btn, roll_table, set_play, theme):
    mo.stop(not play_sim_btn.value or R is None)
    _items = get_roll()
    _sel = roll_table.value
    _keep = {int(x) for x in _sel["#"]} if _sel is not None and len(_sel) else set(range(len(_items)))
    _chosen = [it for i, it in enumerate(_items) if i in _keep]
    mo.stop(not _chosen)
    with mo.status.spinner(title=theme.loading_line(f"{len(_chosen)} random alpha(s)")):
        _res = R.play(_chosen)
    set_play(get_play() + _res)
    return


@app.cell(hide_code=True)
def _(get_play, mo, pd, views):
    _res = get_play()
    play_results = mo.ui.table(pd.DataFrame([{"#": i, **views.result_row(t)} for i, t in enumerate(_res)]),
                               selection="single", initial_selection=[len(_res) - 1] if _res else None,
                               page_size=8, label="What the dice brought back (select one to read it)")
    play_to_lab = mo.ui.run_button(label="Send this one to the Lab (robustness, gate, submit)", kind="neutral")
    return play_results, play_to_lab


@app.cell(hide_code=True)
def _(get_play, get_results, mo, play_results, play_to_lab, set_results):
    mo.stop(not play_to_lab.value)
    _sel = play_results.value
    mo.stop(_sel is None or not len(_sel))
    _t = get_play()[int(_sel.iloc[0]["#"])]
    if not any(_x is _t for _x in get_results()):
        set_results(get_results() + [_t])
    return


@app.cell(hide_code=True)
def _(J, R, SANDBOX, get_play, get_roll, mo, play, play_mode, play_n, play_region, play_results, play_seed,
      play_shuffle, play_sim_btn, play_to_lab, roll_btn, roll_table):
    if R is None:
        play_view = mo.callout(mo.md("The playground needs a BRAIN session (or sandbox mode)."), kind="warn")
    else:
        _st = play.play_stats(R.journal)       # the sandbox keeps its own in-memory journal
        _best = f"{_st['best_sharpe']:.2f}" if _st["best_sharpe"] is not None else "-"
        _parts = [
            mo.md('<span class="hl-ticker">&gt; wake up, Zacc ... the market has patterns nobody has tried. '
                  'Roll some dice.</span>'),
            mo.md("No Pyramids, no plan, no ranking: **random idea cards** (built-in or yours, any family) and "
                  "**wild rolls** (a random field from a random dataset dropped into a random template - two "
                  "fields always come from the same dataset, so the alpha stays *single dataset*). Rolling is free; "
                  "only **Simulate** spends simulations" + ("." if SANDBOX else
                  " from your BRAIN quota.")),
            mo.md(f'<span class="hl-score">dice thrown <b>{_st["plays"]}</b></span>'
                  f'<span class="hl-score">today <b>{_st["today"]}</b></span>'
                  f'<span class="hl-score">PASS <b>{_st["pass"]}</b></span>'
                  f'<span class="hl-score">NEAR <b>{_st["near"]}</b></span>'
                  f'<span class="hl-score">best Sharpe <b>{_best}</b></span>'),
            mo.hstack([play_mode, play_region], justify="start", gap=2, wrap=True),
            mo.hstack([play_n, play_seed, play_shuffle], justify="start", gap=2, wrap=True),
            roll_btn,
        ]
        if get_roll():
            _parts += [roll_table, play_sim_btn]
        elif roll_btn.value:
            _parts.append(mo.callout(mo.md("Nothing rolled: this region has no field list yet - download it on "
                                           "the **Data** tab."), kind="warn"))
        if get_play():
            _parts += [mo.md("### Results"), play_results]
            _sel = play_results.value
            if _sel is not None and len(_sel):
                _t = get_play()[int(_sel.iloc[0]["#"])]
                _parts += [mo.md(_t.markdown()), play_to_lab]
        _parts.append(mo.accordion({"Why the dice still count": mo.md(
            "Random search finds luck as easily as signal: try 40 noise fields and one will look good. So every "
            "roll is journaled as a try for its idea (`play:<card>` or `play:wild:<dataset>`). If a roll goes to "
            "the Lab and the gate, the deflated Sharpe counts all the dice you threw on that idea. A good roll is a "
            "**lead**: before you submit, ask what the economic story is - then it can become a proper card.")}))
        play_view = mo.vstack(_parts)
    return (play_view,)


# =================================================================================================== TABS
@app.cell(hide_code=True)
def _(account_view, cards_view, data_view, drafts_view, header, journal_view, lab_view, mo, play_view,
      pyramids_view, setup_view, week_view):
    mo.vstack([header, mo.ui.tabs({"Week": week_view, "Pyramids": pyramids_view, "Cards": cards_view,
                                   "Drafts": drafts_view, "Lab": lab_view, "Play": play_view, "Journal": journal_view,
                                   "Account": account_view,
                                   "Data": data_view,
                                   "Setup": setup_view})])
    return


if __name__ == "__main__":
    app.run()
