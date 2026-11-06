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
python3 lab/lab.py grid --nifty100     # 14,088 settings (12 setups) x every Nifty 100 stock -> lab/memory.json
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

**Phase B price-action setups.** `lab/setups2.py` adds eight setups, each with a small grid
(<= 8 detection settings x 24 exits = <= 192 settings, 1,128 in all), the same 67/33 split and
the same robust rule. Their best settings sit in `memory.json` next to the original four, and
`alert.py` sends them only when they pass the same quality bar.

| Setup | What it is | ગુજરાતીમાં |
|---|---|---|
| `pdhl` | Previous-day high/low close-break, or a close beyond then back inside (failed break) | ગઈકાલના high/low નો breakout અથવા નિષ્ફળ breakout પછી ઉલટું |
| `cpr` | Floor pivots P, BC, TC, R1, S1: bounce or break | પિવટ લેવલ (P, CPR, R1, S1) પરથી bounce કે break |
| `inside` | 15-min inside bar / NR4 breakout, or day NR7 breakout | 15-મિનિટ inside bar / NR4 કે દિવસના NR7 નો breakout |
| `sweep` | Liquidity sweep: wick through a swing or PDH/PDL, close back inside -> reversal | swing કે PDH/PDL ની ઉપર-નીચે wick પછી અંદર close: ઉલટો ટ્રેડ |
| `odrive` | Opening drive: strong first 15 min, then opening-range break or first pullback | પહેલી 15 મિનિટની મજબૂત ચાલ પછી breakout કે પહેલો pullback |
| `round` | Round-number level (1-2-5 step, ~1% / ~2.5% of price): bounce or break | રાઉન્ડ નંબર લેવલ પર પ્રતિક્રિયા |
| `candle` | Engulfing / pin bar at a swing or pivot level | swing કે pivot લેવલ પર engulfing / pin bar |
| `trend` | EMA 9/21 pullback in trend, or Supertrend(10, 2/3) flip | EMA 9/21 pullback અથવા Supertrend flip |

```bash
python3 lab/lab.py grid --nifty100 --setups pdhl cpr inside sweep odrive round candle trend --cache /tmp/y
python3 lab/evalscore.py --cache /tmp/y        # setup table + score buckets
```

Grid on 2026-11-05 (100 stocks, ~60 days of 5-min bars, last 33% = test, ~20 days). Test record
pooled over each stock's best (rank-1) setting:

| setup | settings | stocks with a robust setting | test trades | win % | avg % |
|---|---|---|---|---|---|
| structure | 3240 | 100 | 790 | 61.6 | +0.411 |
| fvg | 3240 | 98 | 945 | 55.6 | +0.320 |
| ob | 3240 | 100 | 770 | 60.3 | +0.306 |
| vdelta | 3240 | 98 | 713 | 64.0 | +0.360 |
| pdhl | 144 | 90 | 814 | 50.5 | +0.317 |
| cpr | 192 | 99 | 899 | 48.5 | +0.265 |
| inside | 144 | 79 | 1262 | 46.7 | +0.138 |
| sweep | 144 | 95 | 1156 | 41.5 | +0.210 |
| odrive | 144 | 75 | 567 | 50.6 | +0.319 |
| round | 96 | 92 | 1232 | 43.0 | +0.220 |
| candle | 192 | 93 | 1367 | 44.5 | +0.205 |
| trend | 72 | 84 | 1120 | 49.0 | +0.233 |

Every number here is picked partly BY its test half (best of many), so it flatters; with only
~20 test days most stocks have a robust setting for most setups. New setups win less often
than the original four (their targets are wider); fewer of them pass the alert bar.
નવા setups ના આંકડા પણ overfit હોઈ શકે: પહેલાં paper-trade કરો.

