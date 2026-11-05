"""Walk-forward test: the most honest number the lab has. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/walkforward.py --cache /tmp/y                 # all Nifty 100 (about 1 min a stock)
    python3 lab/walkforward.py --cache /tmp/y --limit 30      # a fixed sample (first 30 symbols)
    python3 lab/walkforward.py --cache /tmp/y --grid reduced  # smaller exit grid, ~4x faster

Rolling windows over the ~60 days of 5-min bars: train TRAIN (25) days -> test the next TEST (5)
days, step STEP (5). In every window, for every stock and setup, the best setting is chosen ONLY
from the train window (the lab's robust rule, scaled to 25 days: inner 67/33 split, >= 4 and >= 3
trades, positive in both, ranked by the smaller average). That one setting is then traded on the
5 unseen test days. Pooling the test days of all windows gives truly out-of-sample (OOS) trades:
nothing in the choice knew them. Compare with memory.json, whose "test" numbers were partly used
to choose the settings and so flatter them.

Per stock results are cached in --out-dir (resumable); the pooled file is
backtest_out/walkforward.json, read by `lab/report.py risk|compare|chart`.
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
OUT = os.path.join(ROOT, "backtest_out", "walkforward.json")
TRAIN, TEST, STEP = 25, 5, 5
MIN_A, MIN_B = 4, 3            # inner train / inner test trades in a 25-day window (8 / 5 on ~60 days)
GATE_N, GATE_WIN, GATE_EXP = 8, 60.0, 0.15    # alert.py quality bar, applied to the train window

REDUCED_CORE = dict(side=["long", "both"], dead=[11 * 60 + 30, 14 * 60 + 30], stop=["natural", "p0.5", "p1.0"],
                    tgt=[1.5, 2, "eod"], filt=["none", "sma20"])


def windows(days, train=None, test=None, step=None):
    """[(train_days, test_days)]: train `train` days, then test the next `test` (last may be shorter)."""
    train, test, step = train or TRAIN, test or TEST, step or STEP
    out, s = [], 0
    while s + train < len(days):
        out.append((days[s:s + train], days[s + train:s + train + test]))
        s += step
    return out


def setting_trades(B, pctx, grid="full"):
    """Yield (setup, params, [(day, minute_of_close, side, ret, how, exit_minute)]) for every setting."""
    cache = {}
    for name, (fn, dparams) in lab.SETUPS.items():
        EX = lab.exits_for(name)
        if grid == "reduced" and EX is core.EXITS:
            EX = REDUCED_CORE
        for dvals in itertools.product(*dparams.values()):
            dp = dict(zip(dparams, dvals))
            cands = fn(B, **dp)
            for evals in itertools.product(*EX.values()):
                p = dict(zip(EX, evals))
                tr = []
                for i, side, natural, _ in core.first_per_day(B, cands, p, pctx):
                    st = core.stop_price(B[i]["c"], side, natural, p["stop"])
                    key = (i, side, st, p["tgt"])
                    if key not in cache:
                        cache[key] = core.simulate(B, i, side, st, p["tgt"])
                    r = cache[key]
                    if r is not None:
                        tr.append((B[i]["day"], B[i]["m"] + 5, side, r[0], r[1], B[r[2]]["m"]))
                yield name, dict(dp, **p), tr


def choose(settings, train_days):
    """Best setting of one setup from the train window only. settings = [(params, trades)].
    Returns (params, a_stats, b_stats, whole_window_stats, trades) or None."""
    tset = set(train_days)
    cut = train_days[int(len(train_days) * 0.67)]
    best = None
    for p, tr in settings:
        a = [t[3] for t in tr if t[0] in tset and t[0] < cut]
        b = [t[3] for t in tr if t[0] in tset and t[0] >= cut]
        if len(a) < MIN_A or len(b) < MIN_B:
            continue
        sa, sb = core.stats(a), core.stats(b)
        if sa["exp"] <= 0 or sb["exp"] <= 0:
            continue
        k = min(sa["exp"], sb["exp"])
        if best is None or k > best[0]:
            best = (k, p, sa, sb, core.stats(a + b), tr)
    return None if best is None else best[1:]


def walk_stock(sym, B, days, pctx, grid="full"):
    by_setup = {}
    for name, p, tr in setting_trades(B, pctx, grid):
        by_setup.setdefault(name, []).append((p, tr))
    trades = []
    for w, (trd, ted) in enumerate(windows(days)):
        tes = set(ted)
        for name, settings in by_setup.items():
            ch = choose(settings, trd)
            if ch is None:
                continue
            p, sa, sb, sw, tr = ch
            gate = sw["n"] >= GATE_N and sw["win"] >= GATE_WIN and sw["exp"] >= GATE_EXP
            for d, m, side, r, how, xm in tr:
                if d in tes:
                    trades.append(dict(symbol=sym, setup=name, day=d, time="%02d:%02d" % divmod(m, 60),
                                       side=side, pct=round(r * 100, 4), how=how,
                                       exit="%02d:%02d" % divmod(xm, 60), window=w,
                                       sel=round(min(sa["exp"], sb["exp"]), 4), train_n=sw["n"],
                                       train_win=round(sw["win"], 1), train_exp=round(sw["exp"], 4), gate=gate))
    return trades


def pool(trades, key=None):
    """{group: stats in %} of OOS trades; key(trade) -> group name (default: everything)."""
    g = {}
    for t in trades:
        g.setdefault(key(t) if key else "all", []).append(t["pct"])
    out = {}
    for k, rs in g.items():
        w = sum(1 for x in rs if x > 0)
        out[k] = dict(n=len(rs), win=round(100.0 * w / len(rs), 1), avg=round(sum(rs) / len(rs), 3),
                      tot=round(sum(rs), 2))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="walk-forward test (educational)")
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--cache", help="folder of raw Yahoo files (fetched there when missing)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--grid", choices=["full", "reduced"], default="full")
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "backtest_out", "wf"))
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--only-pool", action="store_true", help="just pool the per-stock files")
    a = ap.parse_args(argv)
    syms = [s.upper() for s in a.symbols] or lab.nifty100()
    if a.limit:
        syms = syms[:a.limit]
    os.makedirs(a.out_dir, exist_ok=True)
    for sym in ([] if a.only_pool else syms):
        f = os.path.join(a.out_dir, sym + ".json")
        if os.path.exists(f):
            continue
        t0 = time.time()
        try:
            B, gaps, bad, days, pctx = lab.prepare(sym, cache=a.cache)
        except Exception as e:
            print("%s: data error (%s), skipped" % (sym, type(e).__name__), flush=True)
            continue
        if len(days) < TRAIN + 5:
            print("%s: only %d clean days, skipped" % (sym, len(days)), flush=True)
            continue
        tr = walk_stock(sym, B, days, pctx, a.grid)
        with open(f + ".tmp", "w") as fh:
            json.dump({"symbol": sym, "days": len(days), "first": days[0], "last": days[-1],
                       "windows": len(windows(days)), "grid": a.grid, "trades": tr}, fh)
        os.replace(f + ".tmp", f)
        print("%s: %d days, %d OOS trades (%.0fs)" % (sym, len(days), len(tr), time.time() - t0), flush=True)
    docs = [json.load(open(os.path.join(a.out_dir, f))) for f in sorted(os.listdir(a.out_dir)) if f.endswith(".json")]
    docs = [d for d in docs if d["symbol"] in syms]
    trades = [t for d in docs for t in d["trades"]]
    res = {"stocks": len(docs), "symbols": [d["symbol"] for d in docs], "train": TRAIN, "test": TEST,
           "step": STEP, "grid": sorted({d["grid"] for d in docs}),
           "oos_days": sorted({t["day"] for t in trades}), "trades": trades,
           "by_setup": pool(trades, lambda t: t["setup"]), "overall": pool(trades).get("all")}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(res, fh)
    print("pooled %d stocks, %d OOS trades -> %s" % (len(docs), len(trades), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
