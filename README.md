# The Day Trader skill pack, NSE/BSE edition

11 Claude skills for day trading Indian stocks: scan thousands of NSE charts, track breaking
news and exchange filings, time every entry and exit, and replay every outcome before you
risk a rupee. Prices in ₹, times in IST, real Indian intraday charges in every size.

This is a port of Jake Schincariol's MIT-licensed US pack
([github.com/Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill))
to the National Stock Exchange of India and BSE. Free and plain Python (standard library only,
3.8 or newer). No API key for any data: Yahoo Finance's free charts (`.NS` / `.BO` symbols,
`^NSEI`, `^BSESN`), Google News, NSE's public archives and APIs.

And no order goes through until you type yes. Paper trading is the default. Live orders through
Angel One SmartAPI are possible only if you switch them on yourself, and that path is
**UNVERIFIED**: it was built from Angel One's public docs and tested only against mocked HTTP.

> **SEBI disclaimer.** Educational only, not investment advice. The authors are not a
> SEBI-registered Investment Adviser or Research Analyst. SEBI's study found that **7 out of 10
> individual intraday traders (71%) in the equity cash segment made net losses in FY 2022-23**
> (SEBI press release PR No. 13/2024, 24 July 2024,
> https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818619980.pdf), and that 93% of
> individual F&O traders made losses between FY22 and FY24 (PR No. 22/2024). You can lose money.

## Install

Copy the skill folders into Claude Code:

```bash
cp -r nse-day-trader-skill/trader-* ~/.claude/skills/
```

or as a plugin from a local folder (`/plugin marketplace add ./nse-day-trader-skill`, then
`/plugin install nse-day-trader-skill@nse-day-trader-skill`). On claude.ai, upload each skill's
zip (one zip per skill, the folder at its root) under Settings, Capabilities, Skills. Then:

```bash
mkdir -p trader && cp trader-budget/config.example.json trader/config.json   # set your ₹ numbers
```

