---
name: trader-entry
description: >-
  Entry Timer for NSE/BSE day trades. Watches a setup bar by bar and tells you the moment to
  get in: an opening-range breakout (the first 5-minute bar after the 9:15 to 9:30 IST range
  that CLOSES above the range high) or the first close above a level, with an optional volume
  filter. Says triggered, waiting, expired (after no_entries_after, 14:45 IST by default) or
  no data, knows NSE holidays and the Muhurat special session, and writes trader/entry.json
  for trader-exit. Free Yahoo bars, never tick by tick. Use when the user says "when do I get
  in", "has RELIANCE broken out", "watch TCS for the breakout", "entry timing", "tell me the
  moment", or after /trader-scanner and /trader-news.
argument-hint: "check|watch|watchlist SYMBOL [--setup orb|level]"
---

# trader-entry (NSE/BSE)

The Entry Timer watches one setup and says, bar by bar, whether it has triggered. A trigger is
a rule that fired on a closed bar, not a prediction and not a recommendation.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE                       # orb, 5-minute bars
python3 "${CLAUDE_SKILL_DIR}/entry.py" check RELIANCE --now "2026-11-02 10:00" --write
python3 "${CLAUDE_SKILL_DIR}/entry.py" check TCS --setup level --level 2537.00
python3 "${CLAUDE_SKILL_DIR}/entry.py" check INFY --interval 1m --min-volume-x 1.5
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch RELIANCE --every 30 --until 14:45
python3 "${CLAUDE_SKILL_DIR}/entry.py" watchlist                            # every hit in trader/watchlist.json
```

## The rules

- **orb**: the range is the high and low of the first `--or-minutes` (15): the 9:15, 9:20 and
  9:25 bars. It triggers on the first COMPLETED bar after the range that CLOSES above the range
  high. A wick above the high is not a trigger. The 9:15 bar carries the pre-open auction's
  volume, so a `--min-volume-x 1.0` filter is already demanding.
- **level**: the first completed bar that closes above `--level`.
- A trigger's time is the bar's CLOSE time (the 9:30 bar closes at 9:35 AM) and its price is
  that close. A bar counts once it has closed and Yahoo has posted it.
- **Window**: no trigger counts before `no_entries_before` (09:30) or after `no_entries_after`
  (14:45) in `trader/config.json`. Brokers square off intraday (MIS) positions from about
  15:15 to 15:25, so late entries have no room. On the Muhurat session (Sun 2026-11-08,
  14:20 to 15:30 IST) the window keeps its distance from the open and close: 14:35 to 14:45.
- **Calendar**: NSE 2026 holidays (NSE circular NSE/CMTR/71775 plus 15 January) and Muhurat
  (NSE circular NSE/CMTR/76941). On a holiday it says closed and gives the next open.

It writes `trader/entry.json` (`--write`, or on a `watch` trigger): symbol, setup, status,
time, bar, price, level, opening range, IST stamp. trader-exit reads it.

## Example (real data, Mon 2 Nov 2026)

```
RELIANCE  Mon 2026-11-02 10:00 IST  opening-range breakout (15-minute range) on 5-minute bars (Yahoo, free, can lag)
Opening range 9:15-9:30: high ₹1231.60, low ₹1214.60 (3 of 3 bars).
TRIGGERED 9:35 AM at ₹1234.50: the 9:30 bar (bar 3) closed above the range high ₹1231.60 (+0.24%).
```

At 9:27 the same check said RANGE FORMING (2 of 3 bars closed). A later look is a different
trade: the price, the stop distance and the odds have moved.

## Steps

1. `check SYMBOL` once; if waiting, `watch SYMBOL` (one line per closed bar) or a scheduled check.
2. On a trigger, say the time, the price and the range, then hand on to `/trader-exit`
   (the stop and target are set BEFORE buying). Nothing is placed here.
3. On expiry, say so plainly: no entry on this setup today.

## Rules

- Quote the IST bar time and the close. Never say "buy now"; say the rule fired.
- Free Yahoo data lags and is not tick by tick: check the broker's price before any order.
- Circuit limits: a stock at its upper band may not be buyable at the trigger price.

## What it never does

It never places, sizes or checks an order and never promises that a breakout works.

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
