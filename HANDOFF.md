# HYPOLAB handoff - read this first in a new chat

State on 2026-10-11 (evening): **HYPOLAB 1.5.0 = phase 3 done**: the card-writing form (cockpit tab **Drafts**),
drafts in `ideas.sqlite`, live checks with a dry-run binding, approve to `my_cards.yaml`, and the Claude Projects
hand-offs (import CARD, Copy for Critic, attach VERDICT, Friday DIGEST, paste PLAN, rebuild knowledge pack).
1.4.3 = bin noise cards, remove a card from the Lab, boosted alphas with their PnL, faster on a T470s; 1.4.2 = no
more "kernel not found"; 1.4.1 = Matrix theme + Play tab + resume after a shutdown. Everything runs in marimo (no
Jupyter). **157 tests pass** (1 skipped when marimo is missing). **Next: phase 4, the planner's Friday review.**

## How to resume in a new chat
1. Attach the latest `hypolab-1.5.0.zip` (or newer) and say: "Continue HYPOLAB with phase 4. Read HANDOFF.md first."
2. Claude should: unzip into a fresh folder, read this file, `docs/HOW_IT_WORKS.md` and `docs/BRAIN_RULES.md`, run
   `python -m unittest discover -s tests` (all must pass before changing anything), then build.
3. The design rationale is in the doc "HYPOLAB Idea Engine - Design v2":
   https://claude.ai/code/artifact/90188b46-0f1a-4089-9da6-fb8304b38595
   This handoff as a doc (1.4.3 edition; this file is the current one): https://claude.ai/code/artifact/e920f43f-1ff3-4209-8df6-c82222e353e6
   Cheat sheet (updated for 1.5.0): https://claude.ai/code/artifact/37656bd4-b770-4e7c-b83e-83c57ae4eb28

## Who and what for
- Zacc: WorldQuant BRAIN research consultant, **Gold** level, new to quant, struggles to find alpha ideas.
- Laptop: Lenovo T470s, Arch Linux, KDE, CPU only. Only computer. Everything must stay light.
- AI available: **Claude Pro** subscription. No paid API key. Plan: Claude Code non-interactive (`claude -p
  --output-format json --json-schema ...`), with `ANTHROPIC_API_KEY` unset so it uses the Pro plan.
- Goal: **Expert by end of 2026-Q4** (Dec 31). Genius page on Oct 10: signals 1/20, Pyramids 0/10,
  combined alpha performance -0.01/0.5 (Master: 120 / 30 / 1.0). All three are counted **per quarter**.
  Tie-breakers: 2 operators/alpha, 2 fields/alpha, streak 5, community 0.7; the quarter's Streak Freeze is already used.
- Regions on his account: USA, GLB, EUR, ASI, CHN, JPN, AMR, IND, DEU, GBR (D0 in USA, EUR, CHN, JPN, AMR, DEU, GBR).
- Osmosis on Oct 10: only IND/D1, 12 alphas but 1,200,000 points (must be exactly 100,000 per scope) - invalid; he
  needs 3 scopes with >= 10 alphas. Last Sunday to lock a valid allocation for 6 weeks in Q4: **15 Nov**.
- Submissions: BRAIN expects up to **4 alphas + 1 SuperAlpha a day**. SuperAlphas unlock at **100 lifetime
  alphas**; Zacc had **58** on Oct 9 (42 to go). The planner treats 4/day as a ceiling, default 10/week.
