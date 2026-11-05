"""lab/setups2.py (Phase B detectors), lab/score.py, and their wiring into lab/alert (offline)."""

import json
import os
import random
import sys
import tempfile
import unittest
from unittest import mock

from _load import ROOT, load

sys.path.insert(0, os.path.join(ROOT, "lab"))
import core  # noqa: E402
import lab  # noqa: E402
import score  # noqa: E402
import setups2 as s2  # noqa: E402

alert = load("lab", "alert")

D1, D2 = "2026-11-03", "2026-11-04"


def bar(m, o, h, l, c, v=1000, day=D2):
    return dict(day=day, m=m, o=o, h=h, l=l, c=c, v=v)


def flat_day(day=D1, hi=101.0, lo=99.0, close=100.0, n=6):
    """A short previous session with high `hi`, low `lo`, last close `close`."""
    out = [bar(555 + 5 * k, 100, 100.2, 99.8, 100, day=day) for k in range(n)]
    out[1] = bar(560, 100, hi, 99.8, 100, day=day)
    out[2] = bar(565, 100, 100.2, lo, 100, day=day)
    out[-1] = bar(555 + 5 * (n - 1), 100, 100.2, 99.8, close, day=day)
    return out


def walk(days=6, seed=1, start=1000.0):
    rnd = random.Random(seed)
    out, px = [], start
    for d in range(days):
        day = "2026-10-%02d" % (10 + d)
        for m in core.SLOTS:
            o = px
            c = o * (1 + rnd.gauss(0, 0.002))
            h, l = max(o, c) * (1 + abs(rnd.gauss(0, 0.001))), min(o, c) * (1 - abs(rnd.gauss(0, 0.001)))
            out.append(dict(day=day, m=m, o=o, h=h, l=l, c=c, v=rnd.randint(500, 3000)))
            px = c
    return out


class TestLevels(unittest.TestCase):
    def test_prev_day_and_pivots(self):
        B = flat_day() + [bar(555, 100, 100.2, 99.9, 100.1)]
        self.assertEqual(s2.prev_day_hlc(B), {D2: (101.0, 99.0, 100.0)})
        pv = s2.pivots(101.0, 99.0, 100.0)
        self.assertAlmostEqual(pv["P"], 100.0)
        self.assertAlmostEqual(pv["R1"], 101.0)
        self.assertAlmostEqual(pv["S1"], 99.0)
        self.assertLessEqual(pv["BC"], pv["TC"])

    def test_nice_step(self):
        self.assertEqual(s2.nice_step(1250, 0.01), 10.0)
        self.assertEqual(s2.nice_step(1250, 0.025), 20.0)
        self.assertEqual(s2.nice_step(4800, 0.01), 50.0)


