"""Trading Lab: test our own indicators thousands of ways, remember what held up, scan every bar.
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/lab.py grid POWERGRID GRASIM        # 14,088 settings per stock -> lab/memory.json
    python3 lab/lab.py grid --nifty100 --limit 20   # many stocks (about 1 minute each)
    python3 lab/lab.py scan                         # every bar of today, for every remembered setting
    python3 lab/lab.py show POWERGRID               # what the lab remembers about a stock
    python3 lab/lab.py learn                        # after 15:30: grade today's triggers, retire losers
    python3 lab/lab.py lessons                      # what the lab has learned live
    python3 lab/lab.py daily                        # learn + re-test all Nifty 100 (GitHub Actions runs this)
    python3 lab/terminal.py                         # menu for Termux

Setups (see core.py): structure (BOS/CHoCH), fvg (fair value gap retest), ob (order block
retest), vdelta (volume-delta order-flow proxy + n-bar breakout). Each one is tested on
3 x 3 detection settings x 360 exits (side, entry cutoff, stop, target, daily filter) = 3,240,
so 12,960 settings per stock. Phase B (setups2.py): pdhl, cpr, inside, sweep, odrive,
round, candle, trend, each <= 8 detection settings x 24 exits (setups2.EXITS2), 1,128 more.
Every scan hit carries a confluence score 0-10 (score.py). `grid --setups X` re-tests only X and
keeps every other remembered setup of the stock. One trade per setting per day, entry on a bar's close, stop
first when a bar touches both, out at 15:15, 0.05% cost. First 67% of days train, last 33% test.

"robust" = at least 8 train trades, 5 test trades, and a positive average in BOTH halves.
Ranked by the smaller of the two averages. Thousands of settings overfit: a robust setting
is a candidate to paper-trade, not a promise.

Optional Phase A filters (filters.py) and exit rules (risk.py) are OFF here; scan_one takes them
as arguments for alert.py. grid and memory.json do not use them.

The scan reports EVERY trigger of the day with its status (live, target, stop, closed), so a
signal that fired while you were away still shows up. Missing 5-minute bars are listed: a gap
can hide a touch.
"""

import argparse
import datetime as dt
import itertools
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import filters  # noqa: E402
import risk  # noqa: E402
import score as cscore  # noqa: E402
import setups2  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
MEMORY = os.path.join(HERE, "memory.json")
NIFTY100 = os.path.join(HERE, "..", "trader-scanner", "nifty100.csv")
KEEP = 3          # best robust settings remembered per setup per stock
HISTORY = 60      # past grid results remembered per stock
MAX_GAPS = 3
SETUPS = dict(core.SETUPS, **setups2.SETUPS)      # Phase A setups + Phase B price-action setups


def exits_for(name):
    """Exit grid of a setup: the big core.EXITS for the original four, setups2.EXITS2 for Phase B."""
    return setups2.EXITS2 if name in setups2.SETUPS else core.EXITS


def n_settings_all():
    return core.n_settings() + sum(setups2.n_settings(k) for k in setups2.SETUPS)


def load_memory(path=MEMORY):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"stocks": {}, "history": {}}