- Settled: a Pyramid needs **3** submitted alphas (BRAIN's Genius documentation); "10" is the number of Pyramids
  Expert needs. `alphas_per_pyramid` = 3 is right.

## The system in one paragraph
**HYPOLAB** (`hypolab/`) tests ideas: hypothesis card -> bind roles to real fields -> lint (Gold operators) ->
simulate (BRAIN or offline sandbox) -> diagnose (PASS/NEAR/WEAK/NOISE/INVERTED + one next action) -> robustness ->
gate (platform checks, self/prod correlation, deflated Sharpe) -> typed-confirmation submit. Everything is
journaled. **Idea Engine** (`ideaengine/`) decides what is worth testing: goals, weekly plan, submission cap; in
later phases it drafts new cards from papers/news/journal. **marimo apps** (`apps/`) are the only screens.

## File map
| Path | What it is |
|---|---|
| `hypolab/` | The testing engine (v1.0 by an earlier session; small changes since, listed below) |
| `hypolab/library/hypotheses.yaml` | 47 built-in idea cards (story, why_persists, roles = concepts, ladder) |
| `hypolab/concepts.py` | ~75 economic concepts; field nature classifier; direction hints |
| `hypolab/ideas.py` | Binding cards to fields, ranking, data-first "lenses" |
| `hypolab/research.py` | `Researcher`: ideas, card(id), test, follow, boost, scan, robustness, gate, submit |
| `hypolab/journal.py` | `journal.sqlite`: ideas, experiments, submissions, lessons. WAL; `open_readonly()` |
| `hypolab/connect.py` | Mode switch, CLI login, **web login** `begin_login` / `finish_login` |
| `hypolab/brain.py` | BRAIN API client; login split into `begin_login` / `finish_biometric` |
| `hypolab/rules.py` | BRAIN's numeric rules (single dataset, sub-universe, Fitness labels, BRAIN's day, Osmosis) |
| `docs/BRAIN_RULES.md` | Every rule read from BRAIN's pages, with source and HYPOLAB status |
| `ideaengine/store.py` | `ideas.sqlite`: goals (quarter bars + lifetime alphas), weekly plans (+ `extra`: the Reviewer's retry / dead ends / lessons) |
| `ideaengine/drafts.py` | Phase 3: drafts table, form <-> card, `check_card` (dry-run binding), approve to `my_cards.yaml`, VERDICT / DIGEST / PLAN hand-offs |
| `ideaengine/planner.py` | ISO weeks, starting plan W42-W46, goal pace, `submission_status` (cap + SuperAlpha unlock) |
| `ideaengine/views.py` | Tables/heatmap for the apps (unit-tested) |
| `apps/hypolab.css`, `apps/head.html`, `hypolab/theme.py` | The Matrix theme + digital rain (1.4.0) |
| `hypolab/play.py` | The playground: random cards / wild rolls, play stats (1.4.0) |
| `ideaengine/connection.py` | `open_researcher()`: opens HYPOLAB for an app, never prompts |
| `apps/cockpit.py` | Tabs: Week, Pyramids, Cards, Drafts, Lab, Play, Journal, Account, Data, Setup |
| `apps/dataset_scan.py` | Explore + scan a dataset (separate so long scans never block the cockpit) |
| `apps/quant_basics.py` | The learning course on the practice market |
| `claude_projects/` | Instructions for the 4 Claude Projects + generated knowledge pack |
| `ideaengine/knowledge_pack.py` | Builds the knowledge files from the code and live data |
| `tests/` | 157 tests: core, pipeline, connect (fake BRAIN server), links, ideaengine, account, BRAIN rules, play, resume, bin/boost/speed, drafts, apps smoke test |

Run everything: `python -m hypolab cockpit` (= `marimo run apps/`, a gallery of the three apps).

## Files in `~/.hypolab/` (one writer each)
| File | Writer | Notes |
|---|---|---|
| `settings.json` | both | mode, live_region, budgets, `alphas_per_pyramid`, `account_regions`, `max_submissions_per_day` (4), `superalpha_unlock_after` (100) |
| `quota.json` | HYPOLAB | BRAIN's last X-Ratelimit headers (limit, remaining, reset) |
| `sim_options.json` | HYPOLAB | BRAIN's universes / delays / neutralizations per region (Account tab download) |
| `credentials.json`, `session.json` | HYPOLAB | mode 600; cookies only, never pickles |
| `catalog.sqlite` | HYPOLAB | field metadata per region; bundled GLB snapshot loaded on first live use |
| `journal.sqlite` | HYPOLAB | the memory; Idea Engine only reads it |
| `ideas.sqlite` | Idea Engine | goals, plans, drafts (1.5.0) |
| `library/*.yaml` | Idea Engine (on approval) | Zacc's own cards, loaded by HYPOLAB, `source = "mine"`; Approve appends to `my_cards.yaml` (atomic, previous kept as `my_cards.yaml.bak`) |

## Decisions already made (do not reopen without a reason)
1. **Ideas before expressions.** The AI may draft card text (story, mechanism, roles as concepts); it never
   chooses field ids (the binder does), never sends anything to BRAIN, never approves a card.
2. **No second card format and no second simulation log.** Drafts are HYPOLAB cards; the journal is the catalog.
3. **Trial budget is HYPOLAB's** `max_sims_per_idea` (10). The gate's deflated Sharpe counts every try.
4. Engine card ids start with `IE_`; a user card whose id clashes with a built-in one is skipped (built-in wins).
5. **All screens in marimo.** Every simulation sits behind a `run_button`; changing a control never simulates.
   Submit needs a READY gate, the typed `SUBMIT <alpha_id>`, and fewer than 4 submissions today.
6. Apps never block on `input()`: the Setup tab shows the face-scan link plus a button.
7. Sandbox uses an in-memory journal and an in-memory catalog (never touches the real files).
8. Starting plan from zero Pyramids: W42 USA Analyst+Fundamental, W43 USA PV+Model+Risk, W44 GLB
   Analyst+Fundamental, W45 GLB PV+Model+Risk (= 10 tier-1 cells), W46 EUR transfer.
9. Combined alpha performance is a Genius bar, so the system discourages filler submissions everywhere.

## What changed in HYPOLAB since v1.0 (all tested)
- `load_library()` also loads `~/.hypolab/library/*.yaml`; `LOAD_WARNINGS` lists skipped files/ids.
- `Researcher.card(id, region)`; `Researcher.submit` refuses the 5th submission of the day.
- Journal: WAL, `open_readonly()`, `idea()`, `submissions_today()`, `sims_today()` from local midnight.
- Bugs fixed: submit after a kernel restart recorded family "manual"; stray keys in `REGION_DEFAULTS`;
  **sandbox wrote practice fields into the real catalog, so live mode never loaded the bundled GLB catalog**.
- Login split in two steps for web pages; `python -m hypolab cockpit` command.
- Jupyter notebooks, `scripts/build_notebooks.py` and the Jupyter dependencies removed.

## The idea team on Claude Projects (added 2026-10-10)
No API key, so AI runs as four Claude Projects that Zacc sets up from `claude_projects/` (instructions + a
knowledge pack generated by `python -m ideaengine.knowledge_pack`): **BRAIN Library** (briefs from BRAIN
material), **Scout & Writer** (cards in HYPOLAB YAML, ids `IE_`), **Critic** (VERDICT YAML: keep/rewrite/bin),
**Weekly Reviewer** (DIGEST in, PLAN YAML out). Zacc carries messages between them; formats are in
`claude_projects/README.md`. This replaces phase 6's Claude Code automation for now (it can still come later).

## First live run (Oct 10) - fixed in 1.2.1
- Pyramids tab crashed: BRAIN's `/activities/diversity` returned rows with no `delay`. `PyramidTracker` now cleans
  counts (missing delay -> 1, missing count -> 0, no region -> dropped) and lists what it cleaned; the Pyramids
  tab shows BRAIN's raw rows (first 20) so the real format can be checked. If the raw rows show a different
  shape (e.g. delay nested elsewhere), fix `BrainClient.diversity()`.
- Every app page started its own face-scan request when the saved session had expired (links printed in the
  terminal, none usable). Now `connect.resume_saved_login()` starts at most one request, `connect.pending()`
  exposes it, and the Setup tab shows its link and the "I finished the face scan" button.

## Account tab and live operator list (1.3.0, Oct 10)
- `hypolab/account.py`: `BrainClient.submitted_alphas()` pages `/users/self/alphas` filtered on `dateSubmitted`;
  rows go to `journal.sqlite` table `account_alphas` with parsed operators and fields. `operator_audit(journal, y, q)`
  gives used/unused operators per quarter by BRAIN category (rules from Zacc's "ALPHA_ITERATOR (Unused Ops)"
  notebook: REGULAR only, symbols -> operator names, ts_backfill/group_backfill not counted, `=` in named args is
  not an operator). `field_usage()` lists the fields his submissions lean on.
- `operators.sync_operators(brain)` caches GET /operators in `~/.hypolab/operators.json` and merges it into
  `GOLD` at import, so the linter accepts every operator his account has (the PDF list had 82; BRAIN shows 131
  REGULAR operators in 8 categories). API-only operators get light checks.
- Cockpit **Account** tab: one button downloads both; lifetime count replaces the hand-typed 58 in the SuperAlpha
  countdown. Knowledge pack file `08_my_operator_usage.md` feeds the Writer and Reviewer.
- Claude in this cloud workspace cannot reach BRAIN (no credentials, network allowlist); everything account-related
  runs on Zacc's laptop through HYPOLAB.

## Pyramid counts: BRAIN's real format (1.3.1, Oct 10)
Zacc sent the raw rows of `GET /users/{id}/activities/diversity?grouping=region,delay,dataCategory`. Each item is
`{region, delay, alphaCount, dataCategory: {id, name}, dataDiversity: {check, limit}}`. BRAIN also sends subtotals:
`dataCategory.id = null` with a delay = all categories of that region+delay; `delay = null` too = the whole region.
Until 1.3.1 those subtotals were counted as the "Other" category (and the delay-null one as delay 1), which inflated
Other (IND Other would have shown 40). Now `diversity()` tags rows `kind` = cell / region_delay_total /
region_total, `PyramidTracker.totals` keeps the subtotals and the Pyramids tab shows them in their own table.
His rows: GLB D1 = 2 alphas touching fundamental, model, other and pv (one alpha counts in every category it uses);
IND D1 = 20 alphas, all Model. Open question: his Genius page showed Pyramids 0/10 while IND/D1/Model has 20, so
either these counts are not limited to the current quarter or a Pyramid needs more than an alpha count (e.g. the
dataDiversity check). Ask Zacc what BRAIN's Pyramids page shows for IND Model before trusting "filled".

## Theme datasets (Zacc's uploads, Oct 10)
BRAIN's Data > Datasets pages show per dataset: fields, Pyramid theme multiplier (1.1 on most theme sets), coverage,
value score (1-5), alpha count, last field added. Zacc uploads these per region to the BRAIN Library project, which
returns a SHORTLIST (high value, few alphas, coverage >= 30%). First read (USA page 1 of 3, ASI, EUR): top targets
include EUR Europe Relation Dataset (value 5, 25 alphas, 100% coverage), USA ESG (4, 79), ASI Earnings Tax Data
(4, 134), USA Deep Learning Chart Return Prediction (4, 205), Management and Executive Data (USA/EUR, 4, ~300).
HYPOLAB already syncs `value_score`, `pyramid_multiplier` and `alpha_count` per dataset from the API
(`catalog.sqlite`), but the card ranking (`ideas._score`) ignores value score and multiplier: phase 5 should add
them, and the Data tab should sort by them. Concept gaps found: management/executive changes, tax (book-tax), ESG
score, bond/credit spread - add concepts in phase 3 or 7 so cards on these datasets can bind.

## BRAIN's rules and 1.3.2 (Oct 10)
Zacc sent 24 BRAIN documentation/tips pages and his Genius status page. Every rule is in **`docs/BRAIN_RULES.md`**
(project doc `hypolab/BRAIN_RULES.md`) with its source, conflicts between pages, and HYPOLAB's status; it is also
`09_brain_rules.md` in the knowledge pack. **Read it before changing anything rule-related.** BRAIN's docs pages lag
his account (regions, D0 scopes): his account wins.

What 1.3.2 changed (all tested in `tests/test_brain_rules.py`):
- `hypolab/rules.py` (new): single-dataset detection and cutoffs (2.38 D1 / 3.96 D0), sub-universe formula, Fitness
  labels, BRAIN's day (New York midnight), quarter bounds, Osmosis lock deadline.
- Every ladder rung has `profile` / `is_test`; every result's diagnosis says which IS test applies; the sandbox
  applies the 2.38 cutoff to single-dataset alphas and BRAIN's sub-universe formula (was a flat 0.35).
- Journal counts simulations and submissions from New York midnight (was local midnight).
- `brain.record_quota()` / `quota()`: X-Ratelimit headers -> `~/.hypolab/quota.json`; Lab shows it; test() stops at 0.
- `config.account_regions()` (new setting `account_regions`; old `pyramid_regions`/`single_country_region` unused),
  DEU/GBR/JPN/AMR with D0; `BrainClient.sync_simulation_options()` -> `~/.hypolab/sim_options.json` ->
  `config.apply_sim_options()` fills universes/neutralizations per region. DEU/GBR universes are unknown until that
  sync: `make_payload` refuses them with a clear message.
- Lab: neutralization list = the region's real options (risk sets included) and a delay picker.
- Diagnose: Fitness label; correlation advice in BRAIN's order (equivalent field -> similar operator -> meaningful
  grouping) plus a risk set (SLOW if turnover < 20%, else SLOW_AND_FAST) when offered; split-decay fix for the
  sub-universe test; single-dataset note on LOW_2Y_SHARPE.
