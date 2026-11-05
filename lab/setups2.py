"""Trading Lab Phase B: intraday price-action setups. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

Same contract as core.py: every detector returns candidates (index, side, natural_stop, label),
where index = the 5-min bar on whose CLOSE the signal is known. Only bars 0..index are read.
Previous-day levels come from the previous session present in B.

  pdhl     previous-day high/low: close-break (mode=break) or a close beyond then back inside (fail)
  cpr      floor pivots P, BC, TC, R1, S1 from the previous day: bounce or break
  inside   15-min inside bar / 15-min NR4 breakout, or day NR7 (prev day narrowest of 7) breakout
  sweep    liquidity sweep: wick through a swing or PDH/PDL, close back inside -> reversal
  odrive   opening drive: strong first 15 min, then opening-range break or first pullback
  round    round-number level (1-2-5 step, ~1% or ~2.5% of price): bounce or break
  candle   engulfing / pin bar at a swing or pivot level
  trend    EMA 9/21 pullback in trend, or Supertrend(10, 2|3) flip
Each setup has a small grid (<= 8 detection settings x 24 exits = <= 192 settings).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

# ------------------------------------------------------------------ shared helpers


def prev_day_hlc(B):
    """{day: (high, low, close) of the previous session in B}."""
    days, agg = [], {}
    for b in B:
        if b["day"] not in agg:
            days.append(b["day"])
            agg[b["day"]] = [b["h"], b["l"], b["c"]]
        a = agg[b["day"]]
        a[0], a[1], a[2] = max(a[0], b["h"]), min(a[1], b["l"]), b["c"]
    return {d: tuple(agg[days[k - 1]]) for k, d in enumerate(days) if k}


def day_ranges(B):
    """[(day, high - low)] per session in order."""
    out, agg = [], {}
    for b in B:
        if b["day"] not in agg:
            agg[b["day"]] = [b["h"], b["l"]]
            out.append(b["day"])
        a = agg[b["day"]]
        a[0], a[1] = max(a[0], b["h"]), min(a[1], b["l"])
    return [(d, agg[d][0] - agg[d][1]) for d in out]


def pivots(h, l, c):
    """Floor pivots: P, BC, TC, R1, S1 (TC/BC sorted so BC <= TC)."""
    p = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = 2 * p - bc
    bc, tc = min(bc, tc), max(bc, tc)
    return dict(P=p, BC=bc, TC=tc, R1=2 * p - l, S1=2 * p - h)


def ema(values, n):
    out, e, a = [], None, 2.0 / (n + 1)
    for x in values:
        e = x if e is None else e + a * (x - e)
        out.append(e)
    return out


def nice_step(price, frac):
    """A round 1-2-5 step close to price*frac (e.g. 1250 * 1% -> 10, 1250 * 2.5% -> 20)."""
    x = price * frac
    if x <= 0:
        return 1.0
    k = math.floor(math.log10(x))
    best = None
    for kk in (k - 1, k, k + 1):
        for m in (1, 2, 5):
            s = m * 10 ** kk
            d = abs(math.log(s / x))
            if best is None or d < best[0]:
                best = (d, s)
    return float(best[1])


def same_day(B, i, j):
    return 0 <= j < len(B) and B[i]["day"] == B[j]["day"]


def react(B, i, lvl, mode, buf=0.0005):
    """Level reaction on bar i (needs bar i-1 the same day). Returns (side, natural_stop) or None.
    bounce: came from one side, wicked to/through the level, closed back on that side.
    break:  previous close on one side, this close beyond the level by buf."""
    if not same_day(B, i, i - 1):
        return None
    b, pc = B[i], B[i - 1]["c"]
    if mode == "bounce":
        if pc > lvl and b["l"] <= lvl < b["c"]:
            return 1, b["l"]
        if pc < lvl and b["h"] >= lvl > b["c"]:
            return -1, b["h"]
    else:
        if pc <= lvl and b["c"] > lvl * (1 + buf):
            return 1, b["l"]
        if pc >= lvl and b["c"] < lvl * (1 - buf):
            return -1, b["h"]
    return None


# ------------------------------------------------------------------ 1) previous-day high / low

def cand_pdhl(B, mode, buf):
    """break: first close above PDH*(1+buf) -> long (stop = bar low); mirror at PDL.
    fail:  a close beyond PDH*(1+buf) earlier today, then a close back below PDH -> short
           (stop = day high so far); mirror at PDL."""
    pd = prev_day_hlc(B)
    out, day = [], None
    for i, b in enumerate(B):
        if b["day"] != day:
            day, hi, lo, up, dn, done_l, done_s = b["day"], b["h"], b["l"], False, False, False, False
        hi, lo = max(hi, b["h"]), min(lo, b["l"])
        if day not in pd:
            continue
        H, L, _ = pd[day]
        if mode == "break":
            if not done_l and b["c"] > H * (1 + buf):
                out.append((i, 1, b["l"], "pdhl"))
                done_l = True
            if not done_s and b["c"] < L * (1 - buf):
                out.append((i, -1, b["h"], "pdhl"))
                done_s = True
        else:
            if up and not done_s and b["c"] < H:
                out.append((i, -1, hi, "pdhl"))
                done_s = True
            if dn and not done_l and b["c"] > L:
                out.append((i, 1, lo, "pdhl"))
                done_l = True
            up = up or b["c"] > H * (1 + buf)
            dn = dn or b["c"] < L * (1 - buf)
    return out


# ------------------------------------------------------------------ 2) CPR / floor pivots

CPR_SETS = dict(P=("P",), cpr=("BC", "TC"), rs=("R1", "S1"), all=("P", "BC", "TC", "R1", "S1"))


def cand_cpr(B, levels, mode):
    """Bounce / break of the chosen previous-day pivot levels (see react)."""
    pd = prev_day_hlc(B)
    out = []
    for i, b in enumerate(B):
        if b["day"] not in pd:
            continue
        pv = pivots(*pd[b["day"]])
        for name in CPR_SETS[levels]:
            r = react(B, i, pv[name], mode)
            if r:
                out.append((i, r[0], r[1], "cpr"))
                break
    return out


# ------------------------------------------------------------------ 3) inside bar / NR

def bars15(B):
    """15-min bars from complete groups of three 5-min bars: [(close_index, o, h, l, c)]."""
    out, grp = [], []
    for i, b in enumerate(B):
        g = (b["day"], (b["m"] - core.OPEN_M) // 15)
        if grp and grp[0][0] != g:
            grp = []
        grp.append((g, i, b))
        if (b["m"] - core.OPEN_M) % 15 == 10 and len(grp) == 3:
            bs = [x[2] for x in grp]
            out.append((i, bs[0]["o"], max(x["h"] for x in bs), min(x["l"] for x in bs), bs[-1]["c"]))
    return out


def _breakout(B, k0, hi, lo, age, label, out):
    """First 5-min close above hi (long, stop lo) or below lo (short, stop hi) within age bars."""
    for j in range(k0 + 1, min(k0 + 1 + age, len(B))):
        if not same_day(B, k0, j):
            return
        if B[j]["c"] > hi:
            out.append((j, 1, lo, label))
            return
        if B[j]["c"] < lo:
            out.append((j, -1, hi, label))
            return


def cand_inside(B, kind, age):
    """inside15: a 15-min bar inside the previous one; nr4: 15-min bar with the narrowest range of
    the last 4 that day; both traded on a 5-min close beyond it within age bars (stop = other side).
    nr7day: yesterday's range was the narrowest of the last 7 sessions; a close beyond PDH / PDL
    within the first `age` bars of today (stop = yesterday's midpoint)."""
    out = []
    if kind == "nr7day":
        rg = day_ranges(B)
        pd = prev_day_hlc(B)
        nr7 = {rg[k][0] for k in range(7, len(rg)) if rg[k - 1][1] <= min(r for _, r in rg[k - 7:k])}
        first = {}
        for i, b in enumerate(B):
            first.setdefault(b["day"], i)
        for d in sorted(nr7):
            H, L, _ = pd[d]
            i0 = first[d]
            mid = (H + L) / 2
            for j in range(i0, min(i0 + age, len(B))):
                if B[j]["day"] != d:
                    break
                if B[j]["c"] > H:
                    out.append((j, 1, mid, "inside"))
                    break
                if B[j]["c"] < L:
                    out.append((j, -1, mid, "inside"))
                    break
        return out
    q = bars15(B)
    for k in range(1, len(q)):
        i, _, h, l, _ = q[k]
        if kind == "inside15":
            pi, _, ph, pl, _ = q[k - 1]
            if same_day(B, i, pi) and h <= ph and l >= pl:
                _breakout(B, i, h, l, age, "inside", out)
        elif kind == "nr4" and k >= 3:
            w = q[k - 3:k + 1]
            if all(same_day(B, i, x[0]) for x in w) and h - l <= min(x[2] - x[3] for x in w):
                _breakout(B, i, h, l, age, "inside", out)
    return out


# ------------------------------------------------------------------ 4) liquidity sweep

def cand_sweep(B, src, w):
    """A wick takes out a level within the last w bars (same day) and bar i closes back inside:
    above a swing high / PDH -> short (stop = highest high of the window); mirror for lows.
    src = swing2 | swing3 (latest confirmed swing of that order) | pdhl. Each level is used once."""
    out = []
    if src == "pdhl":
        pd = prev_day_hlc(B)
        used = set()
        for i, b in enumerate(B):
            if b["day"] not in pd:
                continue
            H, L, _ = pd[b["day"]]
            win = [B[j] for j in range(max(0, i - w + 1), i + 1) if B[j]["day"] == b["day"]]
            if (b["day"], -1) not in used and max(x["h"] for x in win) > H and b["c"] < H:
                out.append((i, -1, max(x["h"] for x in win), "sweep"))
                used.add((b["day"], -1))
            elif (b["day"], 1) not in used and min(x["l"] for x in win) < L and b["c"] > L:
                out.append((i, 1, min(x["l"] for x in win), "sweep"))
                used.add((b["day"], 1))
        return out
    sw = core.swings(B, 2 if src == "swing2" else 3)
    k, sh, sl = 0, None, None
    for i, b in enumerate(B):
        while k < len(sw) and sw[k][0] <= i:
            _, t, piv, p = sw[k]
            if t == "H":
                sh = [p, piv]
            else:
                sl = [p, piv]
            k += 1
        win = [B[j] for j in range(max(0, i - w + 1), i + 1) if B[j]["day"] == b["day"]]
        if sh and i - sh[1] > 2 and max(x["h"] for x in win) > sh[0]:
            if b["c"] < sh[0]:
                out.append((i, -1, max(x["h"] for x in win), "sweep"))
                sh = None
            elif all(x["c"] > sh[0] for x in win) and len(win) == w:
                sh = None                       # accepted above: a real break, not a sweep
        if sl and i - sl[1] > 2 and min(x["l"] for x in win) < sl[0]:
            if b["c"] > sl[0]:
                out.append((i, 1, min(x["l"] for x in win), "sweep"))
                sl = None
            elif all(x["c"] < sl[0] for x in win) and len(win) == w:
                sl = None
    return out


# ------------------------------------------------------------------ 5) opening drive

def cand_odrive(B, move, mode):
    """First 15 min (09:15-09:30) moves >= move % open-to-close = a drive.
    break:    later 5-min close beyond the opening-range high (low) -> with the drive, stop = OR mid.
    pullback: price pulls back >= 38.2% of the opening range, then a close above the previous bar's
              high (below its low) -> with the drive, stop = the pullback extreme. Void if the
              opposite side of the opening range closes broken first."""
    out = []
    by_day = {}
    for i, b in enumerate(B):
        by_day.setdefault(b["day"], []).append(i)
    for d, idx in by_day.items():
        if len(idx) < 4 or [B[j]["m"] for j in idx[:3]] != [555, 560, 565]:
            continue
        o3 = [B[j] for j in idx[:3]]
        mv = 100.0 * (o3[2]["c"] - o3[0]["o"]) / o3[0]["o"]
        if abs(mv) < move:
            continue
        s = 1 if mv > 0 else -1
        orh, orl = max(x["h"] for x in o3), min(x["l"] for x in o3)
        mid, ext = (orh + orl) / 2, None
        for n, j in enumerate(idx[3:]):
            b = B[j]
            if (s == 1 and b["c"] < orl) or (s == -1 and b["c"] > orh):
                break
            if mode == "break":
                if (s == 1 and b["c"] > orh) or (s == -1 and b["c"] < orl):
                    out.append((j, s, mid, "odrive"))
                    break
            else:
                ext = (b["l"] if s == 1 else b["h"]) if ext is None else (min(ext, b["l"]) if s == 1 else max(ext, b["h"]))
                deep = (ext <= orh - 0.382 * (orh - orl)) if s == 1 else (ext >= orl + 0.382 * (orh - orl))
                pb = B[j - 1]
                if deep and n > 0 and ((s == 1 and b["c"] > pb["h"]) or (s == -1 and b["c"] < pb["l"])):
                    out.append((j, s, ext, "odrive"))
                    break
    return out


# ------------------------------------------------------------------ 6) round numbers

def cand_round(B, scale, mode):
    """Bounce / break of round levels: multiples of a 1-2-5 step near 1% (fine) or 2.5% (coarse)
    of the previous close. The step is fixed per day from the first bar's open."""
    frac = 0.01 if scale == "fine" else 0.025
    out, day, step = [], None, None
    for i, b in enumerate(B):
        if b["day"] != day:
            day, step = b["day"], nice_step(b["o"], frac)
        if not same_day(B, i, i - 1):
            continue
        base = math.floor(B[i - 1]["c"] / step)
        for k in (base - 1, base, base + 1, base + 2):
            r = react(B, i, k * step, mode)
            if r:
                out.append((i, r[0], r[1], "round"))
                break
    return out


# ------------------------------------------------------------------ 7) candle patterns at levels

def engulf(B, i):
    """+1 bullish engulfing, -1 bearish, 0 none (bodies, same day)."""
    if not same_day(B, i, i - 1):
        return 0
    p, b = B[i - 1], B[i]
    if p["c"] < p["o"] and b["c"] > b["o"] and b["c"] >= p["o"] and b["o"] <= p["c"]:
        return 1
    if p["c"] > p["o"] and b["c"] < b["o"] and b["c"] <= p["o"] and b["o"] >= p["c"]:
        return -1
    return 0


def pin(b):
    """+1 bullish pin (long lower wick), -1 bearish pin, 0 none."""
    rng = b["h"] - b["l"]
    if rng <= 0:
        return 0
    body = abs(b["c"] - b["o"])
    lo_w, up_w = min(b["o"], b["c"]) - b["l"], b["h"] - max(b["o"], b["c"])
    if lo_w >= 2 * body and lo_w >= 0.6 * rng and up_w <= 0.25 * rng:
        return 1
    if up_w >= 2 * body and up_w >= 0.6 * rng and lo_w <= 0.25 * rng:
        return -1
    return 0


def _near(px, lvls, tol):
    return any(abs(px - x) <= tol * x for x in lvls)


def cand_candle(B, pat, at, tol):
    """Bullish engulfing / pin whose low is within tol of a level (or traded through it and closed
    above) -> long, stop = pattern low; mirror for shorts. Levels: at=swing -> the last 5
    confirmed swing lows (highs) of order 3; at=pivot -> PDH, PDL, P, BC, TC, R1, S1."""
    pd = prev_day_hlc(B)
    sw = core.swings(B, 3) if at == "swing" else []
    k, lows, highs, out = 0, [], [], []
    for i, b in enumerate(B):
        while k < len(sw) and sw[k][0] <= i:
            (highs if sw[k][1] == "H" else lows).append(sw[k][3])
            k += 1
        s = engulf(B, i) if pat == "engulf" else pin(b)
        if not s:
            continue
        if at == "swing":
            lv = lows[-5:] if s == 1 else highs[-5:]
        else:
            if b["day"] not in pd:
                continue
            H, L, C = pd[b["day"]]
            lv = list(pivots(H, L, C).values()) + [H, L]
        lo = min(b["l"], B[i - 1]["l"]) if pat == "engulf" else b["l"]
        hi = max(b["h"], B[i - 1]["h"]) if pat == "engulf" else b["h"]
        if s == 1 and (_near(lo, lv, tol) or any(lo <= x < b["c"] for x in lv)):
            out.append((i, 1, lo, "candle"))
        elif s == -1 and (_near(hi, lv, tol) or any(b["c"] < x <= hi for x in lv)):
            out.append((i, -1, hi, "candle"))
    return out


# ------------------------------------------------------------------ 8) EMA pullback / Supertrend

def supertrend(B, n=10, mult=3.0):
    """[(direction +1/-1, line)] per bar; Wilder ATR(n); None until n bars are known."""
    out, atr, fu, fl, d = [], None, None, None, 1
    for i, b in enumerate(B):
        pc = B[i - 1]["c"] if i else b["c"]
        tr = max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc))
        atr = tr if atr is None else (atr * (n - 1) + tr) / n
        hl2 = (b["h"] + b["l"]) / 2
        bu, bl = hl2 + mult * atr, hl2 - mult * atr
        if fu is None:
            fu, fl = bu, bl
        else:
            fu = bu if bu < fu or pc > fu else fu
            fl = bl if bl > fl or pc < fl else fl
        if d == 1 and b["c"] < fl:
            d = -1
        elif d == -1 and b["c"] > fu:
            d = 1
        out.append(None if i < n else (d, fl if d == 1 else fu))
    return out


