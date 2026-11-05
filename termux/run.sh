#!/usr/bin/env bash
# Trading Lab, one-command menu for Android Termux (works in any bash too).
# EDUCATIONAL ONLY, not investment advice. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.
#
# First time in Termux:   pkg install -y python git
#                         git clone https://github.com/rajumegal01-source/nse-day-trader-skill.git
#                         bash nse-day-trader-skill/termux/run.sh
# No broker, no orders: every option only reads free market data and prints.

cd "$(dirname "$0")/.." || exit 1
PY="$(command -v python3 || command -v python)"
[ -z "$PY" ] && { echo "python3 missing: pkg install -y python"; exit 1; }
CACHE="${TMPDIR:-/tmp}/lab_cache"
mkdir -p "$CACHE"

menu() {
  cat <<'M'

Trading Lab (Educational only, not investment advice)
 1) Today's intraday scan            (આજનું scan)
 2) Daily picks, print only          (આજના picks, dry run)
 3) Swing scan, daily bars           (swing setups)
 4) Sector strength + breadth        (sector ranking)
 5) NSE calendar + expiries          (holiday / expiry)
 6) Market regime today              (regime)
 7) Journal stats                    (paper + picks)
 8) F&O payoff example               (iron condor)
 9) Export Pine scripts              (pine/*.pine)
10) Facebook post + chart            (content_out/)
 u) Update (git pull)    t) Run tests    q) Quit
M
}

run() { echo "+ $*"; "$PY" "$@"; }

while true; do
  menu
  printf "Choose: "
  read -r c || exit 0
  case "$c" in
    1) run lab/lab.py scan ;;
    2) run lab/alert.py --dry-run ;;
    3) run lab/swing.py scan --cache "$CACHE" ;;
    4) run lab/sector.py --cache "$CACHE" --stocks 10 ;;
    5) run lab/calendar_nse.py ;;
    6) run lab/regime.py today --cache "$CACHE" ;;
    7) run lab/journal_stats.py ;;
    8) run lab/fno.py payoff iron_condor --strikes 23600,23800,24200,24400 --premiums 20,45,50,22 --symbol NIFTY ;;
    9) run lab/pine.py ;;
    10) run lab/content.py ;;
    u) git pull --ff-only ;;
    t) "$PY" -m unittest discover -s tests ;;
    q|Q|0) exit 0 ;;
    *) echo "?" ;;
  esac
done