- Pyramids: counted for the **current quarter** from `account_alphas` (field categories via the catalog, or BRAIN's
  own Pyramid tags if an alpha carries them); diversity API (all time) is only a fallback. `TIERS` now has all 17
  categories. Multipliers: live parse of `/activities/pyramid-multipliers`, else `data/pyramid_multipliers_2026Q4.json`
  (transcribed from his Genius page); `plan(by="guide"|"multiplier")`, per delay, skips cells BRAIN doesn't offer.
- Account tab: one download now also saves simulation options; new sections **Genius tie-breakers**, **Osmosis check**
  (`account.osmosis_check`), **Re-run a submitted alpha** (`Researcher.rerun_variants` / `rerun`, idea id
  `rerun:<alpha_id>`, results go to the Lab). `account_alphas.extra` keeps BRAIN's pyramid/osmosis keys (migrated).
- Knowledge pack: `09_brain_rules.md`; project instructions list it.

Unknowns to check on the first live run of 1.3.2:
- The shape of `/activities/pyramid-multipliers` (if not parsed, the snapshot is used - the Pyramids tab says which).
- Whether BRAIN's alpha JSON carries Pyramid tags / Osmosis points (if yes, `extra` holds them and they are used).
- DEU/GBR universe names (filled by the Account tab download).
- Whether the < 30% turnover factor 0.85 also lowers the single-dataset cutoff (BRAIN_RULES T2).
- Which risk sets JPN/AMR/IND/DEU/GBR offer (the sync answers it).

