"""trader-scanner: the NSE universe, the daily scan and the opening-range scan (offline, real 2026-11-02 data)."""

import datetime
import os
import tempfile
import unittest

from _load import fix, jload, load, run, run_json

scan = load("trader-scanner", "scan")


class TestUniverse(unittest.TestCase):
    def test_equity_list_keeps_eq_only(self):
        with open(fix("trader-scanner", "EQUITY_L-sample.csv"), encoding="utf-8") as fh:
            text = fh.read()
        syms = scan.parse_equity_list(text)[0]
        names = [s[0] for s in syms]
        self.assertIn("RELIANCE", names)
        self.assertIn("M&M", names)
        self.assertIn("BAJAJ-AUTO", names)

    def test_cli_universe(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = run("trader-scanner", "scan.py", ["universe", "--offline",
                                                               fix("trader-scanner", "EQUITY_L-sample.csv")], cwd=d)
            self.assertEqual(code, 0, err)
            self.assertIn("series EQ", out)
            self.assertIn("BE", out)
            with open(os.path.join(d, "trader", "universe.txt"), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
            self.assertTrue(any(l.startswith("RELIANCE|") for l in lines))

    def test_bundled_nifty100(self):
        u = scan.fallback_universe()
        names = [s[0] if isinstance(s, (list, tuple)) else s for s in u]
        self.assertEqual(len(names), 100)
        self.assertIn("RELIANCE", names)

    def test_yahoo_symbols(self):
        self.assertEqual(scan.to_yahoo("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(scan.to_yahoo("RELIANCE.BO"), "RELIANCE.BO")
        self.assertEqual(scan.to_yahoo("^NSEI"), "^NSEI")
        self.assertEqual(scan.from_yahoo("M&M.NS"), "M&M")


class TestCalendar(unittest.TestCase):
    def test_holidays_and_muhurat(self):
        self.assertFalse(scan.trading_day(datetime.date(2026, 11, 10))[0])
        self.assertFalse(scan.trading_day(datetime.date(2026, 1, 15))[0])
        self.assertTrue(scan.trading_day(datetime.date(2026, 11, 8))[0])
        self.assertEqual(scan.session(datetime.date(2026, 11, 8))[0], datetime.time(14, 20))


class TestScans(unittest.TestCase):
    def test_daily_scan(self):
        code, doc, err = run_json("trader-scanner", "scan.py", ["daily", "--offline",
                                  fix("trader-scanner", "nifty50-daily-2026-11-02.json.gz"),
                                  "--now", "2026-11-02 08:30", "--no-write"])
        self.assertEqual(code, 0, err)
        hits = {h["symbol"]: h for h in doc["hits"]}
        self.assertEqual(len(hits), 19)
        self.assertIn("breakout_20d", hits["INFY"]["setups"])
        self.assertIn("oversold", hits["SHRIRAMFIN"]["setups"])

    def test_orb_scan_reliance(self):
        code, doc, err = run_json("trader-scanner", "scan.py", ["orb", "--offline",
                                  fix("trader-scanner", "nifty50-5m-2026-11-02.json.gz"),
                                  "--now", "2026-11-02 10:00", "--min-price", "0", "--no-write"])
        self.assertEqual(code, 0, err)
        self.assertEqual(len(doc["hits"]), 19)
        r = [h for h in doc["hits"] if h["symbol"] == "RELIANCE"][0]
        self.assertAlmostEqual(r["price"], 1234.50, places=2)
        self.assertAlmostEqual(r["or_high"], 1231.60, places=2)
        self.assertAlmostEqual(r["or_low"], 1214.60, places=2)
        self.assertEqual(r["at"], "9:35 AM")

    def test_orb_too_early_and_holiday(self):
        code, out, err = run("trader-scanner", "scan.py", ["orb", "--offline",
                             fix("trader-scanner", "nifty50-5m-2026-11-02.json.gz"), "--now", "2026-11-02 09:25",
                             "--no-write"])
        self.assertEqual(code, 1)
        code, out, err = run("trader-scanner", "scan.py", ["orb", "--now", "2026-11-10 10:00", "--no-write",
                                                           "--symbols", "RELIANCE"])
        self.assertEqual(code, 1)
        self.assertIn("holiday", (out + err).lower())


if __name__ == "__main__":
    unittest.main()
