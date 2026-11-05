"""Market regime (Phase I): which kind of day is it, and do setups behave differently in each?
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/regime.py today --cache /tmp/yd            # today's NIFTY regime
    python3 lab/regime.py intraday --cache /tmp/yd         # lab setups (walk-forward OOS trades) by regime + selector test
    python3 lab/regime.py swing --cache /tmp/yd            # swing setups (5 years) by regime + selector test

Regime of a day, from NIFTY (^NSEI) daily bars up to that day's close:
  high-vol    ATR14 / close is in the top 20% of the last 250 days
  trend-up    otherwise, ADX14 >= 20 and EMA20 higher than 5 days ago
  trend-down  otherwise, ADX14 >= 20 and EMA20 lower than 5 days ago
  range       everything else
An intraday trade on day D uses the regime known at the close of the day BEFORE D (no look-ahead);
a swing signal on day D (entry the next open) uses the regime at D's close.

Adaptive selector: before each test block, look only at earlier trades, and allow a setup in a
regime when its average there was > 0 over >= MIN_N trades. Test-block trades are kept only when
their (setup, regime) was allowed. The walk-forward compares kept trades with all trades in the
same blocks. The selector is OFF in alert.py unless REGIME_SELECT=1 (see README for the verdict).
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WF = os.path.join(ROOT, "backtest_out", "walkforward.json")
TABLE = os.path.join(ROOT, "backtest_out", "regime_table.json")
REGIMES = ("trend-up", "trend-down", "range", "high-vol")
ADX_MIN, VOL_PCTL, VOL_LOOK, SLOPE_DAYS = 20.0, 0.8, 250, 5
MIN_N = 30
FOOT = "Educational only, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી."


# ------------------------------------------------------------------ indicators

def ema(xs, n):
    out, e, a = [], None, 2.0 / (n + 1)
    for x in xs:
        e = x if e is None else e + a * (x - e)
        out.append(e)
    return out


def wilder(xs, n):
    """Wilder smoothing (RMA); None for the first n-1 values."""
    out, s = [], None
    for i, x in enumerate(xs):
        if i < n - 1:
            out.append(None)
            continue
        s = sum(xs[:n]) / n if s is None else (s * (n - 1) + x) / n
        out.append(s)
    return out


def adx_atr(D, n=14):
    """(adx list, atr list), None where not yet known."""
    tr, pdm, mdm = [0.0], [0.0], [0.0]
    for i in range(1, len(D)):
        h, l, pc = D[i]["h"], D[i]["l"], D[i - 1]["c"]
        up, dn = h - D[i - 1]["h"], D[i - 1]["l"] - l
        tr.append(max(h, pc) - min(l, pc))
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
    atr, sp, sm = wilder(tr[1:], n), wilder(pdm[1:], n), wilder(mdm[1:], n)
    atr, sp, sm = [None] + atr, [None] + sp, [None] + sm
    dx = []
    for a, p, m in zip(atr, sp, sm):
        if a is None or a == 0:
            dx.append(None)
        else:
            pdi, mdi = 100 * p / a, 100 * m / a
            dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0.0)
    known = [x for x in dx if x is not None]
    first = dx.index(known[0]) if known else len(dx)
    adx = [None] * first + [x for x in wilder(dx[first:], n)] if known else [None] * len(dx)
    return adx, atr


def classify(D):
    """{day: regime} as of each day's close (None-free days only)."""
    c = [b["c"] for b in D]
    adx, atr = adx_atr(D)
    e20 = ema(c, 20)
    out = {}
    for i in range(len(D)):
        if adx[i] is None or atr[i] is None or i < 60:
            continue
        ap = atr[i] / c[i]
        hist = [atr[j] / c[j] for j in range(max(0, i - VOL_LOOK + 1), i + 1) if atr[j] is not None]
        rank = sum(1 for x in hist if x < ap) / float(len(hist))
        slope = e20[i] - e20[i - SLOPE_DAYS]
        if len(hist) >= 60 and rank >= VOL_PCTL:
            r = "high-vol"
        elif adx[i] >= ADX_MIN and slope > 0:
            r = "trend-up"
        elif adx[i] >= ADX_MIN and slope < 0:
            r = "trend-down"
        else:
            r = "range"
        out[D[i]["day"]] = r
    return out


def regime_before(regimes, day):
    """Regime known before `day` opens: the last classified day strictly before it."""
    ks = [d for d in regimes if d < day]
    return regimes[max(ks)] if ks else None


