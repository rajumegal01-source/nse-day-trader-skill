"""lab/regime.py (Phase I): regime labels, per-regime tables, the selector walk-forward. Offline."""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from _load import ROOT, run

sys.path.insert(0, os.path.join(ROOT, "lab"))
import alert  # noqa: E402
import regime  # noqa: E402


def bars(closes, rng=None):
    d0 = dt.date(2025, 1, 1)
    out = []
    for k, c in enumerate(closes):
        r = rng[k] if rng else 1.0
        out.append(dict(day=(d0 + dt.timedelta(days=k)).isoformat(), m=555, o=c, h=c + r, l=c - r, c=c, v=0))
    return out


def T(day, setup, pct, reg):
    return dict(day=day, setup=setup, pct=pct, regime=reg)


class TestClassify(unittest.TestCase):
    def test_trend_up_and_down(self):
        up = regime.classify(bars([100 + k for k in range(120)]))
        self.assertEqual(up[max(up)], "trend-up")
        cl = [300.0] * 100 + [300 - k for k in range(120)]
        dn = regime.classify(bars(cl, [9.0] * 100 + [c * 0.01 for c in cl[100:]]))   # calmer than before
        self.assertEqual(dn[max(dn)], "trend-down")

    def test_range(self):
        cl = [100 + (1 if k % 2 else -1) for k in range(150)]
        r = regime.classify(bars(cl))
        self.assertEqual(r[max(r)], "range")

    def test_high_vol(self):
        cl = [100 + (1 if k % 2 else -1) for k in range(150)]
        rng = [1.0] * 140 + [8.0] * 10                       # ranges explode at the end
        r = regime.classify(bars(cl, rng))
        self.assertEqual(r[max(r)], "high-vol")
        self.assertTrue(set(r.values()) <= set(regime.REGIMES))

    def test_adx_bounds(self):
        adx, atr = regime.adx_atr(bars([100 + k * 0.5 for k in range(80)]))
        self.assertIsNone(adx[10])
        self.assertTrue(all(0 <= x <= 100 for x in adx if x is not None))
        self.assertAlmostEqual(atr[-1], 2.0, places=6)

    def test_no_look_ahead_tags(self):
        regs = {"2026-11-02": "range", "2026-11-03": "trend-up"}
        tr = regime.tag([dict(day="2026-11-03"), dict(day="2026-11-02")], regs, intraday=True)
        self.assertEqual([t["regime"] for t in tr], ["range", None])          # the day BEFORE
        tr = regime.tag([dict(day="2026-11-03")], regs, intraday=False)
        self.assertEqual(tr[0]["regime"], "trend-up")                         # swing: that close
        self.assertEqual(regime.regime_before(regs, "2026-11-04"), "trend-up")


class TestSelector(unittest.TestCase):
    def trades(self):
        out = []
        for k in range(80):
            d = "d%03d" % k
            reg = "trend-up" if k % 2 else "range"
            out.append(T(d, "fvg", 0.5 if reg == "trend-up" else -0.5, reg))
            out.append(T(d, "orb", -0.2, reg))
        return out

    def test_by_regime_and_allowed(self):
        tab = regime.by_regime(self.trades())
        self.assertEqual(tab["fvg"]["trend-up"]["avg"], 0.5)
        self.assertEqual(tab["ALL"]["range"]["n"], 80)
        self.assertEqual(regime.allowed(self.trades(), min_n=10), {("fvg", "trend-up")})

    def test_walk_uses_only_the_past(self):
        res = regime.selector_walk(self.trades(), block=10, min_n=5)
        self.assertEqual(len(res["blocks"]), 7)
        self.assertEqual(res["blocks"][0]["allowed"], 1)
        self.assertEqual(res["kept"]["avg"], 0.5)
        self.assertTrue(regime.helps(res))
        # a pattern that flips after the history: the selector must not see it coming
        flip = [dict(t, pct=-t["pct"]) if t["day"] >= "d010" else t for t in self.trades()]
        res = regime.selector_walk(flip, block=10, min_n=5)
        self.assertEqual(res["blocks"][0]["kept"]["avg"], -0.5)
        self.assertGreater(res["blocks"][-1]["kept"]["avg"], 0)                   # it adapts, later

    def test_filter_picks(self):
        table = {"fvg": {"trend-up": dict(n=40, avg=0.1)}, "orb": {"trend-up": dict(n=5, avg=0.9)}}
        hits = [dict(setup="fvg"), dict(setup="orb"), dict(setup="cpr")]
        self.assertEqual(regime.filter_picks(hits, "trend-up", table), [dict(setup="fvg")])
        self.assertEqual(regime.filter_picks(hits, "range", table), [])

    def test_alert_hook_off_and_safe(self):
        self.assertFalse(alert.REGIME_SELECT)
        hits = [dict(setup="fvg")]
        self.assertEqual(alert.regime_filter(hits, "2026-11-05", "range", {"fvg": {"range": dict(n=50, avg=-1)}}), [])
        with mock.patch.object(regime, "TABLE", "/nonexistent/x.json"):
            self.assertEqual(alert.regime_filter(hits, "2026-11-05"), hits)

    def test_intraday_cli_needs_walkforward(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run("lab", "regime.py", ["intraday", "--wf", os.path.join(d, "none.json")])
            self.assertEqual(code, 1)
            self.assertIn("walkforward.py", out)

    def test_texts(self):
        res = regime.selector_walk(self.trades(), block=10, min_n=5)
        self.assertIn("OUT-OF-SAMPLE", regime.walk_text(res, "10 days"))
        self.assertIn("fvg", regime.table_text(regime.by_regime(self.trades()), "t"))
        json.dumps(res)


if __name__ == "__main__":
    unittest.main()
