"""Sector and market strength (Phase G). EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/sector.py                     # sector ranking + market breadth, Nifty 100, daily closes
    python3 lab/sector.py --stocks 15         # also the 15 strongest stocks vs NIFTY
    python3 lab/sector.py --json

Relative strength (RS) = the stock's return minus NIFTY's (^NSEI) return over the same days, in
percentage points: 1 week = 5 trading days, 1 month = 21. A sector's RS is the plain average of its
stocks (lab/sectors.csv, editable). Breadth: % of stocks closing above their EMA20 / EMA50, and
advances / declines on the last day (close vs previous close).

Optional alert filter: SECTOR_STRONG=1 python3 lab/alert.py  keeps only picks whose sector is in
the top SECTOR_TOP (3) by 1-month RS. OFF by default: it has NOT been tested out of sample.
"""

import argparse
import csv
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SECTORS = os.path.join(HERE, "sectors.csv")
CACHE = os.path.join(HERE, "..", "backtest_out", "sector_today.json")
INDEX = "^NSEI"
W, M = 5, 21
SECTOR_TOP = int(os.environ.get("SECTOR_TOP", "3"))
FOOT = "Educational only, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી."


def load_sectors(path=SECTORS):
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in fh if not r.startswith("#")]
    return dict((r["symbol"].strip().upper(), r["sector"].strip()) for r in csv.DictReader(rows))


def fetch(sym, rng="6mo", cache=None, tries=3):
    for k in range(tries):
        try:
            return lab.cached_fetch(sym, rng, "1d", cache)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(2 ** (k + 1))


def ema(xs, n):
    out, e, a = [], None, 2.0 / (n + 1)
    for x in xs:
        e = x if e is None else e + a * (x - e)
        out.append(e)
    return out


def ret_on(closes, days, anchor, n):
    """Return (decimal) from `n` index-days before `anchor` to `anchor`, using the stock's last
    close on or before each date. closes = {day: close}; days = the index's sorted days."""
    if anchor not in days:
        return None
    k = days.index(anchor)
    if k - n < 0:
        return None

    def at(d):
        ks = [x for x in closes if x <= d]
        return closes[max(ks)] if ks else None
    a, b = at(days[k - n]), at(anchor)
    return None if not a or b is None else b / a - 1


def rs_rows(daily, index_bars, sectors):
    """[{symbol, sector, r1w, r1m, rs1w, rs1m}] in % (daily = {sym: bars})."""
    days = [b["day"] for b in index_bars]
    ic = dict((b["day"], b["c"]) for b in index_bars)
    anchor = days[-1]
    iw, im = ret_on(ic, days, anchor, W), ret_on(ic, days, anchor, M)
    out = []
    for sym, D in sorted(daily.items()):
        c = dict((b["day"], b["c"]) for b in D)
        rw, rm = ret_on(c, days, anchor, W), ret_on(c, days, anchor, M)
        if rw is None or rm is None or iw is None or im is None:
            continue
        out.append(dict(symbol=sym, sector=sectors.get(sym, "Other"), r1w=round(rw * 100, 2), r1m=round(rm * 100, 2),
                        rs1w=round((rw - iw) * 100, 2), rs1m=round((rm - im) * 100, 2)))
    return out, dict(day=anchor, r1w=None if iw is None else round(iw * 100, 2), r1m=None if im is None else round(im * 100, 2))


def sector_rank(rows):
    g = {}
    for r in rows:
        g.setdefault(r["sector"], []).append(r)
    out = []
    for s, rs in g.items():
        out.append(dict(sector=s, n=len(rs), rs1m=round(sum(r["rs1m"] for r in rs) / len(rs), 2),
                        rs1w=round(sum(r["rs1w"] for r in rs) / len(rs), 2),
                        up1m=round(100.0 * sum(1 for r in rs if r["rs1m"] > 0) / len(rs), 0)))
    out.sort(key=lambda x: (-x["rs1m"], -x["rs1w"]))
    for k, x in enumerate(out):
        x["rank"] = k + 1
    return out


