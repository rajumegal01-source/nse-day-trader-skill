"""Facebook content helper (Phase K): a short Gujarati + English educational post and a simple
SVG chart for one of the day's lab picks. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/content.py                                  # today's first pick from lab/alert_state.json
    python3 lab/content.py --day 2026-11-04 --pick 2        # another day / the second pick
    python3 lab/content.py --from-json hits.json            # a pick from scan output (list of hits)
    python3 lab/content.py --out content_out                # where post.txt and chart.svg go

The text never says buy or sell: a pick is a "setup example" / "rule output" of the lab, with its
entry, stop and target levels and, when known, how it ended in the paper test. The chart (1080 x
1080, square for a Facebook post) is the day's 5-minute closes with entry / stop / target lines.
Review every post yourself before publishing; this tool posts nothing.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "alert_state.json")
OUT = os.path.join(HERE, "..", "content_out")
DISC_GU = "શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી"
DISC_EN = "Educational only, not investment advice"
NAMES = dict(structure="BOS / CHoCH structure", fvg="Fair Value Gap retest", ob="Order Block retest",
             vdelta="volume-delta breakout", pdhl="previous-day high / low", cpr="CPR pivot", inside="inside bar",
             sweep="liquidity sweep", odrive="opening drive", round="round number", candle="candle pattern",
             trend="trend (supertrend)", orb="opening range breakout", breakout="N-day high breakout",
             pullback="EMA pullback", near52="52-week-high zone")
FORBIDDEN = ("buy", "sell", "ખરીદ", "વેચ", "guaranteed", "sure shot", "target pakka")


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def pick_from_state(state, day=None, n=1):
    """(day, pick, result or None) of the n-th pick (1-based) of `day` (default: the latest day with picks)."""
    days = sorted(k[:-6] for k in state if k.endswith("#picks") and state[k])
    if not days:
        return None
    day = day or days[-1]
    picks = state.get(day + "#picks") or []
    if not 1 <= n <= len(picks):
        return None
    p = picks[n - 1]
    res = [r for r in state.get(day + "#results", [])
           if (r["symbol"], r["setup"], r["side"], r["time"]) == (p["symbol"], p["setup"], p["side"], p["time"])]
    return day, p, (res[0] if res else None)


def side_words(side):
    up = str(side).upper() in ("LONG", "1", "UP")
    return ("ઉપર તરફનું setup (long-side rule)", "upside setup (long-side rule)") if up else \
        ("નીચે તરફનું setup (short-side rule)", "downside setup (short-side rule)")


def post_text(day, p, res=None):
    """Gujarati + English post. Never buy / sell language."""
    name = NAMES.get(p.get("setup"), p.get("setup", "setup"))
    gu_side, en_side = side_words(p.get("side"))
    tgt = p.get("target")
    tgt_s = "15:15 exit" if tgt is None else tgt
    lines = [
        "📘 Trading Lab: setup example (%s)" % day,
        "",
        "%s | %s" % (p["symbol"], name),
        "%s, %s IST" % (gu_side, p.get("time", "")),
        "નિયમ પ્રમાણે levels: entry %s | stop %s | target %s" % (p["entry"], p["stop"], tgt_s),
        "",
        "English: rule output of the lab's %s rule on %s, an %s at %s IST." % (name, p["symbol"], en_side, p.get("time", "")),
        "Rule levels: entry %s, stop %s, target %s." % (p["entry"], p["stop"], tgt_s),
    ]
    if res:
        lines += ["", "Paper-test result / પેપર ટેસ્ટ પરિણામ: %s %+.2f%%" % (res.get("result"), float(res.get("pct") or 0))]
    lines += [
        "",
        "આ ફક્ત નિયમ શીખવા માટેનું ઉદાહરણ છે. Lab ના walk-forward test માં હજી કોઈ સાબિત edge મળી નથી.",
        "This is an example for learning a rule. The lab's walk-forward test has found no proven edge.",
        "",
        "⚠️ %s. %s." % (DISC_GU, DISC_EN),
        "#NSE #PriceAction #TradingEducation #શૈક્ષણિક",
    ]
    return "\n".join(lines)


def check_words(text):
    low = text.lower()
    bad = [w for w in FORBIDDEN if w in low]
    if bad:
        raise ValueError("post has forbidden words: %s" % ", ".join(bad))
    return text


def svg_chart(p, closes, day, w=1080, h=1080):
    """closes = [(label 'HH:MM', close)]. Price line + entry / stop / target lines."""
    lv = [("entry", p["entry"], "#1f6feb"), ("stop", p["stop"], "#d1242f")]
    if p.get("target") is not None:
        lv.append(("target", p["target"], "#1a7f37"))
    ys = [c for _, c in closes] + [x[1] for x in lv]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.08 or 1.0
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 120, w - 260, 170, h - 190

    def Y(v):
        return T + (hi - v) / (hi - lo) * (B - T)

    def X(i):
        return L + (R - L) * (i / float(max(len(closes) - 1, 1)))
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
           'font-family="Noto Sans Gujarati, Noto Sans, Arial, sans-serif">' % (w, h, w, h),
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           '<text x="%d" y="70" font-size="40" font-weight="bold" fill="#111">%s %s</text>' % (
               L, esc(p["symbol"]), esc(NAMES.get(p.get("setup"), p.get("setup", "")))),
           '<text x="%d" y="120" font-size="28" fill="#555">setup example / rule output, %s %s IST</text>' % (
               L, esc(day), esc(p.get("time", "")))]
    for k in range(5):
        v = lo + (hi - lo) * k / 4.0
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#eee"/>' % (L, Y(v), R, Y(v)))
        out.append('<text x="%d" y="%.1f" font-size="22" fill="#777" text-anchor="end">%.2f</text>' % (L - 10, Y(v) + 7, v))
    if closes:
        pts = " ".join("%.1f,%.1f" % (X(i), Y(c)) for i, (_, c) in enumerate(closes))
        out.append('<polyline points="%s" fill="none" stroke="#333" stroke-width="3"/>' % pts)
        for i in (0, len(closes) // 2, len(closes) - 1):
            out.append('<text x="%.1f" y="%d" font-size="22" fill="#777" text-anchor="middle">%s</text>' % (
                X(i), B + 35, esc(closes[i][0])))
        if p.get("time"):
            hit = [i for i, (t, _) in enumerate(closes) if t >= p["time"]]
            if hit:
                out.append('<circle cx="%.1f" cy="%.1f" r="10" fill="#1f6feb"/>' % (X(hit[0]), Y(p["entry"])))
    for name, v, col in lv:
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s" stroke-width="3" stroke-dasharray="12 8"/>' % (
            L, Y(v), R, Y(v), col))
        out.append('<text x="%d" y="%.1f" font-size="24" fill="%s">%s %.2f</text>' % (R + 12, Y(v) + 8, col, name, float(v)))
    out.append('<text x="%d" y="%d" font-size="30" fill="#b35900">%s</text>' % (L, h - 95, esc(DISC_GU)))
    out.append('<text x="%d" y="%d" font-size="26" fill="#b35900">%s. No proven edge.</text>' % (L, h - 50, esc(DISC_EN)))
    out.append("</svg>")
    return "\n".join(out)


def day_closes(symbol, day, cache=None):
    """[(HH:MM, close)] of the day's 5-minute bars from Yahoo (empty list when unavailable)."""
    try:
        import core
        import lab
        B, _ = core.sessions(lab.cached_fetch(symbol, "60d", "5m", cache))
    except Exception as e:
        print("no price bars for %s (%s): the chart shows the levels only" % (symbol, type(e).__name__))
        return []
    return [("%02d:%02d" % divmod(b["m"], 60), b["c"]) for b in B if b["day"] == day]