## The eleven

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | NSE EQ universe (EQUITY_L.csv, NIFTY 100 fallback); daily setups and opening-range breakouts from 9:15 IST |
| `/trader-news` | News Monitor | Google News + Yahoo headlines and NSE corporate announcements, new since the last check, in IST |
| `/trader-entry` | Entry Timer | watches a setup bar by bar: the first 5-minute close above the 9:15-9:30 range |
| `/trader-exit` | Exit Planner | stop and target before you enter, snapped to the tick; flat by 15:10, before the MIS square-off |
| `/trader-timemachine` | Time Machine | 10,000 replays of the rest of the session from the stock's own 60 days of bars, plus history |
| `/trader-risk` | Risk Manager | PASS / BLOCK: max loss with charges, daily loss, kill switch, window, circuits, lots, ticks |
| `/trader-budget` | Budget Manager | sizes to your ₹ budget and max loss, counting brokerage, STT, exchange, SEBI, GST, stamp |
| `/trader-broker` | Order Executor | the full ticket and your typed yes; paper by default; LIVE via Angel One SmartAPI (unverified) |
| `/trader-alerts` | Price Alerts | stop, target, % move, opening bell, flat-by; the NSE clock with 2026 holidays and Muhurat |
| `/trader-analyst` | Results Analyst | quarterly results from NSE's XBRL filings (Yahoo fallback): growth, margin, EPS, QoQ, YoY |
| `/trader-bulkdeals` | Bulk Deals Tracker | NSE bulk and block deals, SAST Reg 29 and SEBI PIT insider disclosures (replaces the Pelosi tracker) |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads what the last one
wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by 15:10                                           (while it is open)
news / analyst / bulkdeals                                                    (on a schedule)
```

An example with real data: RELIANCE, Monday 2 November 2026.

1. **`/trader-scanner`** at 10:00 IST: of the NIFTY 50 charts, 19 had closed above their
   15-minute opening range (41 of 100 over the NIFTY 100). RELIANCE is one: range 1214.60 to
   1231.60, the 9:30 bar closed at 1234.50, 0.24% over the top, at 9:35 AM.
2. **`/trader-news`**: RELIANCE closed +11.6% that day; the headlines were its Q2 results
   ("profit rises 33.8% to ₹29,550 crore") and the NSE filings were the analyst-meet transcript.
3. **`/trader-entry`**: at 9:27 RANGE FORMING; at 10:00 TRIGGERED 9:35 AM at ₹1234.50.
4. **`/trader-exit`**: stop at the range midpoint, 1223.10 (11.40 a share at risk, tick 0.10);
   target 2R, 1257.30; flat by 15:10 IST.
5. **`/trader-timemachine`** (seed 19, 59 past sessions): with a 1R target, target first 30.9%,
   stop first 34.1%, neither 35.0%; the same rule on the 59 real sessions fired 31 times, 14
   target, 12 stop. Verdict: close to a coin flip. With 2R and `--until 15:10`: target first 4.3%.
6. **`/trader-budget`** with ₹50,000 and a ₹500 max loss: 30 shares (₹37,035), bound by the 75%
   position cap. At the stop: -₹342.00 gross, ₹39.13 charges, **-₹381.13 net**. At the target:
   ₹644.21 net. Reward:risk 2.00 before charges, 1.69 after. A 1R target was refused: 0.79 after
   charges.
7. **`/trader-risk`**: PASS, net loss at the stop ₹381.13; RELIANCE has no fixed price band (an
   F&O stock).
8. **`/trader-broker`**: the full ticket, PAPER; you type "yes" (live: "yes RELIANCE").
9. **`/trader-alerts`** rings on the stop, the target and at 15:10 to flatten.

## Indian specifics

- **Session**: pre-open order entry 9:00 to 9:08 IST (matching by 9:15), continuous market 9:15
  to 15:30. Brokers square off intraday (MIS) positions from about 15:15 to 15:25.
- **NSE trading holidays 2026** (NSE circular NSE/CMTR/71775 of 12 Dec 2025, plus the 15 Jan
  Maharashtra municipal election holiday; list as on niftyindices.com, read 2 Nov 2026): 15 Jan,
  26 Jan, 3 Mar, 26 Mar, 31 Mar, 3 Apr, 14 Apr, 1 May, 28 May, 26 Jun, 14 Sep, 2 Oct, 20 Oct,
  10 Nov, 24 Nov, 25 Dec.
- **Muhurat trading**: Sunday 8 Nov 2026, pre-open 14:05 to 14:20, market 14:20 to 15:30 IST
  (NSE circular NSE/CMTR/76941 of 19 Oct 2026; BSE notice 20261019-9).
- **Intraday equity charges** (zerodha.com/charges and nseindia.com levies, read 2 Nov 2026):
  brokerage ₹20 or 0.03% per executed order, whichever is lower (set your broker's own in the
  config); STT 0.025% on the sell side; exchange transaction charge NSE 0.00307%, BSE 0.00375%;
  SEBI fee ₹10 per crore; GST 18% on brokerage + transaction + SEBI fee; stamp duty 0.003% on the
  buy side. Futures STT 0.05% (from 1 April 2026), options STT 0.15% of the premium.
- **F&O**: off by default. Lot sizes from Angel One's instrument master (NIFTY 65, BANKNIFTY 30,
  RELIANCE 500, ...), re-checked live before a live order.
- **Circuits**: NSE's `sec_list.csv` price bands (2/5/10/20%); F&O stocks have dynamic bands.
- **Bulk deal**: one client's trades in a day above 0.5% of the listed shares. **Block deal**:
  ₹25 crore minimum in the 08:45-09:00 and 14:05-14:20 windows (SEBI circular 2025/134, from 8 Dec 2025).

## Live trading: Angel One SmartAPI (UNVERIFIED)

> **Status:** login and the order book were checked read-only against the real Angel One API
> (`trader-broker/check_angel.py`, 3 Nov 2026, no order placed). Placing, cancelling and fills are
> tested **only against a mock server**. Before real money: register a static IP, then place one
> tiny LIMIT order by hand-approval and watch it in the Angel One app.

Set `"mode": "live"` and `"broker": "angelone"` in `trader/config.json`. Credentials only from
environment variables or a local file you fill in yourself (`trader/secrets/angel.json`, from
`trader-broker/angel.example.json`, `chmod 600`, git-ignored):

```bash
export ANGEL_API_KEY=...        # SmartAPI app key
export ANGEL_CLIENT_CODE=...    # your Angel One client code
export ANGEL_PIN=...            # your login PIN
export ANGEL_TOTP_SECRET=...    # the base32 secret shown when you enable TOTP
```

Never paste them into a chat. They are never printed or written by the tools. On your typed
`yes RELIANCE`, `ticket.py approve` logs in (loginByPassword with client code, PIN and a TOTP
computed locally with hmac + base32), places the LIMIT entry (placeOrder), watches the order
book (getOrderBook), places the protective SELL stop-loss once the entry fills, and logs out.
`cancel` (cancelOrder) and `pnl` (getTradeBook) work the same way. A daily max-loss kill switch
(`max_daily_loss_inr`) stops new entries for the rest of the day. A Zerodha Kite adapter is a stub.

**SEBI's retail algo / API framework** (SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013,
4 Feb 2025; applicable to all brokers from 1 April 2026 under SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/132):
every API order is treated as an algo order and tagged by the broker; a client using a broker API
must register a **static IP** with the broker (NSE/INVG/67858); up to 10 orders per second per
exchange needs no separate algo registration (this tool sends at most 1 per second); 2-factor
login; a self-built algo is for you and your family only; no market orders through an API algo.
Read the current circulars and your broker's API terms before you go live.

## Trading Lab (`lab/`)

Our own indicators, each tested thousands of ways on every stock, with a memory of what held up:

| Setup | What it is |
|---|---|
| `structure` | Market structure: swing highs/lows, **BOS** (trend continues) and **CHoCH** (trend flips) |
| `fvg` | **Fair Value Gap**: a 3-candle gap, traded on its first retest |
| `ob` | **Order Block**: the last opposite candle before a BOS, traded on its first retest |
| `vdelta` | **Order-flow proxy**: volume delta from each candle + an n-bar breakout. True order flow needs tick / bid-ask data that free sources do not give |

```bash
python3 lab/lab.py grid --nifty100     # 12,960 settings x every Nifty 100 stock -> lab/memory.json
python3 lab/lab.py scan                # every 5-min bar of today, every remembered setting
python3 lab/lab.py scan --at 11:00     # as it looked at 11:00 IST
python3 lab/lab.py show POWERGRID      # what the lab remembers
python3 lab/lab.py learn               # after 15:30 IST: grade today's triggers, retire losing settings
python3 lab/lab.py lessons             # what it learned: win % by setup, by time of day, long vs short
python3 lab/terminal.py                # the lab's own terminal: a menu, works in Termux
```

**It learns every day by itself.** `.github/workflows/lab-daily.yml` runs `lab.py daily` on
GitHub (free for public repos) at 16:30 IST on weekdays: it grades the day's triggers, keeps a
live record for every remembered setting, retires a setting after 5+ live trades with a net
loss, re-tests all Nifty 100 stocks with the new day included, and commits `lab/memory.json`.
Outcomes that a missing 5-minute bar could hide are not learned from. Run it by hand from the
repo's Actions tab (Run workflow).

**Telegram alerts.** `.github/workflows/lab-alerts.yml` runs `lab/alert.py` every 15 minutes in
market hours and sends each new quality trigger once (best setting of its setup, still live,
8+ test trades, 60%+ test wins, +0.15% test average). Setup: make a bot with @BotFather, send it
/start, and save its token as the repo secret `TELEGRAM_TOKEN` (Settings, Secrets and variables,
Actions). Never paste the token anywhere else.

**Phase A filters and exits (optional).** `lab/filters.py`: sideways, nifty (^NSEI vs its
VWAP-proxy/EMA20), relvol, vwap, time, gap. `lab/risk.py`: trail (stop to entry at 1R), partial
(half at 1R), tstop (out after 6 bars without +0.5R), a position-size calculator with approximate
Angel One-like intraday costs, and the alert's daily loss limit (no new picks after 2 stop-outs).
All are off in `lab.py`; `alert.py --filters nifty,gap` is the default (`--filters none` turns it off).
વૈકલ્પિક filters/exits: alert માં default ફક્ત nifty + gap ચાલુ છે, બાકી બધું બંધ.

```bash
python3 lab/evalfilters.py --cache /tmp/y      # replay remembered best settings with / without each rule
python3 lab/risk.py size --capital 50000 --risk 1 --entry 1250 --stop 1240 --target 1270
```

Replay on 2026-11-05 (100 stocks, rank-1 setting per setup, ~60 days, last 33% = test, 21 days):

| rule | test trades | test win % | test avg % | train avg % |
|---|---|---|---|---|
| none (baseline) | 3207 | 59.5 | +0.341 | +0.267 |
| sideways | 2937 | 59.0 | +0.329 | +0.259 |
| nifty | 2635 | 60.2 | +0.357 | +0.262 |
| relvol | 1138 | 57.9 | +0.286 | +0.229 |
| vwap | 2894 | 59.7 | +0.345 | +0.254 |
| time | 2884 | 59.5 | +0.330 | +0.249 |
| gap | 2682 | 60.2 | +0.359 | +0.265 |
| trail | 3207 | 54.0 | +0.313 | +0.247 |
| partial | 3207 | 60.4 | +0.263 | +0.203 |
| tstop | 3207 | 47.5 | +0.181 | +0.087 |
| nifty + gap | 2212 | 61.7 | +0.384 | +0.257 |

Only nifty and gap raised the test average, and only by ~0.02% each; neither helped the train
half, and a day-level bootstrap does not rule out zero. The settings were picked partly on the
test half. Treat the defaults as a weak lean, not an edge. Exits all lowered the average.
નાના sample, overfitting શક્ય: આ ફક્ત શૈક્ષણિક છે.

`lab/memory.json` is the lab's memory: for each stock and setup, how many settings were robust
(positive in BOTH the train and the test half) and the best three, plus a history of past runs.
The scan lists **every** trigger of the day with its status (live / target / stop / close), so
a signal that fired while you were away still shows, and it lists missing 5-minute bars.
Thousands of settings overfit: a robust setting is something to paper-trade, not a promise.

## The tools

```bash
python3 trader-scanner/scan.py universe                       # NSE EQ list -> trader/universe.txt (optional: without it, scans use the bundled NIFTY 100)
python3 trader-scanner/scan.py daily                          # pre-market setups
python3 trader-scanner/scan.py orb --at 10:00                 # opening-range breakouts so far
python3 trader-news/news.py --tickers RELIANCE --hours 24     # headlines, NSE filings, the move
python3 trader-entry/entry.py check RELIANCE                  # waiting / triggered / expired
python3 trader-exit/exit.py plan --stop or-mid --target 2R --tick 0.10 --write
python3 trader-timemachine/timemachine.py run --until 15:10 --write
python3 trader-budget/size.py --write                         # -> trader/orders.json
python3 trader-risk/check.py bands && python3 trader-risk/check.py
python3 trader-broker/ticket.py show                          # the ticket; then approve --reply "yes"
python3 trader-alerts/alerts.py add --from-plan && python3 trader-alerts/alerts.py check
python3 trader-analyst/facts.py RELIANCE TCS
python3 trader-bulkdeals/deals.py deals && python3 trader-bulkdeals/deals.py insider RELIANCE
```

```bash
python3 backtest/orb_grid_sym.py POWERGRID                    # ORB grid backtest: 10,240 settings, train/test split
```

`orb_grid_sym.py` downloads ~60 days of Yahoo 5-minute bars, tests every opening-range setting
(range 5/10/15/30 min, entry cutoff, stop, target, filter, side, volume, buffer), and prints the
most stable one with its test results and what it would have done on the last day. It also lists
**data gaps**: Yahoo's free 5-minute charts sometimes drop bars (15:15-15:25 were missing on
4 Nov 2026), and a missing bar can hide a stop or target touch, so the JSON warns you and days with
more than `--max-gaps` missing bars are left out. Backtests over thousands of settings overfit:
trust the test half, not the train half, and paper-trade before real money.

```bash
python3 backtest/orb_grid_sym.py POWERGRID | python3 backtest/paper_journal.py add -   # log today's signal
python3 backtest/paper_journal.py grade      # after 15:30 IST: target, stop or close (flags missing bars)
python3 backtest/paper_journal.py report     # win %, average, total; says when you have too few trades
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline on fixtures captured from the real sources on 2 Nov 2026 (NSE EQUITY_L,
NIFTY 50 5-minute and daily charts, RELIANCE's 60 days of bars, Google News, NSE announcements,
NSE XBRL results, bulk/block/SAST/PIT files) and on a mocked Angel One server. They reproduce
the numbers above.

