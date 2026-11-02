---
name: trader-alerts
description: >-
  Price Alerts and the NSE clock. Rings when a price, a stop, a target, a percent move, the
  opening bell (9:15 IST, 14:20 on Muhurat) or a time (flat by 15:10, before the MIS
  square-off) hits, once each. Knows NSE's 2026 holidays, the 9:00 to 9:08 pre-open and the
  Muhurat session on 8 Nov 2026. Writes free Yahoo quotes with the previous close to
  trader/prices.json for trader-budget, trader-risk (circuit check) and paper trading. Use
  when the user says "alert me", "is the market open", "market kab khulega", "watch my stop",
  "tell me at 3:10", "set alerts from my plan", or while a trade is open.
argument-hint: "clock | quote SYM --write | add --from-plan | check | list | reset ID"
---

# trader-alerts (NSE/BSE)

Price Alerts watch the numbers in your plan and ring once when one hits. An alert is
information, not an order: in live mode the protective stop-loss at the broker is what stops
you out; in paper mode `ticket.py mark` does.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" clock                          # NSE open? pre-open? next open (IST)
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote RELIANCE ^NSEI --write   # -> trader/prices.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" quote --holdings --write
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --from-plan                # stop, target, flat-by 15:10
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol TCS --pct 3
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --opening-bell
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check                          # rings what hit, once
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" reset reliance-plan-stop
```

## Rule types

| type | rings when |
| --- | --- |
| `above` / `target` | the price is at or above `price` |
| `below` / `stop` | the price is at or below `price` |
| `pct_move` | the price moved `pct` % or more from the previous close (`direction` up/down) |
| `opening_bell` | NSE opened today (9:15 IST; 14:20 on the Muhurat session) |
| `time` | the IST clock passed `at` on a trading day |

A rule from the plan is for the plan's date only. An above/below alert rings once (unless
`"rearm": true`); a pct_move at most once a day. State in `trader/state/alerts.json`.

## The clock

- Pre-open order entry 9:00 to 9:08 IST, matching by 9:15; continuous session 9:15 to 15:30.
- NSE trading holidays 2026 (NSE circular NSE/CMTR/71775, plus 15 January; list as on
  niftyindices.com, read 2026-11-02): 15 Jan, 26 Jan, 3 Mar, 26 Mar, 31 Mar, 3 Apr, 14 Apr,
  1 May, 28 May, 26 Jun, 14 Sep, 2 Oct, 20 Oct, 10 Nov, 24 Nov, 25 Dec.
- Muhurat trading Sunday 8 Nov 2026: pre-open 14:05 to 14:20, normal market 14:20 to 15:30 IST
  (NSE circular NSE/CMTR/76941, 19 Oct 2026; BSE notice 20261019-9).
- Outside 2026 the clock says the holiday list is unknown: check nseindia.com.

## Quotes

Yahoo's chart endpoint (`<SYM>.NS`, `<SYM>.BO`, `^NSEI`, `^BSESN`): free, delayed,
unofficial, for alerts only, never for timing an order. `quote --write` stores the price, the
previous close and the quote time in `trader/prices.json`. Circuit limits: a stock frozen at
its band may not trade at your stop or target at all.

## Example (live, Mon 2 Nov 2026)

```
NSE OPEN (2026-11-02 15:12 IST, regular session).
ALERT RELIANCE is ₹1300.00: at or above your target ₹1257.30 (plan target: 2R).
ALERT Flat by (before the broker's MIS square-off): it is 15:12 IST (set for 15:10) ...
```

## Steps

1. After trader-exit: `add --from-plan`. Then run `check` every few minutes while the trade is
   open (a scheduled task or a loop), with `quote --write` for trader-budget and paper mode.
2. On a ring, say it plainly and point to the action: `ticket.py flatten` + risk + yes.
3. Never place anything because an alert rang.

## What it never does

It never places, sizes or checks an order.

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
