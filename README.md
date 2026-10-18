# hypolab: idea-first alpha research for WorldQuant BRAIN

**Quality ideas first, simulations second.** The notebooks in `WQB.zip` sweep templates over fields. Measured hit
rate: about 0.2%. hypolab instead starts from an economic hypothesis, binds it to *your* data, blocks bad
expressions before they cost a simulation, tells you what each result means and what to do next, and refuses to
call something "submittable" until it has passed robustness and overfitting checks.

Built for: a Gold-level consultant, Arch Linux, a Lenovo T470s, Python and marimo. No GPU, no paid tools.

Two halves, one loop:
- **HYPOLAB** (`hypolab/`) *tests* ideas: bind to your fields, lint, simulate, diagnose, validate, submit.
- **Idea Engine** (`ideaengine/`) decides *what is worth testing*: quarter goals, the weekly plan, the daily
  submission cap, and (in later phases) new hypothesis cards from papers, news and your own journal.
- **Three marimo apps** (`apps/`) are the screens for both. There are no Jupyter notebooks any more.

## Install (Arch)
```bash
unzip hypolab.zip && cd hypolab
bash setup_arch.sh
source ~/.venvs/hypolab/bin/activate
python -m hypolab cockpit          # = marimo run apps/  -> a gallery page with the three apps
```
Everything starts in **sandbox mode**: an offline synthetic market with planted signals, so you can learn and
practise the whole loop - Lab included - without spending simulations. `marimo edit apps/cockpit.py` opens any app
as an editable notebook if you want to see or change its code.

| App | File | What it is for |
|---|---|---|
| Cockpit | `apps/cockpit.py` | Daily work: Week, Pyramids, Cards, Drafts, Lab, Play, Journal, Account, Data, Setup tabs |
| Dataset scan | `apps/dataset_scan.py` | Explore a dataset by field nature, then scan every field against the noise bar. Separate on purpose: a live scan can take 10-30 minutes and would otherwise block the cockpit |
| Quant basics | `apps/quant_basics.py` | What an alpha is, the four numbers BRAIN judges, neutralization, why brute force makes luck, robustness |

## Going live
Open the cockpit's **Setup** tab:
1. **Log in**: email and password. If BRAIN asks for a face scan, a link appears on the page; do the scan, then
   press *I finished the face scan*. Credentials are saved to `~/.hypolab/credentials.json` (readable only by you)
   only after BRAIN accepts them, and only if you tick the box.
2. **Switch to Live** and pick the region. Every tab and app follows the switch (reload the scan and learning apps
   if they are open).
3. On the **Data** tab, download the field list for your region once (metadata only; reused for 7 days).

The apps never wait on a hidden prompt: if a session expires and BRAIN wants a face scan, they point you to Setup.

Same from a terminal:
```bash
python -m hypolab login        # enter + verify + save credentials
python -m hypolab live USA     # the apps use your account, region USA
python -m hypolab status       # where you stand
python -m hypolab sandbox      # back to practice mode
python -m hypolab logout       # delete saved credentials
```

## The cockpit's tabs
| Tab | You see / do |
|---|---|
| Week | The Expert bars for the quarter (signals, Pyramids, combined performance) and the pace needed; this week's region, categories and dataset; the Friday review: copy the week's DIGEST for the Weekly Reviewer, paste its PLAN back |
| Pyramids | Region × category heatmap (live from BRAIN), next cells in the guide's order, alphas needed per Pyramid, live multipliers |
| Cards | Ranked idea cards (built-in and yours) for the region and categories you pick; read a card in full; send it to the Lab; bin noise |
| Drafts | Write your own card in a form (blank, or a copy of any card) or import one from Scout & Writer; live checks on every change (format, Gold operators, concepts, dry-run binding in the region, same family, journal dead ends); copy it for the Critic and attach the VERDICT; approve to `my_cards.yaml` or bin with a reason; rebuild the knowledge pack |
| Lab | Test a rung or your own expression, read the verdict, follow ONE action, boost, robustness battery, gate report, typed-confirmation submit. Every simulation sits behind a button: changing a control never simulates |
| Journal | Verdict mix, tries per idea against the budget, scoreboard, experiments, submissions, lessons (add your own) |
| Account | Downloads your submitted alphas and BRAIN's live operator list: lifetime and quarter counts (feeds the SuperAlpha countdown), operators used and unused per quarter by category, the fields you lean on most |
| Data | What each dataset and field measures (nature, concepts, coverage, crowding), fields by economic concept, free-text search, the guide's datasets, downloading a region |
| Setup | Sandbox/live switch, login with the face-scan step, status, the Gold operator list, the daily routine |

