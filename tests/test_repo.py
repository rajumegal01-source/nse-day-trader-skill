"""The repository itself: structure, frontmatter, disclaimers, Python 3.8 syntax, no secrets."""

import ast
import json
import os
import re
import unittest

from _load import ROOT

SKILLS = {
    "trader-scanner": "scan.py", "trader-news": "news.py", "trader-entry": "entry.py",
    "trader-exit": "exit.py", "trader-timemachine": "timemachine.py", "trader-risk": "check.py",
    "trader-budget": "size.py", "trader-broker": "ticket.py", "trader-alerts": "alerts.py",
    "trader-analyst": "facts.py", "trader-bulkdeals": "deals.py",
}


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    fm, key = {}, None
    for line in m.group(1).splitlines():
        km = re.match(r"^([a-z][a-z-]*):\s*(.*)$", line)
        if km:
            key = km.group(1)
            fm[key] = km.group(2).strip()
        elif key:
            fm[key] = (fm[key] + " " + line.strip()).strip()
    if fm.get("description", "").startswith(">-"):
        fm["description"] = fm["description"][2:].strip()
    return fm


def all_py():
    for d, _, files in os.walk(ROOT):
        if "__pycache__" in d or "/.git" in d:
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(d, f)


class TestStructure(unittest.TestCase):
    def test_eleven_skills_each_with_skill_md_and_script(self):
        dirs = sorted(d for d in os.listdir(ROOT) if d.startswith("trader-"))
        self.assertEqual(dirs, sorted(SKILLS))
        for d, script in SKILLS.items():
            self.assertTrue(os.path.isfile(os.path.join(ROOT, d, "SKILL.md")), d)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, d, script)), d)

    def test_frontmatter_name_and_description(self):
        for d in SKILLS:
            fm = frontmatter(open(os.path.join(ROOT, d, "SKILL.md"), encoding="utf-8").read())
            self.assertIsNotNone(fm, d)
            self.assertEqual(fm.get("name"), d)
            self.assertGreater(len(fm.get("description", "")), 200, d)
            self.assertLess(len(fm.get("description", "")), 1024, d)

    def test_pelosi_is_replaced_by_bulkdeals(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "trader-pelosi")))

    def test_plugin_files(self):
        for name in ("plugin.json", "marketplace.json"):
            doc = json.load(open(os.path.join(ROOT, ".claude-plugin", name), encoding="utf-8"))
            self.assertIn("nse", json.dumps(doc).lower())

    def test_license_keeps_original_and_adds_port(self):
        text = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read()
        self.assertIn("Copyright (c) 2026 Jake Schincariol", text)
        self.assertIn("Copyright (c) 2026 Raju Megal (NSE/BSE port)", text)
        self.assertIn("MIT License", text)

    def test_nse_helper_copies_are_identical(self):
        texts = [open(os.path.join(ROOT, d, "nse.py"), encoding="utf-8").read()
                 for d in ("trader-budget", "trader-risk", "trader-broker")]
        self.assertEqual(texts[0], texts[1])
        self.assertEqual(texts[0], texts[2])


class TestDisclaimers(unittest.TestCase):
    def check(self, text, where):
        low = text.lower()
        for s in ("sebi", "not investment advice", "pr no. 13/2024"):
            self.assertTrue(s in low, "%s: no %r" % (where, s))
        self.assertTrue("7 out of 10" in low or "70%" in low or "71%" in low, where)

    def test_every_skill_md(self):
        for d in SKILLS:
            self.check(open(os.path.join(ROOT, d, "SKILL.md"), encoding="utf-8").read(), d)

    def test_readme(self):
        text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.check(text, "README.md")
        for s in ("ગુજરાતી", "SmartAPI", "static IP", "UNVERIFIED"):
            self.assertTrue(s in text, "README.md: no %r" % s)

    def test_broker_documents_sebi_algo_framework_and_unverified_live(self):
        text = open(os.path.join(ROOT, "trader-broker", "SKILL.md"), encoding="utf-8").read()
        for s in ("SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013", "static IP", "10 orders per second",
                  "UNVERIFIED", "kill switch", "ANGEL_TOTP_SECRET"):
            self.assertIn(s.lower(), text.lower(), s)

    def test_no_us_market_leftovers(self):
        for d in SKILLS:
            for name in os.listdir(os.path.join(ROOT, d)):
                if not name.endswith((".py", ".md")):
                    continue
                text = open(os.path.join(ROOT, d, name), encoding="utf-8").read()
                for bad in ("NYSE", "New York", "Alpaca", "EDGAR", "Pelosi"):
                    if bad == "Pelosi" and d == "trader-bulkdeals" and name == "SKILL.md":
                        continue  # "replacing the US Pelosi tracker"
                    self.assertNotIn(bad, text, "%s/%s has %s" % (d, name, bad))


class TestPython38(unittest.TestCase):
    def test_parses_as_python_38(self):
        for path in all_py():
            src = open(path, encoding="utf-8").read()
            try:
                ast.parse(src, filename=path, feature_version=(3, 8))
            except TypeError:  # very old ast without feature_version
                ast.parse(src, filename=path)

    def test_no_39_plus_apis(self):
        bad = [r"\bzoneinfo\b", r"(?<![\w.])(list|dict|tuple|set)\[", r"\.removeprefix\(", r"\.removesuffix\(",
               r"^\s*match\s+\w+.*:\s*$", r"\bfunctools\.cache\b", r"\bstr \| None\b"]
        for path in all_py():
            if os.path.basename(path) == "test_repo.py":
                continue
            src = open(path, encoding="utf-8").read()
            for pat in bad:
                self.assertIsNone(re.search(pat, src, re.M), "%s uses %s" % (path, pat))

    def test_stdlib_only(self):
        allowed = {"argparse", "ast", "base64", "contextlib", "decimal", "csv", "datetime", "email", "core", "lab", "getpass", "gzip", "hashlib", "hmac", "importlib",
                   "io", "json", "math", "os", "random", "re", "socket", "statistics", "struct", "subprocess",
                   "sys", "tempfile", "time", "unittest", "urllib", "uuid", "xml", "zlib", "shutil", "collections",
                   "itertools", "bisect", "functools", "textwrap", "string", "copy",
                   "nse", "angel", "_load", "filters", "risk", "setups2", "score",
                   "alert", "report", "walkforward", "evalscore", "fno", "swing"}
        for path in all_py():
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for n in names:
                    self.assertIn(n, allowed, "%s imports %s" % (path, n))


class TestNoSecrets(unittest.TestCase):
    def test_no_hardcoded_credentials(self):
        for path in all_py():
            if "/tests/" in path:
                continue
            src = open(path, encoding="utf-8").read()
            self.assertIsNone(re.search(r"['\"][A-Z2-7]{16,}['\"]", src), "base32-looking literal in %s" % path)
            self.assertIsNone(re.search(r"(api_key|pin|totp_secret|password)\s*=\s*['\"][^'\"]+['\"]", src, re.I),
                              "credential literal in %s" % path)

    def test_example_credentials_file_is_empty(self):
        doc = json.load(open(os.path.join(ROOT, "trader-broker", "angel.example.json"), encoding="utf-8"))
        for k in ("api_key", "client_code", "pin", "totp_secret"):
            self.assertEqual(doc[k], "")

    def test_gitignore_keeps_state_and_secrets_out(self):
        self.assertIn("trader/", open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
