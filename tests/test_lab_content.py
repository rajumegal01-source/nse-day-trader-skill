"""lab/content.py (Phase K): Gujarati + English post text and SVG chart, no buy/sell words. Offline."""

import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from _load import ROOT, run

sys.path.insert(0, os.path.join(ROOT, "lab"))
import content  # noqa: E402

P = dict(symbol="RELIANCE", setup="fvg", side="LONG", time="10:05", entry=1305.2, stop=1299.0, target=1317.6)
STATE = {"2026-11-04": ["RELIANCE|fvg|LONG|10:05"],
         "2026-11-04#picks": [P, dict(P, symbol="TCS", side="SHORT", target=None)],
         "2026-11-04#results": [dict(symbol="RELIANCE", setup="fvg", side="LONG", time="10:05", result="target", pct=0.9)],
         "2026-11-03#picks": [dict(P, symbol="SBIN")]}
CLOSES = [("09:15", 1310.0), ("10:05", 1305.0), ("12:00", 1309.0), ("15:25", 1318.0)]


class TestContent(unittest.TestCase):
    def test_pick_from_state(self):
        day, p, r = content.pick_from_state(STATE)
        self.assertEqual((day, p["symbol"], r["result"]), ("2026-11-04", "RELIANCE", "target"))
        day, p, r = content.pick_from_state(STATE, n=2)
        self.assertEqual((p["symbol"], r), ("TCS", None))
        self.assertEqual(content.pick_from_state(STATE, "2026-11-03")[1]["symbol"], "SBIN")
        self.assertIsNone(content.pick_from_state(STATE, n=3))
        self.assertIsNone(content.pick_from_state({}))

    def test_post_text(self):
        t = content.post_text("2026-11-04", P, dict(result="target", pct=0.9))
        for s in ("શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી", "Educational only, not investment advice", "setup example",
                  "rule output", "entry 1305.2", "stop 1299.0", "target 1317.6", "+0.90%", "no proven edge",
                  "ઉપર તરફનું setup"):
            self.assertIn(s, t)
        low = t.lower()
        for w in ("buy", "sell", "ખરીદ", "વેચ"):
            self.assertNotIn(w, low)
        short = content.post_text("2026-11-04", dict(P, side="SHORT", target=None))
        self.assertIn("નીચે તરફનું setup", short)
        self.assertIn("15:15 exit", short)
        self.assertNotIn("result", short.lower().split("rule output")[0])

    def test_check_words(self):
        with self.assertRaises(ValueError):
            content.check_words("Buy now!")
        self.assertEqual(content.check_words("setup example"), "setup example")

    def test_svg(self):
        svg = content.svg_chart(P, CLOSES, "2026-11-04")
        root = ET.fromstring(svg)                                   # well-formed XML
        self.assertTrue(root.tag.endswith("svg"))
        self.assertEqual(svg.count("stroke-dasharray"), 3)          # entry, stop, target
        self.assertIn("<polyline", svg)
        self.assertIn("શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી", svg)
        self.assertIn("target 1317.60", svg)
        svg = content.svg_chart(dict(P, target=None, symbol="A&B"), [], "d")    # no bars, no target, escaping
        ET.fromstring(svg)
        self.assertEqual(svg.count("stroke-dasharray"), 2)
        self.assertNotIn("<polyline", svg)

    def test_cli_offline(self):
        with tempfile.TemporaryDirectory() as d:
            sp = os.path.join(d, "state.json")
            with open(sp, "w", encoding="utf-8") as fh:
                json.dump(STATE, fh)
            out = os.path.join(d, "out")
            code, txt, err = run("lab", "content.py", ["--state", sp, "--out", out, "--no-fetch"])
            self.assertEqual(code, 0, err)
            self.assertTrue(os.path.exists(os.path.join(out, "chart.svg")))
            with open(os.path.join(out, "post.txt"), encoding="utf-8") as fh:
                self.assertIn("RELIANCE", fh.read())
            hp = os.path.join(d, "hits.json")
            with open(hp, "w") as fh:
                json.dump([dict(P, day="2026-11-05", setup="pullback")], fh)
            code, txt, _ = run("lab", "content.py", ["--from-json", hp, "--out", out, "--no-fetch"])
            self.assertEqual(code, 0)
            self.assertIn("EMA pullback", txt)
            code, txt, _ = run("lab", "content.py", ["--state", os.path.join(d, "none.json"), "--no-fetch", "--out", out])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
