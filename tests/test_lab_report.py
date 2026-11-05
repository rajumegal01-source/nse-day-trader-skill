"""lab/report.py and lab/walkforward.py: the math of the honesty tools (offline)."""

import datetime as dt
import os
import sys
import unittest

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
import alert  # noqa: E402
import report  # noqa: E402
import walkforward as wf  # noqa: E402


def T(day, time, pct, sym="A", setup="fvg", exit="15:15", exp=0.3, win=60.0, gate=True):
    return dict(symbol=sym, setup=setup, day=day, time=time, pct=pct, exit=exit, train_exp=exp,
                train_win=win, gate=gate, side=1, how="close")


class TestMath(unittest.TestCase):
    def test_equity_and_drawdown(self):
        self.assertEqual(report.equity([1, -2, 3]), [0.0, 1.0, -1.0, 2.0])
        self.assertAlmostEqual(report.max_drawdown([1, -2, 3, -1, -1.5]), 2.5)
        self.assertEqual(report.max_drawdown([1, 2, 3]), 0.0)
        self.assertAlmostEqual(report.max_drawdown([-1, -1]), 2.0)     # from the start (0)

    def test_streaks(self):
        self.assertEqual(report.streaks([1, 1, -1, -1, -1, 2]), (2, 3, 1))
        self.assertEqual(report.streaks([-1, 0]), (0, 2, -2))          # zero counts as a loss
        self.assertEqual(report.streaks([]), (0, 0, 0))

    def test_summary_and_percentile(self):
        s = report.summary([1.0, -0.5, 0.5, -1.0])
        self.assertEqual((s["n"], s["win"], s["avg"], s["tot"]), (4, 50.0, 0.0, 0.0))
        self.assertEqual(report.percentile([1, 2, 3, 4, 5], 50), 3)
        self.assertAlmostEqual(report.percentile([0, 10], 25), 2.5)

    def test_monte_carlo_deterministic(self):
        r = [1, -1, 0.5, -0.5, 2, -2] * 5
        a = report.monte_carlo(r, [0.5, -0.5, 1.0], runs=200)
        b = report.monte_carlo(r, [0.5, -0.5, 1.0], runs=200)
        self.assertEqual(a, b)
        self.assertLessEqual(a["max_dd"]["5"], a["max_dd"]["50"])
        self.assertLessEqual(a["max_dd"]["50"], a["max_dd"]["95"])
        self.assertGreaterEqual(a["max_dd"]["5"], 2.0)                 # one -2 trade alone
        self.assertLessEqual(a["ret20"]["95"], 20.0)

    def test_nice_ticks(self):
        self.assertEqual(report.nice_ticks(-5.2, 5.0), [-5.0, -2.5, 0.0, 2.5, 5.0])


class TestWalkForward(unittest.TestCase):
    def test_windows(self):
        days = ["d%02d" % k for k in range(60)]
        w = wf.windows(days, 25, 5, 5)
        self.assertEqual(len(w), 7)
        self.assertEqual(w[0][0], days[:25])
        self.assertEqual(w[0][1], days[25:30])
        self.assertEqual(w[-1][1], days[55:60])
        test = [d for _, t in w for d in t]
        self.assertEqual(test, days[25:])                              # every OOS day once
        for tr, te in w:
            self.assertLess(max(tr), min(te))                          # train strictly before test

    def test_windows_partial_last(self):
        w = wf.windows(["d%02d" % k for k in range(33)], 25, 5, 5)
        self.assertEqual([len(t) for _, t in w], [5, 3])

    def test_choose_uses_train_only(self):
        train = ["d%02d" % k for k in range(25)]
        good = [(d, 600, 1, 0.01, "target", 700) for d in train]
        # p2 is far better on later (test) days but loses in the train window: never chosen
        bad = [(d, 600, 1, -0.01, "stop", 700) for d in train] + [("d30", 600, 1, 0.5, "target", 700)]
        p1, p2 = {"k": 1}, {"k": 2}
        ch = wf.choose([(p2, bad), (p1, good)], train)
        self.assertIs(ch[0], p1)
        self.assertEqual(ch[3]["n"], 25)
        self.assertIsNone(wf.choose([(p2, bad)], train))

    def test_pool(self):
        p = wf.pool([dict(pct=1.0, setup="a"), dict(pct=-1.0, setup="a"), dict(pct=2.0, setup="b")],
                    lambda t: t["setup"])
        self.assertEqual(p["a"], dict(n=2, win=50.0, avg=0.0, tot=0.0))
        self.assertEqual(p["b"]["n"], 1)


