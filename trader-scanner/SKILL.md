---
name: trader-scanner
description: >-
  Chart Scanner for Indian stocks (NSE/BSE). Scans thousands of charts for setups:
  opening-range breakouts, bull flags, oversold bounces. Builds the list of NSE EQ-series
  stocks from NSE's EQUITY_L.csv (with a bundled NIFTY 100 fallback), runs a pre-market scan
  of daily closes (20-day closing-high breakout, bull flag, reclaimed the 20-day average,
  oversold, oversold bounce) and an intraday opening-range breakout scan on 5-minute bars
  from 9:15 IST, then writes trader/watchlist.json for trader-news and trader-entry. Free
  Yahoo data (.NS / .BO symbols, ^NSEI, ^BSESN), bar by bar. Use when the user says "scan
  the market", "scan NIFTY", "find me setups", "what is breaking out", "opening range
  breakouts", "scan for bull flags", "oversold stocks", "pre-market scan", "build my
  watchlist", "aaj kya dekhu", or at the start of an Indian trading day before /trader-news.
argument-hint: "[universe | daily | orb] [--at HH:MM]"
---

# trader-scanner (NSE/BSE)

The Chart Scanner is the first step of a day trade. It reads thousands of free charts and
lists the ones that match a rule. That is all it does. A scan is a list of charts that match
a rule, not a list of stocks to buy, and a setup on a chart is not a prediction. Most
individual intraday traders in India lose money (SEBI: 7 in 10 in FY 2022-23); the scanner
does not change that.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                          # -> trader/universe.txt
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                             # before 9:15 IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --symbols RELIANCE,TCS,INFY # or --watchlist FILE, --limit 200
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily --watchlist "${CLAUDE_SKILL_DIR}/nifty100.csv"
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                               # after 9:35 IST -> trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 10:00                    # cut the clock at 10:00 IST
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --watchlist trader/watchlist.json --json
```

Symbols: `RELIANCE` means NSE (Yahoo `RELIANCE.NS`), `RELIANCE.BO` is BSE, `^NSEI` is the
NIFTY 50 and `^BSESN` the SENSEX. Symbols with `&` or `-` (M&M, BAJAJ-AUTO) work.

Flags: `--min-price 50` (rupees) and `--min-volume` (daily 200,000 shares, orb 0),
`--or-minutes 15`, `--max-confirm 200`, `--max-missing 3`, `--now "2026-11-02 10:00"` (IST)
to pin the clock, `--offline PATH`, `--no-write`, `--show N`, `--json`. Exit code 0 when the
scan found something, 1 when it found nothing or could not run (the reason is one plain line).

## What it reads and writes

| file | what |
| --- | --- |
| `trader/universe.txt` | written by `universe`: one `SYMBOL\|Name` a line, read by `daily` and `orb` |
| `trader/watchlist.json` | written by `daily` and `orb`: `mode`, `as_of`, `universe`, `scanned`, `failed`, `hits[]` |
| `trader/config.json` | read by `orb`: `no_entries_after` (default 14:45 IST) |
| `nifty100.csv` | bundled: the NIFTY 100 (and which are NIFTY 50), from niftyindices.com, read 2026-11-02 |

## The universe

`universe` downloads https://archives.nseindia.com/content/equities/EQUITY_L.csv (NSE only
answers a browser User-Agent, which the tool sends) and keeps the `EQ` series: only EQ can be
traded intraday; `BE` and `BZ` are trade-for-trade (delivery only). `--series EQ,BE` widens it.
On 2026-11-02 the file had 2,635 rows: 2,365 EQ kept, 228 BE and 42 BZ dropped. When NSE
cannot be reached it says so and writes the bundled NIFTY 100 list instead (`--no-fallback`
to fail instead).

## The daily scan (before the open)

Yahoo's spark endpoint returns closes for 20 symbols a request, so 2,365 symbols take 119
requests. Liquidity comes from the spark meta: last price at least `--min-price` and the last
session's volume at least `--min-volume`. Run it before 9:15 IST or after 15:30: during the
session today's daily bar is left out.

| setup | the rule on closes |
| --- | --- |
| `breakout_20d` | the last close is above every close of the 20 sessions before it |
| `bull_flag` | up more than 10 % over the 10 sessions before the last 5, then the last 5 closes inside a 5 % range |
| `reclaim_ma20` | the close before was under its 20-day average, the last close is above it |
| `oversold` | RSI 14 (Wilder) under 30 |
| `oversold_bounce` | RSI 14 was under 30 yesterday and today closed up |

## The opening-range breakout scan (during the session)

NSE's continuous session runs 9:15 to 15:30 IST, after the 9:00 to 9:08 pre-open order
entry (the auction matches by 9:15). The opening range is the first `--or-minutes` (15): the
9:15, 9:20 and 9:25 five-minute bars. A hit is the first completed 5-minute bar to CLOSE above
the range high, at that bar's close time.

1. Stage 1, every symbol: spark closes of today's 5-minute bars. A chart goes on only if a
   completed bar after the range closed at or above the highest close of the range.
2. Stage 2, each candidate: the v8 chart with real highs and lows. At most `--max-confirm`
   (200), the most traded first; PARTIAL with the count it skipped.

A chart is usable when every opening-range bar is there and at most `--max-missing` (3)
later bars are missing: Yahoo leaves gaps in thinner Indian charts, and a long gap can mean a
circuit freeze. Before 9:35 IST, on a weekend or NSE holiday, after the close, or after
`no_entries_after` it prints one plain line and writes nothing.

## Calendar

NSE trading holidays 2026 (NSE circular NSE/CMTR/71775 of 2025-12-12, plus the 15 January
Maharashtra municipal election holiday; list as on https://www.niftyindices.com/resources/holiday-calendar,
read 2026-11-02): 15 Jan, 26 Jan, 3 Mar, 26 Mar, 31 Mar, 3 Apr, 14 Apr, 1 May, 28 May, 26 Jun,
14 Sep, 2 Oct, 20 Oct, 10 Nov, 24 Nov, 25 Dec. Muhurat trading: Sunday 2026-11-08, normal
market 14:20 to 15:30 IST (pre-open 14:05 to 14:20), NSE circular NSE/CMTR/76941 of
2026-10-19 (https://archives.nseindia.com/content/circulars/CMTR76941.pdf). On Muhurat day the
opening range starts at 14:20.

## Example (real data, Mon 2 Nov 2026)

```
python3 scan.py orb --offline nifty50-5m-2026-11-02.json.gz --now "2026-11-02 10:00" --min-price 0
Fetched 50 of 50 charts; 50 usable; 35 candidates, 35 confirmed with real highs and lows.
19 of 50 charts closed above their opening-range high by 10:00 AM:
   9:35 AM  RELIANCE        ₹1,234.50  range 1,214.60 to 1,231.60  +0.24% over
