"""lab/filters.py and lab/risk.py (Phase A optional filters and exits) on hand-made bars."""

import os
import sys
import unittest

from _load import ROOT, load

sys.path.insert(0, os.path.join(ROOT, "lab"))
import core  # noqa: E402
import filters  # noqa: E402
import risk  # noqa: E402


def bar(m, o, h, l, c, v=1000, day="2026-11-04"):
    return dict(day=day, m=m, o=o, h=h, l=l, c=c, v=v)


O = 9 * 60 + 15


class TestSeries(unittest.TestCase):
    def test_vwap_weighted_and_resets_each_day(self):
        B = [bar(O, 10, 10, 10, 10, 100), bar(O + 5, 20, 20, 20, 20, 300), bar(O, 50, 50, 50, 50, 10, day="2026-11-05")]
        self.assertAlmostEqual(filters.session_vwap(B)[1], 17.5)
        self.assertAlmostEqual(filters.session_vwap(B)[2], 50)

    def test_vwap_zero_volume_is_mean(self):        # ^NSEI has no volume on Yahoo
        B = [bar(O, 10, 10, 10, 10, 0), bar(O + 5, 20, 20, 20, 20, 0)]
        self.assertAlmostEqual(filters.session_vwap(B)[1], 15)

    def test_ema(self):
        self.assertEqual(filters.ema([1, 1, 1], 5), [1, 1, 1])
        self.assertAlmostEqual(filters.ema([0, 3], 2)[1], 2.0)

    def test_day_range_so_far(self):
        B = [bar(O, 10, 11, 9, 10), bar(O + 5, 10, 12, 10, 11), bar(O, 10, 10.5, 10, 10, day="2026-11-05")]
        self.assertEqual(filters.day_range_so_far(B), [2, 3, 0.5])

    def test_atr_uses_only_earlier_days(self):
        daily = [dict(day="2026-10-%02d" % (k + 1), o=100, h=102, l=98, c=100) for k in range(3)]
        a = filters.atr_by_day(daily, ["2026-10-03", "2026-10-04"], n=2)
        self.assertAlmostEqual(a["2026-10-03"], 4)
        self.assertNotIn("2026-10-02", filters.atr_by_day(daily, ["2026-10-02"], n=2))

    def test_gap_by_day(self):
        B = [bar(O, 100, 100, 100, 100), bar(O, 102, 102, 102, 102, day="2026-11-05")]
        self.assertAlmostEqual(filters.gap_by_day(B)["2026-11-05"], 2.0)
        self.assertEqual(filters.is_gap_day(B, "2026-11-05")[0], True)

    def test_relvol_same_slot_prior_days(self):
        B = [bar(O, 1, 1, 1, 1, 100, day="2026-11-03"), bar(O, 1, 1, 1, 1, 300, day="2026-11-04"),
             bar(O, 1, 1, 1, 1, 400, day="2026-11-05")]
        r = filters.relvol_series(B)
        self.assertIsNone(r[0])
        self.assertAlmostEqual(r[1], 3.0)
        self.assertAlmostEqual(r[2], 2.0)

    def test_nifty_trend(self):
        NB = [bar(O + 5 * k, 100 + k, 100 + k, 100 + k, 100 + k, 0) for k in range(5)]
        self.assertEqual(filters.nifty_trend(NB)[("2026-11-04", O + 20)], 1)