## Fine print

- **Not investment advice. Most intraday traders lose money** (SEBI PR No. 13/2024: 7 in 10 in
  FY 2022-23). A PASS from trader-risk is a rules check, not a recommendation.
- **No trade goes through until you type yes** for that one order (live: `yes SYMBOL`). Never
  "yes to all".
- **Paper first.** The live adapter is UNVERIFIED against a real account.
- **The time machine is a simulation**, not a prediction: results, news, circuits and halts can
  do what 60 days never did.
- **A stop is a plan, not a guarantee**: a gap or a circuit freeze can fill it far worse.
- **The data is free and unofficial**: Yahoo can lag or rate-limit; NSE's site answers browsers
  only and may refuse scripts at any time (the tools then say which source failed).
- **Taxes**: intraday equity profits are speculative business income in India; nothing here is
  tax advice.

## ગુજરાતી સારાંશ

આ પેક NSE/BSE પર ઇન્ટ્રાડે ટ્રેડિંગ શીખવા માટેની 11 Claude સ્કિલ છે: ચાર્ટ સ્કેનર, સમાચાર અને NSE
જાહેરાતો, એન્ટ્રીનો સમય, સ્ટોપ-લોસ અને ટાર્ગેટ, 10,000 વાર ટ્રેડનું રિપ્લે (ટાઇમ મશીન), બજેટ અને
જોખમની તપાસ, ઓર્ડર ટિકિટ, પ્રાઇસ એલર્ટ, ત્રિમાસિક પરિણામ અને બલ્ક/બ્લોક ડીલ. ભાવ ₹ માં અને સમય IST
માં છે; બ્રોકરેજ, STT, એક્સચેન્જ ચાર્જ, SEBI ફી, GST અને સ્ટેમ્પ ડ્યુટી દરેક ગણતરીમાં સામેલ છે.

