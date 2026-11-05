"""Swing trading lab (Phase E): multi-day setups on DAILY bars. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી. No broker, no orders.

    python3 lab/swing.py scan                         # today's setups on the Nifty 100 (last daily bar)
    python3 lab/swing.py test RELIANCE TCS            # 67/33 train/test split, default settings
    python3 lab/swing.py wf --cache /tmp/yd           # walk-forward over ~5 years, all Nifty 100
    python3 lab/swing.py wf --cache /tmp/yd --limit 30

Setups (signal on a day's CLOSE, entry at the NEXT day's open, long only):
  breakout   close above the highest high of the previous N days, volume >= V x its 20-day average
  pullback   uptrend (EMA20 > EMA50, EMA50 rising over 10 days); the day's low touches EMA E and the
             close is back above it
  near52     close first comes within X% of its 52-week (252-day) high
Exits: stop = entry - S x ATR14, target = entry + T x (entry - stop), out at the close after H days
(max hold). A gap through the stop or target fills at the open. Stop first when one day touches
both. 0.1% round-trip cost. One open trade per stock and setting at a time.

Walk-forward: train TRAIN (500) trading days -> test the next TEST (125), step TEST. In each window
every setup's setting is chosen on the train window only, POOLED over all stocks (the lab's robust
rule: inner 67/33 split, positive in both halves, ranked by the smaller average), then traded on
the unseen test days. Pooled test trades = out-of-sample (OOS). The baseline is the same exits
entered on EVERY day of the test windows: a setup only adds something if it beats that.
"""

import argparse
import itertools
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import lab  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "backtest_out", "swing_wf.json")
COST = 0.001                    # 0.1% round trip
TRAIN, TEST = 500, 125
MIN_A, MIN_B = 20, 10           # pooled trades in the inner train / inner test half
FOOT = "Educational only, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી."

SETUPS = {
    "breakout": dict(n=[20, 55], vmult=[1.5, 2.0]),
    "pullback": dict(e=[20, 50]),
    "near52": dict(pct=[2.0, 5.0]),
}
EXITS = dict(atr=[1.5, 2.5], tgt=[2.0, 3.0], hold=[10, 20])
DEFAULT = dict(breakout=dict(n=20, vmult=1.5), pullback=dict(e=20), near52=dict(pct=2.0))
DEFAULT_EXIT = dict(atr=2.0, tgt=2.0, hold=15)


# ------------------------------------------------------------------ data + indicators

def fetch_daily(sym, rng="5y", cache=None, tries=3):
    """Daily bars, oldest first, with retry and backoff (Yahoo is flaky)."""
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


def atr(D, n=14):
    """Simple average true range; None until n days are known."""
    tr = [D[0]["h"] - D[0]["l"]] + [max(D[i]["h"], D[i - 1]["c"]) - min(D[i]["l"], D[i - 1]["c"]) for i in range(1, len(D))]
    return [None if i < n - 1 else sum(tr[i - n + 1:i + 1]) / n for i in range(len(D))]


def signals(D, name, p):
    """Indexes i whose CLOSE gives a signal (entry at D[i+1] open)."""
    c = [b["c"] for b in D]
    out = []
    if name == "breakout":
        n = p["n"]
        for i in range(max(n, 20), len(D)):
            hh = max(b["h"] for b in D[i - n:i])
            av = sum(b["v"] for b in D[i - 20:i]) / 20.0
            if c[i] > hh and av > 0 and D[i]["v"] >= p["vmult"] * av:
                out.append(i)
    elif name == "pullback":
        e20, e50 = ema(c, 20), ema(c, 50)
        ee = e20 if p["e"] == 20 else e50
        for i in range(60, len(D)):
            if e20[i] > e50[i] and e50[i] > e50[i - 10] and D[i]["l"] <= ee[i] < c[i]:
                out.append(i)
    elif name == "near52":
        for i in range(252, len(D)):
            hi = max(b["h"] for b in D[i - 251:i + 1])
            near = c[i] >= hi * (1 - p["pct"] / 100.0)
            hip = max(b["h"] for b in D[i - 252:i])
            was = c[i - 1] >= hip * (1 - p["pct"] / 100.0)
            if near and not was:
                out.append(i)
    else:
        raise ValueError("unknown setup %s" % name)
    return out