Still open from BRAIN_RULES (good phase 3-5 material): planner should front-load quality submissions before 1 Dec
(December may not count toward Q4 performance, G8); USA D0 should default to TOP1000 (S-8); show the risk-handled /
investability stats BRAIN returns (S-5); PnL realization horizon check (H1-H2); value score + multiplier in card
ranking (D4); Osmosis correlation pruning (O6).

Decision pending with Zacc: the starting plan (W42-W46) puts USA/GLB first - the lowest multipliers (mostly 1.0-1.4)
but the easiest to pass; DEU/GBR/JPN/AMR/CHN and all D0 cells pay 1.6-1.9. The Pyramids tab can sort either way.

## UI theme "Matrix" (1.4.0, Oct 10; replaced 1.3.3's "Phosphor")
Zacc asked for greener, "another world", not boring during simulations. All three apps share:
- `apps/hypolab.css` (`marimo.App(css_file="hypolab.css", html_head_file="head.html")`): near-black green background,
  code green #00ff9c (primary), mint body text #d2f5e1 (readability), cyan #5ef2ff (links/info), lime #c4ff3d
  (PASS/LIVE; 1.4.1: solid green instead), violet warnings (1.4.1, was amber), coral. Monospace glowing headings (JetBrains Mono; h1 uppercase with "> " and a blinking cursor),
  uppercase tabs, faint CRT scanlines, a dark glass panel behind the content. Verdicts and the gate status render as
  badges: `<span class="hl-verdict hl-v-<verdict>">` from `Diagnosis.markdown()` / `GateReport.markdown()`.