**Confluence score 0-10** (`lab/score.py`): one point each for structure trend, a same-side
FVG/order block at the bar, near PDH/PDL/pivot, VWAP side, Nifty side, volume above the 20-bar
average, not a gap day, EMA9 vs EMA21, yesterday's close vs SMA20, and close vs today's open.
Every scan line and alert shows it ("score 7/10"). Replay of every stock's rank-1 setting:

| score | 0-3 | 4 | 5 | 6 | 7 | 8 | 9-10 |
|---|---|---|---|---|---|---|---|
| test avg % | +0.105 | +0.193 | +0.230 | +0.284 | +0.289 | +0.322 | +0.378 |
| train avg % | +0.172 | +0.161 | +0.177 | +0.189 | +0.197 | +0.211 | +0.171 |

The test half rises with the score, the train half does not (and for the original four setups
it falls), so alerts still rank by test average; `SCORE_RANK=1` ranks by score first.
score ફક્ત માહિતી માટે બતાવાય છે; ક્રમ હજી test average થી જ નક્કી થાય છે.

**Phase C: reports and honesty tools** (`lab/walkforward.py`, `lab/report.py`).

```bash
python3 lab/report.py weekly --state lab/alert_state.json   # this week's paper picks, phone-sized lines
python3 lab/walkforward.py --cache /tmp/y                   # walk-forward test, all Nifty 100 (~3 min)
python3 lab/report.py wf                                    # out-of-sample vs memory.json, per setup
python3 lab/report.py risk                                  # 2 picks/day OOS simulation, drawdown, Monte Carlo
python3 lab/report.py chart                                 # backtest_out/equity.svg (hand-written SVG)
python3 lab/report.py compare                               # top 10 stock + setup pairs out of sample
```

Weekly report: per pick result, trades, target/stop/close, win %, average, total, best and worst
setup, streaks. `alert.py --result` now keeps each day's outcomes in the state file
(`<day>#results`, picks and results kept 40 days); picks without one are graded from Yahoo.
અઠવાડિયાનો paper report: દરેક pick નું પરિણામ, જીત %, સરેરાશ અને streak, ફોનમાં વાંચી શકાય એવું.

**Walk-forward = the most honest number.** Train 25 days -> choose each stock's best setting per
setup from those days only -> trade it on the next 5 unseen days; step 5, 7 windows, 35
out-of-sample days. Run 2026-11-05, all 100 stocks, full grid:

| setup | OOS trades | OOS win % | OOS avg % | in-sample avg % (memory.json) |
|---|---|---|---|---|
| odrive | 520 | 41.7 | +0.139 | +0.319 |
| pdhl | 1479 | 38.6 | +0.016 | +0.317 |
| structure | 1644 | 45.0 | +0.010 | +0.411 |
| fvg | 1880 | 42.8 | +0.009 | +0.320 |
| cpr | 1607 | 34.0 | +0.003 | +0.265 |
| trend | 2044 | 39.1 | -0.002 | +0.233 |
| round | 2144 | 34.5 | -0.008 | +0.220 |
| vdelta | 1451 | 44.5 | -0.019 | +0.360 |
| inside | 2157 | 36.7 | -0.024 | +0.138 |
| ob | 1474 | 41.3 | -0.034 | +0.306 |
| candle | 2444 | 33.0 | -0.037 | +0.205 |
| sweep | 2035 | 32.7 | -0.044 | +0.210 |
| **all** | **20879** | **38.0** | **-0.009** | **+0.260** |

Out of sample the edge is about zero after the 0.05% cost: the in-sample numbers are mostly
selection luck. 2 picks/day like `alert.py` (quality bar on the train window, nifty/gap filters
not applied): 70 trades, 40% win, avg +0.045%, total +3.15% of one pick's money, max drawdown
10.3, longest losing streak 10; Monte Carlo (2000 reshuffles) drawdown 5.9 / 9.1 / 13.9 and
20-day return -14.6 / +1.0 / +17.8 (5th / 50th / 95th). With 40 train days the picks did
+0.19% a trade on 40 trades: still small and noisy.
walk-forward માં ધાર લગભગ શૂન્ય છે: memory.json ના આંકડા વધારે સારા દેખાય છે, real money પહેલાં paper-trade કરો.

