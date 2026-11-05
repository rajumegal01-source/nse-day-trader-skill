"""Optional exit rules + a position-size calculator for the Trading Lab (Phase A).
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

Exit rules (all OFF by default; with none on, simulate_ex == core.simulate):
  trail     once price reaches +1R, the stop moves to entry (from the NEXT bar)
  partial   book half at +1R, the rest runs to the target / stop / 15:15
  tstop     time stop: exit at the close of bar N (TSTOP_BARS=6, 30 min) after entry
            if price never reached +0.5R by then
Same-bar rule as core.simulate: when a bar touches the stop and a profit level, the stop wins.

Position size (no orders, no broker calls):
    python3 lab/risk.py size --capital 50000 --risk 1 --entry 1250 --stop 1240
    python3 lab/risk.py size --capital 50000 --risk 1 --entry 1250 --stop 1260 --target 1230   # short
Costs are an APPROXIMATE Angel One-like intraday estimate: brokerage min(Rs 20, 0.03%) per order,
STT 0.025% on the sell side, NSE transaction ~0.00297%, SEBI Rs 10/crore, stamp 0.003% on the
buy side, GST 18% on brokerage + transaction + SEBI. Check your broker's contract note.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

EXIT_NAMES = ("trail", "partial", "tstop")
TSTOP_BARS = 6
TSTOP_R = 0.5
MAX_STOPS = 2          # daily loss limit for alert.py: no new picks after this many stop-outs


def simulate_ex(B, i, side, stop, tgt, exits=()):
    """core.simulate with optional exit rules. Returns (return, reason, exit_index) or None."""
    exits = set(exits or ())
    bad = exits - set(EXIT_NAMES)
    if bad:
        raise ValueError("unknown exit rule(s): %s" % ",".join(sorted(bad)))
    if not exits:
        return core.simulate(B, i, side, stop, tgt)
    e = B[i]["c"]
    if stop is None or (side == 1 and stop >= e) or (side == -1 and stop <= e):
        return None
    R = abs(e - stop)
    t = None if tgt == "eod" else e + side * R * tgt
    one_r = e + side * R
    half_r = e + side * R * TSTOP_R
    cur_stop, booked, reached_half, be_armed = stop, None, False, False
    day = B[i]["day"]

    def done(px, reason, j):
        r = side * (px - e) / e
        if booked is not None:
            r = 0.5 * booked + 0.5 * r
        return r - core.COST, reason, j

    j = i + 1
    while j < len(B) and B[j]["day"] == day:
        b = B[j]
        if be_armed:
            cur_stop = e                         # breakeven from the bar after +1R was seen
        fav = b["h"] if side == 1 else b["l"]
        adv = b["l"] if side == 1 else b["h"]
        if (side == 1 and adv <= cur_stop) or (side == -1 and adv >= cur_stop):
            return done(cur_stop, "stop" if cur_stop != e else "breakeven", j)
        hit = lambda lvl: (side == 1 and fav >= lvl) or (side == -1 and fav <= lvl)  # noqa: E731
        if "partial" in exits and booked is None and hit(one_r):
            booked = side * (one_r - e) / e
        if t is not None and hit(t):
            return done(t, "target", j)
        if hit(half_r):
            reached_half = True
        if "trail" in exits and hit(one_r):
            be_armed = True
        if b["m"] >= core.EXIT_M:
            return done(b["c"], "close", j)
        if "tstop" in exits and j - i >= TSTOP_BARS and not reached_half:
            return done(b["c"], "time", j)
        j += 1
    if j - 1 > i:
        return done(B[j - 1]["c"], "close", j - 1)
    return None


# ------------------------------------------------------------------ costs and size

def intraday_costs(qty, buy_px, sell_px, brokerage=20.0, brokerage_pct=0.03):
    """APPROXIMATE Angel One-like intraday equity charges for one round trip (Rs)."""
    buy, sell = qty * buy_px, qty * sell_px
    brk = min(brokerage, buy * brokerage_pct / 100) + min(brokerage, sell * brokerage_pct / 100)
    stt = sell * 0.025 / 100
    txn = (buy + sell) * 0.00297 / 100
    sebi = (buy + sell) * 10 / 1e7
    stamp = buy * 0.003 / 100
    gst = 0.18 * (brk + txn + sebi)
    tot = brk + stt + txn + sebi + stamp + gst
    return {k: round(v, 2) for k, v in dict(brokerage=brk, stt=stt, exchange=txn, sebi=sebi, stamp=stamp,
                                              gst=gst, total=tot).items()}


def position_size(capital, risk_pct, entry, stop, leverage=1.0):
    """qty so that qty x |entry - stop| <= capital x risk%, and qty x entry <= capital x leverage."""
    per = abs(entry - stop)
    if capital <= 0 or risk_pct <= 0 or entry <= 0 or per <= 0:
        return 0
    q = math.floor(capital * risk_pct / 100.0 / per + 1e-9)
    return max(0, min(q, math.floor(capital * leverage / entry + 1e-9)))


def size_report(capital, risk_pct, entry, stop, target=None, leverage=1.0):
    q = position_size(capital, risk_pct, entry, stop, leverage)
    side = 1 if stop < entry else -1
    out = dict(qty=q, side="LONG" if side == 1 else "SHORT", value=round(q * entry, 2),
               risk_budget=round(capital * risk_pct / 100.0, 2), gross_loss_at_stop=round(q * abs(entry - stop), 2))
    if q:
        buy, sell = (entry, stop) if side == 1 else (stop, entry)
        c = intraday_costs(q, buy, sell)
        out["costs_at_stop"] = c
        out["net_loss_at_stop"] = round(out["gross_loss_at_stop"] + c["total"], 2)
        if target is not None:
            buy, sell = (entry, target) if side == 1 else (target, entry)
            ct = intraday_costs(q, buy, sell)
            out["net_profit_at_target"] = round(q * abs(target - entry) - ct["total"], 2)
    return out


def stopouts(picks, hits):
    """How many of today's picks have hit their stop, matched on (symbol, setup, side, time)."""
    keys = {(p["symbol"], p["setup"], p["side"], p["time"]) for p in picks}
    return sum(1 for h in hits if (h["symbol"], h["setup"], h["side"], h["time"]) in keys and h["status"] == "stop")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Position size (educational, approximate costs)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("size")
    s.add_argument("--capital", type=float, required=True)
    s.add_argument("--risk", type=float, default=1.0, help="risk per trade, %% of capital")
    s.add_argument("--entry", type=float, required=True)
    s.add_argument("--stop", type=float, required=True)
    s.add_argument("--target", type=float)
    s.add_argument("--leverage", type=float, default=1.0, help="1 = no margin (default)")
    a = ap.parse_args(argv)
    r = size_report(a.capital, a.risk, a.entry, a.stop, a.target, a.leverage)
    print("%s qty %d  (value Rs %.2f, risk budget Rs %.2f)" % (r["side"], r["qty"], r["value"], r["risk_budget"]))
    if r["qty"]:
        print("loss at stop: Rs %.2f + approx costs Rs %.2f = Rs %.2f"
              % (r["gross_loss_at_stop"], r["costs_at_stop"]["total"], r["net_loss_at_stop"]))
        print("approx costs: " + ", ".join("%s %.2f" % (k, v) for k, v in r["costs_at_stop"].items() if k != "total"))
        if "net_profit_at_target" in r:
            print("net profit at target (after approx costs): Rs %.2f" % r["net_profit_at_target"])
    else:
        print("0 shares: the stop is too wide for this risk, or the inputs are invalid")
    print("Costs are approximate (Angel One-like intraday). No order is placed. Educational only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
