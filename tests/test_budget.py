"""trader-budget: Indian intraday charges, sizing with costs, lots, refusals (offline)."""

import datetime
import json
import os
import tempfile
import unittest

from _load import jdump, jload, load, run

nse = load("trader-budget", "nse")
size = load("trader-budget", "size")

PLAN = {"symbol": "RELIANCE", "side": "buy", "date": "2026-11-02", "setup": "orb", "entry": 1234.50,
        "stop": 1223.10, "target": 1257.30, "entry_time": "9:35 AM", "flat_by": "15:10", "tick_size": 0.10}
CFG = {"budget": 50000, "max_loss_per_trade_inr": 500, "max_position_pct": 75, "max_order_inr": 40000,
       "cash_buffer_pct": 10, "min_reward_risk": 1.0}


class TestCharges(unittest.TestCase):
    def test_round_trip_matches_hand_calculation(self):
        # 30 RELIANCE bought at 1234.50, sold at 1223.10 (checked by hand against zerodha.com/charges)
        ch = nse.charges(30 * 1234.50, 30 * 1223.10)
        self.assertAlmostEqual(ch["brokerage"], 22.12, places=2)   # 0.03% of each leg, under Rs 20
        self.assertAlmostEqual(ch["stt"], 9.17, places=2)         # 0.025% of the sell value
        self.assertAlmostEqual(ch["txn"], 2.26, places=2)         # NSE 0.00307%
        self.assertAlmostEqual(ch["sebi"], 0.07, places=2)        # Rs 10 per crore
        self.assertAlmostEqual(ch["gst"], 4.40, places=2)         # 18% of brokerage + txn + SEBI
        self.assertAlmostEqual(ch["stamp"], 1.11, places=2)       # 0.003% of the buy value
        self.assertAlmostEqual(ch["total"], 39.13, places=2)

    def test_brokerage_caps_at_20_per_order(self):
        ch = nse.charges(400000, 440000)
        self.assertEqual(ch["brokerage"], 40.0)
        self.assertAlmostEqual(ch["stt"], 110.0)
        self.assertAlmostEqual(ch["stamp"], 12.0)

    def test_bse_and_custom_brokerage(self):
        self.assertGreater(nse.charges(100000, 100000, exchange="BSE")["txn"], nse.charges(100000, 100000)["txn"])
        self.assertEqual(nse.charges(100000, 0, cfg={"brokerage_per_order": 0, "brokerage_pct": 0})["brokerage"], 0)

    def test_futures_and_options_rates(self):
        f = nse.charges(0, 1000000, "futures")
        self.assertAlmostEqual(f["stt"], 500.0)          # 0.05% sell, from 2026-04-01
        o = nse.charges(0, 100000, "options")
        self.assertAlmostEqual(o["stt"], 150.0)          # 0.15% of the premium
        self.assertEqual(o["brokerage"], 20.0)

    def test_bad_segment_and_exchange(self):
        with self.assertRaises(nse.NSEError):
            nse.charges(1, 1, "crypto")
        with self.assertRaises(nse.NSEError):
            nse.charges(1, 1, exchange="NYSE")

    def test_breakeven(self):
        self.assertAlmostEqual(nse.breakeven_move(30, 1234.50), 1.31, places=2)


class TestHelpers(unittest.TestCase):
    def test_inr_indian_grouping(self):
        self.assertEqual(nse.inr(123456.5), "\u20b91,23,456.50")
        self.assertEqual(nse.inr(12345678), "\u20b91,23,45,678.00")
        self.assertEqual(nse.inr(-381.13), "-\u20b9381.13")
        self.assertEqual(nse.inr(999.999), "\u20b91,000.00")

    def test_calendar(self):
        self.assertEqual(len(nse.NSE_HOLIDAYS), 16)
        self.assertFalse(nse.trading_day(datetime.date(2026, 11, 10))[0])      # Diwali-Balipratipada
        self.assertFalse(nse.trading_day(datetime.date(2026, 11, 7))[0])       # Saturday
        self.assertTrue(nse.trading_day(datetime.date(2026, 11, 8))[0])        # Muhurat Sunday
        self.assertEqual(nse.session(datetime.date(2026, 11, 8)), (datetime.time(14, 20), datetime.time(15, 30)))
        self.assertEqual(nse.session(datetime.date(2026, 11, 2)), (datetime.time(9, 15), datetime.time(15, 30)))
        b, a = nse.session_window(datetime.date(2026, 11, 8), datetime.time(9, 30), datetime.time(14, 45))
        self.assertEqual((b.time(), a.time()), (datetime.time(14, 35), datetime.time(14, 45)))

    def test_ist_clock(self):
        self.assertEqual(nse.parse_now("2026-11-02 10:00"), datetime.datetime(2026, 11, 2, 4, 30))
        self.assertEqual(nse.to_ist(datetime.datetime(2026, 11, 2, 4, 30)), datetime.datetime(2026, 11, 2, 10, 0))

    def test_lots_ticks_bands(self):
        self.assertEqual(nse.lot_size("RELIANCE", "equity_intraday"), 1)
        self.assertEqual(nse.lot_size("NIFTY", "futures"), 65)
        self.assertEqual(nse.lot_size("RELIANCE26NOVFUT", "futures"), 500)
        self.assertEqual(nse.lot_size("TCS", "futures", {"lot_sizes": {"TCS": 175}}), 175)
        self.assertTrue(nse.on_tick(1234.50, 0.10))
        self.assertFalse(nse.on_tick(1234.55, 0.10))
        self.assertEqual(nse.band_limits(100, 5), (95.0, 105.0))
        self.assertIsNone(nse.band_limits(100, "No Band"))

    def test_fingerprint_changes_with_the_order(self):
        o = {"symbol": "RELIANCE", "qty": 30, "price": "1234.50"}
        self.assertNotEqual(nse.fingerprint(o), nse.fingerprint(dict(o, qty=31)))
        self.assertEqual(nse.fingerprint(o), nse.fingerprint(dict(o, why="anything")))


