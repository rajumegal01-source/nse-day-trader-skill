"""backtest/paper_journal.py: grading a paper trade from 5-minute bars (offline)."""

import importlib.util
import os
import unittest

from _load import ROOT

spec = importlib.util.spec_from_file_location("paper_journal", os.path.join(ROOT, "backtest", "paper_journal.py"))
pj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pj)

TR = dict(symbol="X", date="2026-11-04", time="11:05", side="LONG", entry=100.0, stop=99.0, target=101.5)


class TestGrade(unittest.TestCase):
    def test_target(self):
        g = pj.grade(TR, [("11:10", 100.5, 99.5, 100.2), ("11:15", 101.6, 100.1, 101.4)])
        self.assertEqual((g["result"], g["exit"]), ("target", 101.5))

    def test_stop_wins_a_tie(self):
        g = pj.grade(TR, [("11:10", 101.6, 98.9, 100.0)])
        self.assertEqual(g["result"], "stop")
        self.assertLess(g["pct"], 0)

    def test_close_and_gaps(self):
        g = pj.grade(TR, [("11:10", 100.5, 99.5, 100.2), ("15:15", 100.6, 100.1, 100.4)])
        self.assertEqual((g["result"], g["exit"]), ("close", 100.4))
        self.assertIn("15:20", g["gaps"])


if __name__ == "__main__":
    unittest.main()
