"""Journal analytics (Phase H): how the paper trades and daily picks actually did.
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/journal_stats.py                                  # both sources, default paths
    python3 lab/journal_stats.py --state lab/alert_state.json --paper backtest_out/paper.json
    python3 lab/journal_stats.py --since 2026-11-01 --json

Reads backtest_out/paper.json (backtest/paper_journal.py: graded rows with entry, stop, pct) and the
alert state file (lab/alert.py: '<day>#picks' with entry / stop and '<day>#results' with pct).
Only graded trades count. R-multiple = the trade's % result / its planned risk % (|entry - stop| /
entry), so -1R is a full stop-out (a bit worse after costs). Expectancy = average R (and average %).
Profit factor = sum of wins / |sum of losses|. Streaks: a 0% trade counts as a loss.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
FOOT = "Educational only, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી."


def r_multiple(pct, entry, stop):
    try:
        risk = abs(float(entry) - float(stop)) / float(entry) * 100
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return round(pct / risk, 3) if risk > 0 else None


def weekday(day):
    return DAYS[dt.date(*[int(x) for x in day.split("-")]).weekday()]


def collect(state=None, paper=None, since="", until="9999"):
    """Graded trades from both sources: [{day, symbol, setup, side, pct, r, src}]."""
    out = []
    for day, p, r in report.state_picks(state or {}):
        if r is None or r.get("pct") is None or not since <= day <= until:
            continue
        out.append(dict(day=day, symbol=p["symbol"], setup=p.get("setup", "?"), side=p.get("side", "?").upper(),
                        pct=float(r["pct"]), r=r_multiple(float(r["pct"]), p.get("entry"), p.get("stop")), src="pick",
                        result=r.get("result")))
    for t in paper or []:
        if t.get("pct") is None or not since <= t.get("date", "") <= until:
            continue
        out.append(dict(day=t["date"], symbol=t["symbol"], setup=t.get("setup", "orb"), side=t.get("side", "?").upper(),
                        pct=float(t["pct"]), r=r_multiple(float(t["pct"]), t.get("entry"), t.get("stop")), src="paper",
                        result=t.get("result")))
    out.sort(key=lambda x: (x["day"], x["symbol"]))
    return out


def stats(trades):
    ps = [t["pct"] for t in trades]
    if not ps:
        return dict(n=0)
    wins, losses = [x for x in ps if x > 0], [x for x in ps if x <= 0]
    rs = [t["r"] for t in trades if t["r"] is not None]
    gw, gl = sum(wins), -sum(losses)
    ws, ls, _ = report.streaks(ps)
    return dict(n=len(ps), win=round(100.0 * len(wins) / len(ps), 1), avg=round(sum(ps) / len(ps), 3),
                tot=round(sum(ps), 3), avg_win=round(gw / len(wins), 3) if wins else 0.0,
                avg_loss=round(-gl / len(losses), 3) if losses else 0.0,
                profit_factor=round(gw / gl, 2) if gl > 0 else None,
                exp_r=round(sum(rs) / len(rs), 3) if rs else None, n_r=len(rs),
                best=round(max(ps), 3), worst=round(min(ps), 3),
                win_streak=ws, loss_streak=ls, max_dd=round(report.max_drawdown(ps), 3))


def by(trades, key):
    g = {}
    for t in trades:
        g.setdefault(key(t), []).append(t)
    return dict((k, stats(v)) for k, v in sorted(g.items()))


def analyze(trades):
    return dict(overall=stats(trades), by_setup=by(trades, lambda t: t["setup"]), by_side=by(trades, lambda t: t["side"]),
                by_weekday=by(trades, lambda t: weekday(t["day"])), by_source=by(trades, lambda t: t["src"]),
                r_values=[t["r"] for t in trades if t["r"] is not None])


def line(name, s):
    if not s.get("n"):
        return "%-10s no graded trades" % name
    pf = "-" if s["profit_factor"] is None else "%.2f" % s["profit_factor"]
    er = "-" if s["exp_r"] is None else "%+.2fR" % s["exp_r"]
    return "%-10s %4d trades  win %5.1f%%  avg %+.3f%%  exp %s  PF %s" % (name, s["n"], s["win"], s["avg"], er, pf)


def text(res):
    o = res["overall"]
    out = ["Journal analytics (graded paper trades + daily picks)"]
    if not o.get("n"):
        out += ["no graded trades yet: log paper trades or let lab/alert.py --result grade the picks.", FOOT]
        return "\n".join(out)
    out.append(line("ALL", o))
    out.append("avg win %+.3f%% | avg loss %+.3f%% | best %+.3f%% | worst %+.3f%% | streaks: %d wins, %d losses | "
               "max drawdown %.2f%% points" % (o["avg_win"], o["avg_loss"], o["best"], o["worst"], o["win_streak"],
                                              o["loss_streak"], o["max_dd"]))
    for title, key in (("by setup", "by_setup"), ("by side", "by_side"), ("by weekday", "by_weekday"),
                       ("by source", "by_source")):
        out.append(title + ":")
        for k, s in res[key].items():
            out.append("  " + line(k, s))
    if o["n"] < 30:
        out.append("only %d graded trades: far too few to judge any edge (aim for 30+, and compare with the "
                   "walk-forward out-of-sample numbers)." % o["n"])
    out.append(FOOT)
    return "\n".join(out)


def load(path, default):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def main(argv=None):
    ap = argparse.ArgumentParser(description="journal analytics (educational)")
    ap.add_argument("--state", default=report.STATE)
    ap.add_argument("--paper", default=report.PAPER)
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="9999")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    trades = collect(load(a.state, {}), load(a.paper, []), a.since, a.until)
    res = analyze(trades)
    print(json.dumps(res, indent=1) if a.json else text(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
