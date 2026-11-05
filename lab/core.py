"""Trading Lab core: data, indicators, signals, trade simulation. EDUCATIONAL ONLY.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

Indicators (all from free 5-minute OHLCV bars, no tick data):
  swings      pivot highs/lows with L bars on each side (confirmed L bars later)
  structure   BOS (break of structure, trend continues) and CHoCH (change of character, trend flips)
  fvg         fair value gap: bar i's low above bar i-2's high (bullish), or the mirror (bearish)
  ob          order block: the last opposite candle before a BOS, traded on its first retest
  vdelta      order-flow PROXY: delta = volume * (close-low - (high-close)) / (high-low).
              Real order flow needs tick / bid-ask data, which free sources do not give.
"""

import datetime as dt
import json
import os
import urllib.parse
import urllib.request

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
OPEN_M, LAST_M = 9 * 60 + 15, 15 * 60 + 25          # first and last 5-minute bar of a session
SLOTS = list(range(OPEN_M, LAST_M + 1, 5))           # 75 bars
EXIT_M = 15 * 60 + 15                                # square off from the 15:15 bar
COST = 0.0005                                        # 0.05% a trade


# ------------------------------------------------------------------ data

def fetch(sym, rng, iv, cache_dir=None):
    ysym = sym if sym.startswith("^") else sym + ".NS"           # ^NSEI is an index: no .NS
    url = "https://query2.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s" % (
        urllib.parse.quote(ysym), rng, iv)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=30).read()
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "%s_%s_%s.json" % (sym, rng, iv)), "wb") as fh:
            fh.write(raw)
    return parse(json.loads(raw))