class TestSizing(unittest.TestCase):
    def test_reliance_example(self):
        s = size.size_trade(PLAN, CFG, today="2026-11-02")
        self.assertEqual(s["qty"], 30)
        self.assertEqual(s["bound_by"], "position cap")
        self.assertAlmostEqual(s["at_stop"]["net"], -381.13, places=2)
        self.assertAlmostEqual(s["at_target"]["net"], 644.21, places=2)
        self.assertIsNone(s["refusal"])
        o = size.build_order(s)
        self.assertEqual((o["side"], o["product"], o["order_type"], o["price"], o["stop_loss"]),
                         ("BUY", "MIS", "LIMIT", "1234.50", "1223.10"))

    def test_max_loss_counts_charges(self):
        s = size.size_trade(PLAN, dict(CFG, max_position_pct=100, max_order_inr=10**7, budget=10**6),
                            today="2026-11-02")
        # 500 / 11.40 = 43 shares before charges
        self.assertEqual(s["bound_by"], "max loss")
        self.assertLessEqual(-s["at_stop"]["net"], 500)
        self.assertEqual(s["qty"], 39)  # 40 would lose 508.19 with charges, 39 loses 495.48

    def test_1r_target_refused_after_costs(self):
        s = size.size_trade(dict(PLAN, target=1245.90), CFG, today="2026-11-02")
        self.assertIsNotNone(s["refusal"])
        self.assertIn("after charges", s["refusal"])
        self.assertIsNone(size.build_order(s))

    def test_refusals(self):
        with self.assertRaises(size.SizeError):
            size.size_trade(dict(PLAN, side="sell"), CFG)
        with self.assertRaises(size.SizeError):
            size.size_trade(PLAN, CFG, today="2026-11-03")
        with self.assertRaises(size.SizeError):
            size.size_trade(dict(PLAN, stop=1240), CFG)
        with self.assertRaises(size.SizeError):
            size.size_trade(PLAN, CFG, segment="futures")          # allow_fno is off
        s = size.size_trade(PLAN, dict(CFG, max_loss_per_trade_inr=5), today="2026-11-02")
        self.assertIn("more than your", s["refusal"])

    def test_fno_whole_lots(self):
        cfg = dict(CFG, allow_fno=True, budget=10**7, max_order_inr=10**8, max_loss_per_trade_inr=20000,
                   max_position_pct=100)
        s = size.size_trade(PLAN, cfg, segment="futures", lot=500)
        self.assertEqual(s["qty"] % 500, 0)
        self.assertGreater(s["qty"], 0)

    def test_bse_symbol(self):
        s = size.size_trade(dict(PLAN, symbol="RELIANCE.BO"), CFG)
        self.assertEqual((s["symbol"], s["exchange"]), ("RELIANCE", "BSE"))

    def test_cli_writes_orders(self):
        with tempfile.TemporaryDirectory() as d:
            jdump(PLAN, d, "trader", "plan.json")
            jdump(CFG, d, "trader", "config.json")
            code, out, err = run("trader-budget", "size.py", ["--now", "2026-11-02 10:00", "--write"], cwd=d)
            self.assertEqual(code, 0, err)
            self.assertIn("30 shares of RELIANCE", out)
            self.assertIn("SEBI", out)
            doc = jload(d, "trader", "orders.json")
            self.assertEqual(doc["currency"], "INR")
            self.assertEqual(doc["mode"], "paper")
            self.assertEqual(doc["orders"][0]["qty"], 30)


if __name__ == "__main__":
    unittest.main()
