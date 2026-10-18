# How hypolab works

```
 hypothesis card ──► bind to YOUR data ──► lint ──► simulate ──► diagnose ──► (climb ladder | flip | stop)
 (library/*.yaml)    (catalog + concepts)  (Gold     (BRAIN or     (one next                │
                                            ops)     sandbox)      action)                  ▼
                                                                          robustness ──► gate ──► you submit
 journal.sqlite records every step  ◄───────────────────────────────────────────────────────────┘
 pyramid planner reads your diversity and steers which ideas are generated next
```

## 1. Hypothesis cards: `hypolab/library/hypotheses.yaml`
A card is an *idea*, not a formula. Each card has:

| Field | What it holds |
|---|---|
| `story` | The mechanism: who makes the mistake and why prices adjust slowly. |
| `why_persists` | Why it hasn't been arbitraged away. |
| `references` | Papers, so you can read the original. |
| `roles` | Data *concepts* the idea needs, e.g. `est_eps` or `cfo`, rather than field names. That's what makes one card work in every region. |
| `ladder` | 2–4 rungs from simplest to refined. Each rung teaches one thing. You climb only when the diagnosis says so. |
| `settings`, `expected_turnover`, `watch_out` | Defaults, the turnover range to expect, and known traps. |

The 47 cards cover all 13 Pyramid categories. Add your own in the same format; `validate_library()` checks them.

## 2. Binding: `catalog.py`, `concepts.py`, `ideas.py`
- The catalog (SQLite) holds every dataset and field for each region/universe/delay you sync. The GLB snapshot from
  your zip is bundled.
- Each field gets a *nature*: estimate, flow, stock, ratio, price, count, flag, identifier, date…
- Each field also gets matched to about 70 *concepts* by its id and description.
- A card's roles are filled with the best-matching, best-covered, least-crowded fields.
- Paired roles (e.g. revisions up/down) must come from mirrored fields.
- Ideas are ranked by:
  - the card's strength;
  - how well the data fits, and its coverage;
  - crowding (how many alphas already use the field);
  - which **Pyramid cells you still need**;
  - what your journal says you've already done.

## 3. Linter: `linter.py`
It blocks, *before spending a simulation*:
- operators not on your Gold PDF;
- wrong arity, or positional use of named-only parameters;
- vector fields used without `vec_*`;
- IDs or dates used as signals;
- unused variables.

It warns about:
- low coverage;
- arbitrary or too-short windows on quarterly data;
- deep nesting;
- too many fields;
- unbounded outputs.

## 4. Simulate: `brain.py` (live) or `mock.py` + `sandbox/` (offline)
- `BrainClient` logs in (including biometric/persona), retries on 429/5xx, polls `Retry-After`, batches
  multi-simulations (2–10), and runs at most 3 concurrent requests.
- **Submitting requires typing `SUBMIT <alpha_id>`.**
- The sandbox is a synthetic 500-stock, 6-year market with planted effects (value, quality, revisions, PEAD,
  reversal, sentiment, low-vol) and 40 pure-noise fields. A full FastExpression evaluator and a BRAIN-like backtester
  with the same checks run on it.

## 5. Diagnosis: `diagnose.py`
Every result gets a verdict and *one* recommended next action:

| Verdict | Meaning | Next action |
|---|---|---|
| ERROR | the platform error, translated | the fix |
| INVERTED | strongly negative | flip only if the reverse mechanism makes sense |
| NOISE | \|Sharpe\| < ~0.5 | stop; next idea |
| WEAK | some signal, far from the bar | next rung, or a second independent leg |
| NEAR | close to the bar, e.g. fitness-bound | economic decay, etc. Uses fitness arithmetic: decay can't help below 12.5% turnover |
| PASS | clears the bar | robustness, then the gate |

## 5a. Boosting a weak alpha: `research.boost()`
A Sharpe around 1.0 is often a real but weak signal. `R.boost(result)` adds **one independent second signal**:
- Candidates are other idea cards, from a *different data category* first, each tested alone (a normal, journaled
  test of that idea).
- It measures the PnL correlation with your alpha and **predicts** the combined Sharpe:
  (S1 + S2) / √(2·(1 + ρ)). On the sandbox this predicted 1.39 vs an actual 1.39, and 2.41 vs 2.46.
- It refuses boosters with no signal of their own, boosters too correlated with yours (ρ > 0.7), predicted gains
  under 10%, and boosters that are better *alone* than the combination (the combination would really be their alpha).
- A fast booster on a slow alpha is smoothed over a month so its trading doesn't wreck fitness.
- Combination: `rank(base) + rank(booster)`, or `mode="and"` for `min(rank(base), rank(booster))`.
- Every combination counts as a try on the base idea, so the gate's deflated Sharpe reflects the search.

Sandbox example: gross profitability, Sharpe 1.02 (WEAK), plus a month-smoothed revision-breadth signal
(ρ = 0.03) gives Sharpe 2.34, fitness 2.01, and passes the gate.

