---
name: trader-risk
description: >-
  Risk Manager for NSE/BSE trades. Checks every proposed order against your limits and stops
  anything over them: PASS or BLOCK with the reasons. Max loss per trade including Indian
  intraday charges, the daily max-loss kill switch, daily loss, trades and orders per day,
  reward:risk after charges, the entry window (9:15 to 15:30 IST, no_entries_after 14:45, NSE
  holidays, Muhurat), cash with no MIS leverage, position size, F&O lot multiples, tick sizes,
  circuit (price band) limits from NSE's sec_list.csv, no shorts, no MARKET orders in live
  mode. Writes trader/state/risk.json with each order's fingerprint for trader-broker. Use
  when the user says "check this trade", "is this within my limits", "risk check", "kill
  switch", or after /trader-budget and before /trader-broker.
argument-hint: "[--now HH:MM] | bands"
---

# trader-risk (NSE/BSE)

The Risk Manager is the gate. Every order trader-budget proposes (or trader-broker flatten
writes) gets PASS or BLOCK. trader-broker only shows an order as READY if THIS exact order
(same fingerprint) passed today.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py" bands                      # NSE price bands -> trader/bands.json
python3 "${CLAUDE_SKILL_DIR}/check.py"                            # -> trader/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --now "2026-11-02 10:00"   # pin the clock (IST)
python3 "${CLAUDE_SKILL_DIR}/check.py" --prev-close RELIANCE=1164.90 --json
```

## What blocks

Any order: format (NSE/BSE, segment, product MIS/CNC/NRML, whole qty, F&O whole lots, LIMIT
price, prices on the tick), asset (F&O and options off by default), short (selling more than
you hold), market (no MARKET orders in live mode: NSE's retail-algo rules do not permit market
orders through an API algo).

An entry, on top: **kill switch** (today's realized net loss reached `max_daily_loss_inr`, or
you ran `ticket.py kill`; no new entries until tomorrow), blocked list, size (min/max order),
position cap, cash (the buy plus its charges must fit above the cash buffer; no leverage),
duplicate, `max_orders_per_day`, `max_trades_per_day`, stop (required, below the entry),
**loss** (qty x (entry - stop) + round-trip charges over `max_loss_per_trade_inr`),
reward:risk after charges, **daily loss** (today's net max losses + this one + any loss
already realized over `max_daily_loss_inr`), window (NSE closed, outside the session, before
`no_entries_before` 09:30 or after `no_entries_after` 14:45 IST; Muhurat 14:35 to 14:45 with
the defaults), circuit (the entry price outside the stock's band).

An exit is never blocked by the entry rules: getting out must always be possible. Those rules
become warnings for it.

## Circuits

`check.py bands` reads https://archives.nseindia.com/content/equities/sec_list.csv (NSE's
price band file: 2, 5, 10, 20 % bands). The band is around the previous close, which comes
from trader/prices.json (trader-alerts `quote --write`) or `--prev-close SYM=PRICE`. Stocks in
F&O have no fixed band (dynamic bands), and the tool says so. A target above the upper band
only warns: it may never fill there.

## Example (real numbers, Mon 2 Nov 2026, 10:00 IST)

```
PASS  order 1: BUY 30 RELIANCE (entry)
      net loss at the stop, charges included: ₹381.13
      note: circuit: RELIANCE has no fixed price band (F&O stocks have dynamic bands)
1 passed, 0 blocked (PAPER mode). A PASS is a rules check, not a recommendation.
```

## Steps

1. Once a day before trading: `check.py bands`.
2. After trader-budget: `check.py`. Read every BLOCK reason to the user word for word.
3. On PASS hand on to `/trader-broker`. On BLOCK do not work around it: change the plan or skip.
4. Never edit trader/state/risk.json by hand; a changed order needs a new check.

## What it never does

It never places an order, never loosens a limit, and never treats a PASS as advice.

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