def save_memory(mem, path=MEMORY):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(mem, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


def nifty100():
    import csv
    with open(NIFTY100, encoding="utf-8") as fh:
        return [r["Symbol"].strip().upper() for r in csv.DictReader(fh) if r.get("Symbol")]


def cached_fetch(sym, rng, iv, cache=None):
    """core.fetch, reusing a raw Yahoo file in `cache` when one exists (saved there otherwise)."""
    p = os.path.join(cache, "%s_%s_%s.json" % (sym, rng, iv)) if cache else None
    if p and os.path.exists(p):
        with open(p, "rb") as fh:
            return core.parse(json.loads(fh.read()))
    return core.fetch(sym, rng, iv, cache)


def prepare(sym, rng="60d", cache=None):
    raw = cached_fetch(sym, rng, "5m", cache)
    B, gaps = core.sessions(raw)
    bad = {d for d, g in gaps.items() if len(g) > MAX_GAPS}
    B = [b for b in B if b["day"] not in bad]
    ctx = core.daily_context(cached_fetch(sym, "1y", "1d", cache))
    days = sorted({b["day"] for b in B})
    pctx = {d: core.prev_context(ctx, d) for d in days}
    return B, gaps, sorted(bad), days, pctx


def grid_one(B, days, pctx, setups=None, retired=None):
    split = days[int(len(days) * 0.67)] if days else ""
    out = {}
    cache = {}
    for name, (fn, dparams) in SETUPS.items():
        if setups and name not in setups:
            continue
        tested, rows = 0, []
        dkeys = list(dparams)
        for dvals in itertools.product(*dparams.values()):
            dp = dict(zip(dkeys, dvals))
            cands = fn(B, **dp)
            EX = exits_for(name)
            ekeys = list(EX)
            for evals in itertools.product(*EX.values()):
                p = dict(zip(ekeys, evals))
                tested += 1
                if retired and pkey(dict(dp, **p)) in retired.get(name, ()):
                    continue                  # failed live: the lab learned not to use it
                tr, te = [], []
                for i, side, natural, _ in core.first_per_day(B, cands, p, pctx):
                    st = core.stop_price(B[i]["c"], side, natural, p["stop"])
                    key = (i, side, st, p["tgt"])
                    if key not in cache:
                        cache[key] = core.simulate(B, i, side, st, p["tgt"])
                    r = cache[key]
                    if r is None:
                        continue
                    (tr if B[i]["day"] < split else te).append(r[0])
                a, b = core.stats(tr), core.stats(te)
                if a["n"] >= 8 and b["n"] >= 5 and a["exp"] > 0 and b["exp"] > 0:
                    rows.append((min(a["exp"], b["exp"]), dict(dp, **p), a, b))
        rows.sort(key=lambda x: -x[0])
        uniq, sig = [], set()
        for row in rows:          # settings that took the very same trades count once
            k = (row[2]["n"], round(row[2]["tot"], 6), row[3]["n"], round(row[3]["tot"], 6))
            if k not in sig:
                sig.add(k)
                uniq.append(row)
        rows_best = uniq[:KEEP]
        out[name] = {"tested": tested, "robust": len(rows), "first": days[0] if days else None,
                     "last": days[-1] if days else None,
                     "best": [{"p": p, "train": rnd(a), "test": rnd(b)} for _, p, a, b in rows_best]}
    return out


def pkey(p):
    return json.dumps(p, sort_keys=True)


def rnd(s):
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()}


def cmd_grid(a):
    syms = nifty100() if a.nifty100 else [s.upper() for s in a.symbols]
    if a.limit:
        syms = syms[:a.limit]
    mem = load_memory(a.memory)
    today = dt.datetime.now(core.IST).date().isoformat()
    for sym in syms:
        t0 = time.time()
        try:
            B, gaps, bad, days, pctx = prepare(sym, cache=a.cache)
        except Exception as e:  # network or Yahoo error: skip, keep going
            print("%s: data error (%s), skipped" % (sym, e))
            continue
        if len(days) < 20:
            print("%s: only %d clean days, skipped" % (sym, len(days)))
            continue
        res = grid_one(B, days, pctx, a.setups, mem.get("retired", {}).get(sym))
        merged = dict((mem["stocks"].get(sym) or {}).get("setups") or {})
        merged.update(res)                # re-tested setups replace theirs, the others are kept
        mem["stocks"][sym] = {"date": today, "days": len(days), "first": days[0], "last": days[-1],
                              "skipped_gap_days": bad, "setups": merged}
        h = mem["history"].setdefault(sym, [])
        if not h or h[-1]["date"] != today:
            h.append({"date": today, "robust": {}, "best_test_exp": {}})
        h[-1]["robust"].update({k: v["robust"] for k, v in res.items()})
        h[-1]["best_test_exp"].update({k: (v["best"][0]["test"]["exp"] if v["best"] else None) for k, v in res.items()})
        del h[:-HISTORY]
        mem["updated"] = today
        mem["settings_per_stock"] = n_settings_all()
        save_memory(mem, a.memory)
        print("%s: %d days, %s  (%.0fs)" % (sym, len(days), ", ".join(
            "%s %d robust" % (k, v["robust"]) for k, v in res.items()), time.time() - t0))
    print("Educational only, not investment advice.")
    return 0