Seeing what a boost made (1.4.3): combinations are journaled as `<rung> + boost:<card>`; the report keeps each
booster's solo result (`report.boosters`), and `report.lab_results()` is what the cockpit's Lab adds to its list
(boosters alone, then combinations, the best last so it is selected). `R.performance(result, compare=...)` reads the
cumulative PnL and yearly table (no simulation); the Lab draws the best combination against its base and booster.

## 5b. Dataset scans: `research.scan()`
- Probes every usable field of one dataset once, with the lens that fits its nature, as one batched multi-simulation.
- Prints a **noise bar**: the |Sharpe| that the best of N pure-noise probes beats only 5% of the time. The noise spread
  is the larger of 1/√years and the scan's own robust spread, because real noise has fat tails.
- Every probe is journaled under the dataset's family. An alpha later built from a scanned field is deflated by the
  number of fields scanned.
- This is where BRAIN's expected simulation volume (1000+) is spent best: learning data, not polishing one formula.

## 6. Validation: `robustness.py`, `overfit.py`, `research.gate()`
- **Robustness battery:** rank, binary, winsorize, window ±15%, neighbouring neutralization, liquid universe.
- **Gate:**
  - platform `/check`;
  - self-correlation against your submitted alphas;
  - **production correlation** against BRAIN's pool. This is the originality test: a textbook or copied idea fails
    here however good its Sharpe;
  - train vs test Sharpe;
  - **deflated Sharpe**, using the number of tries the journal recorded for this idea (or the whole dataset scan);
  - robustness score;
  - an auto-written description (idea, data rationale, operator rationale, reference).

## 7. Journal and Pyramids: `journal.py`, `pyramids.py`
- The journal runs in SQLite WAL mode, so the cockpit (and the Idea Engine) can read it while another app writes.
  `Journal.open_readonly()` opens it without the right to write.
- The journal remembers every simulation (with dedupe by canonical expression and settings), every submission and
  every lesson.
- The Pyramid tracker counts **this quarter's** submitted alphas (Genius counts per quarter): from the Account tab
  download, each alpha is placed in every category its fields belong to (or BRAIN's own Pyramid tags when an alpha
  carries them). Without a download it falls back to `/users/{id}/activities/diversity` (all time) or the journal.
  It builds:
  - a region × category matrix;
  - the cells you still need, per delay, in the guide's order or by Pyramid theme multiplier (live from BRAIN, else
    the bundled 2026-Q4 snapshot in `data/pyramid_multipliers_2026Q4.json`); cells BRAIN doesn't offer are left out;
  - a daily plan with the guide's recommended datasets.

## 7a. BRAIN's rules: `rules.py` and `docs/BRAIN_RULES.md` (1.3.2)
- `docs/BRAIN_RULES.md` lists every rule read from BRAIN's own pages, with source, conflicts and HYPOLAB's status.
  It also goes into the knowledge pack as `09_brain_rules.md`.
- `rules.py` holds the numbers: the **single-dataset test** (fields from one dataset, grouping fields excepted ->
  last-2-year Sharpe >= 2.38 at D1 / 3.96 at D0 instead of the IS ladder), the **sub-universe cutoff**
  (0.75 × √(sub/size) × Sharpe), **Fitness labels**, **BRAIN's day** (New York midnight) and the **Osmosis lock
  deadline**. Every ladder rung and every result shows which IS test applies.
- `brain.record_quota()` saves BRAIN's `X-Ratelimit-*` headers after each simulation; the Lab shows the real
  remaining count and HYPOLAB stops at 0.
- `BrainClient.sync_simulation_options()` saves each region's universes, delays and neutralizations (incl. the risk
  sets SLOW / FAST / SLOW_AND_FAST / REVERSION_AND_MOMENTUM / STATISTICAL / CROWDING) to
  `~/.hypolab/sim_options.json`; the Lab offers exactly those. DEU and GBR need this before their first simulation.
- `account.py` adds the Genius views: `tiebreakers()`, `quarter_pyramids()`, `osmosis_check()`.
- `Researcher.rerun(alpha, variants)` re-simulates a submitted alpha with risk sets or at D0; every try counts
  against `rerun:<alpha_id>` and still has to pass the gate.

## 8. Idea Engine and the marimo apps: `ideaengine/`, `apps/`
HYPOLAB tests ideas; the Idea Engine decides what is worth testing. They meet in two places only:
- **Your card files** (`~/.hypolab/library/*.yaml`): `load_library()` loads them after the built-in library and
  marks them `source = "mine"`. A clashing id or a broken file is skipped and listed in `hypotheses.LOAD_WARNINGS`.
- **The journal**: the Idea Engine reads it to measure the week and (later) to find near-misses and scan candidates.

`ideaengine/` today: `store.py` (quarter goals, weekly plans and drafts in `ideas.sqlite`), `planner.py` (ISO weeks, the
starting plan, pace toward the Expert bars, daily submission cap and SuperAlpha unlock), `drafts.py` (phase 3, see
section 12), `views.py` (tables for the cockpit), `connection.py` (opens HYPOLAB without ever prompting). Later phases
add the Friday review, the learning loop and collectors.

