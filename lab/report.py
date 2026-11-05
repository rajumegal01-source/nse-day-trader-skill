"""Reports and honesty tools. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/report.py weekly --state lab/alert_state.json   # this week's paper picks, phone-sized
    python3 lab/walkforward.py --cache /tmp/y                   # first: the walk-forward test
    python3 lab/report.py wf                                    # OOS vs in-sample (memory.json), per setup
    python3 lab/report.py risk                                  # 2 picks/day OOS simulation, drawdown, Monte Carlo
    python3 lab/report.py chart                                 # backtest_out/equity.svg
    python3 lab/report.py compare                               # top stock + setup pairs out of sample

Units: every % is a percent of ONE pick's money, and the equity curve adds them up (each pick the
same rupee amount, no compounding). A drawdown of 3.0 means the curve fell 3 percentage points of
one pick's money from its high: with Rs 10,000 a pick, about Rs 300.
"""

import argparse
import datetime as dt
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
WF = os.path.join(ROOT, "backtest_out", "walkforward.json")
PAPER = os.path.join(ROOT, "backtest_out", "paper.json")
SVG = os.path.join(ROOT, "backtest_out", "equity.svg")
STATE = os.path.join(HERE, "alert_state.json")
MAX_PER_DAY = 2
FOOT = "શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી. Educational only, not investment advice."


# ------------------------------------------------------------------ math

def equity(rets):
    """Running sum of returns, starting at 0: [0, r1, r1+r2, ...]."""
    out, s = [0.0], 0.0
    for r in rets:
        s += r
        out.append(s)
    return out


def max_drawdown(rets):
    """Largest fall of the running sum from its previous high (>= 0, in the units of rets)."""
    peak, dd = 0.0, 0.0
    for v in equity(rets):
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def streaks(rets):
    """(longest win run, longest loss run, current run). A win is > 0; current is +k (k wins in a
    row at the end) or -k (k losses)."""
    lw = ll = cur = 0
    for r in rets:
        if r > 0:
            cur = cur + 1 if cur > 0 else 1
        else:
            cur = cur - 1 if cur < 0 else -1
        lw, ll = max(lw, cur), max(ll, -cur)
    return lw, ll, cur


def summary(rets):
    if not rets:
        return dict(n=0, win=0.0, avg=0.0, tot=0.0)
    w = sum(1 for r in rets if r > 0)
    return dict(n=len(rets), win=round(100.0 * w / len(rets), 1), avg=round(sum(rets) / len(rets), 3),
                tot=round(sum(rets), 2))


