"""trader-timemachine on RELIANCE's real 60 days of 5-minute bars to 2026-11-02 (offline, seed 19)."""

import unittest

from _load import fix, load, run, run_json

tm = load("trader-timemachine", "timemachine")
CHART = fix("trader-timemachine", "RELIANCE-60d5m.json.gz")
FLAGS = ["run", "--symbol", "RELIANCE", "--date", "2026-11-02", "--entry", "1234.50", "--stop", "1223.10",
         "--target", "1245.90", "--entry-time", "9:35 AM", "--setup", "orb", "--stop-rule", "or_mid",
         "--offline", CHART, "--now", "2026-11-02 10:00"]


class TestTimeMachine(unittest.TestCase):
    def test_reproducible_numbers(self):
        code, doc, err = run_json("trader-timemachine", "timemachine.py", FLAGS)
        self.assertEqual(code, 0, err)
        mc = doc["mc"]
        self.assertEqual(mc["pool_sessions"], 59)
        self.assertAlmostEqual(mc["p_target"], 0.3095, places=4)
        self.assertAlmostEqual(mc["p_stop"], 0.3407, places=4)
        self.assertEqual(doc["history"]["triggered"], 31)
        self.assertIn("coin flip", doc["verdict"])
        self.assertIn("IST", doc["data"]["last_bar"])

    def test_session_constants(self):
        self.assertEqual(tm.SESSION_BARS, 75)
        self.assertEqual(tm.OPEN_MIN, 9 * 60 + 15)
        self.assertEqual(tm.CLOSE_MIN, 15 * 60 + 30)

    def test_muhurat_refused(self):
        args = list(FLAGS)
        args[args.index("2026-11-02")] = "2026-11-08"
        code, out, err = run("trader-timemachine", "timemachine.py", args)
        self.assertNotEqual(code, 0)
        self.assertIn("special session", err)

    def test_gap_filling(self):
        bars = {i: {"date": "2026-10-01", "slot": i, "start": "x", "o": 1, "h": 1, "l": 1, "c": 1.0 + i, "v": 1}
                for i in range(75) if i not in (10, 11)}
        full, short = tm.full_sessions({"2026-10-01": bars}, "2026-11-02")
        self.assertEqual(len(full), 1)
        self.assertTrue(full[0][1][10]["filled"])
        self.assertEqual(full[0][1][10]["c"], 10.0)        # flat at the previous close
        del bars[20], bars[30]
        full, short = tm.full_sessions({"2026-10-01": bars}, "2026-11-02")
        self.assertEqual((len(full), len(short)), (0, 1))  # more than 3 missing: left out

    def test_until_flat_by(self):
        args = FLAGS + ["--until", "15:10"]
        code, doc, err = run_json("trader-timemachine", "timemachine.py", args)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["mc"]["until"], "15:10")


if __name__ == "__main__":
    unittest.main()