**Smaller targets (`TARGET_R`, optional, off by default).** `TARGET_R=0.5 python3 lab/alert.py`
sets every pick's target to entry ± 0.5 × |entry − stop| (also for 15:15-exit setups); the pick
is saved with that target and `--result` grades with it. The stop does not move.

```bash
python3 lab/walkforward.py --cache /tmp/y --out-dir /tmp/wfR --out /tmp/wfR_out/walkforward.json --target-r 0.5,0.75,1,1.5
```

Same walk-forward (settings still chosen with their own targets on the train window only; only
the exit changes), run 2026-11-06, all 100 stocks, full grid, 35 OOS days (2026-09-17 to
2026-11-06). Win = target hit or closed positive; avg is after the 0.05% cost. "5 picks/day" =
alert-style picks (quality gate, best train average first, still live when the run sees it).

| target | all OOS trades | win % | stop-hit % | avg % | total % | 5 picks/day trades | win % | stop-hit % | avg % | total % |
|---|---|---|---|---|---|---|---|---|---|---|
| current | 21119 | 37.2 | 54.4 | -0.011 | -240.3 | 175 | 38.9 | 45.1 | +0.070 | +12.16 |
| 0.5R | 21119 | 63.5 | 33.1 | -0.055 | -1165.5 | 175 | 60.0 | 29.7 | -0.055 | -9.68 |
| 0.75R | 21119 | 55.1 | 39.9 | -0.048 | -1019.7 | 175 | 49.7 | 38.9 | -0.064 | -11.24 |
| 1.0R | 21119 | 49.5 | 44.4 | -0.039 | -831.4 | 175 | 47.4 | 38.9 | -0.032 | -5.56 |
| 1.5R | 21119 | 42.2 | 50.2 | -0.031 | -648.0 | 175 | 42.3 | 42.9 | +0.018 | +3.24 |

A smaller target does not move the stop. Stop-hits fall only because some trades that went
+0.5R first and then reversed now book the small target; 33% of all trades still hit the stop
before ever reaching +0.5R. Win % rises, but each win is smaller than each loss, so the average
per trade FALLS at every smaller target: the current targets were best out of sample. Keep
`TARGET_R` unset. (The baseline here, -0.011%, differs from -0.009% above because this run was a day later, so
the 60-day data window moved.)
નાનો target stop ને ખસેડતો નથી: જીત % વધે છે પણ સરેરાશ ઘટે છે, એટલે TARGET_R બંધ રાખો.

`lab/memory.json` is the lab's memory: for each stock and setup, how many settings were robust
(positive in BOTH the train and the test half) and the best three, plus a history of past runs.
The scan lists **every** trigger of the day with its status (live / target / stop / close), so
a signal that fired while you were away still shows, and it lists missing 5-minute bars.
Thousands of settings overfit: a robust setting is something to paper-trade, not a promise.

### Lab Phases D to M (2026-11-06)

Every tool below is plain Python (standard library only), reads free data, and places no orders.
Each prints "Educational only, not investment advice" next to any trade level.
દરેક tool ફક્ત શીખવા માટે છે: કોઈ broker નથી, કોઈ order નથી. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

**Phase D: F&O math** (`lab/fno.py`, `lab/lot_sizes.csv`).

```bash
python3 lab/fno.py price --spot 24000 --strike 24100 --days 6 --iv 13 --type C    # Black-Scholes + greeks
python3 lab/fno.py iv --spot 24000 --strike 24100 --days 6 --premium 95 --type C  # implied vol (bisection)
python3 lab/fno.py payoff iron_condor --strikes 23600,23800,24200,24400 --premiums 20,45,50,22 --symbol NIFTY
python3 lab/fno.py payoff custom --leg +C:24000:180 --leg -C:24300:70             # any legs
python3 lab/fno.py size --symbol NIFTY --premium 120 --lots 2 --capital 100000    # premium vs capital
python3 lab/fno.py chain NIFTY                                                     # NSE option chain (often blocked)
```

