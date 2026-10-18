# Learning path: from "I understand nothing" to submitting your own ideas

Rule of thumb from WorldQuant's own material: **an alpha is a hypothesis about why some stocks will do better than
others, written as a formula.** Learning quant for BRAIN means learning three things:

1. where mispricings come from (economics and behaviour);
2. what the data fields actually measure;
3. how to tell skill from luck.

The tools come last.

Budget: about 1 hour a day. Each week ends with something you *do* in hypolab.

---

## Week 1: what an alpha is, and why most are luck
- **Do:** the cockpit's Setup tab, then the Quant basics app (`apps/quant_basics.py`). The sandbox has *planted* signals, so you can
  check your judgment against the truth.
- **Watch:** WorldQuant's **Learn2Quant** series ([worldquant.com/learn2quant](https://www.worldquant.com/learn2quant/)),
  the intro episodes on alphas, Sharpe, turnover and neutralization. The full playlist is on WorldQuant's YouTube channel
  (playlist id `PLmpIWlqVqfbeQeWM8_0yBgIOGZguQYdXo`).
- **Read:** BRAIN → *Learn* → *Documentation*: "Introduction to Alphas", "Simulation settings", "Alpha checks".
- **Key ideas:** Sharpe; fitness = Sharpe·√(|returns| / max(turnover, 12.5%)); why decay only helps when turnover > 12.5%.

## Week 2: overfitting (the reason your old alphas were 99% trash)
- **Do:** the Quant basics app, section 6 (template sweep on pure noise) and `hypolab.overfit.noise_table()`.
- **Read:**
  - Bailey & López de Prado (2014), *The Deflated Sharpe Ratio*, Journal of Portfolio Management.
  - Harvey, Liu & Zhu (2016), *…and the Cross-Section of Expected Returns*, Review of Financial Studies. Why a t-stat of 2 is not enough after many tries.
- **Takeaway:** every extra simulation *on the same idea* makes a good Sharpe less believable. BRAIN still expects
  1000+ simulations from you, and that's fine: spread them across many ideas and dataset scans (`R.scan`), keep
  about 10 per idea, and let the journal count them so the gate can deflate honestly.

## Week 3: the data (BRAIN's real edge)
- **Do:** the Dataset scan app (`apps/dataset_scan.py`): scan one Tier-1 dataset (about 40 simulations)
  and compare the fields above the noise bar with what their descriptions say.
- **Do:** the cockpit's Data tab. Pick one dataset from the Pyramids guide's Tier-1 list and read **every field
  description**. Tick the dataset on the Data tab to see what each field *is*.
- **Read:** the dataset pages on BRAIN (*Data* tab): coverage, update frequency, description.
- **Takeaway:** quarterly data needs `ts_backfill` and long windows. Vector fields need `vec_*`. IDs and dates are not signals.

## Week 4: the classic anomalies (your idea library)
- **Read:** the references on the hypothesis cards in `hypolab/library/hypotheses.yaml`. Start with:
  - Jegadeesh (1990), short-term reversal.
  - Sloan (1996), accruals.
  - Novy-Marx (2013), gross profitability.
  - Bernard & Thomas (1989), post-earnings drift.
  - Hawkins, Chamberlin & Daniel (1984), estimate revisions.
- **Browse:** **Open Source Asset Pricing** (Chen & Zimmermann): 300+ published predictors, each with its original
  paper and code ([openassetpricing.com](https://www.openassetpricing.com/); paper:
  [SSRN 3604626](https://papers.ssrn.com/abstract=3604626)). Every predictor there is a candidate hypothesis card.
- **Read:** McLean & Pontiff (2016), *Does Academic Research Destroy Stock Return Predictability?*, Journal of Finance.
  Published anomalies lose about a third of their power after publication. Expect weaker results than the paper and
  look for *new data* angles.

## Week 5: the BRAIN way of building
- **Read:** *Finding Alphas: A Quantitative Approach to Building Trading Strategies* (Tulchinsky et al., Wiley, 2nd ed.
  2019), written by WorldQuant people. Chapters on alpha design, turnover, and robustness.
- **Read:** Kakushadze (2016), *101 Formulaic Alphas* (arXiv:1601.00991). Real WorldQuant alphas. Notice how short
  they are, and that their average pairwise correlation is only about 16%.
- **Do:** the cockpit's Cards tab → Lab tab on the sandbox, then **live** with 1–2 ideas a day.

## Week 6+: the consultant routine
- **Do:** in the cockpit, the Lab's robustness and gate on anything that passes; the Week, Pyramids and Journal tabs weekly.
- **Model to copy:** the [WorldQuant consultant spotlight on Eric Gitau](https://worldquant.com/ideas/consultant-spotlight-eric-gitau)
  (Kenyan BRAIN consultant). His approach is to take ideas from research papers and adapt them to BRAIN's datasets,
  which is exactly the card → binding → ladder loop.
- **Habit:** one new hypothesis card a week, written by *you* (copy the YAML format). Write the story first, then the formula.

---

## WorldQuant's robustness rules (from their webinars), as built into hypolab
- Windows should mean something: 5 (week), 21 (month), 63 (quarter), 126, 252 (year), 504.
- Look at value distributions and coverage before ranking anything.
- The idea should survive the **rank test** (rank instead of raw), the **binary test** (sign only), **winsorizing**,
  and a ±15% **window twist**.
- Choose using the train period and keep the last 2 years as a test (`testPeriod = P2Y`).
- Fewer, better simulations. Many simulations produce a few random high-Sharpe alphas.

## What hypolab cannot teach you
Intuition about *why* a market behaves a certain way comes from reading and from writing your own lessons
(the Journal tab's "Add lesson", or `R.journal.add_lesson(...)`). The journal is your notebook of mistakes. Read it every week.