def simulate(D, i, A, ex):
    """Enter at D[i+1] open. Returns (return, how, exit_index) or None (no next day / no ATR)."""
    if i + 1 >= len(D) or A[i] is None or A[i] <= 0:
        return None
    e = D[i + 1]["o"]
    stop = e - ex["atr"] * A[i]
    tgt = e + ex["tgt"] * (e - stop)
    last = min(i + ex["hold"], len(D) - 1)
    for j in range(i + 1, last + 1):
        b = D[j]
        if j > i + 1 and b["o"] <= stop:
            return b["o"] / e - 1 - COST, "stop", j
        if j > i + 1 and b["o"] >= tgt:
            return b["o"] / e - 1 - COST, "target", j
        if b["l"] <= stop:
            return stop / e - 1 - COST, "stop", j
        if b["h"] >= tgt:
            return tgt / e - 1 - COST, "target", j
    if last < i + ex["hold"]:
        return None                                  # not enough future days: still open
    return D[last]["c"] / e - 1 - COST, "time", last


def trades(D, A, sig, ex):
    """Non-overlapping trades: [(signal_day, ret, how, exit_day)]."""
    out, busy = [], -1
    for i in sig:
        if i <= busy:
            continue
        r = simulate(D, i, A, ex)
        if r is None:
            continue
        out.append((D[i]["day"], r[0], r[1], D[r[2]]["day"]))
        busy = r[2]
    return out


def settings():
    for name, dp in SETUPS.items():
        for dv in itertools.product(*dp.values()):
            for ev in itertools.product(*EXITS.values()):
                yield name, dict(zip(dp, dv)), dict(zip(EXITS, ev))


def stock_trades(D):
    """{(setup, pkey): [trade]} for every setting, plus the every-day baseline per exit key."""
    A = atr(D)
    out, sigc = {}, {}
    for name, p, ex in settings():
        k = (name, json.dumps(p, sort_keys=True))
        if k not in sigc:
            sigc[k] = signals(D, name, p)
        out[(name, json.dumps(dict(p, **ex), sort_keys=True))] = trades(D, A, sigc[k], ex)
    base = {}
    for ev in itertools.product(*EXITS.values()):
        ex = dict(zip(EXITS, ev))
        rs = []
        for i in range(252, len(D) - 1):
            r = simulate(D, i, A, ex)
            if r is not None:
                rs.append((D[i]["day"], r[0], r[1], D[r[2]]["day"]))
        base[json.dumps(ex, sort_keys=True)] = rs
    return out, base


# ------------------------------------------------------------------ stats + walk-forward

def stats(rs):
    if not rs:
        return dict(n=0, win=0.0, avg=0.0, tot=0.0)
    w = sum(1 for x in rs if x > 0)
    return dict(n=len(rs), win=round(100.0 * w / len(rs), 1), avg=round(100 * sum(rs) / len(rs), 3),
                tot=round(100 * sum(rs), 2))


def windows(days, train=TRAIN, test=TEST):
    out, s = [], 0
    while s + train < len(days):
        out.append((days[s:s + train], days[s + train:s + train + test]))
        s += test
    return out


def choose(pooled, name, train_days):
    """Best setting of one setup, chosen on the train window only. pooled = {(setup, pk): [trades]}."""
    t0, t1 = train_days[0], train_days[-1]
    cut = train_days[int(len(train_days) * 0.67)]
    best = None
    for (nm, pk), tr in pooled.items():
        if nm != name:
            continue
        a = [t[1] for t in tr if t0 <= t[0] < cut]
        b = [t[1] for t in tr if cut <= t[0] <= t1]
        if len(a) < MIN_A or len(b) < MIN_B:
            continue
        sa, sb = stats(a), stats(b)
        if sa["avg"] <= 0 or sb["avg"] <= 0:
            continue
        k = min(sa["avg"], sb["avg"])
        if best is None or k > best[0]:
            best = (k, pk, sa, sb)
    return None if best is None else best[1:]


