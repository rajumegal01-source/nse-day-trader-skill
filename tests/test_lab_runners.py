"""Phase L runners: the Colab notebook is valid JSON and the Termux menu is valid bash. Offline."""

import json
import os
import re
import shutil
import subprocess
import unittest

from _load import ROOT

NB = os.path.join(ROOT, "notebooks", "trading_lab_colab.ipynb")
SH = os.path.join(ROOT, "termux", "run.sh")


class TestNotebook(unittest.TestCase):
    def setUp(self):
        with open(NB, encoding="utf-8") as fh:
            self.nb = json.load(fh)

    def test_valid_nbformat4(self):
        self.assertEqual(self.nb["nbformat"], 4)
        self.assertIn("kernelspec", self.nb["metadata"])
        for c in self.nb["cells"]:
            self.assertIn(c["cell_type"], ("markdown", "code"))
            self.assertIsInstance(c["source"], list)
            if c["cell_type"] == "code":
                self.assertEqual(c["outputs"], [])

    def test_cells_clone_and_run_tools(self):
        code = "".join("".join(c["source"]) for c in self.nb["cells"] if c["cell_type"] == "code")
        self.assertIn("git clone", code)
        for s in ("lab/lab.py scan", "lab/report.py", "lab/swing.py"):
            self.assertIn(s, code)
        for path in re.findall(r"python3 ((?:lab|backtest)/\w+\.py)", code):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)
        text = "".join("".join(c["source"]) for c in self.nb["cells"])
        self.assertIn("not investment advice", text)
        self.assertLess(os.path.getsize(NB), 20000)


class TestTermux(unittest.TestCase):
    def test_script(self):
        with open(SH, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("not investment advice", text)
        for path in re.findall(r"run ((?:lab|backtest)/\w+\.py)", text):
            self.assertTrue(os.path.exists(os.path.join(ROOT, path)), path)
        self.assertNotRegex(text.lower(), r"angel|smartapi|telegram|placeorder")
        self.assertLess(len(text), 6000)

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_bash_syntax_and_quit(self):
        self.assertEqual(subprocess.run(["bash", "-n", SH]).returncode, 0)
        p = subprocess.run(["bash", SH], input=b"q\n", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(p.returncode, 0)
        self.assertIn(b"Trading Lab", p.stdout)


if __name__ == "__main__":
    unittest.main()
