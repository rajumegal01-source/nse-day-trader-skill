---
name: trader-timemachine
description: >-
  Time Machine for NSE/BSE day trades. Replays every possible outcome of a planned trade before
  you risk a rupee: 10,000 simulated runs of the rest of the session from your entry, each
  5-minute bar drawn from the stock's own bars at that time of day over its last 60 days
  (9:15 to 15:30 IST sessions), plus the same opening-range rule re-run on every one of those
  real sessions. Reports target first, stop first, neither, the price at the close, average R
  and a plain verdict ("close to a coin flip"). Same seed, same numbers. Use when the user says
  "what are the odds", "replay this trade", "backtest this setup", "time machine", "simulate",
  "kitne chance hain", or after /trader-exit and before /trader-budget.
argument-hint: "run [--until 15:10] [--seed 19] | chart"
---

# trader-timemachine (NSE/BSE)

Before you risk a rupee, the Time Machine replays the rest of the session 10,000 times from
the stock's own recent bars, and re-runs the same rule on every past day in the data. It is a
reality check, not a prediction: results, news, circuit limits and halts can do what the last
60 days never did.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                     # trader/plan.json, 10,000 replays, seed 19
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --until 15:10 --write   # stop each replay at your flat-by
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol RELIANCE --date 2026-11-02 --entry 1234.50 \
    --stop 1223.10 --target 1245.90 --entry-time "9:35 AM"
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart                   # ASCII fan chart
```

## How it works

1. One request for 60 days of 5-minute bars (Yahoo v8 chart, `<SYM>.NS`, range=60d). Keep the
   FULL sessions before the plan's date: 75 bars, 9:15 to 15:30 IST. Yahoo leaves a few empty
   bars in Indian charts; a past session with at most 3 empty bars keeps them as flat bars at
   the previous close, one with more is left out. The Muhurat session is never used, and a plan
   for Muhurat day is refused (70 minutes, nothing like it to replay from).
2. The pool: for every bar slot 1..74, each past session's bar as ratios to the previous close.
3. One replay walks the rest of the session; each bar is a random past bar from a nearby slot
   (+-2 bars), scaled to the current price. The stop is checked before the target in every bar
   (the conservative call).
4. Outcomes: target first, stop first, or neither (still open at `--until`, default 15:30;
   use `--until 15:10` to match an MIS trade's flat-by). R: +target R, -1, or the price at
   --until minus the entry over the risk. Costs are NOT in R: trader-budget counts them.
5. History: the plan's own rule (same opening range, stop rule and target R) re-run on every
   past full session.
6. Verdict: target / (target + stop) against break-even 1 / (1 + R): under 5 points "close to a
   coin flip", 5 to 15 "leans", 15+ "strongly".

## Example (real data, RELIANCE, Mon 2 Nov 2026, seed 19)

```
RELIANCE buy: entry 1234.50 at 9:35 AM (bar 3), stop 1223.10, target 1245.90 (1R, risk 11.40 a share).
10,000 replays, 9:35 AM to 3:30 PM (71 five-minute bars), from its last 59 full sessions (2026-08-06 to 2026-10-30).
  target first   30.9 %      stop first   34.1 %      neither   35.0 %
History: the same rule on those 59 real sessions fired 31 times: 14 target, 12 stop, 5 neither.
Close to a coin flip.
```

With the 2R target and `--until 15:10` the same entry hit the target first in only 4.3 % of
replays (stop first 32.1 %, neither 63.6 %): a further target is rarer, not free money.

## Steps

1. After trader-exit: `timemachine.py run --until <flat_by> --write`.
2. Say the three shares, the history line and the verdict, in that order, and the seed.
3. Say plainly that it is a simulation from 60 days of bars, not a forecast, and that charges
   make every outcome a little worse.
4. Hand on to `/trader-budget`.

## What it never does

It never places, sizes or checks an order and never calls a trade a good bet.

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