def cand_trend(B, kind):
    """ema9_21: EMA9 > EMA21, the bar (or the one before) touched EMA9, and it closes above EMA9
    and above the previous bar's high -> long, stop = the lower of the two lows (mirror short).
    st2 / st3: Supertrend(10, 2|3) flips -> trade the new direction, stop = the Supertrend line."""
    out = []
    if kind == "ema9_21":
        cl = [b["c"] for b in B]
        e9, e21 = ema(cl, 9), ema(cl, 21)
        for i in range(21, len(B)):
            if not same_day(B, i, i - 1):
                continue
            b, p = B[i], B[i - 1]
            if e9[i] > e21[i] and min(b["l"], p["l"]) <= e9[i] and b["c"] > e9[i] and b["c"] > p["h"]:
                out.append((i, 1, min(b["l"], p["l"]), "trend"))
            elif e9[i] < e21[i] and max(b["h"], p["h"]) >= e9[i] and b["c"] < e9[i] and b["c"] < p["l"]:
                out.append((i, -1, max(b["h"], p["h"]), "trend"))
        return out
    st = supertrend(B, 10, 2.0 if kind == "st2" else 3.0)
    for i in range(1, len(B)):
        if st[i] and st[i - 1] and st[i][0] != st[i - 1][0] and same_day(B, i, i - 1):
            out.append((i, st[i][0], st[i][1], "trend"))
    return out


