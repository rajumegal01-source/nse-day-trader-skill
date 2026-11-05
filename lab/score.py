"""Confluence score 0-10 for any lab trigger. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

One point for each factor that agrees with the trade side, read only from bars known at the
trigger bar's close:
  trend    market structure (BOS/CHoCH, L=3) trend is on the trade side
  zone     the bar trades inside a same-side FVG or order block formed in the last 24 bars today
  level    the close is within 0.3% of PDH, PDL or a floor pivot (P, BC, TC, R1, S1)
  vwap     close above the session VWAP for a long (below for a short)
  nifty    ^NSEI is above its VWAP proxy and EMA20 for a long (below both for a short)
  volume   the bar's volume is above the average of the previous 20 bars
  nogap    the day did not open >= 1% away from the previous close
  ema      EMA9 above EMA21 for a long (below for a short)
  daily    yesterday's daily close above its SMA20 for a long (below for a short)
  dayopen  close above today's open for a long (below for a short)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import filters  # noqa: E402
import setups2  # noqa: E402

FACTORS = ("trend", "zone", "level", "vwap", "nifty", "volume", "nogap", "ema", "daily", "dayopen")
LEVEL_PCT = 0.003
ZONE_AGE = 24


class Context:
    """Precomputed series for one stock's bars B. NB = ^NSEI bars (optional), pctx = {day: (rsi,
    close, sma20)} from core.prev_context (optional)."""

    def __init__(self, B, NB=None, pctx=None):
        self.B, self.pctx = B, pctx or {}
        tr, t, k = [], 0, 0
        ev = core.structure(B, 3)
        for i in range(len(B)):
            while k < len(ev) and ev[k][0] <= i:
                t = ev[k][1]
                k += 1
            tr.append(t)
        self.trend = tr
        self.zones = [(i, s, lo, hi) for i, s, lo, hi in core.fvgs(B, 0.0)]
        for i, side, kind, lvl, opp in ev:      # order blocks, as in core.cand_ob
            j = i - 1
            while j >= 0 and B[j]["day"] == B[i]["day"]:
                down = B[j]["c"] < B[j]["o"]
                if (side == 1 and down) or (side == -1 and B[j]["c"] > B[j]["o"]):
                    self.zones.append((i, side, B[j]["l"], B[j]["h"]))
                    break
                j -= 1
        self.zones.sort()
        self.pd = setups2.prev_day_hlc(B)
        self.vw = filters.session_vwap(B)
        cl = [b["c"] for b in B]
        self.e9, self.e21 = setups2.ema(cl, 9), setups2.ema(cl, 21)
        self.gap = filters.gap_by_day(B)
        self.nt = filters.nifty_trend(NB) if NB else None
        self.dopen = {}
        for b in B:
            self.dopen.setdefault(b["day"], b["o"])

    def nifty(self, b):
        if not self.nt:
            return 0
        t = self.nt.get((b["day"], b["m"]))
        if t is None:
            ks = [m for (d, m) in self.nt if d == b["day"] and m < b["m"]]
            t = self.nt[(b["day"], max(ks))] if ks else 0
        return t

    def factors(self, i, side):
        B, b = self.B, self.B[i]
        f = {}
        f["trend"] = self.trend[i] == side
        f["zone"] = any(s == side and lo <= b["h"] and b["l"] <= hi and B[j]["day"] == b["day"]
                        for j, s, lo, hi in self.zones if i - ZONE_AGE <= j < i)
        lv = []
        if b["day"] in self.pd:
            H, L, C = self.pd[b["day"]]
            lv = [H, L] + list(setups2.pivots(H, L, C).values())
        f["level"] = any(abs(b["c"] - x) <= LEVEL_PCT * b["c"] for x in lv)
        f["vwap"] = (b["c"] - self.vw[i]) * side > 0
        f["nifty"] = self.nifty(b) == side
        prev = [x["v"] for x in B[max(0, i - 20):i]]
        f["volume"] = bool(prev) and b["v"] > sum(prev) / len(prev)
        f["nogap"] = abs(self.gap.get(b["day"], 0.0)) < filters.GAP_PCT
        f["ema"] = (self.e9[i] - self.e21[i]) * side > 0
        c = self.pctx.get(b["day"])
        f["daily"] = bool(c) and (c[1] - c[2]) * side > 0
        f["dayopen"] = (b["c"] - self.dopen[b["day"]]) * side > 0
        return f

    def score(self, i, side):
        """(score 0-10, [names of the agreeing factors])."""
        f = self.factors(i, side)
        yes = [n for n in FACTORS if f[n]]
        return len(yes), yes


def score(B, i, side, NB=None, pctx=None):
    """One-off convenience: confluence (score, factors) for trigger bar i on side +1/-1."""
    return Context(B, NB, pctx).score(i, side)
