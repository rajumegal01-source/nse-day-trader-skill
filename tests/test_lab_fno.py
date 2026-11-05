"""lab/fno.py (Phase D): Black-Scholes, greeks, implied vol, payoff, lot sizes. Offline."""

import os
import sys
import unittest
from unittest import mock

from _load import ROOT, run

sys.path.insert(0, os.path.join(ROOT, "lab"))
import fno  # noqa: E402


class TestBlackScholes(unittest.TestCase):
    def test_textbook_values(self):                     # Hull: S=K=100, T=1, r=5%, vol 20%
        self.assertAlmostEqual(fno.bs_price(100, 100, 1, 0.05, 0.2, "C"), 10.4506, places=3)
        self.assertAlmostEqual(fno.bs_price(100, 100, 1, 0.05, 0.2, "P"), 5.5735, places=3)

    def test_put_call_parity(self):
        S, K, T, r, v = 24000, 24200, 7 / 365.0, 0.06, 0.13
        c, p = fno.bs_price(S, K, T, r, v, "C"), fno.bs_price(S, K, T, r, v, "P")
        self.assertAlmostEqual(c - p, S - K * fno.math.exp(-r * T), places=6)

    def test_expiry_is_intrinsic(self):
        self.assertEqual(fno.bs_price(110, 100, 0, 0.05, 0.2, "C"), 10)
        self.assertEqual(fno.bs_price(110, 100, 0, 0.05, 0.2, "P"), 0)

    def test_greeks_match_finite_differences(self):
        S, K, T, r, v, h = 1000.0, 1020.0, 30 / 365.0, 0.06, 0.25, 0.01
        for kind in "CP":
            g = fno.greeks(S, K, T, r, v, kind)
            f = lambda s=S, t=T, vol=v: fno.bs_price(s, K, t, r, vol, kind)  # noqa: E731
            self.assertAlmostEqual(g["delta"], (f(s=S + h) - f(s=S - h)) / (2 * h), places=4)
            self.assertAlmostEqual(g["gamma"], (f(s=S + 1) - 2 * f() + f(s=S - 1)), places=4)
            self.assertAlmostEqual(g["vega"], (f(vol=v + 0.0001) - f(vol=v - 0.0001)) / 0.0002 / 100, places=4)
            self.assertAlmostEqual(g["theta"], (f(t=T - 1 / 365.0) - f()), places=2)
        self.assertGreater(fno.greeks(S, K, T, r, v, "C")["delta"], 0)
        self.assertLess(fno.greeks(S, K, T, r, v, "P")["delta"], 0)

    def test_implied_vol_round_trip(self):
        for kind in "CP":
            p = fno.bs_price(24000, 24100, 6 / 365.0, 0.06, 0.137, kind)
            self.assertAlmostEqual(fno.implied_vol(p, 24000, 24100, 6 / 365.0, 0.06, kind), 0.137, places=5)

    def test_implied_vol_impossible(self):
        self.assertIsNone(fno.implied_vol(0.0, 100, 100, 0.1, 0.05))
        self.assertIsNone(fno.implied_vol(150, 100, 100, 0.1, 0.05, "C"))     # above the spot
        self.assertIsNone(fno.implied_vol(5, 100, 100, 0, 0.05))