class TestPicks(unittest.TestCase):
    def test_run_slot(self):
        self.assertEqual(report.run_slot("09:55"), 600)
        self.assertEqual(report.run_slot("10:00"), 600)
        self.assertEqual(report.run_slot("10:05"), 615)

    def test_pick_day_like_alert(self):
        tr = [T("d", "09:55", 1.0, "A", exp=0.2), T("d", "09:50", -1.0, "B", exp=0.5),
              T("d", "09:20", 2.0, "C", gate=False),                     # fails the quality bar
              T("d", "09:20", 2.0, "D", exit="09:25"),                   # exited before the 09:30 run
              T("d", "11:00", 3.0, "E", exp=0.9)]                        # day already full
        got = [t["symbol"] for t in report.pick_day(tr)]
        self.assertEqual(got, ["B", "A"])                                # same run: best train avg first

    def test_simulate_picks_counts_empty_days(self):
        picks, daily = report.simulate_picks([T("d1", "10:00", 1.0)], ["d1", "d2"])
        self.assertEqual(len(picks), 1)
        self.assertEqual(daily, {"d1": 1.0, "d2": 0})

    def test_compare_pairs(self):
        tr = [T("d", "10:00", 1.0, "A")] * 5 + [T("d", "10:00", 2.0, "B")] * 4
        rows, n = report.compare_pairs(tr, 5)
        self.assertEqual((n, rows[0][0]), (1, ("A", "fvg")))


class TestWeekly(unittest.TestCase):
    STATE = {"2026-11-03": ["X"],
             "2026-11-03#picks": [dict(symbol="BSE", setup="vdelta", side="LONG", time="09:55", entry=100.0,
                                       stop=99.0, target=102.0)],
             "2026-11-03#results": [dict(symbol="BSE", setup="vdelta", side="LONG", time="09:55",
                                         result="target", pct=1.95)],
             "2026-11-04#picks": [dict(symbol="ABB", setup="fvg", side="SHORT", time="10:25", entry=100.0,
                                       stop=101.0, target=None)],
             "2026-10-01#picks": [dict(symbol="OLD", setup="fvg", side="LONG", time="10:00", entry=1, stop=0.9,
                                       target=None)]}

    def test_state_picks_parsing(self):
        sp = report.state_picks(self.STATE)
        self.assertEqual([(d, p["symbol"], r and r["result"]) for d, p, r in sp],
                         [("2026-10-01", "OLD", None), ("2026-11-03", "BSE", "target"), ("2026-11-04", "ABB", None)])

    def test_grade_bars(self):
        p = dict(side="SHORT", entry=100.0, stop=101.0, target=None, time="10:25")
        bars = [("10:20", 100.5, 99.8, 100.0), ("10:25", 100.4, 99.0, 99.2), ("15:15", 99.5, 98.5, 99.0),
                ("15:20", 99.0, 97.0, 97.0)]
        g = report.grade_bars(bars, p)
        self.assertEqual((g["result"], g["exit"], g["exit_time"]), ("close", 99.0, "15:15"))
        self.assertAlmostEqual(g["pct"], 0.95)
        p2 = dict(side="LONG", entry=100.0, stop=99.0, target=101.0, time="10:00")
        self.assertEqual(report.grade_bars([("10:00", 101.5, 98.5, 100)], p2)["result"], "stop")   # both: stop
        self.assertIsNone(report.grade_bars([("09:55", 1, 1, 1)], p2))

    def test_weekly_text(self):
        fetch = lambda s, d: [("10:25", 100.2, 98.0, 98.5)]           # noqa: E731
        rows = report.weekly_rows(self.STATE, [dict(date="2026-11-05", symbol="ITC", side="LONG", time="11:05",
                                                    result="stop", pct=-1.05)], "2026-10-30", "2026-11-05", fetch)
        self.assertEqual([r["symbol"] for r in rows], ["BSE", "ABB", "ITC"])
        txt = report.weekly_text(rows, "2026-10-30", "2026-11-05")
        self.assertIn("Trades 3 | target 1 | stop 1 | close 1", txt)
        self.assertIn("Best setup: vdelta +1.95% (1)", txt)
        self.assertIn("Worst setup: orb -1.05% (1)", txt)
        self.assertNotIn("OLD", txt)
        self.assertTrue(all(len(line) < 80 for line in txt.splitlines()))
        empty = report.weekly_text([], "2026-10-30", "2026-11-05")
        self.assertIn("no picks", empty)

    def test_svg(self):
        svg = report.svg_equity([("oos", "#1f6feb", [0, 1, -1, 2])], "t <x>")
        self.assertTrue(svg.startswith("<svg") and svg.endswith("</svg>"))
        self.assertIn("polyline", svg)
        self.assertIn("t &lt;x&gt;", svg)


class TestAlertPrune(unittest.TestCase):
    def test_prune_keeps_picks_longer(self):
        st = {"2026-10-01": [1], "2026-10-01#picks": [2], "2026-10-01#results": [3], "2026-09-01#picks": [4],
              "2026-11-04": [5]}
        self.assertEqual(sorted(alert.prune(st, dt.date(2026, 11, 5))),
                         ["2026-10-01#picks", "2026-10-01#results", "2026-11-04"])


if __name__ == "__main__":
    unittest.main()
