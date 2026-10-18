# HYPOLAB's idea team on Claude Projects

Four Claude Projects act as specialists. They cannot talk to each other: **you carry the messages**, and every
message has a fixed format (below) so it can be pasted straight into the next project or into the cockpit.

| Project | Role | Instructions | Knowledge files to upload |
|---|---|---|---|
| HYPOLAB - BRAIN Library | Reads BRAIN articles and dataset listings you upload; writes briefs and dataset shortlists | `1_brain_library.md` | 02, 04, 05, plus your BRAIN uploads |
| HYPOLAB - Scout & Writer | Turns a source or brief into hypothesis cards | `2_scout_writer.md` | 01, 02, 03, 04, 08, `briefs.md` |
| HYPOLAB - Critic | Attacks cards it did not write | `3_critic.md` | 01, 02, 03, 04, 06, 07, `briefs.md` |
| HYPOLAB - Weekly Reviewer | Reads the week's results; plans the next week | `4_weekly_reviewer.md` | 04, 05, 06, 07, 08 |

The numbered files are in `knowledge/` (see `knowledge/INDEX.md`). `briefs.md` is a file *you* keep: paste each
brief you want the other projects to know into it, and re-upload it weekly.

## Setting one up (claude.ai)
1. Create the project with the name above.
2. Paste the file's text below the line `--- paste from here ---` into the project's custom instructions.
3. Upload the knowledge files listed for it.
4. Keep these projects private: BRAIN materials may be confidential under your consultant agreement.

## The four workflows
1. **Knowledge** (whenever you read something on BRAIN): upload or paste it into **BRAIN Library** -> it returns a
   BRIEF -> keep the useful ones in your `briefs.md`. For a **dataset listing** page (Data > Datasets, one PDF per
   region), ask for a SHORTLIST; then save and upload the description and field-list pages of its top targets,
   and ask for a BRIEF on each. Those briefs are the best food for the Writer: high value score + few alphas =
   room for an original idea.
2. **Ideas** (daily, two hand-offs): paste a source (paper abstract, article, a BRIEF, or a scan candidate from the
   Dataset Scan app) into **Scout & Writer** -> CARD -> paste it into the cockpit's **Drafts** tab (*Import from
   Scout & Writer*): HYPOLAB checks it and binds it to real fields at once -> **Copy for the Critic** (the card plus
   HYPOLAB's dry run) -> paste into **Critic** -> VERDICT -> paste it back on the Drafts tab -> `keep`: **Approve**
   (it joins your library) and test rung 1 in the Lab; `rewrite`: give the fixes to the Writer and import again;
   `bin`: bin the draft with the reason.
3. **Learning** (Friday): on the Week tab, pick the week and copy its **DIGEST** into **Weekly Reviewer** -> PLAN ->
   paste it in *Paste the Reviewer's PLAN* on the Week tab: it is saved for its week, and its lessons and dead ends
   go to the journal (once).
4. **Refresh** (weekly, 5 minutes): press **Rebuild the knowledge pack** (Drafts tab, under the hand-offs) or run
   `python -m ideaengine.knowledge_pack`, and re-upload the files that changed
   (03, 04, 06, 07, 08 change as you work; download your account on the Account tab first), plus `briefs.md`.

## Hand-off formats (every project uses exactly these)

**BRIEF** (BRAIN Library -> you -> other projects)
```
### BRIEF B-<yyyymmdd>-<n>: <topic in a few words>
source: <title of what you uploaded>
key points:
- <3-6 lines, the substance in plain words>
rules or thresholds: <anything BRAIN states as a rule, with its number; "none">
data mentioned: <dataset ids / field types / regions; "none">
idea seeds:
- <mechanism in one sentence> (concepts: <names from 02_concepts.md>)
open questions: <what the source does not say>
```

**SHORTLIST** (BRAIN Library -> you): the dataset targets of one region, format in `1_brain_library.md` step 4.

**CARD** (Scout & Writer -> Critic -> cockpit): one YAML card in HYPOLAB's format (`01_card_format.md`), id
starting `IE_`, preceded by one comment line `# from: <source or brief id>`.

**VERDICT** (Critic -> you)
```yaml
verdict:
  id: IE_...
  decision: keep | rewrite | bin
  scores: {novelty: 1-5, clarity: 1-5, plausibility: 1-5, data_fit: 1-5}
  duplicate_of: <built-in id or null>
  known_factor_in_disguise: <momentum | value | size | quality | low_risk | reversal | null>
  most_likely_failure: <one sentence>
  why_it_could_persist: <one sentence, or "not convincing">
  fixes: [<concrete change>, ...]        # for rewrite
  one_line: <the decision in plain words>
```

**DIGEST** (cockpit -> Weekly Reviewer): the week, plan, simulations, verdict counts, submissions today/this week,
near-misses (NEAR with tries left), inverted results, families at budget, lessons written.

**PLAN** (Weekly Reviewer -> you -> cockpit Week tab)
```yaml
plan:
  week: 2026-Wnn
  region: USA
  categories: [analyst, fundamental]
  dataset_focus: <dataset id>
  card_target: 5
  submit_target: 10
  retry: [<idea ids worth one more rung or a boost>]
  dead_ends: [<families to stop>]
  lessons: [<one line each>]
  review_note: <3 sentences: what worked, what did not, what changes>
```

## What stays outside the projects
Field ids, simulations, the gate and submissions stay in HYPOLAB. The projects write *hypotheses*, never final
expressions bound to fields, and never decide to submit.