def scan_one(sym, info, day=None, at=None, flt=(), exits=(), NB=None, target_r=None):
    """flt = optional filter names (filters.py), exits = optional exit rules (risk.py), both off by
    default. NB = ^NSEI 5-min bars for the 'nifty' filter (fetched here when not given).
    target_r (alert.py TARGET_R): every target becomes entry +/- target_r x |entry - stop|, also
    for 'eod' settings; None keeps each setting's own target."""
    long_hist = "relvol" in flt or any(k in setups2.NEEDS_HISTORY for k in info["setups"])
    raw = core.fetch(sym, "1mo" if long_hist else "5d", "5m")
    B, gaps = core.sessions(raw)
    if not B:
        return [], []
    day = day or B[-1]["day"]
    if at is not None:
        B = [b for b in B if b["day"] < day or b["m"] + 5 <= at]
    B = [b for b in B if b["day"] <= day]
    days5 = sorted({b["day"] for b in B})[-5:]
    B5 = [b for b in B if b["day"] >= days5[0]] if days5 else B   # the original setups see 5 sessions, as before
    daily = core.fetch(sym, "3mo", "1d")
    ctx = core.daily_context(daily)
    pctx = {day: core.prev_context(ctx, day)}
    fo = None
    if flt:
        if "nifty" in flt and NB is None:
            NB, _ = core.sessions(core.fetch("^NSEI", "5d", "5m"))
        if NB is not None and at is not None:
            NB = [b for b in NB if b["day"] < day or b["m"] + 5 <= at]
        fo = filters.Filters(list(flt), B, daily, NB)
    gap_pct = filters.gap_by_day(B).get(day)
    sc = cscore.Context(B, NB, pctx)
    hits, seen = [], set()
    for setup, s in info["setups"].items():
        if setup not in SETUPS:
            continue                      # remembered by a newer lab version: skip, do not crash
        fn, dparams = SETUPS[setup]
        BB = B if setup in setups2.SETUPS else B5
        off = len(B) - len(BB)
        for k, best in enumerate(s["best"]):
            p = best["p"]
            dp = {x: p[x] for x in dparams}
            cands = [(c[0] + off,) + tuple(c[1:]) for c in fn(BB, **dp) if BB[c[0]]["day"] == day]
            if fo is not None:
                cands = fo.keep(cands)
            for i, side, natural, label in core.first_per_day(B, cands, p, pctx):
                st = core.stop_price(B[i]["c"], side, natural, p["stop"])
                e = B[i]["c"]
                if (side == 1 and st >= e) or (side == -1 and st <= e):
                    continue
                tm = p["tgt"] if target_r is None else target_r
                tgt = None if tm == "eod" else e + side * abs(e - st) * tm
                key = (setup, B[i]["m"], side)
                if key in seen:
                    continue
                seen.add(key)
                r = risk.simulate_ex(B, i, side, st, tm, exits)
                cs, cf = sc.score(i, side)
                status = "live" if r is None or (r[1] == "close" and B[-1]["m"] < core.EXIT_M) else r[1]
                hits.append(dict(symbol=sym, day=day, setup=setup, rank=k + 1, time="%02d:%02d" % divmod(B[i]["m"] + 5, 60),
                                 side="LONG" if side == 1 else "SHORT", entry=round(e, 2), stop=round(st, 2),
                                 target=None if tgt is None else round(tgt, 2), last=round(B[-1]["c"], 2),
                                 status=status, pct=None if status == "live" else round(r[0] * 100, 3),
                                 exit_time=None if r is None else "%02d:%02d" % divmod(B[r[2]]["m"], 60),
                                 p=best["p"], test=best["test"], score=cs, factors=cf,
                                 gap_pct=None if gap_pct is None else round(gap_pct, 2)))
    g = gaps.get(day, [])
    if at is not None:
        g = [x for x in g if int(x[:2]) * 60 + int(x[3:]) + 5 <= at]
    return hits, g


