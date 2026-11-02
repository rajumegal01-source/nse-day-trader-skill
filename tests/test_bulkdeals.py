"""trader-bulkdeals on NSE's 2026-11-02 bulk/block files, SAST and PIT captures (offline)."""

import os
import tempfile
import unittest

from _load import fix, load, run, run_json

deals = load("trader-bulkdeals", "deals")
OFF = ["--offline", fix("trader-bulkdeals"), "--now", "2026-11-02T14:00:00Z"]


class TestDeals(unittest.TestCase):
    def test_bulk_and_empty_block(self):
        with open(fix("trader-bulkdeals", "bulk.csv"), encoding="utf-8") as fh:
            bulk = deals.parse_deals_csv(fh.read(), "bulk")
        self.assertEqual(len(bulk), 87)
        top = max(bulk, key=lambda r: r["value"])
        self.assertEqual((top["symbol"], top["client"], top["side"]), ("EDELALTS", "HDFC MUTUAL FUND", "BUY"))
        with open(fix("trader-bulkdeals", "block.csv"), encoding="utf-8") as fh:
            self.assertEqual(deals.parse_deals_csv(fh.read(), "block"), [])

    def test_cli_filters(self):
        code, doc, err = run_json("trader-bulkdeals", "deals.py", OFF + ["deals", "--min-cr", "50"])
        self.assertEqual(code, 0, err)
        self.assertTrue(all(r["value"] >= 50e7 for r in doc["deals"]))
        code, doc, err = run_json("trader-bulkdeals", "deals.py", OFF + ["deals", "--client", "hdfc mutual"])
        self.assertTrue(doc["deals"])
        code, out, err = run("trader-bulkdeals", "deals.py", OFF + ["deals", "--symbols", "NOSUCH"])
        self.assertEqual(code, 1)

    def test_sast_and_pit(self):
        code, out, err = run("trader-bulkdeals", "deals.py", OFF + ["sast", "--days", "3", "--promoters"])
        self.assertEqual(code, 0, err)
        self.assertIn("promoter", out)
        code, doc, err = run_json("trader-bulkdeals", "deals.py", OFF + ["insider", "RELIANCE"])
        self.assertEqual(len(doc), 20)
        market = [r for r in doc if deals.market_trade(r)]
        self.assertTrue(market)
        self.assertTrue(all("Market" in r["mode"] for r in market))
        self.assertTrue(any(r["mode"] == "Off Market" for r in doc))

    def test_new_remembers(self):
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "deals.json")
            code, out, err = run("trader-bulkdeals", "deals.py", OFF + ["new", "--state", st])
            self.assertEqual(code, 0, err)
            code, out, err = run("trader-bulkdeals", "deals.py", OFF + ["new", "--state", st])
            self.assertEqual(code, 1)
            self.assertIn("0 deals", out)


if __name__ == "__main__":
    unittest.main()
