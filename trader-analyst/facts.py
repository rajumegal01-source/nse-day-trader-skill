#!/usr/bin/env python3
"""Results reader for trader-analyst (NSE/BSE port). Standard library only.

Pulls a listed Indian company's quarterly results and lays out what changed, quarter by
quarter: revenue from operations, total expenses, profit before tax, net profit, profit
attributable to the owners, basic EPS, the net margin, and growth against the previous
quarter (QoQ) and the same quarter a year earlier (YoY).

    python3 facts.py RELIANCE
    python3 facts.py RELIANCE TCS --quarters 5
    python3 facts.py INFY --standalone            # standalone instead of consolidated
    python3 facts.py RELIANCE --source yahoo      # Yahoo only
    python3 facts.py RELIANCE TCS --metrics trader/metrics.json

Sources, best first, with graceful fallback:
  1. NSE integrated filings (SEBI's XBRL taxonomy, filed with every quarterly result):
       https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=<SYM>
         &period_ended=all&type=Integrated%20Filing-%20Financials
     then each quarter's XBRL file (nsearchives.nseindia.com/corporate/xbrl/...). The
     quarter is the context that covers about three months and ends on the quarter date.
     Consolidated by default (--standalone for standalone). NSE's site answers browsers
     only and may refuse a script; then the tool says so and falls back.
  2. Yahoo Finance fundamentals time series (no key, often a quarter or two behind and
     with gaps): https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/
       timeseries/<SYM>.NS?type=quarterlyTotalRevenue,quarterlyNetIncome,...
     (Yahoo's quoteSummary endpoint now needs a cookie "crumb", so it is not used.)
  When both answer, the tool says if Yahoo lags NSE's latest quarter.

Amounts are shown in Rs crore (1 crore = 10 million). Offline: --offline DIR reads
nse-results-<SYM>.json, the XBRL files by their own names, and yahoo-ts-<SYM>.json.
Numbers only: this tool never says whether a stock is a buy. Educational only, not
investment advice.
"""

import argparse
import datetime as _dt
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

NSE_LIST = ("https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=%s"
            "&period_ended=all&type=Integrated%%20Filing-%%20Financials")
YAHOO_TS = ("https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/%s"
            "?type=%s&period1=%d&period2=%d")
YAHOO_TYPES = ("quarterlyTotalRevenue", "quarterlyNetIncome", "quarterlyBasicEPS", "quarterlyDilutedEPS",
               "quarterlyOperatingIncome", "quarterlyPretaxIncome", "quarterlyEBITDA")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
CRORE = 1e7
XBRL_FIELDS = {  # our name: SEBI in-capmkt element names, first found wins
    "revenue": ("RevenueFromOperations",),
    "total_income": ("Income",),
    "expenses": ("Expenses",),
    "pbt": ("ProfitBeforeTax",),
    "net_profit": ("ProfitLossForPeriod",),
    "owners_profit": ("ProfitOrLossAttributableToOwnersOfParent",),
    "eps_basic": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                  "BasicEarningsLossPerShareFromContinuingOperations"),
    "eps_diluted": ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                    "DilutedEarningsLossPerShareFromContinuingOperations"),
}


class FactsError(Exception):
    pass


class Fetcher(object):
    def __init__(self, offline=None, pause=0.4):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def raw(self, url, name):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise FactsError("offline: no file %s" % path)
            with open(path, "rb") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data
        except urllib.error.HTTPError as e:
            raise FactsError("HTTP %d for %s" % (e.code, url.split("?")[0]))
        except (urllib.error.URLError, OSError) as e:
            raise FactsError("could not reach %s: %s" % (url.split("/")[2], getattr(e, "reason", e)))

    def json(self, url, name):
        try:
            return json.loads(self.raw(url, name).decode("utf-8"))
        except ValueError:
            raise FactsError("%s did not answer JSON (NSE refuses scripts at times)" % url.split("/")[2])


def _date(s, fmts=("%d-%b-%Y", "%Y-%m-%d")):
    for f in fmts:
        try:
            return _dt.datetime.strptime(str(s).strip().title() if "%b" in f else str(s).strip(), f).date()
        except (TypeError, ValueError):
            continue
    return None


# ---------------------------------------------------------------- NSE XBRL