def make(day, p, res, out, closes):
    text = check_words(post_text(day, p, res))
    os.makedirs(out, exist_ok=True)
    tp, sp = os.path.join(out, "post.txt"), os.path.join(out, "chart.svg")
    with open(tp, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    with open(sp, "w", encoding="utf-8") as fh:
        fh.write(svg_chart(p, closes, day))
    return tp, sp, text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Facebook post text + SVG chart for a lab pick (educational)")
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--from-json", help="JSON list of hits (symbol, setup, side, time, entry, stop, target, day)")
    ap.add_argument("--day")
    ap.add_argument("--pick", type=int, default=1)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--cache")
    ap.add_argument("--no-fetch", action="store_true", help="levels only, no price line")
    a = ap.parse_args(argv)
    if a.from_json:
        with open(a.from_json, encoding="utf-8") as fh:
            hits = json.load(fh)
        if not 1 <= a.pick <= len(hits):
            print("no pick #%d in %s" % (a.pick, a.from_json))
            return 1
        p = hits[a.pick - 1]
        day, res = a.day or p.get("day", ""), None
    else:
        state = json.load(open(a.state, encoding="utf-8")) if os.path.exists(a.state) else {}
        got = pick_from_state(state, a.day, a.pick)
        if not got:
            print("no pick found (state %s, day %s, #%d)" % (a.state, a.day or "latest", a.pick))
            return 1
        day, p, res = got
    closes = [] if a.no_fetch else day_closes(p["symbol"], day, a.cache)
    tp, sp, text = make(day, p, res, a.out, closes)
    print(text)
    print("\nwrote %s and %s (review before posting)" % (tp, sp))
    return 0


if __name__ == "__main__":
    sys.exit(main())