def parse(doc):
    r = doc["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        ts = dt.datetime.fromtimestamp(t, IST)
        out.append(dict(day=ts.date().isoformat(), m=ts.hour * 60 + ts.minute,
                        o=o, h=h, l=l, c=c, v=q["volume"][i] or 0))
    return out


def sessions(bars5):
    """Keep on-grid session bars, one per slot; return (bars, {day: missing 'HH:MM' list})."""
    seen, out = set(), []
    for b in bars5:
        if b["m"] in SLOTS and (b["day"], b["m"]) not in seen:
            seen.add((b["day"], b["m"]))
            out.append(b)
    out.sort(key=lambda b: (b["day"], b["m"]))
    have = {}
    for b in out:
        have.setdefault(b["day"], set()).add(b["m"])
    gaps = {d: ["%02d:%02d" % divmod(m, 60) for m in SLOTS if m not in s] for d, s in have.items()}
    return out, gaps


def daily_context(daily):
    """{day: (rsi14, close, sma20)} of each daily bar, used for the NEXT day's filter."""
    cl = [b["c"] for b in daily]
    rs = [None] * len(cl)
    if len(cl) > 15:
        g = [max(cl[i] - cl[i - 1], 0) for i in range(1, len(cl))]
        ls = [max(cl[i - 1] - cl[i], 0) for i in range(1, len(cl))]
        ag, al = sum(g[:14]) / 14, sum(ls[:14]) / 14
        for i in range(14, len(g)):
            ag, al = (ag * 13 + g[i]) / 14, (al * 13 + ls[i]) / 14
            rs[i + 1] = 100 - 100 / (1 + ag / al) if al else 100.0
    out = {}
    for i, b in enumerate(daily):
        if i >= 19 and rs[i] is not None:
            out[b["day"]] = (rs[i], cl[i], sum(cl[i - 19:i + 1]) / 20)
    return out


def prev_context(ctx, day):
    ks = [k for k in ctx if k < day]
    return ctx[max(ks)] if ks else None


def filter_ok(f, side, c):
    if f == "none":
        return True
    if c is None:
        return False
    r, cl, sma = c
    if f == "sma20":
        return cl > sma if side == 1 else cl < sma
    if f == "rsi50":
        return r > 50 if side == 1 else r < 50
    return True


# ------------------------------------------------------------------ indicators
# Every detector returns candidates: (index, side, natural_stop, label). index = the bar on whose
# CLOSE the signal is known, so a trade enters at that close and nothing looks ahead.

def swings(B, L):
    """[(confirm_index, 'H'|'L', pivot_index, price)] in confirm order."""
    out = []
    for i in range(L, len(B) - L):
        win = B[i - L:i + L + 1]
        if B[i]["h"] == max(x["h"] for x in win) and B[i]["h"] > B[i - 1]["h"]:
            out.append((i + L, "H", i, B[i]["h"]))
        if B[i]["l"] == min(x["l"] for x in win) and B[i]["l"] < B[i - 1]["l"]:
            out.append((i + L, "L", i, B[i]["l"]))
    out.sort()
    return out


def structure(B, L):
    """BOS / CHoCH events: [(index, side, kind, broken_level, opposite_swing_price)]."""
    sw = swings(B, L)
    k, hi, lo, trend, ev = 0, None, None, 0, []
    for i, b in enumerate(B):
        while k < len(sw) and sw[k][0] <= i:
            _, t, _, p = sw[k]
            if t == "H":
                hi = [p, False]
            else:
                lo = [p, False]
            k += 1
        if hi and not hi[1] and b["c"] > hi[0]:
            ev.append((i, 1, "bos" if trend == 1 else "choch", hi[0], lo[0] if lo else None))
            hi[1], trend = True, 1
        if lo and not lo[1] and b["c"] < lo[0]:
            ev.append((i, -1, "bos" if trend == -1 else "choch", lo[0], hi[0] if hi else None))
            lo[1], trend = True, -1
    return ev


def cand_structure(B, L, event):
    out = []
    for i, side, kind, lvl, opp in structure(B, L):
        if event != "both" and kind != event:
            continue
        out.append((i, side, opp, kind))
    return out


def fvgs(B, minpct):
    """[(index_formed, side, bottom, top)]: bullish gap = (B[i-2].h, B[i].l)."""
    out = []
    for i in range(2, len(B)):
        a, c = B[i - 2], B[i]
        if a["day"] != c["day"]:
            continue
        if c["l"] > a["h"] and (c["l"] - a["h"]) / c["c"] >= minpct:
            out.append((i, 1, a["h"], c["l"]))
        if c["h"] < a["l"] and (a["l"] - c["h"]) / c["c"] >= minpct:
            out.append((i, -1, c["h"], a["l"]))
    return out


def cand_fvg(B, minpct, age):
    """First retest of a gap within `age` bars: price trades into the gap and closes outside
    it on the trend side. Stop = the far edge of the gap."""
    out = []
    for i, side, bot, top in fvgs(B, minpct):
        for j in range(i + 1, min(i + 1 + age, len(B))):
            b = B[j]
            if b["day"] != B[i]["day"]:
                break
            if side == 1:
                if b["c"] < bot:
                    break                       # gap filled through: dead
                if b["l"] <= top and b["c"] > top:
                    out.append((j, 1, bot, "fvg"))
                    break
            else:
                if b["c"] > top:
                    break
                if b["h"] >= bot and b["c"] < bot:
                    out.append((j, -1, top, "fvg"))
                    break
    return out


def cand_ob(B, L, age):
    """Order block: the last opposite-colour candle before a BOS/CHoCH move. Trade its first
    retest within `age` bars after the break. Stop = the far side of the block."""
    out = []
    for i, side, kind, lvl, opp in structure(B, L):
        k = i - 1
        while k >= 0 and B[k]["day"] == B[i]["day"]:
            down = B[k]["c"] < B[k]["o"]
            if (side == 1 and down) or (side == -1 and not down and B[k]["c"] > B[k]["o"]):
                break
            k -= 1
        if k < 0 or B[k]["day"] != B[i]["day"]:
            continue
        lo, hi = B[k]["l"], B[k]["h"]
        for j in range(i + 1, min(i + 1 + age, len(B))):
            b = B[j]
            if b["day"] != B[i]["day"]:
                break
            if side == 1:
                if b["c"] < lo:
                    break
                if b["l"] <= hi and b["c"] > hi:
                    out.append((j, 1, lo, "ob"))
                    break
            else:
                if b["c"] > hi:
                    break
                if b["h"] >= lo and b["c"] < lo:
                    out.append((j, -1, hi, "ob"))
                    break
    return out


def delta(b):
    rng = b["h"] - b["l"]
    return b["v"] * ((b["c"] - b["l"]) - (b["h"] - b["c"])) / rng if rng > 0 else 0.0


def cand_vdelta(B, n, thr):
    """Order-flow proxy: over the last n bars of the same day, net delta / volume >= thr AND the
    close breaks the n-bar high (long), or the mirror. Stop = the n-bar low (high)."""
    out = []
    for i in range(len(B)):
        w = B[i - n:i] if i >= n else []
        if len(w) < n or w[0]["day"] != B[i]["day"]:
            continue
        vol = sum(x["v"] for x in w) + B[i]["v"]
        if vol <= 0:
            continue
        d = (sum(delta(x) for x in w) + delta(B[i])) / vol
        if d >= thr and B[i]["c"] > max(x["h"] for x in w):
            out.append((i, 1, min(x["l"] for x in w), "vdelta"))
        elif d <= -thr and B[i]["c"] < min(x["l"] for x in w):
            out.append((i, -1, max(x["h"] for x in w), "vdelta"))
    return out


# ------------------------------------------------------------------ grid

SETUPS = {
    # name: (detector, {detection params}), every setup shares the exit grid below
    "structure": (cand_structure, dict(L=[2, 3, 5], event=["bos", "choch", "both"])),
    "fvg": (cand_fvg, dict(minpct=[0.0, 0.001, 0.002], age=[6, 12, 24])),
    "ob": (cand_ob, dict(L=[2, 3, 5], age=[6, 12, 24])),
    "vdelta": (cand_vdelta, dict(n=[6, 12, 24], thr=[0.3, 0.5, 0.7])),
}
EXITS = dict(side=["long", "both"], dead=[10 * 60 + 30, 11 * 60 + 30, 13 * 60, 14 * 60 + 30],
             stop=["natural", "p0.5", "p1.0"], tgt=[1, 1.5, 2, 3, "eod"], filt=["none", "sma20", "rsi50"])


def n_settings():
    n = 0
    for _, (_, dp) in SETUPS.items():
        k = 1
        for v in list(dp.values()) + list(EXITS.values()):
            k *= len(v)
        n += k
    return n


def stop_price(entry, side, natural, kind):
    if kind == "p0.5":
        return entry * (1 - 0.005 * side)
    if kind == "p1.0":
        return entry * (1 - 0.01 * side)
    return natural


def simulate(B, i, side, stop, tgt):
    """Enter at B[i] close; walk forward the same day. Stop first when a bar touches both."""
    e = B[i]["c"]
    if stop is None or (side == 1 and stop >= e) or (side == -1 and stop <= e):
        return None
    t = None if tgt == "eod" else e + side * abs(e - stop) * tgt
    day = B[i]["day"]
    j = i + 1
    while j < len(B) and B[j]["day"] == day:
        b = B[j]
        if side == 1:
            if b["l"] <= stop:
                return (stop - e) / e - COST, "stop", j
            if t is not None and b["h"] >= t:
                return (t - e) / e - COST, "target", j
        else:
            if b["h"] >= stop:
                return (e - stop) / e - COST, "stop", j
            if t is not None and b["l"] <= t:
                return (e - t) / e - COST, "target", j
        if b["m"] >= EXIT_M:
            return side * (b["c"] - e) / e - COST, "close", j
        j += 1
    if j - 1 > i:
        return side * (B[j - 1]["c"] - e) / e - COST, "close", j - 1
    return None


def first_per_day(B, cands, p, ctx):
    """The first candidate each day that passes side, entry cutoff and filter.
    ctx = {day: previous daily context} (see prev_context)."""
    out, done = [], set()
    for i, side, natural, label in sorted(cands):
        d = B[i]["day"]
        if d in done or B[i]["m"] > p["dead"] or B[i]["m"] >= EXIT_M:
            continue
        if p["side"] == "long" and side != 1:
            continue
        if not filter_ok(p["filt"], side, ctx.get(d) if ctx else None):
            continue
        done.add(d)
        out.append((i, side, natural, label))
    return out


def stats(r):
    if not r:
        return dict(n=0, exp=0.0, win=0.0, tot=0.0)
    w = sum(1 for x in r if x > 0)
    return dict(n=len(r), exp=100 * sum(r) / len(r), win=100.0 * w / len(r), tot=100 * sum(r))