Payoff at expiry with breakevens and max profit / loss (unlimited is reported as such) for
straddle, strangle, bull/bear call and put spreads, iron condor, butterfly, covered call and
protective put. Lot sizes in `lab/lot_sizes.csv` are Nov 2026 values (NIFTY 65, BANKNIFTY 30):
**verify on NSE, lot sizes change**. Selling options needs exchange margin, which is not computed.

**Phase E: swing trading** (`lab/swing.py`), daily bars, long only, entry at the next open.

```bash
python3 lab/swing.py scan                    # today's breakout / pullback / 52-week-high setups
python3 lab/swing.py test --cache /tmp/yd    # 67/33 split with default settings
python3 lab/swing.py wf --cache /tmp/yd      # walk-forward, ~5 years, Nifty 100
```

Setups: close above the N-day high with volume >= V x average; pullback to EMA20/50 in an uptrend;
first close within X% of the 52-week high. Exits: ATR stop, R-multiple target, max hold days,
0.1% round-trip cost. Walk-forward run 2026-11-06 (95 stocks with 5 years of data, 2021-11 to
2026-11, train 500 / test 125 days, settings chosen on the train window pooled over all stocks):

| setup | OOS trades | OOS win % | OOS avg % | every-day baseline avg % |
|---|---|---|---|---|
| breakout | 585 | 39.1 | +0.023 | +0.298 |
| near52 | 816 | 45.5 | +0.802 | +0.587 |
| pullback | 1189 | 47.9 | +1.068 | +0.282 |
| **all** | **2590** | **45.1** | **+0.748** | **+0.381** |

By test window the OOS average was +2.34, -0.02, -0.41, +0.33, -0.51 % (positive in 2 of 5):
one strong 2023-24 bull window carries the pooled number. With default settings, the last 33% of
days lost money for all three setups (-0.24, -0.23, -0.08 % a trade). Today's Nifty 100 list is
used for the past (survivorship bias). **Verdict: no proven swing edge out of sample.**

**Phase F: Pine Script export** (`lab/pine.py` -> `pine/*.pine`).

```bash
python3 lab/pine.py                       # orb, fvg, structure (BOS/CHoCH), pdhl, cpr, swing_breakout
python3 lab/pine.py --symbol POWERGRID    # input defaults from that stock's best memory.json setting
```

TradingView Pine v5 indicators, commented, drawing levels and alerts only (no strategy orders).
Paste a file into the Pine editor. They follow the Python rules closely but not bar-for-bar.

**Phase G: sector and market strength** (`lab/sector.py`, `lab/sectors.csv`).

```bash
python3 lab/sector.py --stocks 10       # sector ranking by 1-month RS vs NIFTY, breadth, strongest stocks
SECTOR_STRONG=1 python3 lab/alert.py --dry-run   # optional: picks only from the top 3 sectors (OFF by default)
```

RS = stock return minus NIFTY return (1 week = 5 days, 1 month = 21). Breadth = % above EMA20 /
EMA50 and advances / declines. The sector filter has not been tested out of sample, so it is off.

**Phase H: journal analytics** (`lab/journal_stats.py`).

```bash
python3 lab/journal_stats.py --state lab/alert_state.json --paper backtest_out/paper.json
```

Expectancy (R and %), R-multiples, win rate and profit factor by setup, side, weekday and source,
streaks and drawdown, from the paper journal and the alert state (`<day>#picks`, `<day>#results`).

**Phase I: market regime** (`lab/regime.py`).