def breadth(daily):
    """% above EMA20 / EMA50 and advance / decline on each stock's last bar."""
    n = a20 = a50 = adv = dec = unch = 0
    for D in daily.values():
        if len(D) < 51:
            continue
        c = [b["c"] for b in D]
        n += 1
        a20 += c[-1] > ema(c, 20)[-1]
        a50 += c[-1] > ema(c, 50)[-1]
        if c[-1] > c[-2]:
            adv += 1
        elif c[-1] < c[-2]:
            dec += 1
        else:
            unch += 1
    pct = (lambda x: round(100.0 * x / n, 1)) if n else (lambda x: 0.0)
    return dict(stocks=n, above_ema20=pct(a20), above_ema50=pct(a50), advances=adv, declines=dec, unchanged=unch,
                ad_ratio=round(adv / float(dec), 2) if dec else None)


def strong_sectors(rank, top=SECTOR_TOP):
    return set(x["sector"] for x in rank[:top])


def is_sector_strong(symbol, rank, sectors=None, top=SECTOR_TOP):
    sectors = sectors if sectors is not None else load_sectors()
    return sectors.get(symbol.upper()) in strong_sectors(rank, top)


def build(syms=None, cache=None):
    sectors = load_sectors()
    syms = syms or lab.nifty100()
    daily = {}
    for s in syms:
        try:
            daily[s] = fetch(s, "6mo", cache)
        except Exception as e:
            print("%s: data error (%s)" % (s, type(e).__name__))
    idx = fetch(INDEX, "6mo", cache)
    rows, nifty = rs_rows(daily, idx, sectors)
    return dict(day=nifty["day"], nifty=nifty, rows=rows, rank=sector_rank(rows), breadth=breadth(daily))


def today_rank(cache_file=CACHE, today=None, builder=build):
    """Sector ranking, built at most once a day (cached in backtest_out/) for alert.py's filter."""
    today = today or dt.datetime.now(lab.core.IST).date().isoformat()
    if os.path.exists(cache_file):
        with open(cache_file) as fh:
            doc = json.load(fh)
        if doc.get("built") == today:
            return doc["rank"]
    doc = builder()
    doc["built"] = today
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "w") as fh:
        json.dump(doc, fh)
    return doc["rank"]


def filter_picks(hits, rank, sectors=None, top=SECTOR_TOP):
    """The 'sector strong' alert hook: keep hits whose stock is in a top-`top` sector."""
    sectors = sectors if sectors is not None else load_sectors()
    keep = strong_sectors(rank, top)
    return [h for h in hits if sectors.get(h["symbol"].upper()) in keep]


def text(doc, stocks=0):
    n, b = doc["nifty"], doc["breadth"]
    out = ["Sector strength on %s (vs NIFTY: 1 week %+.2f%%, 1 month %+.2f%%)" % (doc["day"], n["r1w"] or 0, n["r1m"] or 0),
           "rank  sector                              stocks  RS 1m   RS 1w  beat NIFTY 1m"]
    for x in doc["rank"]:
        out.append("%3d.  %-35s %4d  %+6.2f  %+6.2f  %3.0f%%" % (x["rank"], x["sector"][:35], x["n"], x["rs1m"], x["rs1w"], x["up1m"]))
    out.append("Breadth (%d stocks): %.0f%% above EMA20, %.0f%% above EMA50 | advances %d, declines %d, unchanged %d" % (
        b["stocks"], b["above_ema20"], b["above_ema50"], b["advances"], b["declines"], b["unchanged"]))
    if stocks:
        out.append("Strongest stocks vs NIFTY (1 month):")
        for r in sorted(doc["rows"], key=lambda r: -r["rs1m"])[:stocks]:
            out.append("  %-12s %-28s RS 1m %+6.2f  1w %+6.2f" % (r["symbol"], r["sector"][:28], r["rs1m"], r["rs1w"]))
    out.append("Strength is a description of the past, not a forecast. " + FOOT)
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="sector strength + breadth (educational)")
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--cache")
    ap.add_argument("--stocks", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    doc = build([s.upper() for s in a.symbols] or None, a.cache)
    print(json.dumps(doc, indent=1) if a.json else text(doc, a.stocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
