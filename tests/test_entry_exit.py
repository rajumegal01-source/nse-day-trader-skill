"""trader-entry and trader-exit on RELIANCE, Mon 2026-11-02 (real 5-minute bars, offline)."""

import datetime
import os
import tempfile
import unittest

from _load import fix, jdump, jload, load, run, run_json

entry = load("trader-entry", "entry")
exitp = load("trader-exit", "exit")
CHART = fix("trader-entry", "RELIANCE.json")


class TestEntry(unittest.TestCase):
    def test_triggered_at_935(self):
        code, out, err = run("trader-entry", "entry.py", ["check", "RELIANCE", "--now", "2026-11-02 10:00",
                                                          "--offline", CHART])
        self.assertEqual(code, 0, err)
        self.assertIn("TRIGGERED 9:35 AM", out)
        self.assertIn("1234.50", out)
        self.assertIn("1231.60", out)

    def test_range_forming(self):
        code, out, err = run("trader-entry", "entry.py", ["check", "RELIANCE", "--now", "2026-11-02 09:27",
                                                          "--offline", CHART])
        self.assertNotEqual(code, 0)
        self.assertIn("RANGE FORMING", out)

    def test_writes_entry_json(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = run("trader-entry", "entry.py", ["check", "RELIANCE", "--now", "2026-11-02 10:00",
                                                              "--offline", CHART, "--write"], cwd=d)
            self.assertEqual(code, 0, err)
            doc = jload(d, "trader", "entry.json")
            self.assertEqual(doc["status"], "triggered")
            self.assertAlmostEqual(doc["price"], 1234.50)

    def test_calendar(self):
        self.assertFalse(entry.trading_day(datetime.date(2026, 11, 10))[0])
        self.assertTrue(entry.trading_day(datetime.date(2026, 11, 8))[0])


class TestExit(unittest.TestCase):
    def test_plan_or_mid_2r_tick(self):
        with tempfile.TemporaryDirectory() as d:
            jdump({"symbol": "RELIANCE", "setup": "orb", "status": "triggered", "date": "2026-11-02",
                   "time": "9:35 AM", "bar": 3, "price": 1234.50, "interval": "5m",
                   "opening_range": {"high": 1231.60, "low": 1214.60, "minutes": 15}}, d, "trader", "entry.json")
            code, out, err = run("trader-exit", "exit.py", ["plan", "--stop", "or-mid", "--target", "2R", "--tick",
                                                            "0.10", "--write", "--now", "2026-11-02 10:00"], cwd=d)
            self.assertEqual(code, 0, out + err)
            plan = jload(d, "trader", "plan.json")
            self.assertAlmostEqual(plan["stop"], 1223.10)
            self.assertAlmostEqual(plan["target"], 1257.30)
            self.assertEqual(plan["flat_by"], "15:10")

    def test_wrong_side_refused(self):
        code, out, err = run("trader-exit", "exit.py", ["plan", "--symbol", "RELIANCE", "--entry", "1234.50",
                                                        "--stop", "price:1240", "--now", "2026-11-02 10:00"])
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
