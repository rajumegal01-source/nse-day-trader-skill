"""F&O tools (Phase D): Black-Scholes, greeks, implied volatility, multi-leg payoff, lot-size check.
EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.
No broker, no orders: pure math on numbers you type in.

    python3 lab/fno.py price --spot 24000 --strike 24100 --days 6 --iv 13 --type C
    python3 lab/fno.py iv --spot 24000 --strike 24100 --days 6 --premium 95 --type C
    python3 lab/fno.py payoff straddle --strike 24000 --call 180 --put 170 --symbol NIFTY
    python3 lab/fno.py payoff iron_condor --strikes 23600,23800,24200,24400 --premiums 20,45,50,22
    python3 lab/fno.py payoff custom --leg +C:24000:180 --leg -C:24300:70          # bull call spread
    python3 lab/fno.py size --symbol NIFTY --premium 120 --lots 2 --capital 100000
    python3 lab/fno.py chain NIFTY                  # NSE option chain: often blocked for scripts

Legs: +/- (buy/sell), C (call) / P (put) / F (future or stock), strike (0 for F), premium (or the
entry price for F), optional :N for N lots. Payoff is per unit of underlying, at expiry; times the
lot size gives rupees. Black-Scholes assumes European exercise and constant volatility; NSE index
and stock options are European and cash settled. Real prices include bid/ask spread and costs.
Lot sizes: lab/lot_sizes.csv (verify on NSE, lot sizes change).
"""

import argparse
import csv
import json
import math
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LOTS = os.path.join(HERE, "lot_sizes.csv")
RATE = 0.06            # risk-free rate a year (approx. Indian T-bill); change with --rate
FOOT = "Educational only, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી."


# ------------------------------------------------------------------ Black-Scholes

def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def npdf(x):
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def _d12(S, K, T, r, sig, q=0.0):
    d1 = (math.log(S / K) + (r - q + sig * sig / 2) * T) / (sig * math.sqrt(T))
    return d1, d1 - sig * math.sqrt(T)


def bs_price(S, K, T, r, sig, kind="C", q=0.0):
    """European option price. T in years, sig and r as decimals (0.13 = 13%)."""
    kind = kind.upper()[0]
    if T <= 0:                                   # at expiry: intrinsic value
        return max(S - K, 0) if kind == "C" else max(K - S, 0)
    if sig <= 0:                                 # no volatility: discounted forward intrinsic
        fwd = S * math.exp(-q * T) - K * math.exp(-r * T)
        return max(fwd, 0) if kind == "C" else max(-fwd, 0)
    d1, d2 = _d12(S, K, T, r, sig, q)
    if kind == "C":
        return S * math.exp(-q * T) * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
    return K * math.exp(-r * T) * ncdf(-d2) - S * math.exp(-q * T) * ncdf(-d1)


def greeks(S, K, T, r, sig, kind="C", q=0.0):
    """delta, gamma, theta (per calendar day), vega (per 1 vol point), price."""
    kind = kind.upper()[0]
    d1, d2 = _d12(S, K, T, r, sig, q)
    eq, er = math.exp(-q * T), math.exp(-r * T)
    gamma = eq * npdf(d1) / (S * sig * math.sqrt(T))
    vega = S * eq * npdf(d1) * math.sqrt(T) / 100
    common = -S * eq * npdf(d1) * sig / (2 * math.sqrt(T))
    if kind == "C":
        delta = eq * ncdf(d1)
        theta = common - r * K * er * ncdf(d2) + q * S * eq * ncdf(d1)
    else:
        delta = eq * (ncdf(d1) - 1)
        theta = common + r * K * er * ncdf(-d2) - q * S * eq * ncdf(-d1)
    return dict(price=bs_price(S, K, T, r, sig, kind, q), delta=delta, gamma=gamma, theta=theta / 365, vega=vega)


def implied_vol(price, S, K, T, r, kind="C", q=0.0, lo=0.0001, hi=5.0, tol=1e-7, it=200):
    """Volatility (decimal) that makes bs_price == price, by bisection. None when no vol can."""
    if T <= 0 or price <= 0:
        return None
    plo, phi = bs_price(S, K, T, r, lo, kind, q), bs_price(S, K, T, r, hi, kind, q)
    if not plo - 1e-9 <= price <= phi + 1e-9:
        return None
    for _ in range(it):
        mid = (lo + hi) / 2
        if bs_price(S, K, T, r, mid, kind, q) < price:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


