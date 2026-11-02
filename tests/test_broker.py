"""trader-broker: the yes, paper trading, the kill switch, and LIVE Angel One SmartAPI against
MOCKED HTTP only (the live path is UNVERIFIED against a real account)."""

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import jdump, jload, load

nse = load("trader-broker", "nse")
angel = load("trader-broker", "angel")
ticket = load("trader-broker", "ticket")

ORDER = {"symbol": "RELIANCE", "exchange": "NSE", "segment": "equity_intraday", "product": "MIS", "side": "BUY",
         "qty": 30, "lot_size": 1, "order_type": "LIMIT", "price": "1234.50", "stop_loss": "1223.10",
         "target": "1257.30", "validity": "DAY", "plan": {"entry": 1234.5, "stop": 1223.1, "target": 1257.3,
                                                          "tick_size": 0.10}}
FAKE_SECRET = base64.b32encode(b"12345678901234567890").decode()   # the RFC 6238 test key
CREDS = {"ANGEL_API_KEY": "testkey123", "ANGEL_CLIENT_CODE": "A123456", "ANGEL_PIN": "4321",
         "ANGEL_TOTP_SECRET": FAKE_SECRET}
SCRIPS = json.dumps([{"token": "2885", "symbol": "RELIANCE-EQ", "name": "RELIANCE", "lotsize": "1",
                      "tick_size": "10.000000", "exch_seg": "NSE", "instrumenttype": "", "expiry": ""},
                     {"token": "500325", "symbol": "RELIANCE", "name": "RELIANCE", "lotsize": "1",
                      "tick_size": "5.000000", "exch_seg": "BSE", "instrumenttype": "", "expiry": ""}])


class FakeAngel(object):
    """A pretend SmartAPI server. Records every request; answers like the docs show."""

    def __init__(self, fill="complete", fail_login=False):
        self.calls = []
        self.fill = fill
        self.fail_login = fail_login
        self.n = 0

    def __call__(self, method, url, headers, body):
        path = url.replace(angel.ROOT, "")
        self.calls.append({"method": method, "path": path, "headers": dict(headers), "body": body})
        if path == angel.LOGIN:
            if self.fail_login:
                return 401, json.dumps({"status": False, "message": "Invalid totp", "errorcode": "AB1050"})
            return 200, json.dumps({"status": True, "message": "SUCCESS", "data": {"jwtToken": "JWT-SECRET-TOKEN",
                                                                                     "refreshToken": "R", "feedToken": "F"}})
        if path == angel.PLACE:
            self.n += 1
            return 200, json.dumps({"status": True, "message": "SUCCESS",
                                    "data": {"orderid": "26110200000%d" % self.n, "uniqueorderid": "u%d" % self.n}})
        if path == angel.ORDER_BOOK:
            return 200, json.dumps({"status": True, "data": [
                {"orderid": "261102000001", "orderstatus": self.fill, "tradingsymbol": "RELIANCE-EQ",
                 "transactiontype": "BUY", "quantity": "30", "price": "1234.50", "variety": "NORMAL"},
                {"orderid": "261102000002", "orderstatus": "trigger pending", "tradingsymbol": "RELIANCE-EQ",
                 "transactiontype": "SELL", "quantity": "30", "price": "1216.95", "variety": "STOPLOSS",
                 "ordertag": "ndts1234"}]})
        if path == angel.TRADE_BOOK:
            return 200, json.dumps({"status": True, "data": [
                {"tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "transactiontype": "BUY", "fillsize": "30",
                 "fillprice": "1234.50"},
                {"tradingsymbol": "RELIANCE-EQ", "exchange": "NSE", "transactiontype": "SELL", "fillsize": "30",
                 "fillprice": "1223.10"}]})
        if path == angel.CANCEL:
            return 200, json.dumps({"status": True, "data": {"orderid": body["orderid"]}})
        if path == angel.LOGOUT:
            return 200, json.dumps({"status": True, "data": None})
        return 404, "{}"


