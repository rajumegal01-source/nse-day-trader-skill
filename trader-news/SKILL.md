---
name: trader-news
description: >-
  News Monitor for Indian stocks. Tracks breaking news on every NSE/BSE stock you watch and
  flags what moves it: Google News RSS (India edition) and Yahoo Finance RSS headlines, NSE
  corporate announcements (results, board meetings, orders, pledges, acquisitions) when NSE
  answers, and each stock's move against yesterday's close. Prints only what is new since the
  last check, newest first, in IST, tagged (results, analyst, deal, order, capital, people,
  regulatory, risk, promoter, macro). Use when the user says "news on RELIANCE", "what is
  moving TCS", "any results today", "check the headlines", "corporate announcements", "why is
  this stock up", or after /trader-scanner and before /trader-entry.
argument-hint: "[--tickers SYM ...] [--hours N] [--all]"
---

# trader-news (NSE/BSE)

The News Monitor reads free public feeds for the symbols you watch and tells you what is new.
A headline is a lead, not a fact: open the story or the exchange filing before acting on it.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                                   # watchlist + plan + portfolio
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE TCS INFY
python3 "${CLAUDE_SKILL_DIR}/news.py" --tickers RELIANCE --all --hours 72  # seen items too, 3 days
python3 "${CLAUDE_SKILL_DIR}/news.py" --no-nse                          # headlines only
python3 "${CLAUDE_SKILL_DIR}/news.py" --max-per 3 --json
```

## Sources

| source | URL | notes |
| --- | --- | --- |
| Google News RSS (India) | `https://news.google.com/rss/search?q=<company> share&hl=en-IN&gl=IN&ceid=IN:en` | searched by company name from `trader/universe.txt`, else the symbol |
| Yahoo Finance RSS | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=<SYM>.NS&region=IN&lang=en-IN` | often empty for Indian symbols; kept as a second source |
| NSE corporate announcements | `https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=<SYM>&from_date=..&to_date=..` | exchange filings with the PDF link; NSE answers browsers only and may refuse a script, then the tool says so |
| the move | `https://query2.finance.yahoo.com/v8/finance/chart/<SYM>.NS?range=1d&interval=5m` | last price vs yesterday's close, MOVING at 3 % or more |

An exchange filing marked `!` is one that usually matters: financial results, board meeting
outcomes, acquisitions, schemes of arrangement, resignations, defaults, credit ratings,
pledges, buybacks, dividends, bonuses, splits and order wins. Filings always show; headlines
are capped at `--max-per` (8) per symbol. State in `trader/state/news.json` (30 days) so an
item shows once. `--offline DIR` reads `google-<SYM>.xml`, `yahoo-<SYM>.xml`, `nse-<SYM>.json`
and `chart-<SYM>.json`.

## Example (live, Mon 2 Nov 2026)

```
RELIANCE   1,300.00 +11.60% vs yesterday's close 1,164.90 at 15:29 IST  MOVING
  2026-11-02 18:31 IST  RELIANCE  Multibagg AI via Google News  Reliance Industries Ltd Q2 profit rises 33.8% to ₹29,550 crore
! 2026-11-01 23:09 IST  RELIANCE  NSE filing  Analysts/Institutional Investor Meet/Con. Call Updates: Transcript ...
```

## Steps

1. Run it for the scanner's hits or the symbol the user picked.
2. Say the move first (MOVING or not), then the new exchange filings, then the headlines.
3. Results or a board meeting today mean a gap risk: a day trade is out by the close, but an
   announcement during market hours can move the price through any stop.
4. Hand on to `/trader-entry SYMBOL`. Never call a headline good or bad for the price.

## Rules

- Say where each item came from and its time in IST. Quote, do not paraphrase into a claim.
- If NSE refused the script, say the filings were not checked; do not imply there were none.
- Never turn a headline into a recommendation.

## What it never does

It never places, sizes or checks an order, and never says whether to buy.

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