```bash
python3 lab/regime.py today --cache /tmp/yd       # trend-up / trend-down / range / high-vol
python3 lab/regime.py intraday --cache /tmp/yd    # lab setups by regime (needs walkforward.json)
python3 lab/regime.py swing --cache /tmp/yd       # swing setups by regime, 5 years
```

NIFTY regime from ADX14, ATR14 % (top 20% of 250 days = high-vol) and the EMA20 slope; intraday
trades use the regime known the evening before. An adaptive selector allows a setup only in
regimes where it was positive on earlier trades (>= 30 trades); checked by expanding walk-forward:

| test | all OOS trades | avg % | selector kept | avg % | blocks where kept beat all |
|---|---|---|---|---|---|
| intraday (35 OOS days, 5-day blocks) | 17926 | -0.004 | 3478 | +0.015 | 3 of 5 |
| swing (2024-03 to 2026-10, 125-day blocks) | 3332 | -0.168 | 2034 | +0.079 | 3 of 5 |

Intraday OOS trades did +0.067% on trend-up days and -0.029% on trend-down days (no range or
high-vol day in those 35 days). The selector raised the pooled average a little in both tests but
not consistently, and the intraday sample is very short. **It does not clearly help, so
`REGIME_SELECT` stays off** (`REGIME_SELECT=1` turns it on in `alert.py`).

**Phase J: NSE calendar** (`lab/calendar_nse.py`).

```bash
python3 lab/calendar_nse.py                 # trading day?, next NIFTY weekly / monthly and BANKNIFTY expiry
python3 lab/calendar_nse.py --month 2026-11 # 03 Nov, 09 Nov (Mon: 10th is a holiday), 17 Nov, 23 Nov
```

2026 holidays from NSE circulars 71775 / 71777 (+ 15 Jan via 72260). Since Sep 2025 NIFTY weekly
expires on Tuesday, NIFTY and BANKNIFTY monthly on the last Tuesday; a holiday moves the expiry
to the previous trading day. `alert.py` now skips NSE holidays and weekends quietly.

**Phase K: Facebook content helper** (`lab/content.py`).

```bash
python3 lab/content.py                    # today's first pick -> content_out/post.txt + chart.svg
python3 lab/content.py --day 2026-11-04 --pick 2
```

A short Gujarati + English post ("setup example", "rule output", never buy / sell words) and a
1080x1080 SVG chart with entry / stop / target lines, with the disclaimer
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી. It posts nothing: review before publishing.

**Phase L: easy runners.** `notebooks/trading_lab_colab.ipynb` (open in Google Colab, run the
cells: clone, scan, walk-forward report, swing) and `termux/run.sh` (Android Termux:
`pkg install -y python git`, clone, then `bash nse-day-trader-skill/termux/run.sh`).

**Phase M: docs.** This section, and [docs/GUJARATI_GUIDE.md](docs/GUJARATI_GUIDE.md): a simple
Gujarati guide to every tool. ગુજરાતી માર્ગદર્શિકા: દરેક tool કેવી રીતે ચલાવવું, અને સાચી વાત: હજી કોઈ સાબિત edge નથી.

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
                    filters.py, risk.py, evalfilters.py (Phase A), alert.py,
                    setups2.py, score.py, evalscore.py (Phase B),
                    walkforward.py, report.py (Phase C), fno.py + lot_sizes.csv (D),
                    swing.py (E), pine.py (F), sector.py + sectors.csv (G),
                    journal_stats.py (H), regime.py (I), calendar_nse.py (J), content.py (K)
pine/               TradingView Pine v5 indicators generated by lab/pine.py
notebooks/          trading_lab_colab.ipynb (Google Colab)
termux/             run.sh (Android Termux menu)
docs/               GUJARATI_GUIDE.md
backtest/           orb_grid_sym.py (ORB grid backtest), paper_journal.py (paper trades), educational
tests/              unittest suite + offline fixtures
```

MIT. Original pack by [Jake Schincariol](https://opusjake.ai); NSE/BSE port by Raju Megal.
