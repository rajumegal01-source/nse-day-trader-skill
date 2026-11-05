"""Phase M docs: README sections per phase and the Gujarati guide cover every new tool honestly."""

import os
import unittest

from _load import ROOT

TOOLS = ("fno.py", "swing.py", "pine.py", "sector.py", "journal_stats.py", "regime.py", "calendar_nse.py",
         "content.py", "termux/run.sh", "trading_lab_colab.ipynb")


class TestDocs(unittest.TestCase):
    def test_readme_has_every_phase(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        for ph in "DEFGHIJKLM":
            self.assertIn("**Phase %s:" % ph, text)
        for t in TOOLS:
            self.assertIn(t, text)
        self.assertIn("no proven swing edge out of sample", text)
        self.assertIn("`REGIME_SELECT` stays off", text)

    def test_gujarati_guide(self):
        with open(os.path.join(ROOT, "docs", "GUJARATI_GUIDE.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી", text)
        self.assertIn("-0.009%", text)
        self.assertIn("કોઈ સાબિત edge નથી", text)
        for t in TOOLS[:8]:
            self.assertIn(t, text)

    def test_every_lab_tool_has_a_disclaimer(self):
        for name in ("fno", "swing", "pine", "sector", "journal_stats", "regime", "calendar_nse", "content"):
            with open(os.path.join(ROOT, "lab", name + ".py"), encoding="utf-8") as fh:
                self.assertIn("not investment advice", fh.read().lower().replace("\n", " "), name)


if __name__ == "__main__":
    unittest.main()