class TestDetectors(unittest.TestCase):
    def test_pdhl_break_and_fail(self):
        B = flat_day() + [bar(555, 100, 100.5, 99.9, 100.4), bar(560, 100.4, 101.6, 100.3, 101.5),
                          bar(565, 101.5, 101.7, 100.6, 100.8)]
        k = len(B) - 2
        self.assertIn((k, 1, 100.3, "pdhl"), s2.cand_pdhl(B, "break", 0.0))
        fail = s2.cand_pdhl(B, "fail", 0.0)
        self.assertEqual(fail, [(k + 1, -1, 101.7, "pdhl")])

    def test_cpr_bounce_and_break(self):
        B = flat_day() + [bar(555, 100.4, 100.6, 100.4, 100.5), bar(560, 100.5, 100.6, 99.9, 100.3)]
        self.assertEqual(s2.cand_cpr(B, "P", "bounce")[-1], (len(B) - 1, 1, 99.9, "cpr"))
        B = flat_day() + [bar(555, 99.7, 99.9, 99.6, 99.8), bar(560, 99.8, 100.6, 99.7, 100.5)]
        self.assertEqual(s2.cand_cpr(B, "P", "break")[-1], (len(B) - 1, 1, 99.7, "cpr"))

    def test_inside15_breakout(self):
        B = [bar(555, 100, 102, 100, 101), bar(560, 101, 101.5, 100.2, 101), bar(565, 101, 101.2, 100.4, 101),
             bar(570, 101, 101.5, 100.5, 101), bar(575, 101, 101.4, 100.6, 101), bar(580, 101, 101.3, 100.7, 101),
             bar(585, 101, 101.9, 100.9, 101.8)]
        self.assertEqual(s2.cand_inside(B, "inside15", 6), [(6, 1, 100.5, "inside")])

    def test_nr7day_breakout(self):
        B = []
        for d in range(8):
            w = 0.2 if d == 6 else 2.0          # day 7 (index 6) is the narrowest of the last 7
            day = "2026-10-%02d" % (10 + d)
            B += [bar(555, 100, 100 + w / 2, 100 - w / 2, 100, day=day), bar(560, 100, 100.05, 99.95, 100, day=day)]
        B[-2] = bar(555, 100, 100.3, 100, 100.25, day=B[-2]["day"])
        out = s2.cand_inside(B, "nr7day", 6)
        self.assertEqual(out, [(len(B) - 2, 1, 100.0, "inside")])

    def test_sweep_pdh_reversal(self):
        B = flat_day() + [bar(555, 100.5, 100.7, 100.4, 100.6), bar(560, 100.6, 101.3, 100.5, 100.8)]
        self.assertEqual(s2.cand_sweep(B, "pdhl", 1), [(len(B) - 1, -1, 101.3, "sweep")])

    def test_sweep_swing_low(self):
        closes = [100, 99.5, 99, 98.5, 99, 99.5, 100, 100.2, 100.1]
        B = [bar(555 + 5 * k, c, c + 0.1, c - 0.1, c) for k, c in enumerate(closes)]
        B.append(bar(600, 100, 100.1, 98.2, 99.0))             # wick under the 98.4 swing low, close back above
        self.assertEqual(s2.cand_sweep(B, "swing2", 1)[-1], (len(B) - 1, 1, 98.2, "sweep"))

    def test_opening_drive(self):
        o = [bar(555, 100, 100.45, 99.95, 100.4), bar(560, 100.4, 100.85, 100.35, 100.8),
             bar(565, 100.8, 101.05, 100.75, 101.0)]
        B = o + [bar(570, 101, 101.4, 100.9, 101.3)]
        self.assertEqual(s2.cand_odrive(B, 0.7, "break"), [(3, 1, (101.05 + 99.95) / 2, "odrive")])
        B = o + [bar(570, 101, 101.0, 100.5, 100.6), bar(575, 100.6, 100.9, 100.4, 100.8),
                 bar(580, 100.8, 101.2, 100.7, 101.1)]
        self.assertEqual(s2.cand_odrive(B, 0.7, "pullback"), [(5, 1, 100.4, "odrive")])
        self.assertEqual(s2.cand_odrive(B, 1.5, "break"), [])

    def test_round_bounce(self):
        B = [bar(555, 1255, 1256, 1253, 1254), bar(560, 1254, 1255, 1249.5, 1252)]
        self.assertEqual(s2.cand_round(B, "fine", "bounce"), [(1, 1, 1249.5, "round")])

    def test_candle_shapes(self):
        self.assertEqual(s2.pin(bar(600, 100, 100.1, 99, 100.05)), 1)
        self.assertEqual(s2.pin(bar(600, 100, 101, 99.95, 99.98)), -1)
        B = [bar(600, 101, 101.1, 99.9, 100), bar(605, 99.9, 101.4, 99.8, 101.2)]
        self.assertEqual(s2.engulf(B, 1), 1)

    def test_candle_pin_at_pdl(self):
        B = flat_day() + [bar(555, 99.5, 99.6, 99.3, 99.4), bar(560, 99.4, 99.45, 98.98, 99.42)]
        self.assertEqual(s2.cand_candle(B, "pin", "pivot", 0.001), [(len(B) - 1, 1, 98.98, "candle")])

    def test_supertrend_flip_and_ema(self):
        closes = [100 + 0.3 * k for k in range(30)] + [109 - 0.5 * k for k in range(25)]
        B = [bar(555 + 5 * k, c, c + 0.1, c - 0.1, c) for k, c in enumerate(closes)]
        flips = s2.cand_trend(B, "st2")
        self.assertTrue(flips and flips[0][1] == -1 and flips[0][2] > B[flips[0][0]]["c"])
        up = [100 + 0.2 * k for k in range(30)]
        B = [bar(555 + 5 * k, c, c + 0.1, c - 0.1, c) for k, c in enumerate(up)]
        B.append(bar(705, 105.8, 105.9, 104.6, 105.0))      # dips to EMA9
        B.append(bar(710, 105.0, 106.2, 104.9, 106.1))      # closes above EMA9 and the prior high
        self.assertEqual(s2.cand_trend(B, "ema9_21")[-1][:3], (len(B) - 1, 1, 104.6))

    def test_no_lookahead_every_setup(self):
        B = walk(5, seed=7)
        seen = set()
        for name, (fn, dp) in s2.SETUPS.items():
            for vals in __import__("itertools").product(*dp.values()):
                kw = dict(zip(dp, vals))
                for c in fn(B, **kw)[:4]:
                    i = c[0]
                    seen.add(name)
                    self.assertIn(c, fn(B[:i + 1], **kw), "%s %s looks ahead at %d" % (name, kw, i))
        self.assertGreaterEqual(len(seen), 6, seen)

    def test_grid_sizes(self):
        for name in s2.SETUPS:
            self.assertLessEqual(s2.n_settings(name), 200, name)
        self.assertEqual(set(lab.SETUPS), set(core.SETUPS) | set(s2.SETUPS))
        self.assertIs(lab.exits_for("pdhl"), s2.EXITS2)
        self.assertIs(lab.exits_for("fvg"), core.EXITS)


