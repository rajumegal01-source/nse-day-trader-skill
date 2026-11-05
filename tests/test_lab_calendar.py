"""lab/calendar_nse.py (Phase J): NSE 2026 holidays, trading days, expiry dates; alert.py skips holidays."""

import datetime as dt
import os
import sys
import unittest
from unittest import mock

from _load import ROOT, run

sys.path.insert(0, os.path.join(ROOT, "lab"))
import alert  # noqa: E402
import calendar_nse as cal  # noqa: E402

D = dt.date


class TestTradingDays(unittest.TestCase):
    def test_holiday_list_2026(self):
        h = cal.HOLIDAYS[2026]
        self.assertEqual(len(h), 16)
        for d in h:
            self.assertLess(cal.as_date(d).weekday(), 5, d)                    # weekday holidays only
        self.assertEqual(cal.holiday_name("2026-11-10"), "Diwali-Balipratipada")

    def test_is_trading_day(self):
        self.assertTrue(cal.is_trading_day("2026-11-06"))                      # Friday
        self.assertFalse(cal.is_trading_day("2026-11-07"))                     # Saturday
        self.assertFalse(cal.is_trading_day(D(2026, 11, 8)))                   # Sunday (Muhurat only)
        self.assertFalse(cal.is_trading_day(dt.datetime(2026, 11, 10, 10, 0))) # Diwali-Balipratipada
        self.assertFalse(cal.is_trading_day("2026-01-15"))                     # added by circular 72260
        self.assertTrue(cal.is_trading_day("2027-01-27"))                      # unknown year: weekends only
        self.assertFalse(cal.known_year(2027))

    def test_prev_next(self):
        self.assertEqual(cal.next_trading_day("2026-11-06"), D(2026, 11, 9))
        self.assertEqual(cal.next_trading_day("2026-11-09"), D(2026, 11, 11))  # skips the 10th
        self.assertEqual(cal.prev_trading_day("2026-11-11"), D(2026, 11, 9))
        self.assertEqual(cal.prev_trading_day("2026-11-09", inclusive=True), D(2026, 11, 9))


class TestExpiry(unittest.TestCase):
    def test_november_2026_holiday_shifts(self):
        self.assertEqual(cal.weekly_expiries(2026, 11), [D(2026, 11, 3), D(2026, 11, 9), D(2026, 11, 17), D(2026, 11, 23)])
        self.assertEqual(cal.monthly_expiry(2026, 11), D(2026, 11, 23))        # last Tue 24th is a holiday

    def test_regular_months(self):
        self.assertEqual(cal.monthly_expiry(2026, 12), D(2026, 12, 29))
        self.assertEqual(cal.monthly_expiry(2026, 10), D(2026, 10, 27))
        self.assertEqual(cal.last_weekday(2026, 2), D(2026, 2, 24))
        self.assertEqual(cal.monthly_expiry(2026, 3), D(2026, 3, 30))          # last Tue 31st: Mahavir Jayanti
        self.assertEqual(cal.weekly_expiries(2026, 10)[2], D(2026, 10, 19))    # Tue 20th: Dussehra

    def test_next_expiry(self):
        self.assertEqual(cal.next_expiry("NIFTY", "weekly", "2026-11-06"), D(2026, 11, 9))
        self.assertEqual(cal.next_expiry("NIFTY", "weekly", "2026-11-17"), D(2026, 11, 17))   # same day counts
        self.assertEqual(cal.next_expiry("BANKNIFTY", "monthly", "2026-11-24"), D(2026, 12, 29))
        self.assertEqual(cal.next_expiry("NIFTY", "monthly", "2026-12-30"), D(2027, 1, 26))   # 2027: no list yet
        with self.assertRaises(ValueError):
            cal.next_expiry("BANKNIFTY", "weekly", "2026-11-06")

    def test_cli(self):
        code, out, _ = run("lab", "calendar_nse.py", ["--date", "2026-11-10"])
        self.assertEqual(code, 0)
        self.assertIn("holiday: Diwali-Balipratipada", out)
        self.assertIn("2026-11-23 Mon (moved from 2026-11-24, holiday)", out)
        code, out, _ = run("lab", "calendar_nse.py", ["--month", "2026-11"])
        self.assertIn("2026-11-09 Mon", out)


class TestAlertSkipsHolidays(unittest.TestCase):
    def test_holiday_returns_quietly_before_any_fetch(self):
        class Fake(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return dt.datetime(2026, 11, 10, 10, 0, tzinfo=tz)
        with mock.patch.object(alert.dt, "datetime", Fake), \
                mock.patch.object(alert.lab, "load_memory", side_effect=AssertionError("must not run")):
            self.assertEqual(alert.main(["--dry-run"]), 0)
            self.assertEqual(alert.main(["--result", "--dry-run"]), 0)


if __name__ == "__main__":
    unittest.main()