class Workspace(object):
    def __init__(self, mode="paper", order=ORDER, cfg=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.order = order
        c = {"budget": 50000, "mode": mode, "max_daily_loss_inr": 1500, "fill_wait_seconds": 4}
        c.update(cfg or {})
        jdump(c, self.d, "trader", "config.json")
        jdump({"orders": [order]}, self.d, "trader", "orders.json")
        self.pass_risk()

    def pass_risk(self, verdict="PASS", kind="entry"):
        jdump({"date": "2026-11-02", "results": [{"fingerprint": nse.fingerprint(self.order), "verdict": verdict,
                                                   "reasons": [] if verdict == "PASS" else ["loss: too big"],
                                                   "kind": kind, "max_loss": 381.13, "warnings": []}]},
              self.d, "trader", "state", "risk.json")

    def args(self, *a):
        p = lambda *x: os.path.join(self.d, "trader", *x)  # noqa: E731
        return ["--orders", p("orders.json"), "--config", p("config.json"), "--risk", p("state", "risk.json"),
                "--prices", p("prices.json"), "--state-dir", p("state"), "--now", "2026-11-02 10:00"] + list(a)

    def run(self, *a, transport=None, env=None):
        old = {k: os.environ.get(k) for k in CREDS}
        for k in CREDS:
            os.environ.pop(k, None)
        os.environ.update(env or {})
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = ticket.main(self.args(*a), transport=transport, download=lambda: SCRIPS, sleep=lambda s: None)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return code, out.getvalue(), err.getvalue()

    def close(self):
        self.tmp.cleanup()


class TestTOTP(unittest.TestCase):
    def test_rfc6238_vectors(self):
        # RFC 6238 appendix B, SHA1, truncated to 6 digits: 94287082 -> 287082 at T=59
        self.assertEqual(angel.totp(FAKE_SECRET, at=59), "287082")
        self.assertEqual(angel.totp(FAKE_SECRET, at=1111111109), "081804")
        self.assertEqual(angel.totp(FAKE_SECRET.lower(), at=1234567890), "005924")

    def test_bad_secret(self):
        with self.assertRaises(angel.BrokerError):
            angel.totp("not base32 !!!", at=59)


class TestCredentials(unittest.TestCase):
    def test_from_env(self):
        c = angel.load_credentials(None, env=CREDS)
        self.assertEqual(c["client_code"], "A123456")

    def test_from_file_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            p = jdump({"api_key": "k", "client_code": "c", "pin": "1", "totp_secret": FAKE_SECRET}, d, "angel.json")
            os.chmod(p, 0o600)
            self.assertEqual(angel.load_credentials(p, env={})["pin"], "1")
            with self.assertRaises(angel.BrokerError) as e:
                angel.load_credentials(os.path.join(d, "none.json"), env={"ANGEL_PIN": "9999"})
            msg = str(e.exception)
            self.assertIn("ANGEL_API_KEY", msg)
            self.assertNotIn("9999", msg)

    def test_scrub(self):
        self.assertEqual(angel.scrub("bad key testkey123 pin 4321", {"api_key": "testkey123", "pin": "4321"}),
                         "bad key *** pin ***")


class TestYes(unittest.TestCase):
    def ok(self, reply, need=False):
        return ticket.parse_yes(reply, ORDER, ["RELIANCE", "TCS"], need_symbol=need)[0]

    def test_accepts(self):
        self.assertTrue(self.ok("yes"))
        self.assertTrue(self.ok("Yes, buy 30 RELIANCE"))
        self.assertTrue(self.ok("yes RELIANCE", need=True))
        self.assertTrue(self.ok("haan"))

    def test_refuses(self):
        for r in ("ok", "sure", "go ahead", "", "yes?", "yes to all", "yes but wait", "yes if it dips",
                  "yes TCS", "yes 50 shares", "yes do both"):
            self.assertFalse(self.ok(r), r)
        self.assertFalse(self.ok("yes", need=True))   # live needs the symbol


class TestPaper(unittest.TestCase):
    def setUp(self):
        self.w = Workspace("paper")

    def tearDown(self):
        self.w.close()

    def test_full_ticket(self):
        code, out, _ = self.w.run("show")
        self.assertEqual(code, 0)
        for s in ("RELIANCE on NSE", "BUY", "LIMIT 1234.50", "MIS", "1223.10", "1257.30", "-₹381.13", "PAPER",
                  "READY", "SEBI"):
            self.assertIn(s, out)

    def test_approve_paper_then_stop_then_pnl(self):
        code, out, _ = self.w.run("approve", "--index", "1", "--reply", "ok")
        self.assertEqual(code, 1)
        self.assertIn("Nothing was sent", out)
        code, out, _ = self.w.run("approve", "--index", "1", "--reply", "yes")
        self.assertEqual(code, 0, out)
        self.assertIn("PAPER: bought 30 RELIANCE", out)
        code, out, _ = self.w.run("show")
        self.assertIn("DONE", out)
        code, _, err = self.w.run("approve", "--index", "1", "--reply", "yes")
        self.assertEqual(code, 1)                       # never twice
        jdump({"as_of": "2026-11-02T05:00:00Z", "prices": {"RELIANCE": 1222.0}}, self.w.d, "trader", "prices.json")
        code, out, _ = self.w.run("mark")
        self.assertIn("stop 1223.10 hit", out)
        self.assertIn("-₹381.13", out)
        pnl = jload(self.w.d, "trader", "state", "pnl.json")
        self.assertAlmostEqual(pnl["realized_net"], -381.13, places=2)

    def test_blocked_and_unchecked_orders_are_not_ready(self):
        self.w.pass_risk("BLOCK")
        code, out, _ = self.w.run("approve", "--index", "1", "--reply", "yes")
        self.assertEqual(code, 1)
        jdump({"orders": [dict(ORDER, qty=31)]}, self.w.d, "trader", "orders.json")
        self.w.pass_risk()
        code, out, err = self.w.run("show")
        self.assertIn("not in the last risk check", out)

    def test_kill_switch(self):
        code, out, _ = self.w.run("kill", "--reason", "done")
        self.assertEqual(code, 0)
        code, out, err = self.w.run("approve", "--index", "1", "--reply", "yes")
        self.assertEqual(code, 1)
        self.assertIn("kill switch", err)

    def test_kill_switch_trips_on_realized_loss(self):
        jdump({"date": "2026-11-02", "realized_net": -1600}, self.w.d, "trader", "state", "pnl.json")
        code, out, _ = self.w.run("show")
        self.assertIn("BLOCKED by the kill switch", out)
        self.assertTrue(jload(self.w.d, "trader", "state", "killswitch.json")["tripped"])

    def test_flatten_writes_a_sell_ticket(self):
        self.w.run("approve", "--index", "1", "--reply", "yes")
        code, out, _ = self.w.run("flatten", "--symbol", "RELIANCE", "--price", "1240")
        self.assertEqual(code, 0)
        o = jload(self.w.d, "trader", "orders.json")["orders"][0]
        self.assertEqual((o["side"], o["qty"], o["order_type"], o["price"]), ("SELL", 30, "LIMIT", "1240.00"))


class TestLiveMocked(unittest.TestCase):
    """UNVERIFIED LIVE: the requests below match Angel One's published docs; no real account was used."""

    def setUp(self):
        self.w = Workspace("live")

    def tearDown(self):
        self.w.close()

    def test_live_needs_credentials(self):
        code, out, err = self.w.run("approve", "--index", "1", "--reply", "yes RELIANCE", transport=FakeAngel())
        self.assertEqual(code, 1)
        self.assertIn("ANGEL_API_KEY", err)

    def test_live_needs_symbol_in_yes(self):
        fake = FakeAngel()
        code, out, _ = self.w.run("approve", "--index", "1", "--reply", "yes", transport=fake, env=CREDS)
        self.assertEqual(code, 1)
        self.assertIn("yes RELIANCE", out)
        self.assertEqual(fake.calls, [])               # nothing was sent

    def test_live_entry_then_stop_loss(self):
        fake = FakeAngel()
        code, out, err = self.w.run("approve", "--index", "1", "--reply", "yes RELIANCE", transport=fake, env=CREDS)
        self.assertEqual(code, 0, out + err)
        paths = [c["path"] for c in fake.calls]
        self.assertEqual(paths, [angel.LOGIN, angel.PLACE, angel.ORDER_BOOK, angel.PLACE, angel.LOGOUT])
        login = fake.calls[0]
        self.assertEqual(login["body"]["clientcode"], "A123456")
        self.assertEqual(login["body"]["password"], "4321")
        self.assertRegex(login["body"]["totp"], r"^\d{6}$")
        self.assertEqual(login["headers"]["X-PrivateKey"], "testkey123")
        self.assertNotIn("Authorization", login["headers"])
        entry = fake.calls[1]
        self.assertEqual(entry["headers"]["Authorization"], "Bearer JWT-SECRET-TOKEN")
        b = entry["body"]
        self.assertEqual((b["variety"], b["tradingsymbol"], b["symboltoken"], b["transactiontype"], b["exchange"],
                          b["ordertype"], b["producttype"], b["duration"], b["price"], b["quantity"]),
                         ("NORMAL", "RELIANCE-EQ", "2885", "BUY", "NSE", "LIMIT", "INTRADAY", "DAY", "1234.50", "30"))
        self.assertLess(len(b["ordertag"]), 20)
        sl = fake.calls[3]["body"]
        self.assertEqual((sl["variety"], sl["ordertype"], sl["transactiontype"], sl["triggerprice"]),
                         ("STOPLOSS", "STOPLOSS_LIMIT", "SELL", "1223.10"))
        self.assertLess(float(sl["price"]), 1223.10)
        self.assertIn("261102000001", out)
        self.assertIn("UNVERIFIED", out)
        for secret in ("testkey123", "4321", FAKE_SECRET, "JWT-SECRET-TOKEN"):
            self.assertNotIn(secret, out + err)
        state = json.dumps(jload(self.w.d, "trader", "state", "broker.json"))
        for secret in ("testkey123", FAKE_SECRET, "JWT-SECRET-TOKEN"):
            self.assertNotIn(secret, state)

    def test_live_unfilled_entry_warns_no_stop(self):
        fake = FakeAngel(fill="open")
        code, out, err = self.w.run("approve", "--index", "1", "--reply", "yes RELIANCE", transport=fake, env=CREDS)
        self.assertEqual(code, 0, err)
        self.assertIn("NO stop-loss", out)
        self.assertEqual([c["path"] for c in fake.calls].count(angel.PLACE), 1)

    def test_live_login_failure_is_scrubbed(self):
        fake = FakeAngel(fail_login=True)
        code, out, err = self.w.run("approve", "--index", "1", "--reply", "yes RELIANCE", transport=fake, env=CREDS)
        self.assertEqual(code, 1)
        self.assertIn("Invalid totp", err)
        self.assertNotIn("4321", err)
        rec = jload(self.w.d, "trader", "state", "broker.json")["orders"][-1]
        self.assertEqual(rec["status"], "failed")

    def test_live_tick_checked_against_master(self):
        bad = dict(ORDER, price="1234.55", plan=dict(ORDER["plan"], tick_size=0.05))
        w = Workspace("live", order=bad)
        try:
            code, out, err = w.run("approve", "--index", "1", "--reply", "yes RELIANCE", transport=FakeAngel(), env=CREDS)
            self.assertEqual(code, 1)
            self.assertIn("tick", err)
        finally:
            w.close()

    def test_live_pnl_from_trade_book_trips_kill_switch(self):
        w = Workspace("live", cfg={"max_daily_loss_inr": 300})
        try:
            code, out, err = w.run("pnl", transport=FakeAngel(), env=CREDS)
            self.assertEqual(code, 0, err)
            self.assertIn("-₹342.00 gross", out)
            self.assertIn("Kill switch: ON", out)
        finally:
            w.close()

    def test_live_cancel_needs_yes_with_the_id(self):
        fake = FakeAngel()
        code, out, _ = self.w.run("cancel", "--order-id", "261102000002", "--reply", "yes", transport=fake, env=CREDS)
        self.assertEqual(code, 1)
        self.assertEqual(fake.calls, [])
        code, out, _ = self.w.run("cancel", "--order-id", "261102000002", "--reply", "yes cancel 261102000002",
                                  transport=fake, env=CREDS)
        self.assertEqual(code, 0)
        self.assertIn(angel.CANCEL, [c["path"] for c in fake.calls])

    def test_throttle(self):
        waits = []
        clock = [100.0]
        a = angel.AngelOne({"api_key": "k"}, transport=FakeAngel(), clock=lambda: clock[0],
                           sleep=lambda s: waits.append(s), min_gap=1.0)
        a._throttle()
        a._throttle()
        self.assertEqual(len(waits), 1)

    def test_kite_is_a_stub(self):
        with self.assertRaises(angel.BrokerError):
            angel.KiteConnect()

    def test_realized_from_trades(self):
        gross, net = angel.realized_from_trades([
            {"tradingsymbol": "X", "transactiontype": "BUY", "fillsize": "10", "fillprice": "100"},
            {"tradingsymbol": "X", "transactiontype": "SELL", "fillsize": "10", "fillprice": "110"},
            {"tradingsymbol": "Y", "transactiontype": "BUY", "fillsize": "5", "fillprice": "50"}])
        self.assertEqual((gross, net), (100.0, 100.0))


if __name__ == "__main__":
    unittest.main()
