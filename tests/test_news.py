"""trader-news on RELIANCE, 2026-11-02 (real Google News, Yahoo and NSE captures, offline)."""

import datetime
import os
import tempfile
import unittest

from _load import fix, load, run, run_json

news = load("trader-news", "news")
NOW = "2026-11-02T15:00:00Z"


class TestNews(unittest.TestCase):
    def test_offline_run(self):
        with tempfile.TemporaryDirectory() as d:
            args = ["--tickers", "RELIANCE", "--offline", fix("trader-news"), "--now", NOW, "--hours", "72",
                    "--state", os.path.join(d, "news.json")]
            code, doc, err = run_json("trader-news", "news.py", args)
            self.assertEqual(code, 0, err)
            kinds = {i["kind"] for i in doc["items"]}
            self.assertEqual(kinds, {"headline", "filing"})
            filings = [i for i in doc["items"] if i["kind"] == "filing"]
            self.assertTrue(all(i["source"] == "NSE filing" for i in filings))
            self.assertTrue(any(i["important"] for i in filings))
            self.assertTrue(any("Google News" in i["source"] for i in doc["items"]))
            mv = doc["moves"][0]
            self.assertEqual(mv["ticker"], "RELIANCE")
            # second run: everything seen
            code, out, err = run("trader-news", "news.py", args)
            self.assertEqual(code, 1)
            self.assertIn("Nothing new", out)
            self.assertIn("IST", out)

    def test_parsers(self):
        with open(fix("trader-news", "nse-RELIANCE.json"), "rb") as fh:
            items = news.parse_nse(fh.read(), "RELIANCE")
        self.assertTrue(items)
        self.assertEqual(items[0]["time"].tzinfo, datetime.timezone.utc)
        self.assertEqual(news.parse_nse_time("01-Nov-2026 23:09:22"),
                         datetime.datetime(2026, 11, 1, 17, 39, 22, tzinfo=datetime.timezone.utc))
        with self.assertRaises(news.NewsError):
            news.parse_nse(b"<html>blocked</html>", "RELIANCE")

    def test_tags_and_symbols(self):
        self.assertEqual(news.yahoo_symbol("RELIANCE"), "RELIANCE.NS")
        self.assertEqual(news.yahoo_symbol("TCS.BO"), "TCS.BO")
        it = [{"title": "Reliance Q2 profit rises 33.8%; SEBI probe on block deal", "summary": "", "ticker": "RELIANCE",
               "kind": "headline"}]
        tags = news.tag(it, {"RELIANCE": "Reliance Industries Limited"})[0]["tags"]
        for t in ("results", "regulatory", "deal"):
            self.assertIn(t, tags)


if __name__ == "__main__":
    unittest.main()
