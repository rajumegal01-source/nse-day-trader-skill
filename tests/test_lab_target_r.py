"""alert.py TARGET_R small-target mode and the walk-forward comparison. Offline."""

import datetime as dt
import json
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
import alert  # noqa: E402
import core  # noqa: E402
import lab  # noqa: E402
import walkforward  # noqa: E402


def walk(days=6, seed=1, px=1000.0):
    """Random-walk 5-min bars (as in test_lab_setups2)."""
    rnd, out = random.Random(seed), []
    for d in range(days):
        day = (dt.date(2026, 8, 3) + dt.timedelta(days=d)).isoformat()
        for m in core.SLOTS:
            o, c = px, px * (1 + rnd.gauss(0, 0.002))
            h, l = max(o, c) * (1 + abs(rnd.gauss(0, 0.001))), min(o, c) * (1 - abs(rnd.gauss(0, 0.001)))
            out.append(dict(day=day, m=m, o=o, h=h, l=l, c=c, v=rnd.randint(500, 3000)))
            px = c
    return out


DAILY = [dict(day="2026-%02d-%02d" % (6 + k // 28, 1 + k % 28), m=0, o=100, h=101, l=99, c=100 + k * 0.1, v=1)
         for k in range(40)]
P = dict(kind="st2", side="both", dead=870, stop="natural", tgt="eod", filt="none")
INFO = {"setups": {"trend": {"best": [{"p": P, "test": {"n": 9, "win": 70.0, "exp": 0.3}}]}}}


def scan(B, **kw):
    with mock.patch.object(core, "fetch", side_effect=lambda s, r, iv, c=None: DAILY if iv == "1d" else B):
        return lab.scan_one("TEST", INFO, B[-1]["day"], **kw)[0]


class TestTargetR(unittest.TestCase):
    def test_env_parse(self):
        self.assertIsNone(alert.target_r_env(""))
        self.assertEqual(alert.target_r_env("0.5"), 0.5)
        with self.assertRaises(ValueError):
            alert.target_r_env("-1")

    def test_scan_one_target(self):
        B = walk(6, seed=11)
        base, small = scan(B), scan(B, target_r=0.5)
        self.assertTrue(base)
        self.assertEqual(len(base), len(small))
        for h0, h in zip(base, small):
            self.assertIsNone(h0["target"])                 # eod setting: 15:15 exit normally
            sd = 1 if h["side"] == "LONG" else -1
            self.assertAlmostEqual(h["target"], h["entry"] + sd * 0.5 * abs(h["entry"] - h["stop"]), delta=0.011)
            self.assertEqual((h["entry"], h["stop"]), (h0["entry"], h0["stop"]))   # stop never moves
            if h0["status"] == "stop" and h["status"] != "target":
                self.assertEqual(h["status"], "stop")

    def hit(self):
        return dict(symbol="X", day="2026-11-05", setup="pdhl", rank=1, status="live", side="LONG", time="10:00",
                    entry=100.0, stop=99.0, target=100.5, last=100.1, test={"n": 9, "win": 70.0, "exp": 0.3})

    def run_alert(self, tr, argv=(), picks=None):
        calls = []

        def fake(*a, **kw):
            calls.append(kw)
            return [self.hit()], []
        mem = {"stocks": {"X": {"setups": {"pdhl": {"best": [{"p": {}}]}}}}}
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "s.json")
            if picks is not None:
                with open(st, "w") as fh:
                    json.dump({"2026-11-05#picks": picks}, fh)
            with mock.patch.object(alert, "TARGET_R", tr), mock.patch.object(alert.lab, "scan_one", side_effect=fake), \
                    mock.patch.object(alert.lab, "load_memory", return_value=mem), \
                    mock.patch.object(alert, "nifty_bars", return_value=[]), mock.patch("builtins.print"):
                alert.main(["--local", "--day", "2026-11-05", "--state", st, "--filters", "none"] + list(argv))
            if not os.path.exists(st):
                return calls, {}
            with open(st) as fh:
                return calls, json.load(fh)

    def test_alert_saves_target_r(self):
        calls, state = self.run_alert(0.5)
        self.assertEqual(calls[0], {"target_r": 0.5})
        self.assertEqual(state["2026-11-05#picks"][0]["target_r"], 0.5)
        self.assertEqual(state["2026-11-05#picks"][0]["target"], 100.5)
        self.assertIn("(0.5R)", alert.line(dict(self.hit(), target_r=0.5)))

    def test_alert_unset_unchanged(self):
        calls, state = self.run_alert(None)
        self.assertEqual(calls[0], {})
        self.assertNotIn("target_r", state["2026-11-05#picks"][0])
        self.assertNotIn("R)", alert.line(self.hit()))

    def test_result_grades_with_saved_target_r(self):
        pk = [dict(symbol="X", setup="pdhl", side="LONG", time="10:00", entry=100.0, stop=99.0, target=100.5,
                   rules="none", target_r=0.5)]
        calls, _ = self.run_alert(None, ["--result"], pk)
        self.assertEqual(calls[0], {"target_r": 0.5})

    def test_max_per_day_still_works(self):
        with mock.patch.object(alert, "MAX_PER_DAY", 1):
            pk = [dict(symbol="Y", setup="pdhl", side="LONG", time="09:30", entry=1, stop=0.9, target=1.1, rules="none")]
            calls, state = self.run_alert(0.5, picks=pk)
        self.assertEqual(calls, [])
        self.assertEqual(len(state["2026-11-05#picks"]), 1)

    def test_walkforward_alt_and_table(self):
        B = walk(40, seed=3)
        days = sorted({b["day"] for b in B})
        tr = walkforward.walk_stock("T", B, days, {d: None for d in days}, "reduced", (0.5, 1.0))
        self.assertTrue(tr)
        self.assertTrue(all(set(t["alt"]) == {"0.5", "1.0"} for t in tr))
        tab = walkforward.target_r_table(tr, sorted({t["day"] for t in tr}), (0.5, 1.0), 5)
        self.assertEqual(set(tab), {"current", "0.5", "1.0"})
        self.assertEqual(tab["current"]["all"]["n"], len(tr))
        self.assertGreaterEqual(tab["0.5"]["all"]["win"], tab["1.0"]["all"]["win"])
        plain = walkforward.walk_stock("T", B, days, {d: None for d in days}, "reduced")
        self.assertEqual([dict(t, alt=None) for t in plain], [dict(t, alt=None) for t in tr])
        self.assertNotIn("alt", plain[0])


if __name__ == "__main__":
    unittest.main()
