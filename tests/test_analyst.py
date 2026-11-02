"""trader-analyst on RELIANCE (real NSE integrated-filing XBRL and Yahoo captures, offline)."""

import unittest

from _load import fix, load, run_json

facts = load("trader-analyst", "facts")


class TestAnalyst(unittest.TestCase):
    def test_nse_xbrl_quarter(self):
        with open(fix("trader-analyst", "INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml"), "rb") as fh:
            q = facts.parse_xbrl(fh.read())
        self.assertEqual((q["start"], q["end"]), ("2026-07-01", "2026-09-30"))
        self.assertEqual(q["revenue"], 3328610000000.0)
        self.assertEqual(q["net_profit"], 295500000000.0)      # Rs 29,550 crore
        self.assertEqual(q["eps_basic"], 18.88)

    def test_offline_run_with_growth_and_lag_note(self):
        code, doc, err = run_json("trader-analyst", "facts.py", ["RELIANCE", "--offline", fix("trader-analyst")])
        self.assertEqual(code, 0, err)
        r = doc[0]
        self.assertIn("NSE", r["source"])
        q = r["quarters"][0]
        self.assertEqual(q["end"], "2026-09-30")
        self.assertAlmostEqual(q["revenue_yoy"], 28.6)
        self.assertAlmostEqual(q["net_profit_yoy"], 33.8)
        self.assertAlmostEqual(q["revenue_qoq"], 6.7)
        self.assertTrue(any("lags" in n for n in r["notes"]))

    def test_yahoo_fallback_skips_qoq_across_a_gap(self):
        code, doc, err = run_json("trader-analyst", "facts.py", ["RELIANCE", "--offline", fix("trader-analyst"),
                                                                 "--source", "yahoo"])
        self.assertEqual(code, 0, err)
        qs = {q["end"]: q for q in doc[0]["quarters"]}
        self.assertIsNone(qs["2025-12-31"]["revenue_qoq"])     # Yahoo has no 2025-09-30 quarter
        self.assertIsNotNone(qs["2026-06-30"]["revenue_qoq"])

    def test_no_source(self):
        code, out, err = facts.main(["NOSUCH", "--offline", fix("trader-analyst")]), None, None
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
