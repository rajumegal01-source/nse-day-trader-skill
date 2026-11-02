---
name: trader-budget
description: >-
  Budget Manager for NSE/BSE day trades, in rupees. Sizes every position to your budget and
  your max loss per trade WITH the Indian intraday costs counted: brokerage (default ₹20 or
  0.03% per order, whichever is lower, configurable), STT 0.025% on the sell side, exchange
  transaction charges (NSE 0.00307%, BSE 0.00375%), SEBI fee ₹10 per crore, 18% GST and stamp
  duty 0.003% on the buy side. Whole shares, whole F&O lots when F&O is on, no MIS leverage,
  reward:risk checked after charges. Writes one order (LIMIT entry, MIS, stop-loss, target) to
  trader/orders.json. Use when the user says "how many shares", "size this trade", "kitne
  shares lu", "position size", "₹500 max loss", "what are the charges", or after
  /trader-timemachine and before /trader-risk.
argument-hint: "[--budget ₹] [--max-loss ₹] [--write]"
---

# trader-budget (NSE/BSE)

The Budget Manager turns a plan into a size. The loss at the stop counts the charges, because
on small intraday trades the charges are a real share of the risk.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                                  # trader/plan.json + trader/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write                          # -> trader/orders.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --budget 50000 --max-loss 500
python3 "${CLAUDE_SKILL_DIR}/size.py" --limit 1234.50 --write
python3 "${CLAUDE_SKILL_DIR}/size.py" --segment futures --lot-size 500  # F&O: whole lots (allow_fno must be on)
```

Copy `config.example.json` to `trader/config.json` and set your own numbers (rupees).

## How many shares

```
loss(q) = q x (entry - stop) + charges(buy q at entry, sell q at stop)
q = the largest whole number (a multiple of the lot for F&O) with
  max loss      loss(q) <= max_loss_per_trade_inr
  position cap  q x entry <= budget x max_position_pct
  max order     q x entry <= max_order_inr
  cash          q x entry + buy-side charges <= budget minus the cash buffer
```

No MIS leverage is used to size (brokers offer up to about 5x intraday margin on equity; this
pack sizes on cash only). Reward:risk is checked AFTER charges: net profit at the target over
net loss at the stop must reach `min_reward_risk` (1.0). A 1R target never passes after costs.

## The charges (verified 2026-11-02)

| charge | equity intraday | source |
| --- | --- | --- |
| brokerage | ₹20 or 0.03% per executed order, whichever is lower (yours may differ: `brokerage_per_order`, `brokerage_pct`) | https://zerodha.com/charges |
| STT | 0.025% of the sell value | https://zerodha.com/charges ; https://support.zerodha.com (STT rates) |
| exchange transaction | NSE 0.00307%, BSE 0.00375% of turnover | https://zerodha.com/charges |
| SEBI turnover fee | ₹10 per crore (0.0001%) | https://www.nseindia.com/static/invest/first-time-investor-sebi-turnover-fees-stt-other-levies |
| GST | 18% on brokerage + transaction charges + SEBI fee | https://zerodha.com/charges |
| stamp duty | 0.003% of the buy value | https://zerodha.com/charges ; NSE levies page |

Futures (F&O): STT 0.05% sell side (from 1 April 2026, Budget 2026-27), NSE txn 0.00183%,
stamp 0.002%. Options: STT 0.15% of the premium on the sell side, NSE txn 0.03553% of the
premium, stamp 0.003%, flat ₹20 brokerage. Delivery (CNC): STT 0.1% both sides, stamp 0.015%.
Statutory rates change with each Budget; your contract note is the truth. DP charges on
delivery sells are not counted.

**F&O lot sizes** (Angel One instrument master, read 2026-11-02): NIFTY 65, BANKNIFTY 30,
FINNIFTY 60, MIDCPNIFTY 120, RELIANCE 500, TCS 225, SBIN 750. NSE revises lots periodically:
`"lot_sizes"` in the config wins, and trader-broker re-checks against the live master. F&O is
off unless `"allow_fno": true`: SEBI found 93% of individual F&O traders made losses between FY22 and FY24
(SEBI PR No. 22/2024, https://www.sebi.gov.in/sebi_data/attachdocs/sep-2024/1727086965496.pdf).

## Example (real numbers, RELIANCE, Mon 2 Nov 2026)

Budget ₹50,000, max loss ₹500, plan entry 1234.50, stop 1223.10, target 1257.30 (2R):

```
Limits: max loss 39, position cap 30 <- binds, max order 32, cash 36
Size: 30 shares of RELIANCE = ₹37,035.00 at 1234.50.
If the stop fills at 1223.10: -₹342.00 gross, ₹39.13 charges, -₹381.13 net.
If the target fills at 1257.30: ₹684.00 gross, ₹39.79 charges, ₹644.21 net.
  charges at the stop: brokerage ₹22.12, STT ₹9.17, exchange ₹2.26, SEBI ₹0.07, GST ₹4.40, stamp ₹1.11
Reward:risk 2.00 before charges, 1.69 after. Break-even: the price must rise 1.31 just to pay the charges.
Proposed order: BUY 30 RELIANCE on NSE, limit 1234.50, MIS, day, stop-loss 1223.10, target 1257.30
```

With the 1R target (1245.90) it refused: reward:risk after charges 0.79, under the 1.0 minimum.

## Steps

1. `size.py` first and read the limits table to the user, then `size.py --write`.
2. Say the size, the net loss at the stop and the net profit at the target, both after
   charges, and the break-even move.
3. Hand on to `/trader-risk`. Nothing is placed here.

## What it never does

It never places or checks an order, never uses leverage, never sizes a short.

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
