# Audit of `WQB.zip`: what helps a beginner and what doesn't

I read every file in the archive. The short verdict matches your instinct: **the code mostly automates
*simulating*, not *thinking*.** Those are different things. The notebooks take a template, fill it with every field
they can find, and fire off simulations. On BRAIN that gives what you saw: thousands of alphas, nearly all failing
in-sample (IS), and the few that pass are usually luck. They fail the out-of-sample (OS) period later or are
highly correlated with each other.

Measured evidence from the archive itself (AlphaForge's knowledge notes): hand-written, idea-driven alphas
passed **25.4%** of the time, template sweeps **0.21%**, and LLM-generated alphas **0.16%**. A 100× gap.
That is the whole case for an idea-first system.

---

## 1. Security: act on these first

| Issue | Where | What to do |
|---|---|---|
| **A live GitHub personal access token is shipped in the archive** | `ACE Studio/update_token.txt` | It belongs to the ACE Studio author, not to you. Don't share or re-upload that folder publicly. Delete the file. (I did not print or use it.) |
| Your BRAIN password is stored as **plaintext JSON** | ACE `ace_lib.py` writes `~/secrets/platform-brain.json` | Delete that file after moving to hypolab. hypolab reads env vars or a `0600` file inside a `0700` folder, and never puts the password in a notebook. |
| The session is saved as a **pickle** | ACE `ace_lib.py` | Loading a pickle from disk can execute code. hypolab stores only cookies as JSON. |
| AlphaForge is **obfuscated** (pyarmor, Windows `.pyd`) and needs a licence key | `AlphaForge/` | You can't read what it does with your credentials, and it doesn't run on Arch anyway. Only its `.md` knowledge notes are useful (and they were used here). |

---

## 2. File-by-file findings

### Modular-ACE-API `ace_lib.py` (2,463 lines): the engine most notebooks import

- **Login bug:** `start_session` treats HTTP **201** (BRAIN's *success* code for `POST /authentication`) as a wrong
  password in one branch. It deletes the saved credentials and recurses, which is why "it keeps asking for my password".
- **Duplicate function definitions.** The later definition silently wins, so reading the file top-down misleads you.
- `simulate_alpha_list_multi` **ignores its batch-size parameter.**
- Every alpha gets the placeholder text `regular_description`. BRAIN expects a real description
  (idea + data rationale + operator rationale), and reviewers notice.
- `markandstore` **crashes**: it references `datetime.datetime` wrongly and uses an undefined `blue_count`.
- `XhinkuAlphaFilter`:
  - uses a `passThreshold` that doesn't correspond to any BRAIN check;
  - labels Sharpe < −1.7 as "baddie" (a strongly negative Sharpe is often a *flipped good idea*);
  - can tag **failed** alphas as `top_performer`.
- In the search branch of `get_datafields`, **count is hard-coded to 100**, so results past 100 are silently dropped.

### Gold `ace_lib.py`
- `get_datafields` without a search term fetches **only the first page** (50 fields). Large datasets look tiny.

### Notebooks
| Notebook | What it does | Problem |
|---|---|---|
| RegularAlpha / GLB | template × field sweeps | Duplicated templates (same alpha simulated twice). No hypothesis, so no way to know *why* something works. |
| BOOSTER / ITERATOR | wraps alphas in more operators | Uses `arc_sin`, `pasteurize`, `sigmoid`, `s_log_1p`, `log_diff`. **None are on your Gold operator PDF**, so these simulations error out. ITERATOR also applies templates to **currency ISO codes and date fields**, which are labels, not signals. |
| SettingsVariator | 84-combination grid over decay/neutralization/truncation | This is how you manufacture a lucky Sharpe. With 1,000 tries on pure noise, the *expected best* 5-year Sharpe is about 1.46, close to the 1.58 bar. |
| SUPER / SUPERAlpha | combines random alphas | Random selection. Region mismatch (selects from USA, simulates in EUR/GLB). Its filter on `self_correlation > 0.5` keeps exactly the alphas you *don't* want. |

### ARC package
- Clean engineering, the best code in the archive.
- Its templates use `ts_returns`, `ts_skewness` and `ts_kurtosis`, which are **not on your Gold PDF**.
- Still template-first, not idea-first.

### `research_engine` phase_5
- Good design of guard rails (budgets, gates).
- It imports `wqb-core`, **which is not in the archive**, so it can't run.
- Its recipes are linear-only.
- Ideas were borrowed (budget, gate) and rebuilt here.

### ACE Studio
- Idea generation depends on an LLM. Measured hit rate is 0.16% (see above).
- Its category "pillars" table is a decent map of BRAIN data categories.
- It also contains the token issue from section 1.

### AlphaForge knowledge notes (`.md`): **the most valuable part of the zip**
Measured lessons, all encoded into hypolab:
- Correlation follows the **data family**: one good alpha per idea axis, not ten variants.
- `min()` of two independent signals is a powerful conjunction ("cheap AND improving").
- `vector_neut` and dilution are decorrelation tools.
- STATISTICAL neutralization works best in GLB.
- Some parameters must be **named** (`winsorize(x, std=4)`, `hump(x, hump=0.01)`), otherwise you get "invalid number of inputs".
- **One bad expression cancels a whole multi-simulation**, so lint before sending.
- `operator_tips.json` has 55 operator notes.

### `ECONOMICAL_LOOKBACK.jpeg`
A handwritten "booster" recipe using look-backs of 63/126/252/504 days (quarter, half-year, year, two years).
The useful part is the principle: **windows should mean something economically**. hypolab's linter flags
arbitrary windows like 37 or 113.

### `ace-catalog.json`
A real GLB / MINVOL1M / delay-1 catalog: 137 datasets, 27,114 fields. It is bundled (compressed) in
`data/` so the idea generator works on day one, before you sync your own regions.

### The two PDFs
- **Operators PDF:** every operator in it is in `hypolab/operators.py` (`GOLD`), with arity, named parameters
  and argument kinds. The linter **blocks** anything outside that list *before* it costs a simulation.
- **Pyramids guide:** its tiers, regions and recommended datasets are in `hypolab/pyramids.py`.
  - Tier 1: Analyst, Fundamental, Model, PV, Risk.
  - Tier 2: Earnings, Imbalance, Other, Macro.
  - Tier 3: Option, News, Sentiment.
  - Regions: USA, GLB, EUR, ASI, IND, plus one single country.
  - It also includes the guide's notes (e.g. *avoid model110*).
  - One gap in the guide: item "d)" of the Model section is missing between pages.

### BRAIN's own alpha-examples page
The "fundamental" example actually shows a price/volume expression. That's a small thing, but it shows why
copying examples doesn't teach you the *why*.

---

## 3. What was missing everywhere (and what hypolab adds)

| Missing in the zip | hypolab |
|---|---|
| Ideas with an economic mechanism | 47 hypothesis cards: story, why it persists, references, roles, ladder, settings, expected turnover, traps |
| Mapping an idea to *your* data | Concept matcher over the catalog (what a field *is*: estimate, flow, stock, ratio, flag, ID, date…) |
| Stopping bad expressions before they cost a sim | Linter: Gold-only operators, named parameters, vector fields, IDs/dates, coverage, windows |
| Reading results | Diagnosis: ERROR / INVERTED / NOISE / WEAK / NEAR / PASS with **one** next action |
| Knowing whether a Sharpe is luck | Journal counts every try; deflated Sharpe; train/test split; robustness battery |
| A plan for promotion | Pyramid planner reads your real `/activities/diversity` and points to the empty cells |
| Learning | `docs/LEARNING_PATH.md` and the Quant basics app, where the answers are known so you can check your judgment |
