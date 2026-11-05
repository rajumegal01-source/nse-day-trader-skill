"""lab/pine.py (Phase F): generated Pine v5 text looks like a valid indicator. Offline."""

import json
import os
import re
import shutil
import sys
import tempfile
import unittest

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
import pine  # noqa: E402


def balanced(text):
    pairs, stack, in_str = {")": "(", "]": "[", "}": "{"}, [], False
    for line in text.splitlines():
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"':
                in_str = not in_str
            elif not in_str and line[i:i + 2] == "//":
                break
            elif not in_str and ch in "([{":
                stack.append(ch)
            elif not in_str and ch in ")]}":
                if not stack or stack.pop() != pairs[ch]:
                    return False
            i += 1
        if in_str:
            return False          # a string never spans lines in Pine
    return not stack


class TestPine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = pine.write_all(self.tmp)

    def test_all_files_written(self):
        self.assertEqual(sorted(os.path.basename(p) for p in self.paths),
                         sorted(n + ".pine" for n in ("orb", "fvg", "structure", "pdhl", "cpr", "swing_breakout")))

    def test_compiles_looking_structure(self):
        for p in self.paths:
            text = open(p, encoding="utf-8").read()
            name = os.path.basename(p)
            self.assertTrue(text.startswith("//@version=5\n"), name)
            self.assertEqual(text.count("indicator("), 1, name)
            self.assertIn("overlay=true", text)
            self.assertNotIn("{{", text, name)
            self.assertNotIn("\t", text, name)
            self.assertTrue(balanced(text), "%s: unbalanced brackets or quotes" % name)
            self.assertIn("alertcondition(", text, name)
            self.assertIn("Educational only, not investment advice", text, name)
            self.assertNotRegex(text, r"strategy\.(entry|order|close)", name)      # draws only, no orders
            lines = text.splitlines()
            for k, line in enumerate(lines):
                s = line.strip()
                self.assertEqual((len(line) - len(line.lstrip(" "))) % 4, 0, "%s:%d indent" % (name, k + 1))
                if re.match(r"^(if|else|for|while)\b", s) or s.endswith("=>"):
                    nxt = lines[k + 1] if k + 1 < len(lines) else ""
                    self.assertGreater(len(nxt) - len(nxt.lstrip(" ")), len(line) - len(line.lstrip(" ")),
                                       "%s:%d block has no body" % (name, k + 1))

    def test_inputs_and_levels(self):
        text = open(os.path.join(self.tmp, "structure.pine"), encoding="utf-8").read()
        self.assertIn("ta.pivothigh(high, L, L)", text)
        self.assertIn('"choch"', text)
        self.assertIn('input.int(1130, "No new signals after', text)       # dead 690 min = 11:30
        cpr = open(os.path.join(self.tmp, "cpr.pine"), encoding="utf-8").read()
        for lvl in ("P = (ph_ + pl_ + pc_) / 3", "R1 = 2 * P - pl_", "S1 = 2 * P - ph_"):
            self.assertIn(lvl, cpr)

    def test_symbol_defaults_from_memory(self):
        mem = {"stocks": {"ABC": {"setups": {
            "structure": {"best": [{"p": {"L": 5, "event": "choch", "dead": 630, "side": "long",
                                          "stop": "p1.0", "tgt": "eod", "filt": "none"}}]},
            "fvg": {"best": []}}}}}
        mp = os.path.join(self.tmp, "mem.json")
        with open(mp, "w") as fh:
            json.dump(mem, fh)
        out = os.path.join(self.tmp, "abc")
        pine.write_all(out, "abc", mp)
        st = open(os.path.join(out, "structure.pine"), encoding="utf-8").read()
        self.assertIn('input.int(5, "Pivot length', st)
        self.assertIn('input.string("choch", "Setup on"', st)
        self.assertIn('input.int(1030, "No new signals', st)
        self.assertIn('input.float(0.0, "Target in R', st)                 # eod -> exit at 15:15
        self.assertIn("best remembered setting for ABC", st)
        fvg = open(os.path.join(out, "fvg.pine"), encoding="utf-8").read()
        self.assertIn("general defaults", fvg)                               # nothing remembered

    def test_committed_files_are_current(self):
        for p in self.paths:
            committed = os.path.join(ROOT, "pine", os.path.basename(p))
            self.assertTrue(os.path.exists(committed), committed)
            self.assertEqual(open(committed, encoding="utf-8").read(), open(p, encoding="utf-8").read(),
                             "pine/ is stale: run python3 lab/pine.py")


if __name__ == "__main__":
    unittest.main()
