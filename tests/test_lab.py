"""lab/core.py: indicators and trade simulation on hand-made bars (offline)."""

import os
import sys
import unittest

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
import core  # noqa: E402


def bar(m, o, h, l, c, v=1000, day="2026-11-04"):
    return dict(day=day, m=m, o=o, h=h, l=l, c=c, v=v)


def series(closes, start=9 * 60 + 15):
    out = []
    for k, c in enumerate(closes):
        o = closes[k - 1] if k else c
        out.append(bar(start + 5 * k, o, max(o, c) + 0.1, min(o, c) - 0.1, c))
    return out


class TestIndicators(unittest.TestCase):
    def test_bullish_fvg(self):
        B = [bar(555, 100, 101, 99, 100.5), bar(560, 100.5, 104, 100.4, 103.8), bar(565, 103.8, 105, 102, 104.5)]
        g = core.fvgs(B, 0.0)
        self.assertEqual(g, [(2, 1, 101, 102)])

    def test_fvg_retest_entry(self):
        B = [bar(555, 100, 101, 99, 100.5), bar(560, 100.5, 104, 100.4, 103.8), bar(565, 103.8, 105, 102, 104.5),
             bar(570, 104.5, 104.6, 101.8, 102.5)]
        c = core.cand_fvg(B, 0.0, 6)
        self.assertEqual(c[0][:3], (3, 1, 101))

    def test_structure_bos_and_choch(self):
        B = series([100, 101, 102, 101, 100, 99, 100, 101, 102, 103, 104, 103, 102, 101, 100, 99, 98, 97])
        kinds = [(e[1], e[2]) for e in core.structure(B, 2)]
        self.assertIn((1, "choch"), kinds)
        self.assertIn((-1, "choch"), kinds)

    def test_no_lookahead_in_swings(self):
        B = series([100, 101, 102, 101, 100, 99])
        for confirm, _, pivot, _ in core.swings(B, 2):
            self.assertEqual(confirm, pivot + 2)

    def test_delta_sign(self):
        self.assertGreater(core.delta(bar(600, 100, 102, 100, 102)), 0)
        self.assertLess(core.delta(bar(600, 102, 102, 100, 100)), 0)

    def test_simulate_stop_first_and_eod(self):
        B = [bar(600, 100, 100, 100, 100), bar(605, 100, 103, 98, 100)]
        r = core.simulate(B, 0, 1, 99, 2)
        self.assertEqual(r[1], "stop")
        B = [bar(900, 100, 100, 100, 100), bar(915, 100, 100.5, 99.5, 100.3)]
        self.assertEqual(core.simulate(B, 0, 1, 99, "eod")[1], "close")

    def test_grid_size(self):
        self.assertGreaterEqual(core.n_settings(), 10000)


if __name__ == "__main__":
    unittest.main()