class TestFilters(unittest.TestCase):
    def test_empty_is_off(self):
        B = [bar(O, 10, 10, 10, 10)]
        f = filters.Filters([], B)
        self.assertTrue(f.ok(1, 0))
        self.assertEqual(filters.parse_names("none"), [])
        self.assertEqual(filters.parse_names("Nifty, gap"), ["nifty", "gap"])

    def test_unknown_name(self):
        with self.assertRaises(ValueError):
            filters.Filters(["moon"], [])

    def test_vwap_filter_sides(self):
        B = [bar(O, 10, 10, 10, 10), bar(O + 5, 12, 12, 12, 12)]
        f = filters.Filters(["vwap"], B)
        self.assertTrue(f.ok(1, 1))
        self.assertEqual(f.why_not(-1, 1), "vwap")

    def test_time_filter(self):
        B = [bar(O, 10, 10, 10, 10), bar(10 * 60, 10, 10, 10, 10), bar(14 * 60 + 30, 10, 10, 10, 10)]
        f = filters.Filters(["time"], B)
        self.assertEqual([f.ok(1, i) for i in range(3)], [False, True, False])

    def test_sideways_filter(self):
        daily = [dict(day="2026-10-%02d" % (k + 1), o=100, h=102, l=98, c=100) for k in range(15)]
        quiet = [bar(O, 100, 100.5, 99.8, 100)]
        busy = [bar(O, 100, 101.5, 99.5, 101)]
        self.assertFalse(filters.Filters(["sideways"], quiet, daily).ok(1, 0))   # 0.7 < 0.35 x 4
        self.assertTrue(filters.Filters(["sideways"], busy, daily).ok(1, 0))     # 2.0 >= 1.4

    def test_nifty_blocks_against_trend(self):
        B = [bar(O + 10, 50, 50, 50, 50)]
        NB = [bar(O + 5 * k, 100 - k, 100 - k, 100 - k, 100 - k, 0) for k in range(3)]
        f = filters.Filters(["nifty"], B, None, NB)
        self.assertEqual(f.why_not(1, 0), "nifty")
        self.assertTrue(f.ok(-1, 0))

    def test_gap_and_relvol_filters_and_keep(self):
        B = [bar(O, 100, 100, 100, 100, 100), bar(O, 103, 103, 103, 103, 100, day="2026-11-05")]
        self.assertFalse(filters.Filters(["gap"], B).ok(1, 1))
        self.assertFalse(filters.Filters(["relvol"], B).ok(1, 1))           # 1.0x < 1.5x
        self.assertEqual(filters.Filters(["gap"], B).keep([(0, 1, 99, "x"), (1, 1, 99, "x")]), [(0, 1, 99, "x")])


class TestExits(unittest.TestCase):
    def path(self, *hlc):
        B = [bar(600, 100, 100, 100, 100)]
        for k, (h, l, c) in enumerate(hlc):
            B.append(bar(605 + 5 * k, c, h, l, c))
        return B

    def test_no_rules_equals_core(self):
        B = self.path((101, 99.5, 100.5), (103, 100, 102.5))
        self.assertEqual(risk.simulate_ex(B, 0, 1, 99, 2), core.simulate(B, 0, 1, 99, 2))

    def test_unknown_rule(self):
        with self.assertRaises(ValueError):
            risk.simulate_ex(self.path((101, 99.5, 100)), 0, 1, 99, 2, ["moon"])

    def test_trail_moves_stop_to_entry(self):
        B = self.path((101.2, 100.2, 101), (100.5, 99.9, 100))      # +1R, then back to entry
        r = risk.simulate_ex(B, 0, 1, 99, 3, ["trail"])
        self.assertEqual(r[1], "breakeven")
        self.assertAlmostEqual(r[0], -core.COST)
        self.assertEqual(core.simulate(B, 0, 1, 99, 3)[1], "close")

    def test_partial_books_half(self):
        B = self.path((101.2, 100.2, 101), (101, 98.5, 99))          # +1R then stop
        r = risk.simulate_ex(B, 0, 1, 99, 3, ["partial"])
        self.assertAlmostEqual(r[0], 0.5 * 0.01 + 0.5 * -0.01 - core.COST)
        B = self.path((102.2, 100, 102))                              # target 2R same bar as 1R
        self.assertAlmostEqual(risk.simulate_ex(B, 0, 1, 99, 2, ["partial"])[0], 0.015 - core.COST)

    def test_short_side_partial(self):
        B = self.path((99.8, 98.8, 99), (99, 97.9, 98))
        r = risk.simulate_ex(B, 0, -1, 101, 2, ["partial"])
        self.assertEqual(r[1], "target")
        self.assertAlmostEqual(r[0], 0.015 - core.COST)

    def test_time_stop(self):
        B = self.path(*[(100.3, 99.8, 100.1)] * 8)
        r = risk.simulate_ex(B, 0, 1, 99, 2, ["tstop"])
        self.assertEqual((r[1], r[2]), ("time", risk.TSTOP_BARS))
        B = self.path((100.6, 99.8, 100.4), *[(100.3, 99.8, 100.1)] * 7)   # reached +0.5R: no time stop
        self.assertNotEqual(risk.simulate_ex(B, 0, 1, 99, 2, ["tstop"])[1], "time")