def tag(trades, regimes, intraday=True):
    """Adds 'regime' to each trade (dict with 'day')."""
    days = sorted(regimes)
    import bisect
    for t in trades:
        k = bisect.bisect_left(days, t["day"]) if intraday else bisect.bisect_right(days, t["day"])
        t["regime"] = regimes[days[k - 1]] if k > 0 else None
    return trades


# ------------------------------------------------------------------ stats + selector

def stats(ps):
    if not ps:
        return dict(n=0, win=0.0, avg=0.0)
    return dict(n=len(ps), win=round(100.0 * sum(1 for x in ps if x > 0) / len(ps), 1), avg=round(sum(ps) / len(ps), 4))


def by_regime(trades):
    """{setup: {regime: stats}} plus {'ALL': {regime: stats}}; pct in %."""
    g = {}
    for t in trades:
        if t.get("regime") is None:
            continue
        g.setdefault(t["setup"], {}).setdefault(t["regime"], []).append(t["pct"])
        g.setdefault("ALL", {}).setdefault(t["regime"], []).append(t["pct"])
    return dict((s, dict((r, stats(v)) for r, v in d.items())) for s, d in g.items())


def allowed(history, min_n=MIN_N):
    """{(setup, regime)} whose average in `history` trades is > 0 over >= min_n trades."""
    tab = by_regime(history)
    return set((s, r) for s, d in tab.items() if s != "ALL" for r, x in d.items() if x["n"] >= min_n and x["avg"] > 0)


def selector_walk(trades, block, min_n=MIN_N, warmup=1):
    """Expanding walk-forward of the selector. Blocks of `block` days that have trades;
    the first `warmup` blocks are history only. Returns per-block and pooled stats of all vs kept."""
    days = sorted({t["day"] for t in trades if t.get("regime")})
    blocks = [days[k:k + block] for k in range(0, len(days), block)]
    rows, all_p, kept_p = [], [], []
    for b in range(warmup, len(blocks)):
        lo, hi = blocks[b][0], blocks[b][-1]
        hist = [t for t in trades if t["day"] < lo and t.get("regime")]
        ok = allowed(hist, min_n)
        test = [t for t in trades if lo <= t["day"] <= hi and t.get("regime")]
        kept = [t for t in test if (t["setup"], t["regime"]) in ok]
        a, k = [t["pct"] for t in test], [t["pct"] for t in kept]
        all_p += a
        kept_p += k
        rows.append(dict(block=b, first=lo, last=hi, allowed=len(ok), all=stats(a), kept=stats(k)))
    return dict(blocks=rows, all=stats(all_p), kept=stats(kept_p))


def helps(res):
    """'clearly helps' = kept beats all pooled, kept > 0, >= 30 kept trades, and kept beats all in
    at least 2/3 of the blocks that kept something."""
    a, k = res["all"], res["kept"]
    bl = [r for r in res["blocks"] if r["kept"]["n"]]
    beat = sum(1 for r in bl if r["kept"]["avg"] > r["all"]["avg"])
    return bool(k["n"] >= 30 and k["avg"] > 0 and k["avg"] > a["avg"] and bl and beat * 3 >= 2 * len(bl))


# ------------------------------------------------------------------ alert hook

def filter_picks(hits, regime, table):
    """alert.py hook: keep hits whose setup averaged > 0 (>= MIN_N trades) in today's regime.
    table = {setup: {regime: stats}} (backtest_out/regime_table.json)."""
    out = []
    for h in hits:
        s = (table.get(h["setup"]) or {}).get(regime) or {}
        if s.get("n", 0) >= MIN_N and s.get("avg", 0) > 0:
            out.append(h)
    return out


# ------------------------------------------------------------------ CLI

def nifty(cache, rng="5y"):
    import swing
    return swing.fetch_daily("^NSEI", rng, cache)


def table_text(tab, title):
    out = [title, "setup        " + "".join("%-22s" % r for r in REGIMES)]
    for s in sorted(tab, key=lambda x: (x == "ALL", x)):
        cells = []
        for r in REGIMES:
            x = tab[s].get(r)
            cells.append("%-22s" % ("-" if not x else "%5d %+.3f%%" % (x["n"], x["avg"])))
        out.append("%-12s " % s + "".join(cells))
    return "\n".join(out)