Three marimo apps sit over both packages (run them together with `python -m hypolab cockpit`):
- `apps/cockpit.py`: Week, Pyramids, Cards, Drafts, Lab, Play, Journal, Account, Data, Setup. Setup logs in with `connect.begin_login` / `connect.finish_login`, so a face scan is a link plus a button, never a hidden prompt.
- `apps/dataset_scan.py`: dataset explore and scan, separate so a long live scan never blocks the cockpit.
- `apps/quant_basics.py`: the quant-basics course on the practice market.

In sandbox mode each app has its own in-memory practice journal; in live mode all of them share `~/.hypolab/journal.sqlite`.
`Researcher.card(id, region)` builds the one card the Lab works on. Every simulation is behind a run button, and
submitting needs the gate's READY plus the typed `SUBMIT <alpha_id>`.

## 9. Play: `play.py` (1.4.0)
- `roll()` makes random alphas for free: random idea cards (any family, the Pyramid plan ignored) or wild rolls (a
  random field, or two fields of one dataset, in a random template), linted, with optional shuffled settings and a
  seed to reproduce a roll. `Researcher.play()` simulates them as purpose `play`; each roll counts as a try for its
  `play:...` idea, so the gate's deflated Sharpe knows how many dice were thrown. Cockpit tab **Play**.

## 10. Binning noise cards (1.4.3)
`R.bin(card_id, reason)` puts a card in the journal's `binned` table: it disappears from `R.ideas()` (and so from
boosters), `R.roll()`, the cockpit's Cards ranking and Lab list, and "Restore results". `R.restore(card_id)` brings it
back; nothing is ever deleted. In the cockpit: **Cards > Bin this card** and **The bin**; in the Lab, **Bin card**.

## 11. Speed on a small laptop (1.4.3)
Concept matching and field enrichment for a region are computed once and cached in `~/.hypolab/cache/` (rebuilt
automatically after a catalog sync or a change to the concept rules). The background rain has a **[ FX ]** switch
(full / calm / off) at the bottom right of the apps.

## 12. Writing cards: `ideaengine/drafts.py` (phase 3, 1.5.0)
A draft IS a HYPOLAB card, kept in `ideas.sqlite` table `drafts` with a state: **draft** (a check fails or it was
never checked), **checked** (every check passes), **approved** (appended to `~/.hypolab/library/my_cards.yaml`),
**binned** (set aside with a reason; restore puts it back to draft).
- `form_defaults(card)` / `card_from_form(values, base)`: the cockpit form and back. Keys the form does not show
  (role `categories`, `pair_with`, `type`, `min_coverage`, a rung's `when`, `beginner` ...) are kept from the base
  card; all 47 built-in cards survive the round trip unchanged (tested).
- `parse_cards(text)`: pasted CARDs (code fences and `# from:` lines are fine, several cards at once); a VERDICT or a
  PLAN pasted in the wrong box is recognised.
- `check_card(card, catalog, region, journal=...)`, no simulation: required fields and types; id format and
  **clash with any library id** (error); category, horizon, strength, family; concepts exist (with "did you mean");
  `validate_library` (syntax, placeholders, Gold operator errors); linter warnings (odd windows, unbounded output);
  field ids written directly (warning); a **dry-run binding** with `build_card` in the region, each rung's IS test
  (single dataset 2.38 or IS ladder), or which role found no field; same family / same concepts in the library;
  the journal's record for the family (dead end = 5+ tries, none WEAK or better).
- `Drafts(store)`: `save` (rename-aware), `bin`, `restore`, `attach_verdict` (the Critic's block; advice only),
  `approve` (refuses errors; `append_to_my_cards` writes atomically, keeps `.bak`, refuses duplicate ids and anything
  that would not load back).
- Hand-offs: `critic_message` (card + checks + dry run as YAML comments), `digest(journal, store, week)` (the Friday
  DIGEST), `parse_plan` / `apply_plan` (the Reviewer's PLAN: saved for its week with retry / dead ends / lessons;
  lessons and dead ends go to the journal once), `rebuild_knowledge_pack()`.
- Concepts added for the theme datasets: `pretax_income`, `income_tax`, `esg_score`, `credit_spread`,
  `management_change`.

## Files you own
| File | Contents |
|---|---|
| `~/.hypolab/credentials.json` | `{"email": ..., "password": ...}`, mode 600. Or use the env vars `BRAIN_EMAIL` and `BRAIN_PASSWORD`. |
| `~/.hypolab/session.json` | Cookies only. |
| `~/.hypolab/catalog.sqlite` | Synced metadata. |
| `~/.hypolab/journal.sqlite` | Your research history. **Back this up.** |
| `~/.hypolab/settings.json` | Sandbox/live `mode`, `live_region`, budgets, thresholds, alphas per pyramid. |
| `~/.hypolab/ideas.sqlite` | The Idea Engine: quarter goals, weekly plans, card drafts. |
| `~/.hypolab/library/*.yaml` | Your own hypothesis cards (`my_cards.yaml` is written by Approve, `.bak` = the previous version). **Back these up.** |