class TestSizeAndLimits(unittest.TestCase):
    def test_position_size(self):
        self.assertEqual(risk.position_size(100000, 1, 100, 98), 500)
        self.assertEqual(risk.position_size(10000, 1, 100, 99.9), 100)       # capped by capital
        self.assertEqual(risk.position_size(10000, 1, 100, 100), 0)
        self.assertEqual(risk.position_size(10000, 1, 100, 99.9, leverage=5), 500)

    def test_costs(self):
        c = risk.intraday_costs(100, 1000, 1010)
        self.assertAlmostEqual(c["brokerage"], 40.0)                         # Rs 20 cap each side
        self.assertAlmostEqual(c["stt"], 25.25)
        self.assertAlmostEqual(c["stamp"], 3.0)
        small = risk.intraday_costs(1, 100, 100)
        self.assertAlmostEqual(small["brokerage"], 0.06)                     # 0.03% below the cap
        self.assertGreater(c["total"], c["brokerage"] + c["stt"])

    def test_size_report_short(self):
        r = risk.size_report(50000, 1, 500, 505, target=490)
        self.assertEqual((r["side"], r["qty"]), ("SHORT", 100))
        self.assertGreater(r["net_loss_at_stop"], 500)
        self.assertLess(r["net_profit_at_target"], 1000)

    def test_stopouts(self):
        picks = [dict(symbol="A", setup="fvg", side="LONG", time="10:00"), dict(symbol="B", setup="ob", side="SHORT", time="11:00")]
        hits = [dict(symbol="A", setup="fvg", side="LONG", time="10:00", status="stop"),
                dict(symbol="B", setup="ob", side="SHORT", time="11:00", status="live"),
                dict(symbol="C", setup="ob", side="SHORT", time="11:00", status="stop")]
        self.assertEqual(risk.stopouts(picks, hits), 1)

    def test_cli(self):
        from _load import run
        code, out, _ = run("lab", "risk.py", ["size", "--capital", "50000", "--risk", "1", "--entry", "1250", "--stop", "1240"])
        self.assertEqual(code, 0)
        self.assertIn("LONG qty 40", out)
        self.assertIn("approximate", out)


class TestAlertRules(unittest.TestCase):
    def test_split_rules(self):
        alert = load("lab", "alert")
        self.assertEqual(alert.split_rules("nifty,gap,trail"), (["nifty", "gap"], ["trail"]))
        self.assertEqual(alert.split_rules("none"), ([], []))
        with self.assertRaises(ValueError):
            alert.split_rules("nifty,moon")

    def test_gap_flag_in_line(self):
        alert = load("lab", "alert")
        h = dict(symbol="A", setup="fvg", side="LONG", time="10:00", entry=1, stop=0.9, target=None, last=1,
                 test=dict(n=9, win=70, exp=0.3), gap_pct=-2.1)
        self.assertIn("gap day -2.1%", alert.line(h))
        h["gap_pct"] = 0.2
        self.assertNotIn("gap day", alert.line(h))


if __name__ == "__main__":
    unittest.main()