def walk_text(res, unit):
    out = ["selector walk-forward (blocks of %s):" % unit, "block  first       last        allowed  all: n  avg %    | kept: n  avg %"]
    for r in res["blocks"]:
        out.append("%5d  %s  %s  %7d  %7d  %+.4f | %7d  %+.4f" % (r["block"], r["first"], r["last"], r["allowed"],
                                                                 r["all"]["n"], r["all"]["avg"], r["kept"]["n"], r["kept"]["avg"]))
    a, k = res["all"], res["kept"]
    out.append("OUT-OF-SAMPLE: all %d trades avg %+.4f%% | selector kept %d trades avg %+.4f%%" % (a["n"], a["avg"], k["n"], k["avg"]))
    out.append("verdict: %s" % ("the selector helped out of sample here (still not proof; off by default)" if helps(res)
                                else "the selector does NOT clearly help out of sample: keep it off"))
    return "\n".join(out)


def cmd_today(a):
    reg = classify(nifty(a.cache, "2y"))
    d = max(reg)
    print("NIFTY regime at the close of %s: %s" % (d, reg[d]))
    print("Last 10 days: " + ", ".join("%s %s" % (k[5:], reg[k]) for k in sorted(reg)[-10:]))
    print(FOOT)
    return 0


def cmd_intraday(a):
    if not os.path.exists(a.wf):
        print("no %s: run python3 lab/walkforward.py --cache /tmp/y first" % a.wf)
        return 1
    with open(a.wf) as fh:
        doc = json.load(fh)
    trades = [dict(day=t["day"], setup=t["setup"], pct=t["pct"]) for t in doc["trades"]]
    tag(trades, classify(nifty(a.cache)), intraday=True)
    tab = by_regime(trades)
    print(table_text(tab, "Lab setups, walk-forward OOS trades (%d stocks), n and avg %% a trade by regime" % doc["stocks"]))
    res = selector_walk(trades, a.block, a.min_n)
    print(walk_text(res, "%d days that have trades" % a.block))
    os.makedirs(os.path.dirname(a.table), exist_ok=True)
    with open(a.table, "w") as fh:
        json.dump(dict(source="walkforward OOS", table=tab, selector=dict(all=res["all"], kept=res["kept"],
                                                                          helps=helps(res))), fh)
    print("only %d OOS days: a regime table this short is a description, not evidence." % len({t["day"] for t in trades}))
    print(FOOT)
    return 0


def swing_trades(cache, syms):
    import swing
    out = []
    for s in syms:
        try:
            D = swing.fetch_daily(s, "5y", cache)
        except Exception as e:
            print("%s: data error (%s)" % (s, type(e).__name__))
            continue
        A = swing.atr(D)
        for name in swing.SETUPS:
            for t in swing.trades(D, A, swing.signals(D, name, swing.DEFAULT[name]), swing.DEFAULT_EXIT):
                out.append(dict(day=t[0], setup=name, pct=round(t[1] * 100, 4), symbol=s))
    return out


def cmd_swing(a):
    syms = lab.nifty100()[:a.limit] if a.limit else lab.nifty100()
    trades = swing_trades(a.cache, syms)
    tag(trades, classify(nifty(a.cache)), intraday=False)
    print(table_text(by_regime(trades), "Swing setups (default settings, %d stocks, ~5 years), n and avg %% by regime" % len(syms)))
    res = selector_walk(trades, a.block, a.min_n, warmup=a.warmup)
    print(walk_text(res, "%d days that have trades, first %d block(s) history only" % (a.block, a.warmup)))
    print("Survivorship bias: today's Nifty 100 list is used for the past.")
    print(FOOT)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="market regime (educational)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("today")
    p.add_argument("--cache")
    p = sub.add_parser("intraday")
    p.add_argument("--cache")
    p.add_argument("--wf", default=WF)
    p.add_argument("--table", default=TABLE)
    p.add_argument("--block", type=int, default=5)
    p.add_argument("--min-n", type=int, default=MIN_N)
    p = sub.add_parser("swing")
    p.add_argument("--cache")
    p.add_argument("--limit", type=int)
    p.add_argument("--block", type=int, default=125)
    p.add_argument("--warmup", type=int, default=4)
    p.add_argument("--min-n", type=int, default=MIN_N)
    a = ap.parse_args(argv)
    fn = dict(today=cmd_today, intraday=cmd_intraday, swing=cmd_swing).get(a.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