# ------------------------------------------------------------------ payoff at expiry

def leg(side, kind, strike, premium, lots=1):
    return dict(side=1 if side in (1, "+", "buy", "B") else -1, kind=kind.upper()[0], strike=float(strike),
                premium=float(premium), lots=int(lots))


def parse_leg(text):
    """'+C:24000:180' or '-P:23800:60:2' or '+F:0:24050' -> leg dict."""
    t = text.strip()
    if t[0] not in "+-":
        raise ValueError("leg must start with + (buy) or - (sell): %r" % text)
    parts = t[1:].split(":")
    if len(parts) not in (3, 4) or parts[0].upper() not in ("C", "P", "F"):
        raise ValueError("leg format is +C:strike:premium[:lots]: %r" % text)
    return leg(t[0], parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else 1)


def leg_value(l, S):
    """Profit per unit of one leg at expiry price S."""
    if l["kind"] == "C":
        v = max(S - l["strike"], 0) - l["premium"]
    elif l["kind"] == "P":
        v = max(l["strike"] - S, 0) - l["premium"]
    else:                                        # future / stock bought at `premium`
        v = S - l["premium"]
    return l["side"] * l["lots"] * v


def payoff(legs, S):
    return sum(leg_value(l, S) for l in legs)


def analyze(legs):
    """Breakevens, max profit, max loss (None = unlimited), per unit. Payoff is piecewise linear,
    with kinks only at strikes, so checking 0, every strike and the slope beyond is exact."""
    ks = sorted({l["strike"] for l in legs if l["kind"] != "F"} | {l["premium"] for l in legs if l["kind"] == "F"})
    pts = [0.0] + ks
    vals = [payoff(legs, s) for s in pts]
    top = (ks[-1] if ks else 1.0) * 2 + 1
    slope_up = payoff(legs, top + 1) - payoff(legs, top)
    pts.append(top)
    vals.append(payoff(legs, top))
    bes = []
    for (a, va), (b, vb) in zip(zip(pts, vals), zip(pts[1:], vals[1:])):
        if va == 0 and (not bes or abs(bes[-1] - a) > 1e-9):
            bes.append(a)
        if va * vb < 0:
            bes.append(a + (b - a) * (-va) / (vb - va))
    if vals[-1] == 0 and (not bes or abs(bes[-1] - top) > 1e-9):
        bes.append(top)
    if vals[-1] * (vals[-1] + slope_up) < 0:
        bes.append(top - vals[-1] / slope_up)
    bes = [round(b, 2) for b in bes if b > 0]
    mx = None if slope_up > 1e-9 else max(vals)
    mn = None if slope_up < -1e-9 else min(vals)
    net = sum(l["side"] * l["lots"] * l["premium"] for l in legs if l["kind"] != "F")
    return dict(breakevens=bes, max_profit=None if mx is None else round(mx, 2),
                max_loss=None if mn is None else round(mn, 2), net_premium=round(-net, 2))


def table(legs, lo, hi, steps=12, lot=1):
    step = (hi - lo) / float(steps)
    return [(round(lo + k * step, 2), round(payoff(legs, lo + k * step) * lot, 2)) for k in range(steps + 1)]


def strategy(name, strikes, prems, short=False):
    """Preset legs. strikes / prems are lists, low strike first (see the module help)."""
    k, p, s = strikes, prems, (-1 if short else 1)
    if name == "straddle":
        return [leg(s, "C", k[0], p[0]), leg(s, "P", k[0], p[1])]
    if name == "strangle":                                  # put strike, call strike
        return [leg(s, "P", k[0], p[0]), leg(s, "C", k[1], p[1])]
    if name == "bull_call":
        return [leg(1, "C", k[0], p[0]), leg(-1, "C", k[1], p[1])]
    if name == "bear_put":
        return [leg(-1, "P", k[0], p[0]), leg(1, "P", k[1], p[1])]
    if name == "bull_put":                                  # credit spread
        return [leg(1, "P", k[0], p[0]), leg(-1, "P", k[1], p[1])]
    if name == "bear_call":
        return [leg(-1, "C", k[0], p[0]), leg(1, "C", k[1], p[1])]
    if name == "iron_condor":                               # long put, short put, short call, long call
        return [leg(1, "P", k[0], p[0]), leg(-1, "P", k[1], p[1]), leg(-1, "C", k[2], p[2]), leg(1, "C", k[3], p[3])]
    if name == "butterfly":                                 # calls: 1 low, -2 mid, 1 high
        return [leg(1, "C", k[0], p[0]), leg(-1, "C", k[1], p[1], 2), leg(1, "C", k[2], p[2])]
    if name == "covered_call":                              # stock bought at p[0], call sold at k[0] for p[1]
        return [leg(1, "F", 0, p[0]), leg(-1, "C", k[0], p[1])]
    if name == "protective_put":
        return [leg(1, "F", 0, p[0]), leg(1, "P", k[0], p[1])]
    raise ValueError("unknown strategy %s" % name)


