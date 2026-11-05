"""lab/swing.py (Phase E): daily-bar setups, multi-day simulation, walk-forward. Offline."""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
import swing  # noqa: E402

D0 = dt.date(2024, 1, 1)


def day(k):
    return (D0 + dt.timedelta(days=k)).isoformat()


def bars(closes, vols=None, rng=1.0):
    out = []
    for k, c in enumerate(closes):
        o = closes[k - 1] if k else c
        out.append(dict(day=day(k), m=555, o=o, h=max(o, c) + rng, l=min(o, c) - rng, c=c,
                        v=(vols[k] if vols else 1000)))
    return out


EX = dict(atr=2.0, tgt=2.0, hold=5)


class TestIndicators(unittest.TestCase):
    def test_atr(self):
        D = bars([100] * 20)
        A = swing.atr(D, 14)
        self.assertIsNone(A[12])
        self.assertAlmostEqual(A[13], 2.0)

    def test_breakout_needs_volume(self):
        cl = [100] * 30 + [105]
        self.assertEqual(swing.signals(bars(cl), "breakout", dict(n=20, vmult=1.5)), [])
        vol = [1000] * 30 + [3000]
        self.assertEqual(swing.signals(bars(cl, vol), "breakout", dict(n=20, vmult=1.5)), [30])

    def test_near52_only_first_entry(self):
        cl = [100 + k * 0.01 for k in range(260)]      # always at the high: no FIRST entry
        self.assertEqual(swing.signals(bars(cl, rng=0), "near52", dict(pct=2.0)), [])
        cl = [100] * 250 + [80] * 5 + [99, 99.5, 100]
        sig = swing.signals(bars(cl, rng=0), "near52", dict(pct=2.0))
        self.assertEqual(sig, [255])                   # 99 >= 101 * 0.98 first, after the dip

    def test_pullback(self):
        cl = [100 + k for k in range(80)]
        D = bars(cl, rng=0.5)
        D[75]["l"] = D[75]["c"] - 10                   # dips to the EMA20, closes above it
        self.assertIn(75, swing.signals(D, "pullback", dict(e=20)))
        self.assertNotIn(74, swing.signals(D, "pullback", dict(e=20)))
        with self.assertRaises(ValueError):
            swing.signals(D, "nope", {})


class TestSimulate(unittest.TestCase):
    def setUp(self):
        self.D = bars([100] * 30, rng=0.5)
        self.A = [2.0] * 30                            # stop = entry - 4, target = entry + 8

    def test_time_exit(self):
        r = swing.simulate(self.D, 10, self.A, EX)
        self.assertEqual(r[1:], ("time", 15))
        self.assertAlmostEqual(r[0], -0.001)

    def test_stop_target_and_gap(self):
        D = [dict(b) for b in self.D]
        D[13]["l"] = 95
        self.assertEqual(swing.simulate(D, 10, self.A, EX)[1:], ("stop", 13))
        D = [dict(b) for b in self.D]
        D[12]["h"] = 109
        r = swing.simulate(D, 10, self.A, EX)
        self.assertEqual(r[1:], ("target", 12))
        self.assertAlmostEqual(r[0], 0.08 - 0.001)
        D = [dict(b) for b in self.D]
        D[12].update(o=90, l=89)                       # gap below the stop: filled at the open
        r = swing.simulate(D, 10, self.A, EX)
        self.assertEqual(r[1], "stop")
        self.assertAlmostEqual(r[0], -0.1 - 0.001)
        D = [dict(b) for b in self.D]
        D[12].update(l=95, h=109)                      # both in one day: stop first
        self.assertEqual(swing.simulate(D, 10, self.A, EX)[1], "stop")

    def test_open_trade_is_none_and_no_overlap(self):
        self.assertIsNone(swing.simulate(self.D, 27, self.A, EX))
        tr = swing.trades(self.D, self.A, [5, 6, 7, 11, 27], EX)
        self.assertEqual([t[0] for t in tr], [day(5), day(11)])   # 6, 7 while in a trade


class TestWalkForward(unittest.TestCase):
    def test_windows(self):
        w = swing.windows(list(range(800)), 500, 125)
        self.assertEqual([(len(a), len(b)) for a, b in w], [(500, 125), (500, 125), (500, 50)])

    def test_choose_train_only(self):
        tdays = [day(k) for k in range(100)]
        good = [(day(k), 0.01, "target", day(k)) for k in range(0, 100, 2)]
        late = [(day(k), -0.01, "stop", day(k)) for k in range(0, 100, 2)] + [(day(k), 0.9, "target", day(k)) for k in range(100, 160)]
        pooled = {("pullback", "good"): good, ("pullback", "late"): late}
        self.assertEqual(swing.choose(pooled, "pullback", tdays)[0], "good")
        self.assertIsNone(swing.choose(pooled, "breakout", tdays))

    def test_verdict_needs_most_windows(self):
        res = dict(overall=dict(n=100, avg=0.7), baseline=dict(avg=0.3),
                   by_window={"0": dict(avg=2.3), "1": dict(avg=-0.1), "2": dict(avg=-0.4)},
                   base_by_window={"0": dict(avg=2.2), "1": dict(avg=-0.4), "2": dict(avg=-0.2)})
        self.assertTrue(swing.verdict(res).startswith("no proven edge"))
        res["by_window"] = {"0": dict(avg=1.0), "1": dict(avg=0.2), "2": dict(avg=-0.1)}
        self.assertIn("not proof", swing.verdict(res))
        res["overall"]["n"] = 5
        self.assertIn("too few", swing.verdict(res))

    def test_cmd_wf_on_synthetic_cache(self):
        import math
        n = 700
        cl = [100 + 10 * math.sin(k / 15.0) + k * 0.05 for k in range(n)]
        ts = [int(dt.datetime(2023, 1, 2, 3, 45).timestamp()) + 86400 * k for k in range(n)]
        doc = {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [dict(
            open=[cl[k - 1] if k else cl[0] for k in range(n)], high=[c + 1 for c in cl], low=[c - 1 for c in cl],
            close=cl, volume=[1000 + (k % 7) * 400 for k in range(n)])]}}]}}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "AAA_5y_1d.json"), "w") as fh:
                json.dump(doc, fh)
            out = os.path.join(d, "wf.json")
            self.assertEqual(swing.main(["wf", "AAA", "--cache", d, "--out", out]), 0)
            res = json.load(open(out))
            self.assertEqual(res["stocks"], 1)
            self.assertEqual(res["windows"], 2)
            for t in res["trades"]:                    # every OOS trade sits in a test window
                self.assertGreater(t["day"], res["first"])
            self.assertIn("verdict", swing.wf_text(res))
            self.assertIn("not investment advice", swing.wf_text(res))


if __name__ == "__main__":
    unittest.main()