```

RELIANCE's range is the 9:15 to 9:25 bars, high 1231.60, low 1214.60; the 9:30 bar closed at
1234.50, 0.24 % over the high, at 9:35 AM. Live over the NIFTY 100 (re-run that evening with
`--now "2026-11-02 10:00"`): 41 of 100 usable charts had broken their range by 10:00. The user picks one chart; Claude hands it to
`/trader-news RELIANCE`, then `/trader-entry RELIANCE`.

## Steps

1. Once a week or so: `scan.py universe`.
2. Before 9:15 IST: `scan.py daily`. Tell the user the counts and the top few by setup.
3. After 9:35 IST (10:00 is a good default): `scan.py orb`. Say how many usable charts broke
   their range and when, and that a later hit is closer to the price now.
4. The user picks one chart. Hand it on: `/trader-news SYMBOL`, then `/trader-entry SYMBOL`.
   Never pick for them.

## Rules

- Say what was scanned: how many symbols, how many charts came back, how many were usable,
  and the time of the data (IST).
- Say "matched a rule", never "a buy", "a winner" or "a good trade".
- Never print a P&L, a return or a profit figure. A hit is stale once the price has moved on.
- Remember the circuit limits: a stock frozen at its band can show a "breakout" you cannot buy.

## What it never does

It never places, sizes or checks an order, never says which stock to buy, never calls the
data real time, and never promises that a setup works.

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