def percentile(xs, q):
    """Linear-interpolated percentile, q in 0..100."""
    s = sorted(xs)
    if not s:
        return 0.0
    k = (len(s) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def monte_carlo(rets, daily, runs=2000, horizon=20, seed=7, chunk=40):
    """Reshuffle the trade order `runs` times: max drawdown and longest losing run of each order.
    Bootstrap `horizon` days (with replacement) from daily sums: the 20-day return. `chunk` trades
    (about 20 days of 2 picks) give the losing run you should expect in a month."""
    rnd = random.Random(seed)
    dds, lls, lmon, hz = [], [], [], []
    xs = list(rets)
    for _ in range(runs):
        rnd.shuffle(xs)
        dds.append(max_drawdown(xs))
        lls.append(streaks(xs)[1])
        lmon.append(streaks(xs[:chunk])[1])
        hz.append(sum(rnd.choice(daily) for _ in range(horizon)) if daily else 0.0)
    pct = lambda v: {str(q): round(percentile(v, q), 2) for q in (5, 50, 95)}  # noqa: E731
    return dict(runs=runs, max_dd=pct(dds), loss_streak=pct(lls), loss_streak_40=pct(lmon),
                ret20=pct(hz), p_ret20_below0=round(100.0 * sum(1 for v in hz if v < 0) / max(len(hz), 1), 1),
                p_streak40_ge5=round(100.0 * sum(1 for v in lmon if v >= 5) / max(len(lmon), 1), 1))


# ------------------------------------------------------------------ 2 picks a day, like alert.py

def run_slot(hhmm):
    """alert.py runs every 15 minutes; a bar closing at hh:mm is seen by the next run at or after it."""
    h, m = map(int, hhmm.split(":"))
    t = h * 60 + m
    return -(-t // 15) * 15


def pick_day(trades, k=MAX_PER_DAY):
    """alert.py's choice on one day: runs in time order; in each run the still-live triggers that
    pass the quality gate, best train average (then win %) first, until k picks."""
    by_run = {}
    for t in trades:
        if not t.get("gate", True):
            continue
        r = run_slot(t["time"])
        xh, xm = map(int, t["exit"].split(":"))
        if xh * 60 + xm + 5 <= r:
            continue                  # already hit stop/target before the run saw it: not live
        by_run.setdefault(r, []).append(t)
    out = []
    for r in sorted(by_run):
        for t in sorted(by_run[r], key=lambda x: (-x["train_exp"], -x["train_win"], x["symbol"], x["setup"])):
            if len(out) < k:
                out.append(t)
    return out


def simulate_picks(trades, days, k=MAX_PER_DAY):
    """(picks in time order, {day: sum of that day's pick %} for every OOS day, 0 when none)."""
    by_day = {}
    for t in trades:
        by_day.setdefault(t["day"], []).append(t)
    picks, daily = [], {}
    for d in days:
        p = pick_day(by_day.get(d, []), k)
        picks += sorted(p, key=lambda x: x["time"])
        daily[d] = sum(x["pct"] for x in p)
    return picks, daily


# ------------------------------------------------------------------ weekly paper report

def grade_bars(bars, pick, cost=0.05):
    """Grade a pick on its day's 5-min bars [(start 'HH:MM', high, low, close)]: stop first when a
    bar touches both, else target, else the 15:15 bar's close (or the last bar). None: no bar after."""
    long_ = pick["side"] == "LONG"
    e, s, tg = pick["entry"], pick["stop"], pick.get("target")
    after = [b for b in bars if b[0] >= pick["time"]]
    if not after:
        return None
    px, how, at = after[-1][3], "close", after[-1][0]
    for t, hi, lo, cl in after:
        if (lo <= s) if long_ else (hi >= s):
            px, how, at = s, "stop", t
            break
        if tg is not None and ((hi >= tg) if long_ else (lo <= tg)):
            px, how, at = tg, "target", t
            break
        if t >= "15:15":
            px, how, at = cl, "close", t
            break
    pct = ((px - e) if long_ else (e - px)) / e * 100 - cost
    return dict(result=how, pct=round(pct, 3), exit=round(px, 2), exit_time=at)


def state_picks(state):
    """[(day, pick, result or None)] from an alert state file: '<day>#picks', '<day>#results'."""
    out = []
    for k in sorted(state):
        if not k.endswith("#picks"):
            continue
        day = k[:-6]
        res = {(r["symbol"], r["setup"], r["side"], r["time"]): r for r in state.get(day + "#results", [])}
        for p in state[k]:
            out.append((day, p, res.get((p["symbol"], p["setup"], p["side"], p["time"]))))
    return out


def fetch_day_bars(sym, day, cache=None):
    import core
    import lab
    B, _ = core.sessions(lab.cached_fetch(sym, "60d", "5m", cache))
    return [("%02d:%02d" % divmod(b["m"], 60), b["h"], b["l"], b["c"]) for b in B if b["day"] == day]


def weekly_rows(state, paper, since, until, fetch=None):
    """Rows {day, symbol, setup, side, time, result, pct} of picks/paper trades in [since, until]."""
    rows = []
    for day, p, r in state_picks(state):
        if not since <= day <= until:
            continue
        if r is None and fetch is not None:
            try:
                r = grade_bars(fetch(p["symbol"], day), p)
            except Exception:
                r = None
        rows.append(dict(day=day, symbol=p["symbol"], setup=p["setup"], side=p["side"], time=p["time"],
                         result=r["result"] if r else "open", pct=r["pct"] if r else None, src="pick"))
    for t in paper or []:
        if since <= t.get("date", "") <= until and t.get("pct") is not None:
            rows.append(dict(day=t["date"], symbol=t["symbol"], setup=t.get("setup", "orb"), side=t["side"],
                             time=t["time"], result=t["result"], pct=t["pct"], src="paper"))
    rows.sort(key=lambda x: (x["day"], x["time"]))
    return rows


def weekly_text(rows, since, until):
    out = ["📅 Weekly paper report %s → %s" % (since, until)]
    done = [r for r in rows if r["pct"] is not None]
    if not rows:
        return "\n".join(out + ["આ અઠવાડિયે કોઈ pick નથી (no picks this week).", FOOT])
    rets = [r["pct"] for r in done]
    s = summary(rets)
    cnt = {k: sum(1 for r in done if r["result"] == k) for k in ("target", "stop", "close")}
    out.append("Trades %d | target %d | stop %d | close %d%s" % (
        s["n"], cnt["target"], cnt["stop"], cnt["close"],
        " | open %d" % (len(rows) - len(done)) if len(rows) > len(done) else ""))
    if done:
        out.append("જીત (win) %.0f%% | avg %+.2f%% | total %+.2f%%" % (s["win"], s["avg"], s["tot"]))
        by = {}
        for r in done:
            by.setdefault(r["setup"], []).append(r["pct"])
        ranked = sorted(by.items(), key=lambda kv: -sum(kv[1]))
        b, w = ranked[0], ranked[-1]
        out.append("Best setup: %s %+.2f%% (%d)" % (b[0], sum(b[1]), len(b[1])))
        if len(ranked) > 1:
            out.append("Worst setup: %s %+.2f%% (%d)" % (w[0], sum(w[1]), len(w[1])))
        lw, ll, cur = streaks(rets)
        out.append("Streak: હમણાં %d %s | longest win %d, loss %d" % (abs(cur), "win" if cur > 0 else "loss", lw, ll))
    out.append("--")
    for r in rows:
        out.append("%s %s %s %s %s → %s" % (r["day"][5:], r["symbol"], r["setup"].upper(), r["side"], r["time"],
                                          "%s %+.2f%%" % (r["result"], r["pct"]) if r["pct"] is not None else "open"))
    out.append("Small sample: 1 અઠવાડિયું કંઈ સાબિત નથી કરતું.")
    out.append(FOOT)
    return "\n".join(out)


# ------------------------------------------------------------------ SVG equity chart (hand-written)

def nice_ticks(lo, hi, n=6):
    """Round tick values (1-2-5 steps) covering lo..hi."""
    import math
    raw = (hi - lo) / max(n - 1, 1)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    v = math.ceil(lo / step - 1e-9) * step
    out = []
    while v <= hi + 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def svg_equity(series, title, w=720, h=360):
    """series = [(label, colour, [y values])]; x = trade number. Self-contained SVG text."""
    pad_l, pad_r, pad_t, pad_b = 56, 16, 40, 44
    ys = [v for _, _, s in series for v in s] or [0.0]
    lo, hi = min(min(ys), 0.0), max(max(ys), 0.0)
    if hi - lo < 1e-9:
        hi = lo + 1.0
    n = max((len(s) for _, _, s in series), default=2)
    n = max(n, 2)
    X = lambda i: pad_l + (w - pad_l - pad_r) * i / (n - 1)        # noqa: E731
    Y = lambda v: pad_t + (h - pad_t - pad_b) * (hi - v) / (hi - lo)  # noqa: E731
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="Helvetica, Arial, sans-serif" font-size="12">' % (w, h, w, h),
         '<rect width="100%" height="100%" fill="#ffffff"/>',
         '<text x="%d" y="22" font-size="15" font-weight="bold" fill="#111">%s</text>' % (pad_l, esc(title))]
    for v in nice_ticks(lo, hi):
        o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#e5e5e5"/>' % (pad_l, w - pad_r, Y(v), Y(v)))
        o.append('<text x="%d" y="%.1f" text-anchor="end" fill="#555">%+.1f%%</text>' % (pad_l - 6, Y(v) + 4, v))
    o.append('<line x1="%d" x2="%d" y1="%.1f" y2="%.1f" stroke="#888" stroke-dasharray="4 3"/>'
             % (pad_l, w - pad_r, Y(0), Y(0)))
    o.append('<text x="%d" y="%d" text-anchor="middle" fill="#555">trade number (each pick = same rupee amount)</text>'
             % ((pad_l + w - pad_r) // 2, h - 10))
    o.append('<text x="%d" y="%d" fill="#555">0</text>' % (pad_l, h - pad_b + 16))
    o.append('<text x="%d" y="%d" text-anchor="end" fill="#555">%d</text>' % (w - pad_r, h - pad_b + 16, n - 1))
    for k, (label, col, s) in enumerate(series):
        if len(s) >= 2:
            pts = " ".join("%.1f,%.1f" % (X(i), Y(v)) for i, v in enumerate(s))
            o.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>' % (col, pts))
        lx = w - pad_r - 260
        ly = pad_t + 4 + 18 * k
        o.append('<line x1="%d" x2="%d" y1="%d" y2="%d" stroke="%s" stroke-width="3"/>' % (lx, lx + 18, ly, ly, col))
        o.append('<text x="%d" y="%d" fill="#222">%s</text>' % (lx + 24, ly + 4, esc(label)))
    o.append("</svg>")
    return "\n".join(o)


# ------------------------------------------------------------------ commands

def load_json(path, default=None):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def need_wf(path):
    doc = load_json(path)
    if not doc:
        print("no walk-forward results at %s: run `python3 lab/walkforward.py --cache /tmp/y` first" % path)
    return doc


def cmd_weekly(a):
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    until = a.until or dt.datetime.now(ist).date().isoformat()
    since = (dt.date.fromisoformat(until) - dt.timedelta(days=a.days - 1)).isoformat()
    state = load_json(a.state, {})
    paper = load_json(a.paper, [])
    fetch = None if a.no_fetch else (lambda s, d: fetch_day_bars(s, d, a.cache))
    print(weekly_text(weekly_rows(state, paper, since, until, fetch), since, until))
    return 0


def in_sample(memory):
    import evalscore
    import lab
    return evalscore.setup_table(lab.load_memory(memory))


def cmd_wf(a):
    doc = need_wf(a.wf)
    if not doc:
        return 1
    ins = in_sample(a.memory)
    print("Walk-forward: %d stocks, train %d → test %d days, step %d, %d OOS days (%s → %s)"
          % (doc["stocks"], doc["train"], doc["test"], doc["step"], len(doc["oos_days"]),
             doc["oos_days"][0], doc["oos_days"][-1]))
    print("OOS = truly unseen days. IS = memory.json test half (chosen partly by it).")
    for k in sorted(doc["by_setup"], key=lambda x: -doc["by_setup"][x]["avg"]):
        o, i = doc["by_setup"][k], ins.get(k, {})
        print("%-9s OOS %5d tr  win %4.1f%%  avg %+.3f%% | IS avg %+.3f%% win %4.1f%%"
              % (k, o["n"], o["win"], o["avg"], i.get("avg", 0.0), i.get("win", 0.0)))
    o = doc["overall"]
    n_is = sum(v["n"] for v in ins.values())
    avg_is = sum(v["tot"] for v in ins.values()) / n_is if n_is else 0.0
    print("ALL       OOS %5d tr  win %4.1f%%  avg %+.3f%% | IS avg %+.3f%%" % (o["n"], o["win"], o["avg"], avg_is))
    print("આ સૌથી પ્રામાણિક આંકડો છે (the most honest number). " + FOOT)
    return 0


def risk_numbers(doc, k=MAX_PER_DAY, runs=2000):
    picks, daily = simulate_picks(doc["trades"], doc["oos_days"], k)
    rets = [p["pct"] for p in picks]
    s = summary(rets)
    lw, ll, _ = streaks(rets)
    gated = [t["pct"] for t in doc["trades"] if t.get("gate", True)]
    return dict(picks=s, max_dd=round(max_drawdown(rets), 2), longest_loss=ll, longest_win=lw,
                days=len(daily), days_with_picks=len({p["day"] for p in picks}),
                mc=monte_carlo(rets, list(daily.values()), runs), gated_all=summary(gated),
                all_trades=summary([t["pct"] for t in doc["trades"]]), rets=rets,
                pick_list=picks)


def cmd_risk(a):
    doc = need_wf(a.wf)
    if not doc:
        return 1
    r = risk_numbers(doc, runs=a.runs)
    s, mc = r["picks"], r["mc"]
    print("OOS 2-picks/day simulation (%d stocks, %d OOS days)" % (doc["stocks"], r["days"]))
    print("Trades %d | win %.1f%% | avg %+.3f%% | total %+.2f%%" % (s["n"], s["win"], s["avg"], s["tot"]))
    print("Max drawdown %.2f | longest losing streak %d (win streak %d)" % (r["max_dd"], r["longest_loss"], r["longest_win"]))
    print("Monte Carlo %d reshuffles (5th / 50th / 95th):" % mc["runs"])
    print("  max drawdown   %.2f / %.2f / %.2f" % tuple(mc["max_dd"][q] for q in ("5", "50", "95")))
    print("  20-day return  %+.2f / %+.2f / %+.2f  (below 0: %.0f%%)" % (
        tuple(mc["ret20"][q] for q in ("5", "50", "95")) + (mc["p_ret20_below0"],)))
    print("  losing streak  %.0f / %.0f / %.0f (whole sample); in 40 trades %.0f / %.0f / %.0f, 5+ in a row %.0f%%" % (
        tuple(mc["loss_streak"][q] for q in ("5", "50", "95")) + tuple(mc["loss_streak_40"][q] for q in ("5", "50", "95"))
        + (mc["p_streak40_ge5"],)))
    g, al = r["gated_all"], r["all_trades"]
    print("For reference: every gated OOS trade %d, avg %+.3f%%; every OOS trade %d, avg %+.3f%%"
          % (g["n"], g["avg"], al["n"], al["avg"]))
    print("Units: % of one pick's money, summed (no compounding). Filters nifty/gap not applied. " + FOOT)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({k: v for k, v in r.items() if k not in ("rets", "pick_list")}, fh, indent=1)
    return 0


def cmd_chart(a):
    doc = load_json(a.wf)
    series = []
    if doc:
        rets = risk_numbers(doc, runs=1)["rets"]
        series.append(("walk-forward OOS, 2 picks/day (%d)" % len(rets), "#1f6feb", equity(rets)))
    rows = weekly_rows(load_json(a.state, {}), load_json(a.paper, []), "0000", "9999")
    pr = [r["pct"] for r in rows if r["pct"] is not None]
    if pr:
        series.append(("paper results (%d)" % len(pr), "#e8590c", equity(pr)))
    if not series:
        print("nothing to chart: run lab/walkforward.py first")
        return 1
    txt = svg_equity(series, "Equity curve, % of one pick's money (educational)")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(txt)
    print("wrote %s" % a.out)
    return 0


def compare_pairs(trades, min_n=5, top=10):
    by = {}
    for t in trades:
        by.setdefault((t["symbol"], t["setup"]), []).append(t["pct"])
    rows = [(k, summary(v)) for k, v in by.items() if len(v) >= min_n]
    rows.sort(key=lambda kv: (-kv[1]["avg"], -kv[1]["n"]))
    return rows[:top], len(rows)


def cmd_compare(a):
    doc = need_wf(a.wf)
    if not doc:
        return 1
    rows, total = compare_pairs(doc["trades"], a.min_n, a.top)
    print("Top %d stock + setup pairs by OOS avg (>= %d OOS trades; %d pairs qualify)" % (len(rows), a.min_n, total))
    for (sym, setup), s in rows:
        print("%-11s %-9s %3d tr  win %3.0f%%  avg %+.2f%%" % (sym, setup, s["n"], s["win"], s["avg"]))
    print("Best of %d pairs: some will be luck. Paper-trade first. %s" % (total, FOOT))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="reports and honesty tools (educational)")
    ap.add_argument("--wf", default=WF, help="walk-forward results (lab/walkforward.py)")
    ap.add_argument("--memory", default=os.path.join(HERE, "memory.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("weekly")
    w.add_argument("--state", default=STATE)
    w.add_argument("--paper", default=PAPER)
    w.add_argument("--days", type=int, default=7)
    w.add_argument("--until", help="YYYY-MM-DD (default today)")
    w.add_argument("--no-fetch", action="store_true", help="do not grade missing results from Yahoo")
    w.add_argument("--cache")
    sub.add_parser("wf")
    r = sub.add_parser("risk")
    r.add_argument("--runs", type=int, default=2000)
    r.add_argument("--json")
    c = sub.add_parser("chart")
    c.add_argument("--state", default=STATE)
    c.add_argument("--paper", default=PAPER)
    c.add_argument("--out", default=SVG)
    m = sub.add_parser("compare")
    m.add_argument("--min-n", type=int, default=5)
    m.add_argument("--top", type=int, default=10)
    a = ap.parse_args(argv)
    return {"weekly": cmd_weekly, "wf": cmd_wf, "risk": cmd_risk, "chart": cmd_chart, "compare": cmd_compare}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
