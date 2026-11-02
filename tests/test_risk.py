"""trader-risk: PASS / BLOCK with Indian rules (offline)."""

import os
import tempfile
import unittest

from _load import fix, jdump, jload, load, run

check = load("trader-risk", "check")
nse = load("trader-risk", "nse")

ORDER = {"symbol": "RELIANCE", "exchange": "NSE", "segment": "equity_intraday", "product": "MIS", "side": "BUY",
         "qty": 30, "lot_size": 1, "order_type": "LIMIT", "price": "1234.50", "stop_loss": "1223.10",
         "target": "1257.30", "validity": "DAY", "plan": {"entry": 1234.5, "stop": 1223.1, "target": 1257.3,
                                                          "tick_size": 0.10}}
CFG = {"budget": 50000, "max_loss_per_trade_inr": 500, "max_daily_loss_inr": 1500, "max_position_pct": 75,
       "max_order_inr": 40000}
T10 = nse.parse_now("2026-11-02 10:00")


def run_check(orders=None, cfg=None, now=T10, **kw):
    return check.check(orders or [ORDER], dict(CFG, **(cfg or {})), now=now, **kw)


class TestRisk(unittest.TestCase):
    def test_pass(self):
        r = run_check()
        self.assertEqual(r["pass"], 1, r["results"][0]["reasons"])
        self.assertAlmostEqual(r["results"][0]["max_loss"], 381.13, places=2)
        self.assertEqual(r["results"][0]["fingerprint"], nse.fingerprint(ORDER))

    def blocked(self, r, word):
        res = r["results"][0]
        self.assertEqual(res["verdict"], "BLOCK")
        self.assertTrue(any(word in x for x in res["reasons"]), res["reasons"])

    def test_window(self):
        self.blocked(run_check(now=nse.parse_now("2026-11-02 15:00")), "window")
        self.blocked(run_check(now=nse.parse_now("2026-11-02 09:20")), "no_entries_before")
        self.blocked(run_check(now=nse.parse_now("2026-11-10 10:00")), "NSE holiday")
        self.blocked(run_check(now=nse.parse_now("2026-11-07 10:00")), "weekend")
        self.blocked(run_check(now=nse.parse_now("2026-11-02 08:00")), "outside the session")

    def test_muhurat_window(self):
        self.blocked(run_check(now=nse.parse_now("2026-11-08 14:25")), "window")
        self.assertEqual(run_check(now=nse.parse_now("2026-11-08 14:40"))["pass"], 1)

    def test_loss_with_charges(self):
        self.blocked(run_check(cfg={"max_loss_per_trade_inr": 380}), "charges")  # 342 gross, 381.13 net

    def test_daily_loss_and_kill_switch(self):
        state = {"orders": [{"date": "2026-11-02", "status": "placed", "symbol": "TCS", "side": "BUY",
                             "kind": "entry", "max_loss": 1300}]}
        self.blocked(run_check(state=state), "daily loss")
        self.blocked(run_check(killswitch=(True, "manual")), "kill switch")
        self.blocked(run_check(pnl={"date": "2026-11-02", "realized_net": -1200}), "already lost")

    def test_reward_risk_after_costs(self):
        self.blocked(run_check([dict(ORDER, target="1245.90")]), "reward:risk")

    def test_format_and_asset(self):
        self.blocked(run_check([dict(ORDER, price="1234.55")]), "tick")
        self.blocked(run_check([dict(ORDER, product="CNC")]), "product")
        self.blocked(run_check([dict(ORDER, qty=0)]), "qty")
        fut = dict(ORDER, segment="futures", product="NRML", qty=250, lot_size=500, symbol="RELIANCE26NOVFUT")
        r = run_check([fut], cfg={"allow_fno": True, "budget": 10**7, "max_order_inr": 10**8,
                                  "max_loss_per_trade_inr": 10**6, "max_daily_loss_inr": 10**6})
        self.blocked(r, "lots")
        self.blocked(run_check([fut]), "F&O is off")

    def test_market_orders_blocked_live(self):
        mkt = dict(ORDER, order_type="MARKET")
        del mkt["price"]
        self.blocked(run_check([mkt], cfg={"mode": "live"}), "MARKET")

    def test_cash_no_leverage(self):
        self.blocked(run_check(cfg={"budget": 30000, "max_position_pct": 100, "max_order_inr": 10**6}), "cash")

    def test_short_and_exit(self):
        sell = dict(ORDER, side="SELL", price="1240.00")
        self.blocked(run_check([sell]), "short")
        pf = {"cash": 10000, "positions": [{"symbol": "RELIANCE", "qty": 30, "avg_price": 1234.5}]}
        r = run_check([sell], portfolio=pf, now=nse.parse_now("2026-11-02 15:05"))
        self.assertEqual(r["results"][0]["verdict"], "PASS")       # an exit is never blocked by the window
        self.assertEqual(r["results"][0]["kind"], "exit")
        self.assertTrue(any("window" in w for w in r["results"][0]["warnings"]))

    def test_duplicate_in_batch(self):
        r = run_check([ORDER, dict(ORDER, qty=1)], cfg={"max_position_pct": 100, "max_order_inr": 10**6,
                                                         "budget": 200000})
        self.assertEqual(r["results"][1]["verdict"], "BLOCK")

    def test_circuit(self):
        self.blocked(run_check(bands={"RELIANCE": 5.0}, prev_close={"RELIANCE": 1100.0}), "circuit")
        r = run_check(bands={"RELIANCE": 10.0}, prev_close={"RELIANCE": 1140.0})  # band 1026.00 to 1254.00
        self.assertEqual(r["pass"], 1)
        self.assertTrue(any("upper circuit" in w for w in r["results"][0]["warnings"]))

    def test_sec_list_parse(self):
        text = "Symbol,Series,Security Name,Band,Remarks\nABC,EQ,ABC Ltd,5,\nXYZ,BE,XYZ Ltd,20,\nRELIANCE,EQ,RIL,No Band,\n"
        self.assertEqual(check.parse_sec_list(text), {"ABC": 5.0, "XYZ": 20.0, "RELIANCE": "No Band"})

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            jdump({"orders": [ORDER]}, d, "trader", "orders.json")
            jdump(CFG, d, "trader", "config.json")
            code, out, err = run("trader-risk", "check.py", ["--now", "2026-11-02 10:00"], cwd=d)
            self.assertEqual(code, 0, out + err)
            self.assertIn("PASS", out)
            self.assertEqual(jload(d, "trader", "state", "risk.json")["date"], "2026-11-02")
            jdump({"date": "2026-11-02", "tripped": True, "reason": "test"}, d, "trader", "state", "killswitch.json")
            code, out, err = run("trader-risk", "check.py", ["--now", "2026-11-02 10:00"], cwd=d)
            self.assertEqual(code, 1)
            self.assertIn("kill switch", out)


if __name__ == "__main__":
    unittest.main()
