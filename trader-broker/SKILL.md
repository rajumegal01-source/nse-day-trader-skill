---
name: trader-broker
description: >-
  Order Executor for NSE/BSE. Shows every approved order as a full ticket (symbol, exchange,
  side, quantity or lots, LIMIT price, product MIS/CNC/NRML, stop-loss, target, validity,
  estimated charges and the net loss at the stop, PAPER or LIVE) and sends it only after you
  type yes for THAT order. Paper trading by default; LIVE through Angel One SmartAPI when
  "mode": "live" (login with client code, PIN and TOTP; LIMIT entry, then a protective SELL
  stop-loss; order book; cancel; trade-book P&L). Daily max-loss kill switch. Zerodha Kite is
  a stub. UNVERIFIED LIVE: tested only against mocked HTTP. Use when the user says "place
  the order", "buy it", "send it to Angel One", "paper trade this", "cancel my order", "my
  P&L today", "kill switch", or after /trader-risk passes an order.
argument-hint: "show | approve --index N --reply \"yes ...\" | pnl | kill | status | cancel"
---

# trader-broker (NSE/BSE)

The Order Executor is the only skill in this pack that can lead to an order. It does its work
around the one moment that matters: your yes, typed for one order, in the chat.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                                # every ticket, READY or not
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"     # PAPER
python3 "${CLAUDE_SKILL_DIR}/ticket.py" approve --index 1 --reply "yes RELIANCE"   # LIVE: name the symbol
python3 "${CLAUDE_SKILL_DIR}/ticket.py" decline --index 1
python3 "${CLAUDE_SKILL_DIR}/ticket.py" protect --index 1                   # LIVE: SL for an entry that filled late
python3 "${CLAUDE_SKILL_DIR}/ticket.py" status                              # LIVE order book / paper positions
python3 "${CLAUDE_SKILL_DIR}/ticket.py" cancel --order-id 2611... --reply "yes cancel 2611..."
python3 "${CLAUDE_SKILL_DIR}/ticket.py" mark                                # PAPER: stops and targets hit?
python3 "${CLAUDE_SKILL_DIR}/ticket.py" flatten --symbol RELIANCE --price 1240.00   # a SELL ticket
python3 "${CLAUDE_SKILL_DIR}/ticket.py" pnl                                 # today's realized net P&L
python3 "${CLAUDE_SKILL_DIR}/ticket.py" kill --reason "done for today"      # kill switch ON until tomorrow
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log
```

## The yes

`approve` needs `--reply` with the user's words, exactly as typed. It refuses "ok", "sure",
"go", "do it", "yes to all", a yes with a condition ("yes but ...", "yes if ..."), a yes that
names a different stock or number, and any order that is not READY. In LIVE mode the yes must
also name the symbol: `yes RELIANCE`. Claude never types the yes for the user and never
approves more than the one order the user said yes to. An order is READY only if trader-risk
passed THIS exact order today (fingerprint match), the kill switch is off and nobody has
decided on it yet.

## The ticket

```
ORDER 1 of 1, PAPER
  Symbol        RELIANCE on NSE (equity intraday)
  Side          BUY
  Quantity      30
  Price / type  LIMIT 1234.50
  Product       MIS (intraday, the broker squares it off ~15:15-15:25)
  Validity      DAY
  Stop-loss     1223.10 (paper: closes the position when the price touches it)
  Target        1257.30
  Cost          ₹37,035.00 for the shares + about ₹15.61 charges on the buy
  At the stop   -₹381.13 net (₹39.13 charges incl. STT, exchange, SEBI, GST, stamp)
  At the target ₹644.21 net (₹39.79 charges)
  Account       PAPER (simulated)
  READY: trader-risk PASS, waiting for your yes