- ડિફોલ્ટ રીતે ફક્ત પેપર ટ્રેડિંગ. Angel One SmartAPI થી લાઇવ ઓર્ડર ત્યારે જ જાય છે જ્યારે તમે
  config માં `"mode": "live"` કરો અને દરેક ઓર્ડર માટે જાતે "yes SYMBOL" લખો. લાઇવ ભાગ હજી
  વાસ્તવિક ખાતા પર ચકાસાયેલ નથી (UNVERIFIED).
- પાસવર્ડ, PIN કે TOTP ક્યારેય ચેટમાં ન લખો; ફક્ત environment variables અથવા તમારી પોતાની
  ફાઇલમાં રાખો. API માટે બ્રોકર પાસે static IP રજીસ્ટર કરાવવો જરૂરી છે (SEBI નિયમ).
- રોજનું મહત્તમ નુકસાન પહોંચે તો kill switch આખો દિવસ નવા ટ્રેડ રોકી દે છે.
- **ચેતવણી:** આ ફક્ત શિક્ષણ માટે છે, રોકાણ સલાહ નથી. SEBI ના અભ્યાસ મુજબ FY 2022-23 માં ઇન્ટ્રાડે
  કરનારા 10 માંથી 7 વ્યક્તિગત ટ્રેડરોને નુકસાન થયું હતું. તમે પૈસા ગુમાવી શકો છો.

## Files

```
trader-scanner/     SKILL.md, scan.py, nifty100.csv
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py, nse.py
trader-budget/      SKILL.md, size.py, nse.py, config.example.json
trader-broker/      SKILL.md, ticket.py, angel.py, nse.py, angel.example.json
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, facts.py, metrics.example.json
trader-bulkdeals/   SKILL.md, deals.py
lab/                core.py (indicators), lab.py (grid, scan, show), memory.json,
                    filters.py, risk.py, evalfilters.py (Phase A), alert.py
backtest/           orb_grid_sym.py (ORB grid backtest), paper_journal.py (paper trades), educational
tests/              unittest suite + offline fixtures
```

MIT. Original pack by [Jake Schincariol](https://opusjake.ai); NSE/BSE port by Raju Megal.
