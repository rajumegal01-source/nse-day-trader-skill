---
name: trader-bulkdeals
description: >-
  Bulk Deals and Insider Tracker for NSE, replacing the US Pelosi tracker. Shows today's NSE
  bulk and block deals from NSE's public archives (who bought or sold, how much, at what
  price, net by symbol), SAST Regulation 29 disclosures (holders crossing 5 % and 2 % changes,
  promoters flagged) and SEBI PIT insider-trading disclosures by promoters, directors and their
  relatives, with what is new since the last check. Use when the user says "bulk deals today",
  "block deals", "who bought RELIANCE", "promoter buying", "insider trades", "SAST
  disclosures", "FII/MF bulk deal", or on a schedule after the close.
argument-hint: "deals | sast --days 7 | insider SYMBOL | new"
---

# trader-bulkdeals (NSE)

The Bulk Deals and Insider Tracker reads public NSE disclosures of big trades and of what
insiders and large holders did. These are filings made after the fact. They are public, not
inside information, and they are not a signal to copy: a promoter's sale can be a pledge
invocation, a gift or estate planning, and a broker's bulk buy can be a client's or an
intraday flip (the same broker often shows on both sides).

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/deals.py" deals                         # today's bulk + block deals
python3 "${CLAUDE_SKILL_DIR}/deals.py" deals --symbols RELIANCE,TCS
python3 "${CLAUDE_SKILL_DIR}/deals.py" deals --min-cr 25 --client "mutual fund"
python3 "${CLAUDE_SKILL_DIR}/deals.py" deals --watchlist trader/watchlist.json
python3 "${CLAUDE_SKILL_DIR}/deals.py" sast --days 7 --promoters
python3 "${CLAUDE_SKILL_DIR}/deals.py" insider RELIANCE --market-only
python3 "${CLAUDE_SKILL_DIR}/deals.py" new                           # new since the last `new`
```

## What the disclosures are

| kind | rule | source |
| --- | --- | --- |
| bulk deal | all trades in a day by one client in one stock adding up to more than 0.5 % of the company's listed shares, normal market | SEBI master circular for stock exchanges, chapter 1 |
| block deal | one trade of ₹25 crore or more in a block window (08:45 to 09:00 and 14:05 to 14:20 IST), delivery only, since 8 Dec 2025 | SEBI circular SEBI/HO/MRD/POD-III/CIR/P/2025/134 (8 Oct 2025); NSE block deal FAQ |
| SAST Reg 29 | an acquirer crossing 5 %, and changes of 2 % after that | SEBI (SAST) Regulations, 2011 |
| PIT | trades by promoters, directors, KMP and their relatives above the disclosure limits | SEBI (PIT) Regulations, 2015 |

## Sources (free, public, no key)

- `https://archives.nseindia.com/content/equities/bulk.csv` and `.../block.csv` (today's deals;
  `NO RECORDS` on a quiet day)
- `https://www.nseindia.com/api/corporate-sast-reg29?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY`
- `https://www.nseindia.com/api/corporates-pit?index=equities&symbol=<SYMBOL>` (per symbol;
  the all-company date query answered empty when tested)

NSE answers a browser User-Agent only and may refuse a script at any time; the tool then says
which source failed. `--offline DIR` reads `bulk.csv`, `block.csv`, `sast.json`,
`pit-<SYM>.json`. State for `new`: `trader/state/deals.json` (45 days).

## Example (live, Mon 2 Nov 2026)

```
NSE bulk and block deals, 02-NOV-2026: 87 deals.
  bulk  EDELALTS    BUY       806,167 @ 1679.75       ₹135.42 cr  HDFC MUTUAL FUND
  bulk  RATNAVEER   SELL    1,600,595 @ 376.41         ₹60.25 cr  ARIHANT CAPITAL MARKETS LIMITED
  bulk  RATNAVEER   BUY     1,569,808 @ 377.20         ₹59.21 cr  ARIHANT CAPITAL MARKETS LIMITED
SAST: 02-Nov-2026 13:01 WAAREEENER Acquisition C T Doshi Family trust Reg29(2) promoter after: 44.14%
```

Block deals that day: none. The same broker buying and selling about the same quantity is
usually intraday market-making, not a view.

## Steps

1. After the close (bulk deals are published in the evening): `deals.py new` for the watchlist.
2. Say who, what side, how much in ₹ crore and the price, and the net by symbol.
3. For a stock the user is about to trade: `insider SYMBOL --market-only`.
4. Never say "smart money is buying"; say what was disclosed.

## What it never does

It never places, sizes or checks an order and never treats a disclosure as a tip.

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