# ------------------------------------------------------------------ grid

EXITS2 = dict(side=["long", "both"], dead=[11 * 60 + 30, 14 * 60 + 30], stop=["natural", "p0.5"],
              tgt=[1.5, 2, "eod"], filt=["none"])          # 24 exits

SETUPS = {
    "pdhl": (cand_pdhl, dict(mode=["break", "fail"], buf=[0.0, 0.001, 0.002])),
    "cpr": (cand_cpr, dict(levels=["P", "cpr", "rs", "all"], mode=["bounce", "break"])),
    "inside": (cand_inside, dict(kind=["inside15", "nr4", "nr7day"], age=[6, 24])),
    "sweep": (cand_sweep, dict(src=["swing2", "swing3", "pdhl"], w=[1, 3])),
    "odrive": (cand_odrive, dict(move=[0.4, 0.7, 1.0], mode=["break", "pullback"])),
    "round": (cand_round, dict(scale=["fine", "coarse"], mode=["bounce", "break"])),
    "candle": (cand_candle, dict(pat=["engulf", "pin"], at=["swing", "pivot"], tol=[0.001, 0.003])),
    "trend": (cand_trend, dict(kind=["ema9_21", "st2", "st3"])),
}
NEEDS_HISTORY = ("inside",)     # nr7day reads 7 past sessions: scan fetches 1 month of bars


def n_settings(name):
    k = 1
    for v in list(SETUPS[name][1].values()) + list(EXITS2.values()):
        k *= len(v)
    return k