def cmd_scan(a):
    mem = load_memory(a.memory)
    syms = [s.upper() for s in a.symbols] or sorted(mem["stocks"])
    at = None
    if a.at:
        hh, mm = a.at.split(":")
        at = int(hh) * 60 + int(mm)
    allhits, gapnote = [], {}
    for sym in syms:
        info = mem["stocks"].get(sym)
        if not info or not any(v["best"] for v in info["setups"].values()):
            continue
        try:
            hits, gaps = scan_one(sym, info, a.day, at)
        except Exception as e:
            print("%s: data error (%s)" % (sym, e))
            continue
        allhits += hits
        if gaps:
            gapnote[sym] = gaps
    allhits.sort(key=lambda h: (h["status"] != "live", h["time"]))
    if a.json:
        print(json.dumps({"hits": allhits, "gaps": gapnote}, indent=1))
        return 0
    if not allhits:
        print("No trigger today for the remembered settings.")
    for h in allhits:
        print("%-11s %-9s %-5s %s entry %s stop %s target %s last %s  [%s]  score %d/10  test: %d trades, %.0f%% win, avg %+.2f%%"
              % (h["symbol"], h["setup"], h["side"], h["time"], h["entry"], h["stop"], h["target"], h["last"],
                 h["status"], h["score"], h["test"]["n"], h["test"]["win"], h["test"]["exp"]))
    for sym, g in gapnote.items():
        print("%s: missing 5-min bars %s (a touch may be hidden; check the chart)" % (sym, ", ".join(g)))
    print("Rule output from a backtest, not a buy/sell call. Educational only, not investment advice.")
    return 0


def bucket(t):
    return "09:15-11:00" if t <= "11:00" else ("11:00-13:00" if t <= "13:00" else "13:00-15:30")


def cmd_learn(a):
    """After the close: grade every trigger of the day, keep a live record of each remembered
    setting, retire settings that keep losing live, and update the lessons."""
    mem = load_memory(a.memory)
    live = mem.setdefault("live", {})
    retired = mem.setdefault("retired", {})
    journal = mem.setdefault("journal", {})
    day_hits, gaps_all = [], {}
    for sym, info in sorted(mem["stocks"].items()):
        if not any(v["best"] for v in info["setups"].values()):
            continue
        try:
            hits, gaps = scan_one(sym, info, a.day)
        except Exception as e:
            print("%s: data error (%s)" % (sym, e))
            continue
        day_hits += [h for h in hits if h["status"] != "live"]
        if gaps:
            gaps_all[sym] = gaps
    if not day_hits:
        print("nothing to learn: no closed trigger")
        return 0
    day = a.day or max(h.get("day", "") for h in day_hits) or dt.datetime.now(core.IST).date().isoformat()
    if day in journal and not a.force:
        print("already learned from %s (use --force to redo)" % day)
        return 0
    for h in day_hits:   # a missing bar between entry and exit may hide the real outcome
        h["gap"] = any(h["time"] <= g <= (h["exit_time"] or "15:25") for g in gaps_all.get(h["symbol"], []))
    journal[day] = [{k: h[k] for k in ("symbol", "setup", "side", "time", "entry", "stop", "target", "status", "pct", "gap")}
                    for h in day_hits]
    for d in sorted(journal)[:-HISTORY]:
        del journal[d]
    newly = 0
    for h in day_hits:
        if h["gap"]:
            continue                     # do not learn from an outcome a missing bar may hide
        rec = live.setdefault(h["symbol"], {}).setdefault(h["setup"], {}).setdefault(
            pkey(h["p"]), {"n": 0, "wins": 0, "tot": 0.0})
        rec["n"] += 1
        rec["wins"] += 1 if h["pct"] > 0 else 0
        rec["tot"] = round(rec["tot"] + h["pct"], 3)
        rec["last"] = day
        if rec["n"] >= 5 and rec["tot"] < 0:
            r = retired.setdefault(h["symbol"], {}).setdefault(h["setup"], [])
            if pkey(h["p"]) not in r:
                r.append(pkey(h["p"]))
                newly += 1
    lessons = {}
    for d, hs in journal.items():
        for h in hs:
            if h["pct"] is None or h.get("gap"):
                continue
            for key in (h["setup"], "%s %s" % (h["setup"], bucket(h["time"])), "%s %s" % (h["setup"], h["side"])):
                l = lessons.setdefault(key, {"n": 0, "wins": 0, "tot": 0.0})
                l["n"] += 1
                l["wins"] += 1 if h["pct"] > 0 else 0
                l["tot"] = round(l["tot"] + h["pct"], 3)
    mem["lessons"] = lessons
    save_memory(mem, a.memory)
    w = sum(1 for h in day_hits if h["pct"] > 0)
    print("%s: learned from %d triggers (%d won), %d settings retired, %d skipped for missing bars"
          % (day, len(day_hits), w, newly, sum(1 for h in day_hits if h["gap"])))
    return 0