def walk(pooled, base, days):
    """OOS trades of the walk-forward and the matching every-day baseline."""
    oos, bl, picks = [], [], []
    for w, (trd, ted) in enumerate(windows(days)):
        lo, hi = ted[0], ted[-1]
        for name in SETUPS:
            ch = choose(pooled, name, trd)
            if ch is None:
                picks.append(dict(window=w, setup=name, setting=None))
                continue
            pk, sa, sb = ch
            picks.append(dict(window=w, setup=name, setting=json.loads(pk), train_a=sa, train_b=sb))
            for t in pooled[(name, pk)]:
                if lo <= t[0] <= hi:
                    oos.append(dict(setup=name, day=t[0], pct=round(t[1] * 100, 4), how=t[2], window=w))
            ex = json.loads(pk)
            ek = json.dumps(dict((k, ex[k]) for k in EXITS), sort_keys=True)
            bl += [dict(setup=name, day=t[0], pct=round(t[1] * 100, 4), window=w) for t in base[ek] if lo <= t[0] <= hi]
    return oos, bl, picks


def pool_by(rows, key):
    g = {}
    for r in rows:
        g.setdefault(key(r), []).append(r["pct"] / 100.0)
    return dict((k, stats(v)) for k, v in sorted(g.items()))


def merge(per_stock):
    """[(sym, trades_dict, base_dict)] -> pooled dicts with the symbol inside each trade."""
    pooled, base = {}, {}
    for sym, tr, bs in per_stock:
        for k, v in tr.items():
            pooled.setdefault(k, []).extend(v)
        for k, v in bs.items():
            base.setdefault(k, []).extend(v)
    return pooled, base


# ------------------------------------------------------------------ CLI

def load_universe(a):
    syms = [s.upper() for s in getattr(a, "symbols", [])] or lab.nifty100()
    if getattr(a, "limit", None):
        syms = syms[:a.limit]
    return syms


def cmd_wf(a):
    syms = load_universe(a)
    per, days = [], set()
    for s in syms:
        try:
            D = fetch_daily(s, a.range, a.cache)
        except Exception as e:
            print("%s: data error (%s), skipped" % (s, type(e).__name__), flush=True)
            continue
        if len(D) < TRAIN + 60:
            print("%s: only %d days, skipped" % (s, len(D)))
            continue
        tr, bs = stock_trades(D)
        per.append((s, tr, bs))
        days |= {b["day"] for b in D}
    pooled, base = merge(per)
    days = sorted(days)
    oos, bl, picks = walk(pooled, base, days)
    res = dict(stocks=len(per), first=days[0] if days else None, last=days[-1] if days else None,
               train=TRAIN, test=TEST, windows=len(windows(days)), cost_pct=COST * 100,
               overall=stats([t["pct"] / 100 for t in oos]), baseline=stats([t["pct"] / 100 for t in bl]),
               by_setup=pool_by(oos, lambda t: t["setup"]), base_by_setup=pool_by(bl, lambda t: t["setup"]),
               by_window=pool_by(oos, lambda t: t["window"]), base_by_window=pool_by(bl, lambda t: t["window"]),
               picks=picks, trades=oos)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(res, fh)
    print(wf_text(res))
    return 0


def wf_text(res):
    o, b = res["overall"], res["baseline"]
    out = ["Swing walk-forward: %d stocks, %s to %s, %d windows (train %d / test %d days), cost %.1f%%" % (
        res["stocks"], res["first"], res["last"], res["windows"], res["train"], res["test"], res["cost_pct"]),
        "OUT-OF-SAMPLE: %d trades, %.1f%% win, avg %+.3f%% a trade" % (o["n"], o["win"], o["avg"]),
        "baseline (same exits, entered every day): %d trades, avg %+.3f%%" % (b["n"], b["avg"]),
        "setup       OOS n   win %   avg %   | baseline avg %"]
    for k, s in res["by_setup"].items():
        bb = res["base_by_setup"].get(k, {})
        out.append("%-10s %6d  %5.1f  %+7.3f  | %+7.3f" % (k, s["n"], s["win"], s["avg"], bb.get("avg", 0.0)))
    out.append("window   OOS n   avg %   | baseline avg %")
    for k, s in sorted(res["by_window"].items(), key=lambda kv: int(kv[0])):
        bb = res.get("base_by_window", {}).get(k, {})
        out.append("%-6s %7d  %+7.3f  | %+7.3f" % (k, s["n"], s["avg"], bb.get("avg", 0.0)))
    out.append("verdict: " + verdict(res))
    out.append("Survivorship bias: today's Nifty 100 list is used for the past, which flatters every number.")
    out.append(FOOT)
    return "\n".join(out)