class TestPayoff(unittest.TestCase):
    def test_long_straddle(self):
        r = fno.analyze(fno.strategy("straddle", [100], [6, 4]))
        self.assertEqual(r["breakevens"], [90.0, 110.0])
        self.assertEqual(r["max_loss"], -10.0)
        self.assertIsNone(r["max_profit"])                                    # unlimited
        self.assertEqual(r["net_premium"], -10.0)

    def test_short_strangle_unlimited_loss(self):
        r = fno.analyze(fno.strategy("strangle", [90, 110], [3, 2], short=True))
        self.assertEqual(r["breakevens"], [85.0, 115.0])
        self.assertEqual(r["max_profit"], 5.0)
        self.assertIsNone(r["max_loss"])

    def test_iron_condor(self):
        legs = fno.strategy("iron_condor", [90, 95, 105, 110], [1, 2.5, 2.5, 1])
        r = fno.analyze(legs)
        self.assertEqual(r["max_profit"], 3.0)
        self.assertEqual(r["max_loss"], -2.0)
        self.assertEqual(r["breakevens"], [92.0, 108.0])
        self.assertEqual(fno.payoff(legs, 100), 3.0)

    def test_spreads(self):
        r = fno.analyze(fno.strategy("bull_call", [100, 110], [5, 2]))
        self.assertEqual((r["max_profit"], r["max_loss"], r["breakevens"]), (7.0, -3.0, [103.0]))
        r = fno.analyze(fno.strategy("bear_put", [90, 100], [2, 6]))
        self.assertEqual((r["max_profit"], r["max_loss"], r["breakevens"]), (6.0, -4.0, [96.0]))
        r = fno.analyze(fno.strategy("bull_put", [90, 100], [2, 6]))
        self.assertEqual((r["max_profit"], r["max_loss"], r["breakevens"]), (4.0, -6.0, [96.0]))

    def test_covered_call_and_butterfly(self):
        r = fno.analyze(fno.strategy("covered_call", [110], [100, 3]))
        self.assertEqual((r["max_profit"], r["max_loss"], r["breakevens"]), (13.0, -97.0, [97.0]))
        r = fno.analyze(fno.strategy("butterfly", [90, 100, 110], [12, 5, 1]))
        self.assertEqual((r["max_profit"], r["max_loss"]), (7.0, -3.0))
        self.assertEqual(r["breakevens"], [93.0, 107.0])

    def test_parse_leg(self):
        l = fno.parse_leg("-P:23800:60:2")
        self.assertEqual((l["side"], l["kind"], l["strike"], l["premium"], l["lots"]), (-1, "P", 23800, 60, 2))
        for bad in ("C:1:2", "+X:1:2", "+C:1"):
            with self.assertRaises(ValueError):
                fno.parse_leg(bad)

    def test_table_scales_by_lot(self):
        legs = [fno.leg(1, "C", 100, 5)]
        self.assertEqual(fno.table(legs, 90, 110, 2, lot=65), [(90.0, -325.0), (100.0, -325.0), (110.0, 325.0)])


class TestSize(unittest.TestCase):
    def test_lot_csv(self):
        lots = fno.lot_sizes()
        self.assertEqual(lots["NIFTY"], 65)
        self.assertEqual(lots["BANKNIFTY"], 30)
        self.assertIn("verify on nse", open(fno.LOTS, encoding="utf-8").read().lower())

    def test_size_check(self):
        r = fno.size_check(120, 65, 2, 100000, max_pct=10)
        self.assertEqual((r["cost"], r["pct"], r["ok"], r["max_lots"]), (15600, 15.6, False, 1))
        self.assertTrue(fno.size_check(10, 65, 1, 100000)["ok"])

    def test_chain_fails_gracefully(self):
        with mock.patch.object(fno.urllib.request, "build_opener", side_effect=OSError("blocked")):
            self.assertIsNone(fno.fetch_chain("NIFTY"))


class TestCLI(unittest.TestCase):
    def test_payoff_cli(self):
        code, out, err = run("lab", "fno.py", ["payoff", "iron_condor", "--strikes", "23600,23800,24200,24400",
                                               "--premiums", "20,45,50,22", "--symbol", "NIFTY"])
        self.assertEqual(code, 0, err)
        self.assertIn("lot 65", out)
        self.assertIn("max profit: 3445.00", out)                            # (45+50-20-22) x 65
        self.assertIn("Educational only, not investment advice", out)

    def test_price_and_size_cli(self):
        code, out, _ = run("lab", "fno.py", ["price", "--spot", "100", "--strike", "100", "--days", "365",
                                             "--iv", "20", "--rate", "0.05"])
        self.assertIn("price 10.45", out)
        code, out, _ = run("lab", "fno.py", ["size", "--symbol", "NIFTY", "--premium", "100", "--capital", "50000"])
        self.assertIn("TOO BIG", out)
        self.assertIn("not investment advice", out)


if __name__ == "__main__":
    unittest.main()
