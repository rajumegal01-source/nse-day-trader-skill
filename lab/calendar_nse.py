"""NSE trading calendar (Phase J): holidays, trading days, F&O expiry dates. EDUCATIONAL ONLY.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    python3 lab/calendar_nse.py                 # today: trading day?, next expiries, holidays left
    python3 lab/calendar_nse.py --month 2026-11 # every NIFTY / BANKNIFTY expiry of a month

Holidays 2026: NSE circular NSE/CMTR/71775 (12 Dec 2025, equity) and NSE/FAOP/71777 (F&O, same
dates), plus 15 Jan 2026 added by NSE/CMTR/72260 (12 Jan 2026, Maharashtra municipal election).
Checked 2026-11-06 against https://www.niftyindices.com/resources/holiday-calendar and
https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf . Muhurat trading on Sunday
8 Nov 2026 is a special evening session, not a regular trading day. Add next year's list when NSE
publishes it (usually in December); until then only weekends count as closed for that year.

Expiry rules since 1 Sep 2025 (NSE circulars FAOP68685 / FAOP68747): NIFTY weekly = Tuesday of the
week, NIFTY monthly = last Tuesday of the month, BANKNIFTY = monthly only, last Tuesday (its weekly
options ended in Nov 2024). If the expiry Tuesday is a trading holiday, the contract expires on the
PREVIOUS trading day. Verify near holidays on NSE: the exchange can change any of this.
"""

import argparse
import datetime as dt
import sys

HOLIDAYS = {
    2026: {
        "2026-01-15": "Municipal Corporation Election - Maharashtra",
        "2026-01-26": "Republic Day",
        "2026-03-03": "Holi",
        "2026-03-26": "Shri Ram Navami",
        "2026-03-31": "Shri Mahavir Jayanti",
        "2026-04-03": "Good Friday",
        "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
        "2026-05-01": "Maharashtra Day",
        "2026-05-28": "Bakri Id",
        "2026-06-26": "Muharram",
        "2026-09-14": "Ganesh Chaturthi",
        "2026-10-02": "Mahatma Gandhi Jayanti",
        "2026-10-20": "Dussehra",
        "2026-11-10": "Diwali-Balipratipada",
        "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
        "2026-12-25": "Christmas",
    },
}
# holidays that fall on a weekend (no effect on trading, listed by NSE for completeness)
WEEKEND_HOLIDAYS = {"2026-02-15": "Mahashivratri", "2026-03-21": "Id-Ul-Fitr", "2026-08-15": "Independence Day",
                    "2026-11-08": "Diwali Laxmi Pujan (Muhurat trading session)"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TUESDAY = 1
FOOT = "Educational only, not investment advice. Verify dates on nseindia.com."


def as_date(d):
    if isinstance(d, dt.datetime):
        return d.date()
    if isinstance(d, dt.date):
        return d
    return dt.date(*[int(x) for x in str(d)[:10].split("-")])


def known_year(year):
    return year in HOLIDAYS


def holiday_name(d):
    d = as_date(d)
    return HOLIDAYS.get(d.year, {}).get(d.isoformat())


def is_trading_day(d):
    """Mon-Fri and not an NSE trading holiday (for years in HOLIDAYS; other years: weekends only)."""
    d = as_date(d)
    return d.weekday() < 5 and holiday_name(d) is None


def prev_trading_day(d, inclusive=False):
    d = as_date(d)
    if not inclusive:
        d -= dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def next_trading_day(d, inclusive=False):
    d = as_date(d)
    if not inclusive:
        d += dt.timedelta(days=1)
    while not is_trading_day(d):
        d += dt.timedelta(days=1)
    return d


def shift(d):
    """The real expiry for a scheduled expiry day d: d, or the previous trading day."""
    return prev_trading_day(d, inclusive=True)


def last_weekday(year, month, wd=TUESDAY):
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    while d.weekday() != wd:
        d -= dt.timedelta(days=1)
    return d


def monthly_expiry(year, month):
    """NIFTY / BANKNIFTY monthly expiry (last Tuesday, holiday-shifted)."""
    return shift(last_weekday(year, month))


def weekly_expiries(year, month):
    """Every NIFTY weekly expiry whose scheduled Tuesday falls in the month (holiday-shifted)."""
    d = dt.date(year, month, 1)
    while d.weekday() != TUESDAY:
        d += dt.timedelta(days=1)
    out = []
    while d.month == month:
        out.append(shift(d))
        d += dt.timedelta(days=7)
    return out


def next_expiry(index="NIFTY", kind="weekly", today=None):
    """Next expiry on or after `today` for NIFTY (weekly / monthly) or BANKNIFTY (monthly)."""
    today = as_date(today or dt.datetime.now(IST).date())
    if index.upper() == "BANKNIFTY" and kind == "weekly":
        raise ValueError("BANKNIFTY has monthly expiries only")
    y, m = today.year, today.month
    for _ in range(14):
        cands = weekly_expiries(y, m) if kind == "weekly" else [monthly_expiry(y, m)]
        for c in cands:
            if c >= today:
                return c
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def holidays_left(today=None):
    today = as_date(today or dt.datetime.now(IST).date())
    return [(d, n) for d, n in sorted(HOLIDAYS.get(today.year, {}).items()) if d >= today.isoformat()]


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE calendar (educational)")
    ap.add_argument("--date", help="YYYY-MM-DD (default today, IST)")
    ap.add_argument("--month", help="YYYY-MM: list that month's expiries")
    a = ap.parse_args(argv)
    if a.month:
        y, m = [int(x) for x in a.month.split("-")]
        print("NIFTY weekly: " + ", ".join("%s %s" % (d, d.strftime("%a")) for d in weekly_expiries(y, m)))
        mo = monthly_expiry(y, m)
        print("NIFTY + BANKNIFTY monthly: %s %s" % (mo, mo.strftime("%a")))
        print(FOOT)
        return 0
    today = as_date(a.date) if a.date else dt.datetime.now(IST).date()
    h = holiday_name(today)
    state = "trading day" if is_trading_day(today) else ("holiday: " + h if h else "weekend")
    print("%s (%s): %s" % (today, today.strftime("%A"), state))
    if not known_year(today.year):
        print("no NSE holiday list for %d in lab/calendar_nse.py yet: only weekends are known." % today.year)
    print("next trading day: %s" % next_trading_day(today))
    for idx, kind in (("NIFTY", "weekly"), ("NIFTY", "monthly"), ("BANKNIFTY", "monthly")):
        d = next_expiry(idx, kind, today)
        moved = " (moved from %s, holiday)" % last_weekday(d.year, d.month) if kind == "monthly" and d != last_weekday(d.year, d.month) else ""
        if kind == "weekly" and d.weekday() != TUESDAY:
            moved = " (Tuesday is a holiday)"
        print("%-9s %-7s expiry: %s %s%s" % (idx, kind, d, d.strftime("%a"), moved))
    left = holidays_left(today)
    if left:
        print("holidays left this year: " + "; ".join("%s %s" % (d, n) for d, n in left))
    print(FOOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
