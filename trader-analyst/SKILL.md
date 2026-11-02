---
name: trader-analyst
description: >-
  Results Analyst for Indian listed companies. Reads quarterly results and sums up what
  changed: revenue from operations, net profit, profit to owners, basic EPS and net margin,
  with QoQ and YoY growth, in ₹ crore. Reads NSE's integrated-filing XBRL (consolidated by
  default, standalone on request), falls back to Yahoo Finance's fundamentals time series, and
  says when Yahoo lags the exchange filing. Use when the user says "Q2 results of RELIANCE",
  "what changed in TCS results", "quarterly numbers", "EPS growth", "profit badha ya ghata",
  "results analysis", or before trading a stock that just reported.
argument-hint: "SYMBOL [SYMBOL ...] [--quarters 5] [--standalone]"
---

# trader-analyst (NSE/BSE)

The Results Analyst reads what a company reported and lays the quarters side by side. Numbers
only: it never says whether a stock is a buy.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE TCS --quarters 5
python3 "${CLAUDE_SKILL_DIR}/facts.py" INFY --standalone
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE --source yahoo
python3 "${CLAUDE_SKILL_DIR}/facts.py" RELIANCE TCS --metrics trader/metrics.json
```

## Sources, best first

1. **NSE integrated filings** (SEBI's XBRL taxonomy, filed with every quarterly result):
   `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=<SYM>&period_ended=all&type=Integrated%20Filing-%20Financials`,
   then each quarter's XBRL file on nsearchives.nseindia.com. The quarter is the context
   covering about three months; fields `RevenueFromOperations`, `Expenses`, `ProfitBeforeTax`,
   `ProfitLossForPeriod`, `ProfitOrLossAttributableToOwnersOfParent`,
   `BasicEarningsLossPerShare...`. A revised filing of the same quarter is skipped.
2. **Yahoo Finance fundamentals time series** (no key):
   `https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/<SYM>.NS?type=quarterlyTotalRevenue,quarterlyNetIncome,...`.
   It was a quarter behind NSE and skipped a quarter for RELIANCE on 2026-11-02; a QoQ across a
   gap is left blank. Yahoo's quoteSummary endpoint now needs a cookie crumb, so it is not used.

If NSE refuses the script, the tool says so and uses Yahoo; if both fail it says so. It
degrades, it does not guess.

## Example (real data, RELIANCE, consolidated, read 2026-11-02)

```
quarter end      revenue      QoQ      YoY  net profit      YoY   to owners      EPS EPS YoY margin
2026-09-30       332,861    +6.7%   +28.6%      29,550   +33.8%      25,548    18.88  +40.7%   8.9%
2026-06-30       311,850    +4.4%        -      23,196        -      20,946    15.48       -   7.4%
What changed: revenue +28.6% YoY; net profit +33.8% YoY; basic EPS +40.7% YoY; net margin 8.9% (7.4%).
Filed with NSE 30-Oct-2026 21:32:55 IST (Un-Audited).
NOTE: Yahoo's latest quarter is 2026-06-30, behind NSE's 2026-09-30.
```

## Steps

1. Run it for the symbol. Say the latest quarter's end date and when it was filed.
2. Say what changed in growth and margin terms, and which basis (consolidated or standalone).
3. A results day is a gap-risk day for a day trade; say so if results are due or just out.

## What it never does

It never places, sizes or checks an order and never calls results good or bad for the price.

## Safety

- Not financial advice. A PASS from trader-risk is a rules check, not a recommendation.
- Paper trading is the default (`"mode": "paper"`). Live trading through Angel One SmartAPI is
  the user's own decision, made in their own `trader/config.json` (`"mode": "live"`), and the
  live adapter is UNVERIFIED (built from the public docs, tested only against mocked answers).
- Nothing in this pack places an order except trader-broker, and only when trader-risk passed
  THAT exact order today (same fingerprint), the kill switch is off, and the user typed an
  explicit yes for that one order in the chat (live: `yes SYMBOL`). Never "yes to all".
- The risk and budget limits always block: max loss per trade (charges included), the daily
  max-loss kill switch, trades per day, the entry window, cash with no MIS leverage.
- No short selling, F&O, options or margin unless the config allows it and the user confirms.
- Broker credentials live in environment variables or a local file the user fills in
  (`trader/secrets/angel.json`), never in the chat, never in a repo, never printed.

## SEBI disclaimer

- **Educational only, not investment advice.** This is software that reads public data
  and does arithmetic. It does not know your situation and cannot see the future.
- **Not a SEBI-registered adviser.** Neither the authors nor this skill are a SEBI-registered
  Investment Adviser or Research Analyst. Nothing here is a recommendation to buy or sell.
- **Most intraday traders lose money.** SEBI's study of individual intraday traders in the
  equity cash segment found that 7 out of 10 (71%) made net losses in FY 2022-23
  (SEBI press release PR No. 13/2024, 24 July 2024:
  https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818619980.pdf). You can lose money.
