"""Paper-trade journal for ORB signals. EDUCATIONAL ONLY: not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

Before real money, log 20-30 paper trades and see whether the rule still works live.
No broker, no orders: it only writes backtest_out/paper.json.

    python3 backtest/orb_grid_sym.py POWERGRID | python3 backtest/paper_journal.py add -
    python3 backtest/paper_journal.py add --symbol POWERGRID --side LONG --entry 260.5 --stop 257.89 --target 264.41 --date 2026-11-04 --time 11:05
    python3 backtest/paper_journal.py grade          # after 15:30 IST: target, stop or close, from Yahoo 5-min bars
    python3 backtest/paper_journal.py report         # trades, win %, average %, total %

Grading: after the entry time, the first 5-minute bar whose low reaches the stop (long) counts as
a stop, whose high reaches the target counts as a target; both in one bar counts as a stop (the
worse case). Otherwise the trade exits at the last bar before 15:15. Missing bars are listed as
gaps: a gap can hide a touch, so check those trades on your own chart and fix them with `set`.
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
COST = 0.0005  # 0.05% a trade, as in orb_grid_sym.py


def load(path):
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []


def save(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)


def bars(sym, day):
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s.NS?range=60d&interval=5m" % sym
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = json.load(urllib.request.urlopen(req, timeout=30))["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r["timestamp"]):
        if None in (q["high"][i], q["low"][i], q["close"][i]):
            continue
        ts = dt.datetime.fromtimestamp(t, IST)
        if ts.date().isoformat() == day:
            out.append((ts.strftime("%H:%M"), q["high"][i], q["low"][i], q["close"][i]))
    return out


def grade(tr, bl):
    have = {b[0] for b in bl}
    slots = ["%02d:%02d" % divmod(9 * 60 + 15 + 5 * k, 60) for k in range(75)]
    gaps = [s for s in slots if s > tr["time"] and s not in have]
    long_ = tr["side"] == "LONG"
    e, s, tg = tr["entry"], tr["stop"], tr.get("target")
    after = [b for b in bl if b[0] > tr["time"]]
    if not after:
        return None
    exit_px, how = None, None
    for t, hi, lo, cl in after:
        hit_s = lo <= s if long_ else hi >= s
        hit_t = tg is not None and (hi >= tg if long_ else lo <= tg)
        if hit_s:
            exit_px, how = s, "stop"
            break
        if hit_t:
            exit_px, how = tg, "target"
            break
        if t >= "15:15":
            exit_px, how = cl, "close"
            break
    if exit_px is None:
        exit_px, how = after[-1][3], "close"
    pct = ((exit_px - e) / e if long_ else (e - exit_px) / e) - COST
    return dict(exit=round(exit_px, 2), result=how, pct=round(pct * 100, 3), gaps=gaps)


def main(argv=None):
    ap = argparse.ArgumentParser(description="paper-trade journal (educational)")
    ap.add_argument("--file", default="backtest_out/paper.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("json", nargs="?", help="'-' to read orb_grid_sym.py output from stdin")
    for k in ("symbol", "side", "date", "time"):
        a.add_argument("--" + k)
    for k in ("entry", "stop", "target"):
        a.add_argument("--" + k, type=float)
    sub.add_parser("grade")
    sub.add_parser("report")
    st = sub.add_parser("set", help="fix a graded trade by hand after checking the chart")
    st.add_argument("n", type=int, help="trade number from report")
    st.add_argument("--exit", type=float, required=True)
    st.add_argument("--result", choices=["target", "stop", "close"], required=True)
    o = ap.parse_args(argv)
    rows = load(o.file)

    if o.cmd == "add":
        if o.json == "-":
            d = json.load(sys.stdin)
            sig = d.get("signal")
            if not sig:
                print("no signal today for %s: nothing logged" % d.get("symbol"))
                return 0
            tr = dict(symbol=d["symbol"], date=d["today"], time=sig["time"][:5], side=sig["side"],
                      entry=sig["entry"], stop=sig["stop"], target=sig["target"])
        else:
            if not all([o.symbol, o.side, o.date, o.time, o.entry, o.stop]):
                ap.error("add needs --symbol --side --date --time --entry --stop (and --target)")
            tr = dict(symbol=o.symbol.upper(), date=o.date, time=o.time, side=o.side.upper(),
                      entry=o.entry, stop=o.stop, target=o.target)
        if any(r["symbol"] == tr["symbol"] and r["date"] == tr["date"] for r in rows):
            print("already logged: %s %s" % (tr["symbol"], tr["date"]))
            return 0
        rows.append(tr)
        save(o.file, rows)
        print("logged #%d %s %s %s entry %s stop %s target %s" % (len(rows), tr["symbol"], tr["date"], tr["side"],
                                                                 tr["entry"], tr["stop"], tr["target"]))
    elif o.cmd == "grade":
        now = dt.datetime.now(IST)
        for r in rows:
            if "result" in r:
                continue
            if r["date"] == now.date().isoformat() and now.strftime("%H:%M") < "15:30":
                print("%s %s: market still open, grade after 15:30 IST" % (r["symbol"], r["date"]))
                continue
            g = grade(r, bars(r["symbol"], r["date"]))
            if g is None:
                print("%s %s: no bars from Yahoo yet" % (r["symbol"], r["date"]))
                continue
            r.update(g)
            warn = "  CHECK CHART, missing bars: %s" % ", ".join(g["gaps"]) if g["gaps"] else ""
            print("%s %s: %s at %s (%+.2f%%)%s" % (r["symbol"], r["date"], g["result"], g["exit"], g["pct"], warn))
        save(o.file, rows)
    elif o.cmd == "set":
        r = rows[o.n - 1]
        pct = ((o.exit - r["entry"]) if r["side"] == "LONG" else (r["entry"] - o.exit)) / r["entry"] - COST
        r.update(exit=o.exit, result=o.result, pct=round(pct * 100, 3), gaps=[], checked=True)
        save(o.file, rows)
        print("#%d fixed: %s at %s (%+.2f%%)" % (o.n, o.result, o.exit, r["pct"]))
    else:
        done = [r for r in rows if "result" in r]
        for i, r in enumerate(rows, 1):
            print("#%d %s %s %s %s" % (i, r["date"], r["symbol"], r["side"],
                                       "%s %+.2f%%" % (r["result"], r["pct"]) if "result" in r else "open"))
        if done:
            w = sum(1 for r in done if r["pct"] > 0)
            tot = sum(r["pct"] for r in done)
            print("graded %d: win %.0f%%, average %+.2f%%, total %+.2f%% (before tax and slippage)"
                  % (len(done), 100.0 * w / len(done), tot / len(done), tot))
            if len(done) < 20:
                print("only %d trades: too few to judge. Aim for 20-30 before any real money." % len(done))
        print("Educational only, not investment advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