class TestScore(unittest.TestCase):
    def test_range_and_factors(self):
        B = walk(4, seed=3)
        ctx = score.Context(B)
        for i in range(30, len(B), 37):
            for side in (1, -1):
                s, f = ctx.score(i, side)
                self.assertTrue(0 <= s <= 10)
                self.assertEqual(s, len(f))
                self.assertTrue(set(f) <= set(score.FACTORS))

    def test_dayopen_vwap_side(self):
        B = flat_day() + [bar(555, 100, 100.2, 99.9, 100.1), bar(560, 100.1, 100.9, 100.1, 100.8, v=5000)]
        _, f_long = score.score(B, len(B) - 1, 1)
        _, f_short = score.score(B, len(B) - 1, -1)
        for n in ("dayopen", "vwap", "volume", "nogap"):
            self.assertIn(n, f_long)
        self.assertNotIn("dayopen", f_short)
        self.assertNotIn("vwap", f_short)


class TestEvalScore(unittest.TestCase):
    def test_clear_needs_both_halves(self):
        evalscore = load("lab", "evalscore")
        names = [evalscore.bucket_name(lo) for lo, _ in evalscore.BUCKETS]
        up = {b: {"n": 50, "exp": 0.1 * k} for k, b in enumerate(names)}
        flat = {b: {"n": 50, "exp": 0.2} for b in names}
        self.assertTrue(evalscore.monotonic({"test": up}))
        self.assertTrue(evalscore.clear({"test": up, "train": up}))
        self.assertFalse(evalscore.clear({"test": up, "train": flat}))
        self.assertFalse(evalscore.monotonic({"test": dict(up, **{names[2]: {"n": 5, "exp": 0.25}})}))


class TestWiring(unittest.TestCase):
    def test_grid_merge_keeps_old_setups(self):
        B = walk(25, seed=5)
        days = sorted({b["day"] for b in B})
        old = {"stocks": {"TEST": {"date": "x", "days": 1, "first": "a", "last": "b", "skipped_gap_days": [],
                                   "setups": {"structure": {"tested": 1, "robust": 1, "best": [{"p": {}, "train": {}, "test": {}}]}}}},
               "history": {}}
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "m.json")
            with open(path, "w") as fh:
                json.dump(old, fh)
            with mock.patch.object(lab, "prepare", return_value=(B, {}, [], days, {d: None for d in days})):
                lab.main(["--memory", path, "grid", "TEST", "--setups", "pdhl", "trend"])
            with open(path) as fh:
                mem = json.load(fh)
        st = mem["stocks"]["TEST"]["setups"]
        self.assertEqual(st["structure"], old["stocks"]["TEST"]["setups"]["structure"])
        self.assertIn("pdhl", st)
        self.assertEqual(st["pdhl"]["tested"], s2.n_settings("pdhl"))
        self.assertIn("first", st["trend"])

    def test_scan_scores_and_skips_unknown(self):
        B = walk(6, seed=11)
        daily = [dict(day="2026-%02d-%02d" % (6 + k // 28, 1 + k % 28), m=0, o=100, h=101, l=99, c=100 + k * 0.1, v=1)
                 for k in range(40)]

        def fake(sym, rng, iv, cache_dir=None):
            return daily if iv == "1d" else B
        p = dict(kind="st2", side="both", dead=870, stop="natural", tgt="eod", filt="none")
        info = {"setups": {"trend": {"best": [{"p": p, "test": {"n": 9, "win": 70.0, "exp": 0.3}}]},
                           "fromthefuture": {"best": [{"p": {}, "test": {}}]}}}
        with mock.patch.object(core, "fetch", side_effect=fake):
            hits, _ = lab.scan_one("TEST", info, B[-1]["day"])
        self.assertTrue(hits)
        for h in hits:
            self.assertTrue(0 <= h["score"] <= 10)
            self.assertEqual(h["setup"], "trend")

    def test_alert_rank_and_line(self):
        a = dict(score=8, test={"exp": 0.2, "win": 60.0})
        b = dict(score=5, test={"exp": 0.9, "win": 80.0})
        with mock.patch.object(alert, "SCORE_RANK", True):
            self.assertEqual(sorted([b, a], key=alert.rank_key)[0], a)
        with mock.patch.object(alert, "SCORE_RANK", False):
            self.assertEqual(sorted([a, b], key=alert.rank_key)[0], b)
        h = dict(symbol="X", setup="pdhl", side="LONG", time="10:00", entry=1, stop=0.9, target=1.2, last=1,
                 test={"n": 9, "win": 70.0, "exp": 0.3}, score=7)
        self.assertIn("score 7/10", alert.line(h))


if __name__ == "__main__":
    unittest.main()