def verdict(res):
    """'edge?' only when the pooled OOS average beats zero and the baseline AND most windows do too."""
    o, b = res["overall"], res["baseline"]
    ws = res["by_window"]
    bw = res.get("base_by_window", {})
    pos = sum(1 for s in ws.values() if s["avg"] > 0)
    beat = sum(1 for k, s in ws.items() if s["avg"] > bw.get(k, {}).get("avg", 0.0))
    if o["n"] < 30:
        return "too few OOS trades to say anything"
    if o["avg"] > 0 and o["avg"] > b["avg"] and pos * 3 >= len(ws) * 2 and beat * 3 >= len(ws) * 2:
        return "OOS above zero and the baseline in most windows: a lead to paper-trade, not proof"
    return ("no proven edge out of sample: positive in %d of %d windows, above the baseline in %d"
            % (pos, len(ws), beat))


def cmd_test(a):
    syms = load_universe(a)
    rows = {}
    for s in syms:
        try:
            D = fetch_daily(s, a.range, a.cache)
        except Exception as e:
            print("%s: data error (%s)" % (s, type(e).__name__))
            continue
        cut = D[int(len(D) * 0.67)]["day"]
        A = atr(D)
        for name in SETUPS:
            tr = trades(D, A, signals(D, name, DEFAULT[name]), DEFAULT_EXIT)
            rows.setdefault(name, [[], []])
            rows[name][0] += [t[1] for t in tr if t[0] < cut]
            rows[name][1] += [t[1] for t in tr if t[0] >= cut]
    print("default settings, exits %s; first 67%% of days = train, last 33%% = test" % DEFAULT_EXIT)
    for name, (tr, te) in rows.items():
        s1, s2 = stats(tr), stats(te)
        print("%-9s train %4d trades avg %+.3f%% | TEST %4d trades %.0f%% win avg %+.3f%%" % (
            name, s1["n"], s1["avg"], s2["n"], s2["win"], s2["avg"]))
    print(FOOT)
    return 0


def scan_one(sym, D):
    A = atr(D)
    i = len(D) - 1
    hits = []
    for name in SETUPS:
        if i in signals(D, name, DEFAULT[name]) and A[i]:
            e = D[i]["c"]
            st = e - DEFAULT_EXIT["atr"] * A[i]
            hits.append(dict(symbol=sym, setup=name, day=D[i]["day"], close=round(e, 2), stop=round(st, 2),
                             target=round(e + DEFAULT_EXIT["tgt"] * (e - st), 2), hold=DEFAULT_EXIT["hold"]))
    return hits


def cmd_scan(a):
    hits = []
    for s in load_universe(a):
        try:
            D = fetch_daily(s, "2y", a.cache)
        except Exception as e:
            print("%s: data error (%s)" % (s, type(e).__name__))
            continue
        hits += scan_one(s, D)
    if not hits:
        print("no swing setup on the last daily bar")
    for h in hits:
        print("%s %s %s: close %s | stop %s | target %s | max %d days (rule output, not a call)" % (
            h["day"], h["symbol"], h["setup"], h["close"], h["stop"], h["target"], h["hold"]))
    print("No setup has a proven out-of-sample edge (see `swing.py wf`).")
    print(FOOT)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="swing trading lab (educational)")
    sub = ap.add_subparsers(dest="cmd")
    for n in ("scan", "test", "wf"):
        p = sub.add_parser(n)
        p.add_argument("symbols", nargs="*")
        p.add_argument("--cache", help="folder of raw Yahoo files")
        p.add_argument("--limit", type=int)
        p.add_argument("--range", default="5y")
        if n == "wf":
            p.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    fn = dict(scan=cmd_scan, test=cmd_test, wf=cmd_wf).get(a.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(a)


if __name__ == "__main__":
    sys.exit(main())
