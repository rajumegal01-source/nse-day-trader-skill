"""Phase B check: setup table + does a higher confluence score mean a better trade?
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/evalscore.py --cache /tmp/y            # all stocks in memory.json (fetches Yahoo)
    python3 lab/evalscore.py --cache /tmp/y --json out.json

1) Per setup, from memory.json: stocks with a robust setting, and the pooled TEST record of each
   stock's best (rank 1) setting.
2) Replays every stock's rank-1 setting of every setup on ~60 days of 5-min bars (same 67/33
   split), scores each trade with score.py, and pools train / test trades per score bucket.
   monotonic() says whether the TEST average rises bucket by bucket (each bucket >= MIN_BUCKET
   trades); clear() also needs the TRAIN half's top bucket to beat its bottom bucket. Only a clear
   result justifies alert.py ranking by score (SCORE_RANK). CAVEAT: settings were chosen partly by
   their test half, so all averages flatter them.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import lab  # noqa: E402
import score  # noqa: E402

BUCKETS = ((0, 3), (4, 4), (5, 5), (6, 6), (7, 7), (8, 8), (9, 10))
MIN_BUCKET = 30


def bucket_name(s):
    for lo, hi in BUCKETS:
        if lo <= s <= hi:
            return "%d-%d" % (lo, hi) if lo != hi else str(lo)
    return "?"


def setup_table(mem):
    out = {}
    for sym, info in mem["stocks"].items():
        for k, v in info["setups"].items():
            t = out.setdefault(k, {"stocks": 0, "n": 0, "wins": 0.0, "tot": 0.0, "tested": v.get("tested")})
            if v["best"]:
                b = v["best"][0]["test"]
                t["stocks"] += 1
                t["n"] += b["n"]
                t["wins"] += b["win"] * b["n"] / 100.0
                t["tot"] += b["tot"]
    for t in out.values():
        t["win"] = round(100.0 * t["wins"] / t["n"], 1) if t["n"] else 0.0
        t["avg"] = round(t["tot"] / t["n"], 3) if t["n"] else 0.0
        del t["wins"]
        t["tot"] = round(t["tot"], 2)
    return out


def score_buckets(mem, cache, limit=None):
    NB = None
    try:
        NB = core.sessions(lab.cached_fetch("^NSEI", "60d", "5m", cache))[0]
    except Exception as e:
        print("^NSEI: data error (%s), nifty factor is 0" % type(e).__name__)
    pool = {}       # (half, bucket) -> [returns]
    per_score = {}
    syms = sorted(mem["stocks"])[:limit] if limit else sorted(mem["stocks"])
    for sym in syms:
        info = mem["stocks"][sym]
        try:
            B, gaps, bad, days, pctx = lab.prepare(sym, cache=cache)
        except Exception as e:
            print("%s: data error (%s), skipped" % (sym, type(e).__name__))
            continue
        if len(days) < 20:
            continue
        split = days[int(len(days) * 0.67)]
        ctx = score.Context(B, NB, pctx)
        for setup, s in info["setups"].items():
            if not s["best"] or setup not in lab.SETUPS:
                continue
            p = s["best"][0]["p"]
            fn, dparams = lab.SETUPS[setup]
            cands = fn(B, **{k: p[k] for k in dparams})
            for i, side, natural, _ in core.first_per_day(B, cands, p, pctx):
                st = core.stop_price(B[i]["c"], side, natural, p["stop"])
                r = core.simulate(B, i, side, st, p["tgt"])
                if r is None:
                    continue
                sc, _ = ctx.score(i, side)
                half = "train" if B[i]["day"] < split else "test"
                pool.setdefault((half, bucket_name(sc)), []).append(r[0])
                per_score.setdefault((half, sc), []).append(r[0])
    tab = {}
    for (half, bk), rs in pool.items():
        tab.setdefault(half, {})[bk] = lab.rnd(core.stats(rs))
    ps = {}
    for (half, sc), rs in per_score.items():
        ps.setdefault(half, {})[str(sc)] = lab.rnd(core.stats(rs))
    return tab, ps


def monotonic(tab, half="test", min_n=MIN_BUCKET, margin=0.05):
    """True when the average rises (never falls) from each bucket to the next, every bucket has
    >= min_n trades, and the top bucket beats the bottom by >= margin percentage points."""
    order = [bucket_name(lo) for lo, _ in BUCKETS]
    rows = [tab.get(half, {}).get(b) for b in order]
    if any(r is None or r["n"] < min_n for r in rows):
        return False
    ex = [r["exp"] for r in rows]
    return all(b >= a for a, b in zip(ex, ex[1:])) and ex[-1] - ex[0] >= margin


def clear(tab):
    """Test average rises bucket by bucket AND the train half agrees (top bucket > bottom)."""
    order = [bucket_name(lo) for lo, _ in BUCKETS]
    tr = [tab.get("train", {}).get(b) for b in order]
    return monotonic(tab) and bool(tr[0] and tr[-1]) and tr[-1]["exp"] > tr[0]["exp"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="setup table + score buckets (educational)")
    ap.add_argument("--memory", default=lab.MEMORY)
    ap.add_argument("--cache")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    mem = lab.load_memory(a.memory)
    st = setup_table(mem)
    print("setup      settings  robust stocks  test trades  win%%   avg%%")
    for k in lab.SETUPS:
        t = st.get(k)
        if t:
            print("%-10s %8s  %13d  %11d  %5.1f  %+.3f" % (k, t["tested"], t["stocks"], t["n"], t["win"], t["avg"]))
    tab, ps = score_buckets(mem, a.cache, a.limit)
    for half in ("train", "test"):
        print("\nscore bucket (%s half, every stock's rank-1 setting of every setup)" % half)
        for lo, _ in BUCKETS:
            r = tab.get(half, {}).get(bucket_name(lo))
            if r:
                print("  %-5s %5d trades  win %4.1f%%  avg %+.3f%%" % (bucket_name(lo), r["n"], r["win"], r["exp"]))
    mono, clr = monotonic(tab), clear(tab)
    print("\ntest average rises with score: %s; train agrees (clear): %s" % ("YES" if mono else "no",
                                                                           "YES" if clr else "no"))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"setups": st, "buckets": tab, "per_score": ps, "monotonic_test": mono, "clear": clr}, fh, indent=1)
    print("Educational only, not investment advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
