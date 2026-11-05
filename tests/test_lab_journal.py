"""lab/journal_stats.py (Phase H): expectancy, R-multiples, breakdowns from both journal formats."""

import json
import os
import sys
import tempfile
import unittest

from _load import ROOT, run

sys.path.insert(0, os.path.join(ROOT, "lab"))
import journal_stats as js  # noqa: E402

STATE = {
    "2026-11-03": ["X|fvg|LONG|10:05"],                                    # sent keys: ignored
    "2026-11-03#picks": [dict(symbol="AAA", setup="fvg", side="LONG", time="10:05", entry=100, stop=99, target=102),
                         dict(symbol="BBB", setup="orb", side="SHORT", time="10:30", entry=200, stop=202, target=196)],
    "2026-11-03#results": [dict(symbol="AAA", setup="fvg", side="LONG", time="10:05", result="target", pct=1.95),
                           dict(symbol="BBB", setup="orb", side="SHORT", time="10:30", result="stop", pct=-1.05)],
    "2026-11-04#picks": [dict(symbol="CCC", setup="fvg", side="LONG", time="11:00", entry=50, stop=49.5, target=None)],
}
PAPER = [dict(symbol="POWERGRID", date="2026-11-05", time="11:05", side="LONG", entry=260.0, stop=257.4,
              target=265.2, result="stop", pct=-1.05),
         dict(symbol="OPEN", date="2026-11-05", time="11:05", side="LONG", entry=1, stop=0.9)]   # not graded


class TestJournal(unittest.TestCase):
    def test_collect_both_sources(self):
        tr = js.collect(STATE, PAPER)
        self.assertEqual([t["symbol"] for t in tr], ["AAA", "BBB", "POWERGRID"])   # CCC, OPEN ungraded
        self.assertEqual([t["src"] for t in tr], ["pick", "pick", "paper"])
        self.assertEqual(tr[0]["r"], 1.95)                     # risk 1% -> 1.95R
        self.assertEqual(tr[1]["r"], -1.05)
        self.assertEqual(tr[2]["r"], -1.05)
        self.assertEqual(js.collect(STATE, PAPER, since="2026-11-04"), js.collect({}, PAPER))

    def test_r_multiple_edge_cases(self):
        self.assertIsNone(js.r_multiple(1.0, 100, 100))
        self.assertIsNone(js.r_multiple(1.0, None, 99))
        self.assertEqual(js.r_multiple(-0.5, 100, 99.5), -1.0)

    def test_stats(self):
        s = js.stats(js.collect(STATE, PAPER))
        self.assertEqual((s["n"], s["win"]), (3, 33.3))
        self.assertAlmostEqual(s["avg"], -0.05)
        self.assertEqual(s["profit_factor"], round(1.95 / 2.1, 2))
        self.assertAlmostEqual(s["exp_r"], round((1.95 - 1.05 - 1.05) / 3, 3))
        self.assertEqual((s["win_streak"], s["loss_streak"]), (1, 2))
        self.assertAlmostEqual(s["max_dd"], 2.1)
        self.assertEqual(js.stats([]), dict(n=0))
        self.assertIsNone(js.stats([dict(pct=1.0, r=None)])["profit_factor"])    # no losses

    def test_breakdowns(self):
        res = js.analyze(js.collect(STATE, PAPER))
        self.assertEqual(sorted(res["by_setup"]), ["fvg", "orb"])
        self.assertEqual(res["by_side"]["SHORT"]["n"], 1)
        self.assertEqual(sorted(res["by_weekday"]), ["Thu", "Tue"])      # 2026-11-03 Tue, 11-05 Thu
        self.assertEqual(res["by_source"]["paper"]["n"], 1)
        t = js.text(res)
        self.assertIn("far too few", t)
        self.assertIn("not investment advice", t)

    def test_cli_with_files_and_empty(self):
        with tempfile.TemporaryDirectory() as d:
            sp, pp = os.path.join(d, "s.json"), os.path.join(d, "p.json")
            json.dump(STATE, open(sp, "w"))
            json.dump(PAPER, open(pp, "w"))
            code, out, err = run("lab", "journal_stats.py", ["--state", sp, "--paper", pp])
            self.assertEqual(code, 0, err)
            self.assertIn("ALL           3 trades", out)
            code, out, _ = run("lab", "journal_stats.py", ["--state", os.path.join(d, "none"), "--paper", "x"])
            self.assertIn("no graded trades yet", out)


if __name__ == "__main__":
    unittest.main()