- `apps/head.html`: fonts + a **digital-rain canvas** (katakana + quant glyphs, ~18 fps, paused when hidden, static
  under prefers-reduced-motion, z-index -1). It speeds up while marimo shows a spinner (`.animate-spin`). The `html`
  element carries the background; `body` must stay transparent or the canvas is hidden.
- `hypolab/theme.py`: palette for charts (`apply_matplotlib()`), `PYRAMID_LEVELS`, and `loading_line()` - random
  spinner titles ("Following the white rabbit through the order book ...") used by Lab, re-run and Play spinners.
- Selector notes: marimo copies the custom CSS into shadow roots. Callouts `.admonition.<kind>`; tabs
  `[role=tab][data-state=active]`; form panels `div[class*="--amber-1"][class*="--amber-7"]`; buttons by class
  (`--grass-9` success, `bg-action` form submit, `--red-9` danger) - their children need the dark text colour too;
  checkboxes `[role=checkbox][data-state=checked]`. Never style bare `[data-kind]`.
- `mo.ui.table(initial_selection=...)` does not show ticks on screen; Play uses "tick none = all" instead.

## Play tab (1.4.0, Oct 10)
A playground outside the Pyramid plan: `hypolab/play.py` + cockpit tab **Play** (between Lab and Journal).
- `roll(catalog, region, n, mode, seed, shuffle_settings)` (also `Researcher.roll`): free, linted, reproducible by seed.
  mode "cards" = any card from the library (built-in + mine), random rung; "wild" = random field (or two fields of the
  SAME dataset, so still single-dataset) from a random dataset into a random template (`TEMPLATES_ONE/TWO`, windows
  5..252, groups industry/subindustry/sector, random sign); "mix" = either. Settings shuffle: decay {0,2,4,6,10},
  any non-NONE neutralization the region offers, truncation {0.05,0.08,0.1}.
