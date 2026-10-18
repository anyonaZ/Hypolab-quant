"""Economic concept ontology: what a datafield MEASURES.

BRAIN has 400,000+ fields with vendor-specific names (``fnd6_int_ibmiiq``,
``anl4_dez1advancedafv4_est`` ...). A hypothesis is written in economic
language ("operating cash flow divided by market value"), so we need a bridge
from economics to field ids. This module classifies each field by

* **nature** - what kind of number it is (a level from the balance sheet, a
  flow from the income statement, an analyst estimate, a count, a 1-100 rank,
  a date, a code, ...). Nature decides which operators make sense: you never
  ``ts_delta`` a currency ISO code, never ``rank`` a report date, and you
  ``ts_backfill`` anything quarterly. (The ITERATOR notebook in the zip
  happily applied ``ts_rank(abs(x))`` to ``anl69_aeps_best_crncy_iso`` - a
  currency code. This is the check that prevents that.)
* **concepts** - which economic quantities it plausibly represents, matched
  with transparent regular expressions over the field id AND description.

Matching is heuristic and deliberately explainable: every match records the
pattern that fired, so you can see *why* a field was chosen and overrule it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------- natures

NATURES = {
    "group": "categorical grouping (sector, cluster id) - use only as the group argument",
    "identifier": "code / text / id - NOT a number with meaning; never use in arithmetic",
    "date": "a date, time or fiscal-period label - not usable as a signal",
    "flag": "0/1 indicator - use as a condition (trade_when / if_else) or a gate",
    "count": "a count of things (analysts, filings, stories) - often scale with company size",
    "rank_score": "a vendor percentile/score - already normalised; check the description for direction",
    "estimate": "a forward-looking analyst/model estimate - pair with price or with its own past value",
    "change": "already a change / revision / growth number",
    "ratio": "a ratio, margin, yield or per-share number - comparable across stocks",
    "price": "a price level - not comparable across stocks until divided or ranked over time",
    "flow": "an income-statement / cash-flow amount - scale by size (cap, assets, sales) before ranking",
    "stock": "a balance-sheet amount - scale by size before ranking; changes slowly (quarterly)",
    "level": "a numeric level of unclear type - inspect before use",
}

_NATURE_RULES: List[Tuple[str, str]] = [
    ("identifier", r"\b(iso|currency code|country code|ticker|isin|cusip|sedol|identifier|\bid\b|headline|"
                   r"text\b|summary text|url|name of|entity|category of|type of|classification code|"
                   r"sector name|industry name|exchange code|symbol)"),
    ("date", r"\b(date|dates|timestamp|utc|time of day|day of week|month of year|period end)\b|"
             r"(^|\| )(the )?(fiscal|calendar|reporting) (year|quarter|period)\b|"
             r"(fiscal|reporting) (year|quarter|period) (associated|label|identifier|in the cube|of the event)|"
             r"quarter indicator"),
    ("flag", r"\b(indicator|flag|whether|boolean|binary|dummy|is_[a-z]+)"),
    ("count", r"\b(number of|count of|count\b|# of|how many|total number)"),
    ("rank_score", r"\b(percentile|rank\b|ranking|score|rating|grade|decile|quintile|probability|likelihood|"
                   r"signal strength)"),
    ("estimate", r"\b(estimate|estimated|forecast|consensus|expected|expectation|guidance|projected|projection|"
                 r"predict|prediction|smartestimate|target price|price target|fy1|fy2|next (year|quarter)|forward)"),
    ("change", r"\b(change|revision|revised|growth|delta|momentum|increase|decrease|upgrade|downgrade|"
               r"surprise|difference)"),
    ("ratio", r"\b(ratio|margin|yield|per share|percentage|percent|return on|turnover ratio|coverage ratio|"
              r"multiple|to (price|sales|book|assets|equity))"),
    ("price", r"\b(price|close|open|high|low|vwap|bid|ask)\b"),
    ("flow", r"\b(income|revenue|sales|earnings|ebit|ebitda|cash flow|expense|expenses|cost|profit|dividend|"
             r"capital expenditure|capex|interest paid|tax)"),
    ("stock", r"\b(assets|liabilities|debt|equity|inventor|receivable|payable|cash and|reserves|"
              r"shares outstanding|book value|goodwill|intangible)"),
]


def classify_nature(field_id: str, description: str, ftype: str = "MATRIX") -> str:
    t = (ftype or "").upper()
    if t == "GROUP":
        return "group"
    if t in ("SYMBOL", "UNIVERSE"):
        return "identifier"
    text = f"{field_id.replace('_', ' ')} | {description or ''}".lower()
    for nature, pattern in _NATURE_RULES:
        if re.search(pattern, text):
            return nature
    return "level"


#: natures that must never be used as numeric signals
NON_NUMERIC = {"identifier", "date", "group"}

# ---------------------------------------------------------------- concepts


@dataclass
class Concept:
    name: str
    include: List[str]
    exclude: List[str] = field(default_factory=list)
    natures: Optional[List[str]] = None       # preferred natures (None = any numeric)
    canonical: List[str] = field(default_factory=list)   # standard field ids worth trying first
    note: str = ""

    def __post_init__(self):
        self._inc = [re.compile(p) for p in self.include]
        self._exc = [re.compile(p) for p in self.exclude]
        # one combined pattern each: a single search rejects the ~99% of fields that do not match (1.4.3 speed-up)
        self._any_inc = re.compile("|".join(f"(?:{p})" for p in self.include)) if self.include else None
        self._any_exc = re.compile("|".join(f"(?:{p})" for p in self.exclude)) if self.exclude else None

    def match(self, field_id: str, description: str) -> Tuple[float, str]:
        """Return (strength, reason). strength 0 = no match."""
        fid = field_id.lower()
        return self.match_text(fid, f"{fid.replace('_', ' ')} | {(description or '').lower()}")

    def match_text(self, fid: str, text: str) -> Tuple[float, str]:
        """match() on a pre-lowered id and pre-built text (the catalog builds these once per region)."""
        if fid in self.canonical:
            return 3.0, f"standard field '{fid}'"
        if self._any_inc is None or not self._any_inc.search(text):
            return 0.0, ""
        if self._any_exc is not None and self._any_exc.search(text):
            return 0.0, ""
        hits = [rx.pattern for rx in self._inc if rx.search(text)]
        if not hits:
            return 0.0, ""
        strength = 1.0 + 0.5 * (len(hits) - 1)
        fid_text = fid.replace("_", " ")
        if any(rx.search(fid_text) for rx in self._inc if rx.pattern in hits):
            strength += 0.5     # the id itself names the concept
        return strength, f"matched /{hits[0]}/"


def _c(name, include, exclude=(), natures=None, canonical=(), note=""):
    return Concept(name, list(include), list(exclude), list(natures) if natures else None, list(canonical), note)


EST = r"(estimate|estimation|forecast|consensus|expected|projected|predict|smart ?est|fy1|fy2|forward|next (year|quarter)|\best\b|mean est)"

CONCEPTS: Dict[str, Concept] = {c.name: c for c in [
    # ------------------------------------------------------- price / volume
    _c("returns", [r"\bdaily returns?\b", r"^returns\b"], [r"specific|residual|idiosyncratic|forecast|expected"],
       canonical=["returns"], note="daily close-to-close return"),
    _c("close", [r"\bclose price\b", r"^close\b"], [r"option|bond|index|fx|future"], canonical=["close"]),
    _c("open", [r"\bopen(ing)? price\b", r"^open\b"], [r"option|interest"], canonical=["open"]),
    _c("high", [r"\bhigh price\b", r"^high\b"], [r"option|52"], canonical=["high"]),
    _c("low", [r"\blow price\b", r"^low\b"], [r"option|52"], canonical=["low"]),
    _c("vwap", [r"\bvwap\b", r"volume.weighted average price"], canonical=["vwap"]),
    _c("volume", [r"\btrading volume\b", r"^volume\b", r"daily volume"], [r"option|average|adv|news|search|post"],
       canonical=["volume"]),
    _c("adv", [r"\badv20\b", r"average daily (dollar )?volume"], canonical=["adv20"]),
    _c("cap", [r"\bmarket cap", r"^cap\b", r"market value of equity", r"\bmktcap\b"],
       [r"group|sector|industry|companies in|total market cap of companies|percentile|rank"],
       canonical=["cap"]),
    _c("sharesout", [r"shares outstanding", r"\bsharesout\b", r"outstanding shares"], [r"option|institution"],
       canonical=["sharesout"]),
    _c("specific_return", [r"specific (daily )?return", r"idiosyncratic.*return", r"residual.*return", r"\bspret\b"]),
    _c("beta", [r"\bbeta\b"], [r"\bbeta of (iwm|qqq|spy|vea|vwo|vt|mtum|qual|usmv|vlue|size)\b|etf|r-squared"]),
    _c("volatility", [r"\bvolatility\b", r"\bstd(ev)? of returns\b"], [r"implied|option|sector exposure|estimate"]),
    _c("specific_risk", [r"specific risk", r"idiosyncratic (risk|vol)", r"residual vol"]),
    # ------------------------------------------------------- fundamentals
    _c("sales", [r"\b(total )?revenues?\b", r"\b(net )?sales\b", r"\bturnover\b(?! ratio)"],
       [r"cost of|per share|estimate|estimation|forecast|growth|surprise|guidance|predict|projected|ratio|margin|%|percent|"
        r"to inventory|inventory turnover|asset turnover",
        r"receivable|share of|customer"], natures=["flow", "level"], canonical=["sales", "revenue"]),
    _c("cogs", [r"cost of (goods|revenue|sales)", r"\bcogs\b"], [r"estimate|forecast|ratio"], natures=["flow", "level"],
       canonical=["cogs"]),
    _c("gross_profit", [r"gross (profit|income)"], [r"margin|estimate|forecast|ratio|growth"], natures=["flow", "level"]),
    _c("operating_income", [r"operating (income|profit)", r"\bebit\b(?!da)", r"income from operations"],
       [r"margin|estimate|forecast|ratio|growth|per share|before extraordinary"], natures=["flow", "level"],
       canonical=["operating_income"]),
    _c("ebitda", [r"\bebitda\b"], [r"estimate|forecast|margin|ratio|growth|surprise|revis|analyst"], natures=["flow", "level"]),
    _c("net_income", [r"net income", r"income before extraordinary", r"\bnet (profit|earnings)\b"],
       [EST, r"margin|ratio|growth|per share|minority|noncontrolling|tax|highest|lowest|maximum|minimum|median|mean"],
       natures=["flow", "level"], canonical=["net_income", "income"]),
    _c("eps", [r"earnings per share", r"\beps\b"], [EST, r"surprise|growth|revision|analyst|guidance|std|dispersion"],
       natures=["flow", "ratio", "level"], canonical=["eps"]),
    _c("cfo", [r"cash flow from operations", r"operating cash flow", r"cash (flow )?from operating",
               r"net cash provided by operating", r"cash flows? from operating activities", r"\bcfo\b", r"cashflow.op"],
       [EST, r"per share|ratio|growth|chief financial|compensation|variab|other operating|volatil"],
       natures=["flow", "level"], canonical=["cashflow_op"]),
    _c("capex", [r"capital expenditure", r"\bcapex\b"], [EST, r"ratio|growth"], natures=["flow", "level"],
       canonical=["capex"]),
    _c("fcf", [r"free cash flow", r"\bfcf\b"], [r"yield|ratio|growth|" + EST], natures=["flow", "level"]),
    _c("assets", [r"total assets", r"^assets\b", r"\bassets ?- ?total\b"], [r"current|intangible|other|growth|return on|turnover|per share|" + EST],
       natures=["stock", "level"], canonical=["assets"]),
    _c("liabilities", [r"total liabilities", r"^liabilities\b"], [r"current|other|long.term|" + EST],
       natures=["stock", "level"], canonical=["liabilities"]),
    _c("debt", [r"total debt", r"long.term debt", r"\bdebt\b"], [r"ratio|to equity|rating|credit|yield|" + EST],
       natures=["stock", "level"], canonical=["debt", "debt_lt"]),
    _c("equity", [r"(total |common |shareholders.? |stockholders.? )equity", r"book value(?! per share)"],
       [r"return on|ratio|per share|reserves|" + EST], natures=["stock", "level"], canonical=["equity"]),
    _c("bvps", [r"book value per share", r"\bbvps\b"], [EST], natures=["ratio", "level"], canonical=["bookvalue_ps"]),
    _c("current_assets", [r"(total )?current assets"], [r"other|" + EST], natures=["stock", "level"],
       canonical=["assets_curr"]),
    _c("current_liabilities", [r"(total )?current liabilities"], [r"other|" + EST], natures=["stock", "level"],
       canonical=["liabilities_curr"]),
    _c("inventory", [r"\binventor(y|ies)\b"], [r"turnover|days|" + EST], natures=["stock", "level"], canonical=["inventory"]),
    _c("receivables", [r"\breceivables?\b"], [r"turnover|days|" + EST], natures=["stock", "level"], canonical=["receivable"]),
    _c("rnd", [r"research (and|&) development", r"\br&d\b", r"\brd expense"], [EST], natures=["flow", "level"]),
    _c("sga", [r"selling,? general", r"\bsg&a\b"], [EST], natures=["flow", "level"]),
    _c("dividend", [r"\bdividends? (per share|paid)\b", r"^dividend\b"], [r"yield|growth|payout|" + EST + r"|projected"],
       natures=["flow", "level"], canonical=["dividend"]),
    _c("enterprise_value", [r"enterprise value", r"\bev\b"], [r"to |/|ratio|multiple"], natures=["level", "stock"],
       canonical=["enterprise_value"]),
    _c("roe", [r"return on (common )?equity", r"\broe\b"], [EST], natures=["ratio", "level"]),
    _c("roa", [r"return on (total )?assets", r"\broa\b"], [EST], natures=["ratio", "level"]),
    # ------------------------------------------------------------ analyst
    _c("est_eps", [r"(eps|earnings per share|earnings).{0,40}" + EST, EST + r".{0,40}(eps|earnings per share)"],
       [r"std|standard deviation|dispersion|surprise|number of|count|revis|change|growth|high|low|previous|currency|"
        r"date|period|time|group|actual|class|trend|diffusion|probability|highest|lowest|maximum|minimum|\bnum"],
       natures=["estimate", "level", "ratio", "flow"],
       note="forward EPS estimate (consensus mean/median)"),
    _c("est_sales", [r"(revenue|sales).{0,40}" + EST, EST + r".{0,40}(revenue|sales)"],
       [r"std|standard deviation|dispersion|surprise|number of|count|revis|change|growth|currency|date|period|group"],
       natures=["estimate", "level", "flow"]),
    _c("est_ltg", [r"long.term growth", r"\bltg\b", r"(5|five|10).?year.{0,20}growth"],
       [r"actual|class|trend|probability|predicted|diffusion|\bcos\b|number of|companies|group"],
       natures=["estimate", "ratio", "level", "change"],
       note="analysts' long-term growth forecast"),
    _c("est_dispersion", [r"standard deviation of .{0,40}(estimate|forecast)", r"(estimate|forecast)s? .{0,20}(std|"
                          r"standard deviation|dispersion)", r"dispersion"], [r"price|return"],
       note="disagreement among analysts"),
    _c("num_estimates", [r"number of (estimates|analysts|forecasts|brokers)", r"analyst count", r"estimates count",
                         r"coverage count"], [r"up|down|raised|lowered|revis|group"]),
    _c("rev_up", [r"(revis(ed|ing)|raised|upgrad).{0,30}(up|estimate|forecast)", r"estimates? raised",
                  r"analysts? (count )?revising up", r"\bups?\b.{0,20}estimate", r"analysts? raising"], [r"down|lower|cut|group"]),
    _c("rev_down", [r"(revis(ed|ing)|lowered|downgrad).{0,30}(down|estimate|forecast)", r"estimates? lowered",
                    r"analysts? (count )?revising down", r"analysts? (lowering|cutting)"], [r"\bup\b|rais|upward|upgrad|group"]),
    _c("recommendation", [r"recommendation", r"analyst rating", r"buy/sell rating", r"\brating\b.{0,20}analyst"],
       [r"count|number|detail|date"], note="CHECK DIRECTION: in many vendors 1 = strong buy"),
    _c("target_price", [r"target price", r"price target"], [r"count|number|date|std"]),
    _c("surprise", [r"surprise", r"actual.{0,30}(minus|vs|versus|relative to).{0,30}(estimate|consensus|forecast|predicted)",
                    r"(earnings|eps|net (profit|income)).{0,40}surprise", r"surprise.{0,40}(earnings|eps|net (profit|income))"],
       [r"date|time|count|revenue|sales|ebitda|dividend"], note="earnings surprise"),
    _c("call_tone", [r"(earnings|conference) call", r"transcript", r"management (tone|discussion)"],
       [r"date|time|count|number of|credit|flag"], note="tone/sentiment of earnings calls"),
    _c("guidance", [r"guidance"], [r"date|count"]),
    # ------------------------------------------------------------ events
    _c("earnings_date", [r"(earnings|report(ing)?) (release |announcement )?date", r"announcement date",
                         r"days? (until|to|since) .{0,20}(earnings|announcement)"]),
    # ----------------------------------------------- sentiment / news
    _c("sentiment", [r"sentiment", r"\btone\b"], [r"std|standard deviation|dispersion|confidence|count|number|positive|negative|neutral"]),
    _c("sentiment_pos", [r"positive (sentiment|news|tone|posts?)", r"\bpos(itive)?\b.{0,20}sentiment"], [r"std|standard deviation|count|number"]),
    _c("sentiment_neg", [r"negative (sentiment|news|tone|posts?)", r"\bneg(ative)?\b.{0,20}sentiment"], [r"std|standard deviation|count|number"]),
    _c("sentiment_dispersion", [r"(std|standard deviation|dispersion).{0,30}sentiment", r"sentiment.{0,30}(std|dispersion)"]),
    _c("news_volume", [r"\bbuzz\b", r"number of (news|stories|articles|posts|mentions)", r"news (count|volume)",
                       r"(story|article|post) count", r"attention"]),
    # ------------------------------------------- positioning / ownership
    _c("short_interest", [r"short interest", r"shares (sold )?short", r"short ratio", r"days to cover",
                          r"securities lending", r"short.?sale", r"lendable"], [r"squeeze|volatility|borrowings|term borrow"]),
    _c("inst_ownership", [r"institutional (ownership|holdings?|investors?)", r"held by .{0,20}institution",
                          r"shares held by (all )?institutional"], [r"count|number of|bought|sold|acquired|disposed|purchased"]),
    _c("inst_buyers", [r"institutional investors who purchased", r"institutional buyers", r"(shares|value).{0,40}(acquired|purchased) by institutional",
                       r"count_institutional_buyers"]),
    _c("inst_sellers", [r"institutional investors who sold", r"institutional sellers", r"(shares|value).{0,40}(disposed|sold) by institutional",
                        r"count_institutional_sellers"]),
    _c("inst_holders", [r"number of institutional (investors|holders)", r"institutional holders", r"count_institutional_holders"]),
    _c("insider_buy", [r"(shares|value)? ?bought by .{0,20}(director|executive|insider|officer)", r"insider (buy|purchase)",
                       r"total_buy_shares"], [r"mean|average|avg"]),
    _c("insider_sell", [r"(shares|value)? ?sold by .{0,20}(director|executive|insider|officer)", r"insider (sell|sale)",
                        r"total_sell_shares"], [r"mean|average|avg"]),
    # --------------------------------------------------------- options
    _c("implied_vol", [r"implied volatility", r"\bimpvol"], [r"put|call|skew|spread|term|surface|realized|historical|probability|quantile|label|confidence|bucket"]),
    _c("implied_vol_call", [r"call.{0,30}implied volatility", r"implied volatility.{0,30}call"]),
    _c("implied_vol_put", [r"put.{0,30}implied volatility", r"implied volatility.{0,30}put"]),
    _c("iv_skew", [r"(volatility )?skew", r"smirk"]),
    _c("put_call", [r"put.?call ratio", r"put.?to.?call", r"put (volume|open interest)"]),
    _c("realized_vol", [r"realized volatility", r"historical volatility", r"trailing.{0,20}realized"]),
    # ---------------------------------------------------- vendor models
    _c("value_score", [r"\bvaluation\b", r"\bvalue (score|rank|model)", r"intrinsic value", r"relative valuation", r"cheap"],
       [r"momentum"], natures=["rank_score", "ratio", "level"]),
    _c("quality_score", [r"\bquality\b", r"earnings quality", r"accrual", r"piotroski"], natures=["rank_score", "level", "ratio"]),
    _c("momentum_score", [r"momentum (score|rank|model|percentile)", r"price momentum"], natures=["rank_score", "level"]),
    _c("revision_score", [r"revision (score|model|percentile|component)", r"estimate revision"], natures=["rank_score", "level", "change"]),
    _c("credit_risk", [r"credit (risk|score|rating)", r"default (risk|probability)", r"distance to default", r"structural credit"]),
    _c("dividend_score", [r"dividend (score|model|prediction|alpha)", r"income score"]),
    # 1.5.0: concept gaps found in the theme-dataset shortlists (HANDOFF "Theme datasets")
    _c("pretax_income", [r"pre.?tax (income|profit|earnings)", r"income before (income )?tax", r"\bebt\b",
                         r"earnings before tax"], [r"margin|ratio|growth|per share|" + EST], natures=["flow", "level"],
       note="pre-tax (book) income; with income_tax it gives the effective tax rate / book-tax gap"),
    _c("income_tax", [r"income tax(es)? (expense|paid|provision)", r"provision for (income )?tax", r"\btax expense\b",
                      r"taxes paid", r"current tax", r"deferred tax", r"effective tax rate", r"\btaxable income\b"],
       [r"before|pre.?tax|net of tax|after.?tax|" + EST],
       note="tax expense, taxes paid, deferred tax or tax rate (book-tax differences, tax avoidance)"),
    _c("esg_score", [r"\besg\b", r"environmental,? social", r"sustainab", r"\bcarbon\b", r"emission", r"governance score",
                     r"controvers"], [r"date|count of reports|currency"],
       note="ESG / sustainability / carbon / controversy scores (direction differs by vendor: check it)"),
    _c("credit_spread", [r"credit spread", r"(bond|cds|yield|option.adjusted|z.)\s?spread", r"credit default swap",
                         r"\bcds\b"], [r"bid.ask|date|count|notional|contract|\bleg\b|leg ?\d|amount"],
       note="the firm's bond or CDS spread: what the credit market charges for its risk"),
    _c("management_change", [r"(ceo|cfo|chief executive|chief financial|executive|officer|director|board|management) "
                             r"(change|turnover|departure|appointment|resignation|hire|tenure|succession)",
                             r"(new|incoming|outgoing) (ceo|cfo|chief executive|management)",
                             r"(executive|management|board) (compensation|pay|ownership|age|experience)"],
       [r"insider (buy|sell|purchase|sale)|bought|sold"],
       note="management and executive data: changes, tenure, pay (Management and Executive datasets)"),
    _c("predicted_return", [r"predicted return", r"return prediction", r"expected return", r"alpha score", r"forecast(ed)? return"]),
    _c("vendor_score", [r"\bscore\b", r"percentile", r"\brank\b", r"\bsignal\b", r"composite", r"model (output|rank)"],
       [r"sector exposure|industry exposure|constituent|weight in|count|number of|date|currency|probability that|class"],
       natures=["rank_score", "level", "ratio", "estimate", "change"],
       note="any finished vendor score/rank (model datasets)"),
    _c("order_imbalance", [r"imbalance", r"buy.?sell (pressure|ratio|volume)", r"order flow", r"auction (volume|imbalance)"],
       [r"date|time|count of exchanges"], note="order/auction imbalance - temporary price pressure"),
    _c("relationship_group", [r"relationship", r"supply chain", r"customer", r"supplier", r"competitor", r"peer",
                              r"cluster", r"network", r"statistical(ly)? (industry|defined|cluster)", r"pca"],
       note="a GROUP field linking economically related firms"),
    # ------------------------------------------------------------- macro
    _c("macro_series", [r"\b(inflation|interest rate|yield curve|gdp|unemployment|pmi|cpi|treasury|fx rate|exchange rate|"
                        r"oil|commodity)\b"], note="market-level series: same value for every stock"),
    _c("rate_sensitivity", [r"sensitivity to (the )?(interest rate|inflation)", r"(interest rate|inflation) (beta|sensitivity)"]),
]}


@dataclass
class ConceptMatch:
    field_id: str
    concept: str
    strength: float
    reason: str


def match_concepts(field_id: str, description: str, nature: Optional[str] = None,
                   concepts: Optional[Sequence[str]] = None) -> List[ConceptMatch]:
    """All concepts a field plausibly represents (strongest first)."""
    out: List[ConceptMatch] = []
    for name in (concepts or CONCEPTS):
        c = CONCEPTS[name]
        s, why = c.match(field_id, description)
        if s <= 0:
            continue
        if nature in NON_NUMERIC and name not in ("earnings_date",):
            continue
        if c.natures and nature and nature not in c.natures:
            s *= 0.5     # weaker match when the nature looks wrong
        out.append(ConceptMatch(field_id, name, s, why))
    out.sort(key=lambda m: -m.strength)
    return out


# ------------------------------------------------------------- direction

_POS = [r"higher (is|=|means) better", r"higher = better", r"higher scores? (indicate|mean|=) (better|more attractive|"
        r"undervalu|stronger|positive)", r"upgrade", r"raised", r"revising up", r"\bbuy(s|ers|ing)?\b", r"bought",
        r"purchas", r"acquired", r"positive"]
_NEG = [r"lower (is|=|means) better", r"lower = better", r"lower .{0,40}(indicat|mean).{0,20}(better|undervalu|cheap)",
        r"higher .{0,20}(more risk|riskier|worse|overvalu)", r"downgrade", r"lowered", r"revising down",
        r"\bsell(s|ers|ing)?\b", r"\bsold\b", r"disposed", r"negative", r"short interest", r"shorted",
        r"days to cover", r"volatility", r"dispersion", r"standard deviation", r"uncertainty", r"default", r"distress"]


def direction_hint(field_id: str, description: str) -> Tuple[int, str]:
    """Best guess of the field's relationship with FUTURE returns.

    +1 = higher value should predict higher returns, -1 = lower, 0 = unknown.
    This is a *prior from the text*, not evidence - the hypothesis card states
    the economic sign and the first simulation tests it.
    """
    text = f"{field_id.replace('_', ' ')} {(description or '').lower()}"
    pos = [p for p in _POS if re.search(p, text)]
    neg = [p for p in _NEG if re.search(p, text)]
    if pos and not neg:
        return 1, f"description suggests higher is better (/{pos[0]}/)"
    if neg and not pos:
        return -1, f"description suggests higher is worse (/{neg[0]}/)"
    return 0, "direction not stated - decide from the economics, then verify once"