def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_xbrl(data):
    """One integrated-filing XBRL -> {"end", "start", values...} for the 3-month context."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise FactsError("the XBRL file is not valid XML: %s" % e)
    ctx = {}
    for c in root:
        if _local(c.tag) != "context":
            continue
        start = end = None
        dims = False
        for e in c.iter():
            n = _local(e.tag)
            if n == "startDate":
                start = _date(e.text, ("%Y-%m-%d",))
            elif n in ("endDate", "instant"):
                end = _date(e.text, ("%Y-%m-%d",))
            elif n in ("segment", "scenario"):
                dims = True
        ctx[c.get("id")] = (start, end, dims)
    quarter = None
    for cid, (s, e, dims) in ctx.items():
        if s and e and not dims and 80 <= (e - s).days <= 100:
            if quarter is None or e > ctx[quarter][1]:
                quarter = cid
    if quarter is None:
        raise FactsError("no three-month period in the XBRL file")
    vals = {}
    want = {}
    for k, names in XBRL_FIELDS.items():
        for n in names:
            want.setdefault(n, []).append(k)
    found = {}
    for e in root.iter():
        n = _local(e.tag)
        if n in want and e.get("contextRef") == quarter and (e.text or "").strip():
            try:
                v = float(e.text.strip())
            except ValueError:
                continue
            for k in want[n]:
                rank = XBRL_FIELDS[k].index(n)
                if k not in found or rank < found[k]:
                    found[k] = rank
                    vals[k] = v
        elif n == "NatureOfReportStandaloneConsolidated" and e.get("contextRef") == quarter:
            vals["nature"] = (e.text or "").strip()
        elif n == "NameOfTheCompany" and (e.text or "").strip():
            vals["company"] = e.text.strip()
    s, en, _ = ctx[quarter]
    vals.update(start=s.isoformat(), end=en.isoformat())
    return vals


def nse_quarters(fetcher, sym, n=5, consolidated=True, errors=None):
    errors = [] if errors is None else errors
    doc = fetcher.json(NSE_LIST % urllib.parse.quote(sym), "nse-results-%s.json" % sym)
    rows = doc.get("data") if isinstance(doc, dict) else doc
    want = "Consolidated" if consolidated else "Standalone"
    rows = [r for r in rows or [] if str(r.get("consolidated")) == want and r.get("xbrl")]
    if not rows and consolidated:
        raise FactsError("NSE lists no consolidated results for %s (try --standalone)" % sym)
    rows.sort(key=lambda r: (_date(r.get("qe_Date")) or _dt.date.min, r.get("broadcast_Date") or ""), reverse=True)
    out, seen = [], set()
    for r in rows:
        q = _date(r.get("qe_Date"))
        if not q or q in seen:
            continue  # a revision of a quarter already read
        seen.add(q)
        try:
            v = parse_xbrl(fetcher.raw(r["xbrl"], r["xbrl"].rsplit("/", 1)[-1]))
        except FactsError as e:
            errors.append("%s %s XBRL: %s" % (sym, q, e))
            continue
        v.update(filed=r.get("broadcast_Date"), xbrl=r["xbrl"], audited=r.get("audited"),
                 company=v.get("company") or r.get("cmName") or r.get("smName"), basis=want)
        out.append(v)
        if len(out) >= n:
            break
    return out


# ---------------------------------------------------------------- Yahoo

def yahoo_quarters(fetcher, sym, n=5, now=None):
    now = now or time.time()
    ysym = sym if sym.endswith((".NS", ".BO")) else sym + ".NS"
    url = YAHOO_TS % (urllib.parse.quote(ysym), ",".join(YAHOO_TYPES), int(now) - 6 * 366 * 86400, int(now))
    doc = fetcher.json(url, "yahoo-ts-%s.json" % sym)
    by = {}
    for res in ((doc.get("timeseries") or {}).get("result") or []):
        t = (res.get("meta") or {}).get("type", [None])[0]
        for x in res.get(t) or []:
            if not x or not x.get("asOfDate"):
                continue
            v = (x.get("reportedValue") or {}).get("raw")
            by.setdefault(x["asOfDate"], {})[t] = v
    if not by:
        raise FactsError("Yahoo has no quarterly numbers for %s" % ysym)
    out = []
    for d in sorted(by, reverse=True)[:n]:
        r = by[d]
        out.append({"end": d, "revenue": r.get("quarterlyTotalRevenue"), "net_profit": r.get("quarterlyNetIncome"),
                    "owners_profit": r.get("quarterlyNetIncome"), "pbt": r.get("quarterlyPretaxIncome"),
                    "eps_basic": r.get("quarterlyBasicEPS"), "eps_diluted": r.get("quarterlyDilutedEPS"),
                    "basis": "Yahoo (as reported to Yahoo)"})
    return out


# ---------------------------------------------------------------- analysis

def pct(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a / b - 1) * 100.0 if b > 0 else (a - b) / abs(b) * 100.0, 1)


def analyse(rows):
    """Add margins, QoQ and YoY to each quarter (newest first)."""
    by_end = {r["end"]: r for r in rows}
    for i, r in enumerate(rows):
        r["net_margin"] = round(r["net_profit"] / r["revenue"] * 100.0, 1) if r.get("revenue") and r.get("net_profit") is not None else None
        prev = rows[i + 1] if i + 1 < len(rows) else None
        e = _date(r["end"], ("%Y-%m-%d",))
        pe = _date(prev["end"], ("%Y-%m-%d",)) if prev else None
        if prev and not (e and pe and 80 <= (e - pe).days <= 100):
            prev = None  # a gap (Yahoo skips quarters): no QoQ
        ya = None
        for d, rr in by_end.items():
            dd = _date(d, ("%Y-%m-%d",))
            if dd and e and 355 <= (e - dd).days <= 375:
                ya = rr
        for k in ("revenue", "net_profit", "owners_profit", "eps_basic"):
            r[k + "_qoq"] = pct(r.get(k), prev.get(k)) if prev else None
            r[k + "_yoy"] = pct(r.get(k), ya.get(k)) if ya else None
    return rows


def changes(rows):
    if not rows:
        return []
    c = rows[0]
    out = []

    def say(label, k):
        y, q = c.get(k + "_yoy"), c.get(k + "_qoq")
        bits = []
        if y is not None:
            bits.append("%+.1f%% YoY" % y)
        if q is not None:
            bits.append("%+.1f%% QoQ" % q)
        if bits:
            out.append("%s %s" % (label, ", ".join(bits)))
    say("Revenue from operations", "revenue")
    say("Net profit", "net_profit")
    say("Profit to owners", "owners_profit")
    say("Basic EPS", "eps_basic")
    if c.get("net_margin") is not None and len(rows) > 1 and rows[1].get("net_margin") is not None:
        out.append("Net margin %.1f%% (%.1f%% the quarter before)" % (c["net_margin"], rows[1]["net_margin"]))
    if not out:
        out.append("Not enough quarters to compare.")
    return out


def cr(v):
    return "-" if v is None else "{:,.0f}".format(v / CRORE)


def pc(v):
    return "-" if v is None else "%+.1f%%" % v


def render(sym, rows, source, notes):
    name = rows[0].get("company") or sym
    out = ["%s (%s). Rs crore except EPS. Source: %s, %s." % (name, sym, source, rows[0].get("basis", ""))]
    out.append("")
    out.append("%-11s %12s %8s %8s %11s %8s %11s %8s %7s %6s" % ("quarter end", "revenue", "QoQ", "YoY", "net profit",
                                                                "YoY", "to owners", "EPS", "EPS YoY", "margin"))
    for r in rows:
        out.append("%-11s %12s %8s %8s %11s %8s %11s %8s %7s %6s" % (
            r["end"], cr(r.get("revenue")), pc(r.get("revenue_qoq")), pc(r.get("revenue_yoy")), cr(r.get("net_profit")),
            pc(r.get("net_profit_yoy")), cr(r.get("owners_profit")),
            "-" if r.get("eps_basic") is None else "%.2f" % r["eps_basic"], pc(r.get("eps_basic_yoy")),
            "-" if r.get("net_margin") is None else "%.1f%%" % r["net_margin"]))
    out.append("")
    out.append("What changed (latest quarter, %s):" % rows[0]["end"])
    for line in changes(rows):
        out.append("  - " + line)
    if rows[0].get("filed"):
        out.append("Filed with NSE %s IST (%s): %s" % (rows[0]["filed"], rows[0].get("audited") or "", rows[0].get("xbrl")))
    for n in notes:
        out.append("NOTE: " + n)
    out.append("Numbers only, not a recommendation. Educational only, not investment advice.")
    return "\n".join(out) + "\n"


def metrics_row(sym, rows, source):
    c = rows[0]
    return {"symbol": sym, "name": c.get("company"), "period_end": c["end"], "basis": c.get("basis"),
            "revenue_cr": None if c.get("revenue") is None else round(c["revenue"] / CRORE, 2),
            "net_profit_cr": None if c.get("net_profit") is None else round(c["net_profit"] / CRORE, 2),
            "eps_basic": c.get("eps_basic"), "revenue_growth_yoy": c.get("revenue_yoy"),
            "net_profit_growth_yoy": c.get("net_profit_yoy"), "eps_growth_yoy": c.get("eps_basic_yoy"),
            "net_margin": c.get("net_margin"), "source": source}


def run_one(fetcher, sym, a, errors):
    notes, rows, source = [], [], None
    nse_rows = ynse = None
    if a.source in ("auto", "nse"):
        try:
            nse_rows = nse_quarters(fetcher, sym, a.quarters, not a.standalone, notes)
        except FactsError as e:
            notes.append("NSE results not read: %s" % e)
    if a.source in ("auto", "yahoo"):
        try:
            ynse = yahoo_quarters(fetcher, sym, a.quarters)
        except FactsError as e:
            if a.source == "yahoo" or not nse_rows:
                notes.append("Yahoo numbers not read: %s" % e)
    if nse_rows:
        rows, source = nse_rows, "NSE integrated filing (XBRL)"
        if ynse and ynse[0]["end"] < nse_rows[0]["end"]:
            notes.append("Yahoo's latest quarter is %s, behind NSE's %s: Yahoo lags the filings."
                         % (ynse[0]["end"], nse_rows[0]["end"]))
    elif ynse:
        rows, source = ynse, "Yahoo Finance fundamentals time series"
        notes.append("Yahoo's quarterly numbers can lag the exchange filing by a quarter or more and skip quarters.")
    if not rows:
        raise FactsError("no results from any source: " + "; ".join(notes))
    return analyse(rows), source, notes


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Results Analyst (trader-analyst, NSE/BSE). Educational only.")
    ap.add_argument("tickers", nargs="*", help="NSE symbols, e.g. RELIANCE TCS")
    ap.add_argument("--quarters", type=int, default=5)
    ap.add_argument("--standalone", action="store_true", help="standalone results (default consolidated)")
    ap.add_argument("--source", choices=["auto", "nse", "yahoo"], default="auto")
    ap.add_argument("--metrics", metavar="FILE", help="merge a row per symbol into this JSON")
    ap.add_argument("--offline", metavar="DIR")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not a.tickers:
        ap.print_help()
        return 2
    fetcher = Fetcher(offline=a.offline)
    results, mrows, failed = [], [], 0
    for t in a.tickers:
        sym = t.upper()
        sym = sym[:-3] if sym.endswith(".NS") else sym
        try:
            rows, source, notes = run_one(fetcher, sym, a, [])
        except FactsError as e:
            print("facts: %s: %s" % (sym, e), file=sys.stderr)
            failed += 1
            continue
        results.append({"symbol": sym, "source": source, "quarters": rows, "changes": changes(rows), "notes": notes})
        mrows.append(metrics_row(sym, rows, source))
        if not a.json:
            sys.stdout.write(render(sym, rows, source, notes) + "\n")
    if a.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    if a.metrics and mrows:
        existing = {}
        if os.path.isfile(a.metrics):
            with open(a.metrics, encoding="utf-8") as fh:
                existing = {r["symbol"]: r for r in json.load(fh).get("companies", [])}
        for r in mrows:
            existing[r["symbol"]] = r
        d = os.path.dirname(a.metrics)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.metrics, "w", encoding="utf-8") as fh:
            json.dump({"as_of": _dt.date.today().isoformat(), "currency": "INR",
                       "companies": sorted(existing.values(), key=lambda r: r["symbol"])}, fh, indent=2)
            fh.write("\n")
        if not a.json:
            print("wrote %s (%d companies)" % (a.metrics, len(existing)))
    return 0 if results and not failed else (1 if results else 2)


if __name__ == "__main__":
    sys.exit(main())
