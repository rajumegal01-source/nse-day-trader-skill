"""trader-alerts: the NSE clock and alerts (offline)."""

import os
import tempfile
import unittest

from _load import fix, jdump, jload, load, run, run_json

alerts = load("trader-alerts", "alerts")
nse_now = alerts.parse_now


class TestClock(unittest.TestCase):
    def status(self, t):
        return alerts.market_status(nse_now(t))

    def test_open_preopen_closed(self):
        self.assertTrue(self.status("2026-11-02 10:00")["open"])
        st = self.status("2026-11-03 09:03")
        self.assertFalse(st["open"])
        self.assertTrue(st.get("pre_open"))
        st = self.status("2026-11-10 11:00")
        self.assertFalse(st["open"])
        self.assertIn("holiday", st["reason"].lower())
        self.assertEqual(st["next_open"], "2026-11-11 09:15")

    def test_muhurat(self):
        st = self.status("2026-11-08 14:30")
        self.assertTrue(st["open"])
        self.assertIn("Muhurat", st["special_session"])
        self.assertFalse(self.status("2026-11-08 14:10")["open"])
        self.assertEqual(self.status("2026-11-07 12:00")["next_open"], "2026-11-08 14:20")


class TestQuotesAndRules(unittest.TestCase):
    def test_quote_offline_has_prev_close(self):
        with tempfile.TemporaryDirectory() as d:
            code, out, err = run("trader-alerts", "alerts.py", ["quote", "RELIANCE", "--write", "--offline",
                                                                fix("trader-alerts")], cwd=d)
            self.assertEqual(code, 0, err)
            doc = jload(d, "trader", "prices.json")
            self.assertEqual(doc["prices"]["RELIANCE"], 1300.0)
            self.assertEqual(doc["detail"]["RELIANCE"]["prev_close"], 1164.9)
            self.assertIn("₹1300.00", out)

    def test_yahoo_url(self):
        self.assertIn("RELIANCE.NS", alerts.yahoo_url("RELIANCE"))
        self.assertIn("TCS.BO", alerts.yahoo_url("TCS.BO"))
        self.assertIn("^NSEI", alerts.yahoo_url("^NSEI"))

    def test_plan_alerts_ring_once(self):
        with tempfile.TemporaryDirectory() as d:
            jdump({"symbol": "RELIANCE", "date": "2026-11-02", "entry": 1234.5, "stop": 1223.1, "target": 1257.3,
                   "flat_by": "15:10"}, d, "trader", "plan.json")
            code, out, err = run("trader-alerts", "alerts.py", ["add", "--from-plan"], cwd=d)
            self.assertEqual(code, 0, err)
            args = ["check", "--now", "2026-11-02 15:12", "--offline", fix("trader-alerts")]
            code, out, err = run("trader-alerts", "alerts.py", args, cwd=d)
            self.assertEqual(code, 0, err)
            self.assertIn("target", out)
            self.assertIn("15:12 IST", out)
            code, out, err = run("trader-alerts", "alerts.py", args, cwd=d)
            self.assertEqual(code, 1)          # rang once already


if __name__ == "__main__":
    unittest.main()
