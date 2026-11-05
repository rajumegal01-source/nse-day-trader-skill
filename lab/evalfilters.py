"""Phase A check: does each optional filter / exit rule help the lab's remembered best settings?
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/evalfilters.py                         # all stocks in memory.json (fetches Yahoo)
    python3 lab/evalfilters.py --limit 30 --cache /tmp/y   # first 30, keep/reuse raw Yahoo files
    python3 lab/evalfilters.py --json out.json

For every stock and setup it takes the best remembered setting (rank 1) and replays it on the
same ~60 days of 5-min bars with the same train (first 67% of days) / test (last 33%) split,
once without anything and once with each filter or exit rule alone. Pooled trades, win % and
average % per trade are printed for both halves. CAVEAT: memory.json picked these settings
partly BY their test half, so the baseline test numbers flatter them; compare with vs without.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import filters  # noqa: E402
import lab  # noqa: E402
import risk  # noqa: E402

VARIANTS = [("baseline", [], [])] + [(n, [n], []) for n in filters.NAMES] + [(n, [], [n]) for n in risk.EXIT_NAMES] \
    + [("+".join(filters.DEFAULT), list(filters.DEFAULT), [])]


def load(sym, rng, iv, cache):
    p = os.path.join(cache, "%s_%s_%s.json" % (sym, rng, iv)) if cache else None
    if p and os.path.exists(p):
        with open(p, "rb") as fh:
            return core.parse(json.loads(fh.read()))
    return core.fetch(sym, rng, iv, cache)


def prepare(sym, cache):
    B, gaps = core.sessions(load(sym, "60d", "5m", cache))
    bad = {d for d, g in gaps.items() if len(g) > lab.MAX_GAPS}
    B = [b for b in B if b["day"] not in bad]
    daily = load(sym, "1y", "1d", cache)
    ctx = core.daily_context(daily)
    days = sorted({b["day"] for b in B})
    return B, daily, days, {d: core.prev_context(ctx, d) for d in days}


def run_setting(B, cands, p, pctx, split, flt=None, exits=()):
    if flt is not None:
        cands = flt.keep(cands)
    tr, te = [], []
    for i, side, natural, _ in core.first_per_day(B, cands, p, pctx):
        st = core.stop_price(B[i]["c"], side, natural, p["stop"])
        r = risk.simulate_ex(B, i, side, st, p["tgt"], exits)
        if r is not None:
            (tr if B[i]["day"] < split else te).append(r[0])
    return tr, te


def quality(best):
    t = best["test"]
    return t["n"] >= 8 and t["win"] >= 60 and t["exp"] >= 0.15


def evaluate(mem, syms, cache=None, variants=VARIANTS, log=print):
    NB, _ = core.sessions(load("^NSEI", "60d", "5m", cache))
    pool = {v[0]: {"all": ([], []), "quality": ([], [])} for v in variants}
    used = []
    for sym in syms:
        info = mem["stocks"].get(sym)
        if not info:
            continue
        try:
            B, daily, days, pctx = prepare(sym, cache)
        except Exception as e:
            log("%s: data error (%s), skipped" % (sym, e))
            continue
        if len(days) < 20:
            continue
        used.append(sym)
        split = days[int(len(days) * 0.67)]
        fobj = {}
        for name, fl, ex in variants:
            fobj[name] = filters.Filters(fl, B, daily, NB) if fl else None
        for setup, s in info["setups"].items():
            if not s["best"]:
                continue
            best = s["best"][0]
            fn, dparams = lab.SETUPS[setup]
            p = best["p"]
            cands = fn(B, **{k: p[k] for k in dparams})
            for name, fl, ex in variants:
                tr, te = run_setting(B, cands, p, pctx, split, fobj[name], ex)
                for grp in ("all", "quality") if quality(best) else ("all",):
                    pool[name][grp][0].extend(tr)
                    pool[name][grp][1].extend(te)
    out = {}
    for name in pool:
        out[name] = {g: {"train": lab.rnd(core.stats(a)), "test": lab.rnd(core.stats(b))} for g, (a, b) in pool[name].items()}
    return out, used


def table(res, grp="all"):
    base = res["baseline"][grp]
    rows = ["%-10s | %5s %5s %7s | %5s %5s %7s | %s" % ("variant", "testN", "win%", "avg%", "trN", "win%", "avg%", "test avg vs base")]
    for name, r in res.items():
        a, b = r[grp]["train"], r[grp]["test"]
        d = b["exp"] - base["test"]["exp"]
        rows.append("%-10s | %5d %5.1f %+7.3f | %5d %5.1f %+7.3f | %+.3f (%d%% of trades)"
                    % (name, b["n"], b["win"], b["exp"], a["n"], a["win"], a["exp"], d,
                       round(100.0 * b["n"] / base["test"]["n"]) if base["test"]["n"] else 0))
    return "\n".join(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Phase A filter/exit evaluation (educational)")
    ap.add_argument("--memory", default=lab.MEMORY)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--cache", help="folder for raw Yahoo files (reused when present)")
    ap.add_argument("--json", help="write the results here")
    a = ap.parse_args(argv)
    mem = lab.load_memory(a.memory)
    syms = sorted(mem["stocks"])[:a.limit] if a.limit else sorted(mem["stocks"])
    res, used = evaluate(mem, syms, a.cache)
    print("%d stocks, best remembered setting per setup, pooled. TEST = last 33%% of days." % len(used))
    print(table(res, "all"))
    print("\nonly settings that pass alert.py's quality bar (test n>=8, win>=60%, avg>=0.15%):")
    print(table(res, "quality"))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"stocks": used, "results": res}, fh, indent=1)
    print("Settings were chosen partly on the test half: small samples, overfitting likely. Educational only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
