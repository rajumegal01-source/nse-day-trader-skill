"""alert.py STOP_MULT wide-stop mode and the walk-forward grid. Offline."""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import alert  # noqa: E402
import risk  # noqa: E402
import walkforward  # noqa: E402
import importlib  # noqa: E402

_t = importlib.import_module("test_lab_target_r")   # shared offline bars + scan helper
scan, walk = _t.scan, _t.walk


class TestStopMult(unittest.TestCase):
    def test_env_parse(self):
        self.assertIsNone(alert.stop_mult_env(""))
        self.assertEqual(alert.stop_mult_env("2"), 2.0)
        with self.assertRaises(ValueError):
            alert.stop_mult_env("0")
        self.assertEqual(alert.opts(None, None), {})
        self.assertEqual(alert.opts(0.5, 2.0), {"target_r": 0.5, "stop_mult": 2.0})

    def test_scan_one_wide_stop_target_in_original_r(self):
        B = walk(6, seed=11)
        base, wide = scan(B, target_r=0.5), scan(B, target_r=0.5, stop_mult=2.0)
        self.assertTrue(base)
        self.assertEqual(len(base), len(wide))
        for h0, h in zip(base, wide):
            sd = 1 if h["side"] == "LONG" else -1
            r0 = abs(h0["entry"] - h0["stop"])
            self.assertAlmostEqual(h["stop"], h["entry"] - sd * 2 * r0, delta=0.021)   # stop 2R away
            self.assertEqual(h["target"], h0["target"])                                # target still 0.5R
            if h0["status"] == "target":
                self.assertEqual(h["status"], "target")    # a wider stop never loses a target
            if h["status"] == "stop":
                self.assertEqual(h0["status"], "stop")     # a wide stop-out was a narrow one first
        self.assertEqual(scan(B), scan(B, stop_mult=None))  # unset: no change

    def test_stopouts_use_stored_stop(self):
        picks = [dict(symbol="A", setup="fvg", side="LONG", time="10:00", stop=98.0)]
        narrow = dict(symbol="A", setup="fvg", side="LONG", time="10:00", status="stop", stop=99.0)
        wide = dict(narrow, status="live", stop=98.0)
        self.assertEqual(risk.stopouts(picks, [narrow]), 0)        # the 1x stop is not the pick's stop
        self.assertEqual(risk.stopouts(picks, [narrow, wide]), 0)
        self.assertEqual(risk.stopouts(picks, [narrow, dict(wide, status="stop")]), 1)

    def hit(self):
        return dict(symbol="X", day="2026-11-05", setup="pdhl", rank=1, status="live", side="LONG", time="10:00",
                    entry=100.0, stop=98.0, target=100.5, last=100.1, test={"n": 9, "win": 70.0, "exp": 0.3})

    def run_alert(self, sm, tr=None, argv=(), picks=None):
        calls = []

        def fake(*a, **kw):
            calls.append(kw)
            return [self.hit()], []
        mem = {"stocks": {s: {"setups": {"pdhl": {"best": [{"p": {}}]}}} for s in "XY"}}
        with tempfile.TemporaryDirectory() as d:
            st = os.path.join(d, "s.json")
            if picks is not None:
                with open(st, "w") as fh:
                    json.dump({"2026-11-05#picks": picks}, fh)
            with mock.patch.object(alert, "STOP_MULT", sm), mock.patch.object(alert, "TARGET_R", tr), \
                    mock.patch.object(alert.lab, "scan_one", side_effect=fake), \
                    mock.patch.object(alert.lab, "load_memory", return_value=mem), \
                    mock.patch.object(alert, "nifty_bars", return_value=[]), mock.patch("builtins.print"):
                alert.main(["--local", "--day", "2026-11-05", "--state", st, "--filters", "none"] + list(argv))
            with open(st) as fh:
                return calls, json.load(fh)

    def test_alert_saves_stop_mult(self):
        calls, state = self.run_alert(2.0, 0.5)
        self.assertEqual(calls[0], {"target_r": 0.5, "stop_mult": 2.0})
        p = state["2026-11-05#picks"][0]
        self.assertEqual((p["stop_mult"], p["stop"], p["target_r"]), (2.0, 98.0, 0.5))
        self.assertIn("98.0 (2x)", alert.line(dict(self.hit(), stop_mult=2.0)))

    def test_alert_unset_unchanged(self):
        calls, state = self.run_alert(None)
        self.assertEqual(calls[0], {})
        self.assertNotIn("stop_mult", state["2026-11-05#picks"][0])

    def test_result_grades_with_saved_stop(self):
        pk = [dict(symbol="X", setup="pdhl", side="LONG", time="10:00", entry=100.0, stop=98.0, target=100.5,
                   rules="none", stop_mult=2.0)]
        calls, _ = self.run_alert(None, None, ["--result"], pk)
        self.assertEqual(calls[0], {"stop_mult": 2.0})

    def test_stopouts_rescan_old_pick(self):
        pk = [dict(symbol="Y", setup="pdhl", side="LONG", time="09:30", entry=1, stop=0.9, target=1.1, rules="none")]
        calls, _ = self.run_alert(2.0, None, picks=pk)
        self.assertIn({"stop_mult": 2.0}, calls)     # today's scan in wide mode
        self.assertIn({}, calls)                     # the 1x pick re-scanned with its own stop

    def test_walkforward_grid(self):
        B = walk(40, seed=3)
        days = sorted({b["day"] for b in B})
        ctx = {d: None for d in days}
        tr = walkforward.walk_stock("T", B, days, ctx, "reduced", (0.5,), (1, 2))
        self.assertTrue(tr)
        self.assertTrue(all(set(t["alt"]) == {"1|cur", "1|0.5", "2|cur", "2|0.5"} for t in tr))
        self.assertTrue(all(t["alt"]["1|cur"][:2] == [t["pct"], t["how"]] for t in tr))   # 1x own = baseline
        tab = walkforward.grid_table(tr, sorted({t["day"] for t in tr}), ["current", "1|cur", "2|0.5"], 5)
        self.assertEqual(tab["current"], tab["1|cur"])
        self.assertLessEqual(tab["2|0.5"]["all"]["stop"], tab["current"]["all"]["stop"])
        self.assertGreaterEqual(tab["2|0.5"]["picks"]["mdd"], 0)
        self.assertEqual(walkforward.mdd([dict(day="d", time="10:00", pct=p) for p in (1, -2, -1, 3)]), 3)
        self.assertEqual(walkforward.mkey(1.5, "cur"), "1.5|cur")


if __name__ == "__main__":
    unittest.main()
