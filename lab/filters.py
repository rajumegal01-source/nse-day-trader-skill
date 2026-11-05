"""Optional trade filters for the Trading Lab (Phase A). EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

All OFF by default: lab.py grid / memory.json are unchanged. A filter looks only at bars known
at the CLOSE of the trigger bar (no look-ahead). Each one answers ok(side, i) -> True/False.

  sideways  skip a quiet day: day range so far < SIDEWAYS_ATR x ATR14 (daily, previous days)
            (no ATR yet -> day range so far < SIDEWAYS_PCT % of price)
  nifty     ^NSEI 5-min at the same bar: no LONG when Nifty is below its session VWAP or EMA20,
            no SHORT when above both. Yahoo gives the index no volume, so its "VWAP" is the
            session average of typical prices (a TWAP proxy).
  relvol    trigger bar volume >= RELVOL x average volume of the same 5-min slot on prior days
  vwap      LONG only above the stock's session VWAP, SHORT only below
  time      trigger bar must start between TIME_FROM and TIME_TO (default 09:30-14:00)
  gap       skip days that opened >= GAP_PCT % away from the previous close (big gap days)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

NAMES = ("sideways", "nifty", "relvol", "vwap", "time", "gap")
DEFAULT = ("nifty", "gap")   # alert.py default: the only two that raised the TEST-half average (weakly)
SIDEWAYS_ATR = 0.35
SIDEWAYS_PCT = 0.6
RELVOL = 1.5
RELVOL_DAYS = 10
TIME_FROM, TIME_TO = 9 * 60 + 30, 14 * 60
GAP_PCT = 1.0
EMA_N = 20


def parse_names(text):
    """'sideways,nifty' -> ['sideways', 'nifty'] ('' or 'none' -> []). Filters() rejects unknown names."""
    out = [x.strip().lower() for x in (text or "").split(",") if x.strip() and x.strip().lower() != "none"]
    return out


# ------------------------------------------------------------------ per-bar series

def session_vwap(B):
    """[vwap at bar i] per day, cumulative typical price x volume. Zero volume -> plain mean."""
    out, day, pv, vv, ps, k = [], None, 0.0, 0.0, 0.0, 0
    for b in B:
        if b["day"] != day:
            day, pv, vv, ps, k = b["day"], 0.0, 0.0, 0.0, 0
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        pv += tp * b["v"]
        vv += b["v"]
        ps += tp
        k += 1
        out.append(pv / vv if vv > 0 else ps / k)
    return out


def ema(values, n):
    out, e, a = [], None, 2.0 / (n + 1)
    for x in values:
        e = x if e is None else e + a * (x - e)
        out.append(e)
    return out


def day_range_so_far(B):
    """[(high - low) of the day up to and including bar i]."""
    out, day, hi, lo = [], None, None, None
    for b in B:
        if b["day"] != day:
            day, hi, lo = b["day"], b["h"], b["l"]
        hi, lo = max(hi, b["h"]), min(lo, b["l"])
        out.append(hi - lo)
    return out


def atr_by_day(daily, days, n=14):
    """{day: ATR(n) of the daily bars strictly BEFORE that day} for each of `days`
    (simple mean of true ranges; a day with fewer than n earlier bars is left out)."""
    tr = []
    for k, b in enumerate(daily):
        pc = daily[k - 1]["c"] if k else b["c"]
        tr.append((b["day"], max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc))))
    out = {}
    for d in days:
        prev = [x for dd, x in tr if dd < d]
        if len(prev) >= n:
            out[d] = sum(prev[-n:]) / n
    return out


def gap_by_day(B):
    """{day: % gap of the first bar's open vs the previous session's last close}."""
    out, prev_c, day = {}, None, None
    for b in B:
        if b["day"] != day:
            if prev_c:
                out[b["day"]] = 100.0 * (b["o"] - prev_c) / prev_c
            day = b["day"]
        prev_c = b["c"]
    return out


def relvol_series(B, days=RELVOL_DAYS):
    """[bar volume / mean volume of the same slot over the previous `days` sessions] (None if no history)."""
    hist, out = {}, []
    for b in B:
        h = hist.setdefault(b["m"], [])
        prev = [x for d, x in h if d < b["day"]][-days:]
        avg = sum(prev) / len(prev) if prev else 0
        out.append(b["v"] / avg if avg > 0 else None)
        if not h or h[-1][0] != b["day"]:
            h.append((b["day"], b["v"]))
    return out


def nifty_trend(NB):
    """{(day, m): +1 above both VWAP-proxy and EMA20, -1 below both, 0 mixed}."""
    vw = session_vwap(NB)
    em = ema([b["c"] for b in NB], EMA_N)
    out = {}
    for b, v, e in zip(NB, vw, em):
        out[(b["day"], b["m"])] = 1 if b["c"] > v and b["c"] > e else (-1 if b["c"] < v and b["c"] < e else 0)
    return out


# ------------------------------------------------------------------ the filter object

class Filters:
    """Precomputes what the chosen filters need for one stock's bars B.
    daily = the stock's daily bars (for ATR); NB = ^NSEI 5-min bars (for 'nifty')."""

    def __init__(self, names, B, daily=None, NB=None):
        bad = [n for n in names if n not in NAMES]
        if bad:
            raise ValueError("unknown filter(s): %s (choose from %s)" % (",".join(bad), ",".join(NAMES)))
        self.names, self.B = list(names), B
        self.vw = session_vwap(B) if "vwap" in names else None
        self.rng = day_range_so_far(B) if "sideways" in names else None
        self.atr = atr_by_day(daily or [], sorted({b["day"] for b in B})) if "sideways" in names else None
        self.rv = relvol_series(B) if "relvol" in names else None
        self.gap = gap_by_day(B) if "gap" in names else None
        self.nt = nifty_trend(NB or []) if "nifty" in names else None

    def why_not(self, side, i):
        """None when every chosen filter passes, else the first failing filter's name."""
        b = self.B[i]
        for n in self.names:
            if n == "sideways":
                a = self.atr.get(b["day"])
                quiet = self.rng[i] < SIDEWAYS_ATR * a if a else 100.0 * self.rng[i] / b["c"] < SIDEWAYS_PCT
                if quiet:
                    return n
            elif n == "nifty":
                t = self.nt.get((b["day"], b["m"]))
                if t is None:                       # missing index bar: latest earlier bar that day
                    ks = [m for (d, m) in self.nt if d == b["day"] and m < b["m"]]
                    t = self.nt[(b["day"], max(ks))] if ks else 0
                if (side == 1 and t == -1) or (side == -1 and t == 1):
                    return n
            elif n == "relvol":
                r = self.rv[i]
                if r is None or r < RELVOL:
                    return n
            elif n == "vwap":
                if (side == 1 and b["c"] <= self.vw[i]) or (side == -1 and b["c"] >= self.vw[i]):
                    return n
            elif n == "time":
                if not TIME_FROM <= b["m"] <= TIME_TO:
                    return n
            elif n == "gap":
                if abs(self.gap.get(b["day"], 0.0)) >= GAP_PCT:
                    return n
        return None

    def ok(self, side, i):
        return self.why_not(side, i) is None

    def keep(self, cands):
        """Drop candidates (i, side, natural, label) that fail; a later trigger that day can still be taken."""
        return [c for c in cands if self.ok(c[1], c[0])]


def is_gap_day(B, day, pct=GAP_PCT):
    """True when `day` opened >= pct % away from the previous close (for flagging in alerts)."""
    g = gap_by_day(B).get(day)
    return g is not None and abs(g) >= pct, g