- `Researcher.play(items)`: simulates via `test(purpose="play", idea_id="play:<card>@R" | "play:wild:<dataset>@R")`,
  logs an ideas row (family "play"). No per-idea cap (BRAIN's daily quota still applies). `journal.trials()` now counts
  purpose "play" too, so the gate's deflated Sharpe includes every die thrown on that idea.
- Tab: dice options, Roll (free), table (tick none = simulate all), Simulate, results with verdict badges, "Send this
  one to the Lab" (gate/submit there), score strip `play_stats()` (dice thrown, today, PASS, NEAR, best Sharpe) read
  from `R.journal` (the sandbox's journal is in memory).
- Tests: `tests/test_play.py`.

## Resume after a shutdown + no yellow (1.4.1, Oct 10)
Zacc asked: can he shut the laptop down mid-alpha and resume? And yellow did not sit with the green.
- **Interrupted simulations:** `BrainClient.simulate(..., on_submitted=cb)` calls `cb(payloads, location)` as soon as
  BRAIN accepts a simulation (it is counted from then). `Researcher.test` writes it to the journal table `pending`
  and clears it after reading the result. After a restart the Lab shows "N simulation(s) were still running" and
  **Fetch them from BRAIN** -> `Researcher.recover_pending()` uses `BrainClient.peek(loc)` (one GET: result if done,
  None if still running, GONE on 404) and `_finish()` (shared with `test`) to diagnose + journal - no new simulation.
- **Recent results:** `Researcher.recent_results(n)` rebuilds TestResults from the journal (diagnosis recomputed,
  card rebuilt from `HYP@REGION` ids via `_card_for`; play/rerun ids keep `idea_id`). Lab box "Pick up where you left
  off" -> **Restore results** when the results list is empty.
- **Last Lab card:** settings.json `last_lab_card`, saved when the Lab card changes, preselected on start.
- **Play:** the last roll is saved to `~/.hypolab/play_last_roll_{sandbox|live}.json` (`play.save_roll/load_roll`,
  card objects not stored; items still play without them).
- Sandbox has an in-memory journal, so resume is a live-mode feature (the sandbox only keeps the Play roll and card).
- Colours: warnings are soft violet `#c3a6ff`; PASS/READY/LIVE are solid code green `#00ff9c` with dark text;
  INVERTED magenta `#ff7ad9`; marimo's radix `--amber-*`, `--yellow-*`, `--orange-*` scales are remapped to a dark
  violet scale in `apps/hypolab.css`. `theme.PASS/WARN/MAGENTA` (old `LIME/AMBER` names alias them).
- Tests: `tests/test_resume.py` (incl. a real HTTP fake BRAIN for the hook and `peek`).

## "kernel not found" (1.4.2, Oct 10)
Zacc saw marimo's "kernel not found": the browser tab outlived its app session. marimo closes a session 120 s after
the websocket drops (laptop asleep, Wi-Fi blip) or when the server restarts. Fixes:
- `python -m hypolab cockpit` passes `--session-ttl` from settings `session_ttl_seconds` (default 3600; each kept
  session ~0.8 GB) unless the user gives one.
- `apps/head.html` self-heal script: if the page text shows "kernel not found" / "Failed to send function request",
  it overlays "session lost while you were away" and reloads into a fresh session (max one reload per 20 s; after 3
  tries in 3 min it stops and tells him to restart the cockpit). The Lab's resume box then restores the work.
- Verified with Playwright by restarting the server under an open page.

## Engine flaws fixed (1.4.3, Oct 11)
Zacc reported: can't discard noise cards, can't remove a card from the Lab, can't see the alpha a boost made or its
performance, and the system is slow.
- **Bin** (`journal.binned` table; `R.bin(id, reason)`, `R.restore(id)`, `R.binned()`): Cards tab "Bin this card"
  with a reason, and "The bin" accordion to restore. Binned cards leave the Cards ranking, the Lab dropdown,
  `R.ideas()` (so boosters), `R.roll()` (Play, `play.roll(exclude=)`), and "Restore results". Nothing is deleted.
  Sandbox bins live only for the session (in-memory journal). `research.card_of_idea()` maps idea ids to cards.
- **Lab**: "Remove card from the Lab" (dropdown shows "(no card: write your own expression)"; settings
  `last_lab_card` = "" remembers it) and "Bin card (noise)". With no card the Lab tests your own expression as
  `manual@<region>`. Results list: "Remove the selected result" / "Clear the list" (journal keeps them).
  `get_lab_card` now holds `(id, time)` so re-sending the same card always switches.
- **Boost visible**: `R.test(rung_name=)`; combinations are journaled as `<rung> + boost:<card>` under the base
  idea; `BoostReport.boosters` (each booster alone, rung "booster alone: ..."), `lab_results()` (boosters, combos,
  best LAST so it is selected), `alpha_ids()`, table columns `booster_alpha`/`combined_alpha`. The Lab keeps the
  boost report on screen while any of its alphas is shown, plus an "Open a boosted alpha" dropdown (`get_focus`).
  The list shows a ▶ on the row displayed below.
- **Performance**: `R.performance(result, compare={label: alpha_id})` -> cumulative PnL + yearly table (API reads,
  never a simulation); `views.pnl_figure`. The best boost is drawn automatically against its base and booster;
  any other result has a "Show its performance" button.
- **Speed** (profiled on the 27k-field GLB catalog): Cards ranking 9 s -> 3.6 s cold, 0.3 s after the first run
  (T470s roughly 2-3x slower). `Concept.match_text` with one combined regex per concept; `Catalog._rows` plain-Python
  rows; `Catalog.lookup_map` (rules.catalog_lookup was rebuilding a 27k dict per card); enriched fields and concept
  matches cached on disk in `~/.hypolab/cache/*.pkl`, keyed by field count + last sync + a hash of the concept
  rules (never for `:memory:`); `load_library()` cached until a card file changes. Results identical (checked
  all 82 concepts on GLB). Browser: no `backdrop-filter`, no `mix-blend-mode`, rain at 14 fps (calm 7) at 1x pixels,
  paused when the window loses focus; **[ FX ]** button bottom right cycles full / calm / off (localStorage
  `hypolab-fx`); the self-heal check uses `textContent` first (no forced layout every 2 s).
- Tests: `tests/test_bin_boost_speed.py` (9).

## Phase 3 - the card-writing form (1.5.0, done Oct 11)
Zacc writes his own cards in the cockpit, or imports the Writer's, without hand-editing YAML.
- **`ideaengine/drafts.py`** + table `drafts` in `ideas.sqlite` (id, yaml, state, source, reason, verdict, decision,
  title, family, created, updated). States: draft (a check fails) / checked (all pass) / approved / binned (reason
  kept; restore -> draft). An approved draft is read-only (copy it to a new id to change it).
- **Form <-> card**: `form_defaults` / `card_from_form`. Keys the form does not show (role categories / pair_with /
  type / min_coverage, rung `when`, beginner, settings like max_trade) are carried over from the loaded card. All 47
  built-in cards survive form + YAML unchanged (test). `card_yaml` writes the library's style (folded story, flow
  settings, short expressions quoted). Form: 4 role rows (concept dropdown, searchable), 3 rungs.
- **Checks** (`check_card`, every change, no simulation, ~0.05-0.4 s warm on the 27k-field GLB catalog): required
  fields/types, id format, **id clash with the library = error**, category/horizon/strength/family, concepts exist
  ("did you mean"), `validate_library` (syntax, placeholders, Gold-operator errors such as NAMED_PARAMETER), linter
  warnings (ARBITRARY_WINDOW ...), field ids written directly (warning), **dry-run binding** (`build_card` in the
  chosen region: field, dataset, coverage, alphas on it; each rung's IS test; or which role found no field), same
  family / same concept set in the library, journal record of the family (dead end = 5+ explore/boost tries, none
  WEAK or better -> warning; the decision stays Zacc's).
- **Approve** -> `append_to_my_cards`: atomic write, `.bak`, refuses duplicate ids and anything that would not load
  back; the card appears on Cards (source mine) and in the Lab list; "Send IE_... to the Lab" button.
- **Hand-offs**: Import box (fences, `# from:` lines, several cards; a VERDICT/PLAN pasted there is recognised);
  "Copy for the Critic" = card + checks + dry run as YAML comments (3_critic.md now explains those lines); paste a
  VERDICT -> stored on its draft and shown (advice only, never approves/bins); Week tab "Friday review": **DIGEST**
  of the selected week (plan, goals pace, submissions, simulations by backend/purpose, verdicts, failed checks,
  drafts approved/binned, near misses with tries left, inverted, ideas at budget, best results, lessons) and **paste
  PLAN** (`parse_plan` clips submit_target to 4/day x 5, drops unknown categories; `apply_plan` saves the plan with
  `extra` = retry/dead_ends/lessons, writes lessons + dead ends to the journal once; the Week tab shows them);
  "Rebuild the knowledge pack" button (uses the real journal read-only, also in sandbox).
- New concepts: `pretax_income`, `income_tax`, `esg_score`, `credit_spread`, `management_change` (checked on the
  GLB snapshot: ESG -> anl11 ESG scores, credit spread -> pv173 z-spreads, management -> qfl_corpexec tenure).
- CSS: disabled buttons now look disabled; `.hl-mdtable` for read-only HTML tables.
- Tests: `tests/test_drafts.py` (23). Browser-checked with Playwright: import -> edit -> save -> verdict -> bin ->
  restore -> approve -> Cards/Lab, copy a built-in card, PLAN paste, DIGEST.

**marimo gotcha found here (0.23.16), keep in mind for every cell that rebuilds UI elements:** the browser keeps a
value per element id (`<cell>-<counter>`). A cell that rebuilds a form with new values but the same ids showed the
OLD text; a cell where elements appear/disappear between runs shifts ids and mixes element types ("(c || []).map is
not a function"). Fixes used: the form cell advances the id counter by 1000 x load number
(`get_context()._id_provider._counter`, private API, wrapped in try); the Drafts view does the same per run; read-only
tables in cells that re-run on every keystroke are HTML (`views.html_table`), not `mo.ui.table`; the form cell
depends only on the loaded card (not on the region), so changing region never wipes edits.

Open for later: approving a card does not yet ask the Critic automatically (phase 6); drafts have no inbox source
list yet (phase 5/7); the DIGEST does not include Pyramid progress (add in phase 4).

## Phase 4 - the planner's Friday review (next)
The DIGEST out / PLAN in loop now exists (1.5.0). Phase 4 makes the planner itself smarter:
1. DIGEST + Week tab: Pyramid progress for the week (cells that moved, from `account_alphas` this quarter), drafts
   approved vs `card_target`, submissions vs `submit_target`, and the pace lines from `goals_view`.
2. `planner.propose()` for the next week from evidence: tracker cells still empty, the retry list and dead ends from
   the last PLAN, near misses with tries left; never push filler (combined performance is a Genius bar).
3. BRAIN_RULES items: front-load quality submissions before 1 Dec (G8), USA D0 default TOP1000 (S-8), the pending
   decision on plan order (guide vs multiplier: ask Zacc).
4. A Friday checklist on the Week tab (download account -> rebuild knowledge pack -> copy DIGEST -> paste PLAN).
5. Tests + apps smoke test; update the cheat sheet.

Phases after: 4 planner Friday review; 5 learning loop (scan candidates, near-misses, inverted, dead ends,
source quality, digest); 6 AI layer over Claude Code (P3 critic first, then P2 writer, P1 extractor, P4 weekly
review); 7 collectors (Open Source Asset Pricing import, arXiv, news RSS); then a SuperAlpha builder once
Zacc reaches 100 lifetime alphas.

## Standing rule: a cheat sheet after every phase
When a phase is complete (tests pass, apps checked), update the **HYPOLAB cheat sheet** doc
(https://claude.ai/code/artifact/37656bd4-b770-4e7c-b83e-83c57ae4eb28): bump the version and phase line, add the
new screens/commands/numbers, keep it to one page, and say what changed at the top. Phases: 1-2 done (+ 1.3.2 BRAIN rules); 3 card form +
Projects import/export (done, 1.5.0); 4 Friday review; 5 learning loop; 6 AI layer (mostly covered by the Claude Projects kit);
7 collectors; 8 SuperAlpha builder at 100 lifetime alphas.

## Practical notes for the next session
- marimo **0.23.16** was used. Read the "marimo gotcha" paragraph in Phase 3 before rebuilding UI elements in a cell.
  Tables select rows by the checkbox; `mo.state` holds cross-cell results; a
  `run_button` + `mo.stop(not btn.value)` guards anything that spends simulations.
- Check UI changes headlessly: `marimo export html apps/X.py` must show no `"ename"` other than
  `ancestor-stopped` (that is what `tests/test_apps.py` does). For clicks, Playwright + Chromium at
  `/opt/pw-browsers` worked; a tiny fake BRAIN server (see `tests/test_connect.py`) tests the login flow.
- Measured on a 2-core, 8 GB box (T470s-like), sandbox: cockpit ~0.8 GB, a scan session ~1 GB, a simulation
  click-to-verdict ~1 s. Live speed is bound by BRAIN, not the UI.
- Nothing has been run against the real BRAIN API in these sessions; the first live login and sync is Zacc's.