Your own cards: write or import them on the **Drafts** tab; **Approve** appends them to
`~/.hypolab/library/my_cards.yaml` (the previous file is kept as `my_cards.yaml.bak`). Any `*.yaml` in that folder in
the same format as `hypolab/library/hypotheses.yaml` also loads. They sit next to the built-in 47, marked `mine`. A
card whose id clashes with a built-in one is skipped and reported at the top of the cockpit.

## The daily loop in code (what the Lab tab does)
```python
from hypolab.research import Researcher
R = Researcher.start()                    # follows the Setup tab switch / `python -m hypolab live USA`
cards = R.ideas(n=10)                     # ranked hypotheses bound to USA fields
card = R.card("ANL_EPS_REVISION")         # or one card by id (built-in or yours)
R.show(cards[0])                          # read the story BEFORE simulating
t = R.test(cards[0], rung=0)              # linted, budgeted, journaled
R.show(t)                                 # verdict + one next action
t2 = R.follow(t, 0)                       # or R.test(card, rung=1)
boost = R.boost(t)                        # weak but real (Sharpe ~1)? add ONE independent second signal
R.show(boost)                             # predicted vs actual gain; boost.best is the combined alpha
gate = R.gate(t2, R.robustness(t2))
R.show(gate)
R.submit(gate, confirm=f"SUBMIT {gate.alpha_id}")   # only you can do this
```

## Simulation volume and guard rails (edit `~/.hypolab/settings.json`)
BRAIN expects 1000+ simulations from consultants who build ideas from scratch, and hypolab is built to spend them
well:
- **Across ideas and datasets, spend freely.** `R.scan(dataset)` probes every field of a dataset in bulk and
  marks which ones clear the *noise bar*. Many idea cards a day, a few rungs each.
- **Within one idea, stay disciplined.** About 10 tries per hypothesis, then rethink. Picking the best of many
  variants of one idea is what produces alphas that die out of sample.
- **Every try is counted.** The gate deflates the Sharpe by the tries on that idea, including every field scanned
  in the dataset when the alpha came from a scan.
- **Originality is checked.** The gate tests correlation with your own alphas *and* with BRAIN's production pool.
  A copied idea fails there, however good its Sharpe.
- A runaway guard of 500 simulations a day, and 2 concurrent requests.
- Gold operators only, checked against your PDF.
- Duplicate simulations are served from the journal.
- Nothing is ever submitted without the typed confirmation.
- At most 4 submissions a day (`max_submissions_per_day`), BRAIN's daily expectation used as a ceiling. The Week tab tracks lifetime submissions toward the 100 that unlock SuperAlphas.

## Docs
- `claude_projects/`: custom instructions and a knowledge pack for running the idea team as Claude Projects.
- `HANDOFF.md`: where the project stands and what comes next (read first when resuming work).
- `docs/AUDIT.md`: line-by-line findings on the zip, **including a live GitHub token shipped inside `ACE Studio/`**.
- `docs/LEARNING_PATH.md`: a 6-week path built from WorldQuant's own material and the core papers.
- `docs/HOW_IT_WORKS.md`: the architecture and where your data lives.
- The design of the Idea Engine (phases, prompts, planner) is in the HYPOLAB Idea Engine design doc.

## Honest limits
- The sandbox teaches judgment; it is not BRAIN. Only live results count.
- BRAIN changes thresholds and adds checks. Its own `/check` is always the authority, and hypolab reads it live.
- The idea cards are well-documented anomalies. Many are crowded, so the edge comes from binding them to less-used
  datasets (the generator penalises crowded fields) and from writing **your own** cards.
- Tests: `python -m unittest discover -s tests` (88 tests, about two minutes).