STRATEGIES = ("straddle", "strangle", "bull_call", "bear_put", "bull_put", "bear_call", "iron_condor",
              "butterfly", "covered_call", "protective_put")


# ------------------------------------------------------------------ lot sizes and position size

def lot_sizes(path=LOTS):
    out = {}
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in fh if not r.startswith("#")]
    for r in csv.DictReader(rows):
        out[r["symbol"].strip().upper()] = int(r["lot"])
    return out


def size_check(premium, lot, lots, capital, max_pct=5.0):
    """Premium outlay of BOUGHT options against capital. Selling needs exchange margin (often
    Rs 1-2 lakh a lot for NIFTY), which this does not compute."""
    cost = premium * lot * lots
    pct = 100.0 * cost / capital if capital else float("inf")
    max_lots = int(capital * max_pct / 100.0 // (premium * lot)) if premium * lot > 0 else 0
    return dict(cost=round(cost, 2), pct=round(pct, 2), ok=pct <= max_pct, max_lots=max_lots, max_pct=max_pct)


# ------------------------------------------------------------------ NSE option chain (optional)

def fetch_chain(symbol, timeout=15):
    """Try NSE's public option-chain JSON. NSE often blocks scripts (401/403): then None."""
    idx = symbol.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
    url = "https://www.nseindia.com/api/option-chain-%s?symbol=%s" % ("indices" if idx else "equities", symbol.upper())
    hdr = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Referer": "https://www.nseindia.com/option-chain"}
    try:
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        opener.open(urllib.request.Request("https://www.nseindia.com/option-chain", headers=hdr), timeout=timeout)
        doc = json.loads(opener.open(urllib.request.Request(url, headers=hdr), timeout=timeout).read())
        return doc if doc.get("records") else None
    except Exception as e:
        print("NSE option chain not available (%s): NSE often blocks scripts. Type premiums by hand." % type(e).__name__)
        return None


# ------------------------------------------------------------------ CLI

def fmt(v):
    return "unlimited" if v is None else "%.2f" % v


def cmd_price(a):
    T, sig = a.days / 365.0, a.iv / 100.0
    g = greeks(a.spot, a.strike, T, a.rate, sig, a.type)
    print("%s %s strike %s, spot %s, %g days, IV %g%%" % (a.symbol or "", a.type, a.strike, a.spot, a.days, a.iv))
    print("price %.2f | delta %.3f | gamma %.5f | theta %.2f/day | vega %.2f per 1%% IV" % (
        g["price"], g["delta"], g["gamma"], g["theta"], g["vega"]))
    print(FOOT)


def cmd_iv(a):
    v = implied_vol(a.premium, a.spot, a.strike, a.days / 365.0, a.rate, a.type)
    print("implied volatility: %s" % ("not found (premium outside model range)" if v is None else "%.2f%%" % (v * 100)))
    print(FOOT)


def cmd_payoff(a):
    if a.name == "custom":
        legs = [parse_leg(x) for x in a.leg or []]
        if not legs:
            raise SystemExit("custom needs --leg, e.g. --leg +C:24000:180")
    else:
        ks = [float(x) for x in (a.strikes or str(a.strike or "")).split(",") if x]
        ps = [float(x) for x in (a.premiums or ",".join(str(x) for x in (a.call, a.put) if x is not None)).split(",") if x]
        legs = strategy(a.name, ks, ps, a.short)
    lot = a.lot or (lot_sizes().get(a.symbol.upper(), 1) if a.symbol else 1)
    res = analyze(legs)
    ks = [l["strike"] or l["premium"] for l in legs]
    lo, hi = min(ks) * 0.95, max(ks) * 1.05
    print("%s, lot %d (verify on NSE, lot sizes change)" % (a.name, lot))
    for l in legs:
        print("  %s %d x %s %s @ %.2f" % ("BUY " if l["side"] > 0 else "SELL", l["lots"], l["kind"],
                                          l["strike"] if l["kind"] != "F" else "", l["premium"]))
    print("expiry price -> P&L (Rs, whole lot)")
    for s, v in table(legs, lo, hi, a.steps, lot):
        print("  %10.2f  %+12.2f" % (s, v))
    print("breakevens: %s" % (", ".join("%.2f" % b for b in res["breakevens"]) or "none"))
    mp = res["max_profit"]
    ml = res["max_loss"]
    print("max profit: %s | max loss: %s (Rs, whole lot) | net premium %+.2f a unit" % (
        fmt(None if mp is None else mp * lot), fmt(None if ml is None else ml * lot), res["net_premium"]))
    print(FOOT)


def cmd_size(a):
    lot = a.lot or lot_sizes().get(a.symbol.upper())
    if not lot:
        raise SystemExit("no lot size for %s: add it to lab/lot_sizes.csv or pass --lot" % a.symbol)
    r = size_check(a.premium, lot, a.lots, a.capital, a.max_pct)
    print("%s: %d lot(s) x %d x premium %.2f = Rs %.2f = %.1f%% of capital (limit %.1f%%) -> %s" % (
        a.symbol.upper(), a.lots, lot, a.premium, r["cost"], r["pct"], r["max_pct"],
        "OK" if r["ok"] else "TOO BIG"))
    print("lots within the limit: %d. Lot size from lab/lot_sizes.csv: verify on NSE, lot sizes change." % r["max_lots"])
    print("Buying risks the whole premium. Selling needs exchange margin, not computed here.")
    print(FOOT)


def cmd_chain(a):
    doc = fetch_chain(a.symbol)
    if not doc:
        return 1
    rec = doc["records"]
    print("%s spot %s, expiries %s" % (a.symbol.upper(), rec.get("underlyingValue"), ", ".join(rec.get("expiryDates", [])[:4])))
    print(FOOT)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="F&O math (educational, no orders)")
    sub = ap.add_subparsers(dest="cmd")
    for name in ("price", "iv"):
        p = sub.add_parser(name)
        p.add_argument("--spot", type=float, required=True)
        p.add_argument("--strike", type=float, required=True)
        p.add_argument("--days", type=float, required=True, help="calendar days to expiry")
        p.add_argument("--type", default="C", choices=["C", "P"])
        p.add_argument("--rate", type=float, default=RATE)
        p.add_argument("--symbol")
        if name == "price":
            p.add_argument("--iv", type=float, required=True, help="volatility in %%, e.g. 13")
        else:
            p.add_argument("--premium", type=float, required=True)
    p = sub.add_parser("payoff")
    p.add_argument("name", choices=STRATEGIES + ("custom",))
    p.add_argument("--strike", type=float)
    p.add_argument("--strikes", help="comma list, low first")
    p.add_argument("--call", type=float)
    p.add_argument("--put", type=float)
    p.add_argument("--premiums", help="comma list in leg order (see lab/fno.py strategy)")
    p.add_argument("--short", action="store_true", help="sell the straddle / strangle")
    p.add_argument("--leg", action="append")
    p.add_argument("--symbol")
    p.add_argument("--lot", type=int)
    p.add_argument("--steps", type=int, default=12)
    p = sub.add_parser("size")
    p.add_argument("--symbol", required=True)
    p.add_argument("--premium", type=float, required=True)
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--capital", type=float, required=True)
    p.add_argument("--lot", type=int)
    p.add_argument("--max-pct", type=float, default=5.0)
    p = sub.add_parser("chain")
    p.add_argument("symbol")
    a = ap.parse_args(argv)
    fn = dict(price=cmd_price, iv=cmd_iv, payoff=cmd_payoff, size=cmd_size, chain=cmd_chain).get(a.cmd)
    if not fn:
        ap.print_help()
        return 2
    return fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