def cmd_lessons(a):
    mem = load_memory(a.memory)
    ls = mem.get("lessons") or {}
    if not ls:
        print("no lessons yet: run `lab.py learn` after the close")
        return 0
    print("What the lab has seen live (last %d days of triggers):" % len(mem.get("journal", {})))
    for k in sorted(ls):
        l = ls[k]
        print("  %-28s %4d trades  win %3.0f%%  avg %+.2f%%" % (k, l["n"], 100.0 * l["wins"] / l["n"], l["tot"] / l["n"]))
    print("  retired settings: %d" % sum(len(x) for s in mem.get("retired", {}).values() for x in s.values()))
    print("Educational only, not investment advice.")
    return 0


def cmd_daily(a):
    """learn from today, then re-test every stock with today's bars included."""
    cmd_learn(a)
    a.symbols, a.nifty100, a.limit, a.setups, a.cache = [], True, None, None, None
    return cmd_grid(a)


def cmd_show(a):
    mem = load_memory(a.memory)
    info = mem["stocks"].get(a.symbol.upper())
    if not info:
        print("nothing remembered for %s: run `lab.py grid %s`" % (a.symbol.upper(), a.symbol.upper()))
        return 1
    print("%s  tested %s on %d days (%s to %s)" % (a.symbol.upper(), info["date"], info["days"], info["first"], info["last"]))
    for k, v in info["setups"].items():
        print("  %-9s %d of %d robust%s" % (k, v["robust"], v["tested"],
                                           "  (%s to %s)" % (v["first"], v["last"]) if v.get("first") else ""))
        for b in v["best"]:
            print("     test %d trades %.0f%% win avg %+.2f%% | train %d avg %+.2f%% | %s"
                  % (b["test"]["n"], b["test"]["win"], b["test"]["exp"], b["train"]["n"], b["train"]["exp"],
                     json.dumps(b["p"], sort_keys=True)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trading Lab (educational)")
    ap.add_argument("--memory", default=MEMORY)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("grid")
    g.add_argument("symbols", nargs="*")
    g.add_argument("--nifty100", action="store_true")
    g.add_argument("--limit", type=int)
    g.add_argument("--setups", nargs="*", choices=list(SETUPS))
    g.add_argument("--cache", help="folder of raw Yahoo files to reuse (e.g. from evalfilters --cache)")
    s = sub.add_parser("scan")
    s.add_argument("symbols", nargs="*")
    s.add_argument("--day", help="YYYY-MM-DD (default: the latest session)")
    s.add_argument("--at", help="HH:MM IST: only bars complete by then")
    s.add_argument("--json", action="store_true")
    w = sub.add_parser("show")
    w.add_argument("symbol")
    for name in ("learn", "daily"):
        l = sub.add_parser(name)
        l.add_argument("--day", help="YYYY-MM-DD (default: the latest session)")
        l.add_argument("--force", action="store_true")
    sub.add_parser("lessons")
    a = ap.parse_args(argv)
    if a.cmd == "grid" and not a.symbols and not a.nifty100:
        ap.error("grid needs symbols or --nifty100")
    return {"grid": cmd_grid, "scan": cmd_scan, "show": cmd_show, "learn": cmd_learn,
            "lessons": cmd_lessons, "daily": cmd_daily}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