```

## Paper mode (the default)

`"mode": "paper"` in `trader/config.json`. A LIMIT entry is assumed filled at its price; `mark`
closes a paper position at its stop or target when `trader/prices.json` (trader-alerts `quote
--write`) shows it touched; `flatten` + risk + yes sells it. Realized P&L after charges goes to
`trader/state/pnl.json`; the paper book is `trader/state/paper.json`.

## Live mode: Angel One SmartAPI (UNVERIFIED LIVE)

`"mode": "live"` and `"broker": "angelone"`. This adapter (`angel.py`) was built from Angel
One's public SmartAPI docs (https://smartapi.angelbroking.com/docs, read 2026-11-02) and tested
offline against mocked HTTP only. It has never sent an order to a real account. Paper-trade
first; then try one tiny order you can afford to lose and check it in the Angel One app.

- **Credentials**, from the environment or a local file only: `ANGEL_API_KEY`,
  `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET`, or `trader/secrets/angel.json`
  (copy `angel.example.json`, `chmod 600`, never commit it). Never paste them in the chat.
  They are never printed or written; error messages are scrubbed of them. The TOTP is computed
  locally (RFC 6238, HMAC-SHA1, 30 s, 6 digits) from the secret Angel One shows when you
  enable TOTP at https://smartapi.angelbroking.com/enable-totp.
- **Flow** on a live yes: login (`POST /rest/auth/angelbroking/user/v1/loginByPassword` with
  clientcode, PIN, TOTP) -> look up the symbol token in Angel One's instrument master (cached
  for the day) and re-check the lot size and tick -> `placeOrder` (variety NORMAL, LIMIT,
  producttype INTRADAY for MIS / DELIVERY for CNC / CARRYFORWARD for NRML, ordertag
  `ndts<fingerprint>`) -> poll `getOrderBook` up to `fill_wait_seconds` (20) -> when complete,
  place the protective SELL stop-loss (variety STOPLOSS, STOPLOSS_LIMIT, trigger at the stop,
  limit `sl_limit_buffer_pct` 0.5 % under it) -> logout. If the entry has not filled yet it says
  so loudly: there is NO stop on the exchange until `ticket.py protect` runs.
- The **target is not sent** (Angel One has no OCO for a plain order pair): trader-alerts
  rings at the target, and you approve a `flatten` SELL, which also cancels the open stop-loss.
- `pnl` reads `getTradeBook`, matches today's buys and sells and estimates the charges.
- Order calls are throttled to `max_orders_per_second` (1), far below SEBI's 10 per second.
- MARKET orders are refused in live mode (and by trader-risk): use LIMIT prices.

## SEBI's retail algo / API framework (applies to every broker from 1 April 2026)

- SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 Feb 2025, "Safer participation of
  retail investors in Algorithmic trading"); the glide-path circular
  SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132 (30 Sep 2025) made it apply to all stock brokers from
  1 April 2026 (https://www.sebi.gov.in/sebi_data/attachdocs/sep-2025/1759232056254.pdf).
- **Static IP**: a client using a broker API must register static IP address(es) with the broker,
  mapped to the API key (NSE circular NSE/INVG/67858 of 5 May 2025). Angel One's static-IP API
  keys only accept place, modify and cancel orders from the registered IP; put that IP in
  `"angel_public_ip"`. Running this from a laptop on home Wi-Fi with a changing IP will fail.
- **Order-rate threshold**: up to 10 orders per second per exchange (TOPS) needs no algo
  registration; above it the algo must be registered with the exchange through the broker.
- **Algo-ID tagging**: every API order is treated as an algo order and tagged by the broker with
  an exchange-issued identifier (NSE FAQ of 3 Nov 2025: client direct API orders under the
  threshold carry the standard tag). The broker does this; the ordertag this tool sets is
  only for your own matching.
- 2-factor login (PIN + TOTP), and a self-built algo may be used for yourself and your family only.
- Market orders through an API algo are not permitted (NSE/MSD/67753, cited in NSE's FAQ).

Read the latest circulars and Angel One's own API terms before going live; they change.

## Kill switch

`max_daily_loss_inr` (₹1,500 in the example config). When today's realized net P&L (`pnl`, or
`mark` in paper) reaches minus that, `trader/state/killswitch.json` trips for the rest of the IST
day: trader-risk blocks every new entry and `approve` refuses them. `ticket.py kill` trips it by
hand. Exits (selling what you hold) are still allowed. It lapses by itself the next day.

## Adding another broker later

Zerodha Kite Connect is a stub (`KiteConnect` in angel.py lists what it would need: a daily
browser login for the request token, `POST /orders/regular`, `X-Kite-Version: 3`). Any adapter
must keep the same gate: risk PASS for the fingerprint, the kill switch, and the typed yes.

## Steps

1. `ticket.py show` and read the whole ticket to the user, including PAPER or LIVE.
2. Wait for the user's own words. Pass them to `approve --reply` unchanged.
3. Say exactly what happened: filled on paper, or Angel One's order id and the stop-loss id.
4. During the trade: trader-alerts rings; `flatten` + risk + yes to get out; `pnl` after.

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
