---
name: trader-exit
description: >-
  Exit Planner for NSE/BSE day trades. Sets your stop and your target BEFORE you enter, so you
  know when to get out: stop at the opening-range midpoint or low, a price, a percent or an ATR
  multiple; target at 1R, 1.5R, 2R or a price; snapped to the stock's tick size; flat by
  15:10 IST, before the broker's intraday (MIS) auto square-off. Refuses stops on the wrong
  side, risk too tight for the spread, shorts and untriggered entries. Writes trader/plan.json
  for trader-timemachine, trader-budget and trader-alerts. Use when the user says "where do I
  put my stop", "set a target", "stop loss kahan lagau", "plan the exit", "risk reward", or
  right after /trader-entry triggers.
argument-hint: "plan [--stop or-mid|or-low|price:X|pct:X|atr:K] [--target 2R|price:X]"
---

# trader-exit (NSE/BSE)

The Exit Planner decides the way out before the way in: the price that proves the trade wrong
(the stop), the price you take profit at (the target) and the time you are out regardless
(flat by). A stop is a plan, not a guarantee: a gap, a circuit freeze or a fast market can
fill past it.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                                     # from trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-mid --target 2R --tick 0.10 --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol RELIANCE --entry 1234.50 --or-high 1231.60 --or-low 1214.60
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5 --offline RELIANCE.json
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol TCS --entry 2538.50 --setup level --stop pct:1
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

## The rules

| stop | how |
| --- | --- |
| `or-mid` | the opening-range midpoint (default for an orb entry) |
| `or-low` | the opening-range low |
| `price:X` / `pct:X` | your price / X percent under the entry |
| `atr:K` | K times the 14-bar ATR under the entry (the session's bars up to the entry bar) |

A long's stop rounds DOWN to the tick, away from the entry; the target rounds half up to the
tick. Targets: `2R` (default), `1R`, `1.5R` (entry + R x risk) or `price:X`.

**Tick size.** NSE sets the tick by price band. Pass `--tick` or set `"tick_size"` (default
0.05) or `"tick_sizes": {"RELIANCE": 0.10}` in `trader/config.json`. Angel One's instrument
master listed RELIANCE at a 0.10 tick and SBIN at 0.05 on 2026-11-02; trader-broker checks
the tick again against that master before a live order.

**Flat by** 15:10 IST by default (`"flat_by"`): out by then, win or lose. Indian brokers
square off MIS positions on their own from about 15:15 to 15:25, usually with a fee. On the
Muhurat session (Sun 2026-11-08, 14:20 to 15:30 IST) a flat-by outside the session moves to
20 minutes before its close.

**Costs** are not in the plan: trader-budget adds brokerage, STT, exchange charges, GST and
stamp duty, and checks the reward:risk after them. A 1R target never clears the costs.

Refused, with the reason: a stop at or above the entry, a target at or below it, a risk under
0.05 % of the price, an entry.json that has not triggered (unless `--entry`), a short.

## Example (real data, Mon 2 Nov 2026)

```
Exit plan: RELIANCE long, Mon 2026-11-02, opening-range breakout on 5-minute bars
  Entry         ₹1,234.50 at 9:35 AM (bar 3)
  Stop          ₹1,223.10  opening-range midpoint: (₹1,231.60 + ₹1,214.60) / 2 = ₹1223.1
  Target        ₹1,257.30  2R (two times the risk)
  Risk a share  ₹11.40 (0.92% of the entry)
  Reward:risk   2.0
  Flat by       15:10 IST, win or lose: no overnight hold (before the broker's MIS square-off)
```

## Steps

1. Right after trader-entry triggers: `exit.py plan --write` (default or-mid stop, 2R).
2. Say the stop, the target, the risk a share and the flat-by time in plain words.
3. Hand on: `/trader-timemachine` replays it, `/trader-budget` sizes it with the costs.
4. Never move a stop further away once the trade is on.

## What it never does

It never places, sizes or checks an order, never shorts, never promises the stop fills at its
price.

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
