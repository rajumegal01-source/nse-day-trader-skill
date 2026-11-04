"""Trading Lab terminal: a small menu for Termux or any shell. EDUCATIONAL ONLY.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/terminal.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable or "python3"

MENU = [
    ("1", "Scan today (આજનું scan)", ["lab/lab.py", "scan"]),
    ("2", "Scan as at a time (સમય પ્રમાણે scan)", ["lab/lab.py", "scan", "--at", "{time}"]),
    ("3", "Show a stock (stock ની memory)", ["lab/lab.py", "show", "{symbol}"]),
    ("4", "Re-test a stock, 12,960 settings (ફરી test)", ["lab/lab.py", "grid", "{symbol}"]),
    ("5", "Lessons (લેબે શું શીખ્યું)", ["lab/lab.py", "lessons"]),
    ("6", "Learn from today, after 15:30 (આજથી શીખો)", ["lab/lab.py", "learn"]),
    ("7", "ORB scan (scanner)", ["trader-scanner/scan.py", "orb"]),
    ("8", "Paper trades report (paper ટ્રેડ)", ["backtest/paper_journal.py", "report"]),
    ("0", "Exit (બહાર)", None),
]


def ask(label):
    try:
        return input(label).strip()
    except EOFError:
        return ""


def build(args):
    out = []
    for x in args:
        if x == "{time}":
            x = ask("Time HH:MM IST: ") or "11:00"
        elif x == "{symbol}":
            x = (ask("Symbol (e.g. POWERGRID): ") or "POWERGRID").upper()
        out.append(x)
    return out


def main():
    while True:
        print("\n=== Trading Lab ===  (educational only, not investment advice)")
        for key, label, _ in MENU:
            print("  %s  %s" % (key, label))
        choice = ask("> ")
        item = next((m for m in MENU if m[0] == choice), None)
        if item is None:
            if choice == "":
                return 0
            print("choose 0-8")
            continue
        if item[2] is None:
            return 0
        args = build(item[2])
        subprocess.call([PY] + [os.path.join(ROOT, args[0])] + args[1:], cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
