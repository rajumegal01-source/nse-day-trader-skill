#!/usr/bin/env python3
"""Bulk / block deals and insider disclosures for trader-bulkdeals (NSE). Standard library only.

Reads NSE's public disclosures of big trades and of what insiders and large holders did:

    python3 deals.py deals                          # today's bulk and block deals (NSE archives)
    python3 deals.py deals --symbols RELIANCE,TCS   # only these
    python3 deals.py deals --min-cr 25              # only deals worth Rs 25 crore or more
    python3 deals.py deals --client "goldman"       # one client name
    python3 deals.py sast --days 7                  # SAST Reg 29 disclosures (5% / 2% holders), all companies
    python3 deals.py sast --days 30 --symbols WAAREEENER
    python3 deals.py insider RELIANCE               # SEBI PIT disclosures: promoters, directors, KMP
    python3 deals.py new                            # what is new since the last `new` (trader/state/deals.json)

What they are (SEBI master circular for stock exchanges, chapter 1; SEBI circular
SEBI/HO/MRD/POD-III/CIR/P/2025/134 of 2025-10-08):
  bulk deal   all trades in a day by one client in one stock adding up to more than 0.5% of
              the company's listed shares, in the normal market; disclosed the same evening
  block deal  one trade of Rs 25 crore or more in a block window (08:45 to 09:00 and 14:05 to
              14:20 IST since 2025-12-08), delivery only
  SAST        SEBI (Substantial Acquisition of Shares and Takeovers) Regulation 29: holders
              crossing 5%, and 2% changes after that
  PIT         SEBI (Prohibition of Insider Trading) Regulations: trades by promoters,
              directors and designated persons above the disclosure limits

Sources (free, public, no key; NSE answers browsers only and may refuse a script at times,
in which case the tool says so plainly):
  https://archives.nseindia.com/content/equities/bulk.csv
  https://archives.nseindia.com/content/equities/block.csv
  https://www.nseindia.com/api/corporate-sast-reg29?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
  https://www.nseindia.com/api/corporates-pit?index=equities&symbol=<SYMBOL>

These are public filings made after the fact, not inside information and not a signal to
copy. A promoter's sale can be a pledge invocation, a gift or estate planning. Educational
only, not investment advice.
"""

import argparse
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BULK_URL = "https://archives.nseindia.com/content/equities/bulk.csv"
BLOCK_URL = "https://archives.nseindia.com/content/equities/block.csv"
SAST_URL = "https://www.nseindia.com/api/corporate-sast-reg29?index=equities&from_date=%s&to_date=%s"
PIT_URL = "https://www.nseindia.com/api/corporates-pit?index=equities&symbol=%s"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
CRORE = 1e7
NOTE = ("Public filings made after the fact, not inside information and not a signal to copy. "
        "Educational only, not investment advice.")


class DealsError(Exception):
    pass


class Fetcher(object):
    def __init__(self, offline=None, pause=0.5):
        self.offline = offline
        self.pause = pause
        self._last = 0.0

    def get(self, url, name, accept="*/*"):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise DealsError("offline: no file %s" % path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept,
                                                   "Accept-Language": "en-IN,en;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            raise DealsError("NSE answered HTTP %d for %s" % (e.code, url.split("?")[0]))
        except (urllib.error.URLError, OSError) as e:
            raise DealsError("could not reach NSE: %s" % getattr(e, "reason", e))

    def json(self, url, name):
        text = self.get(url, name, accept="application/json")
        try:
            return json.loads(text)
        except ValueError:
            raise DealsError("NSE did not answer JSON (it refuses scripts at times; try again later)")


def _f(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- bulk / block

def parse_deals_csv(text, kind):
    """bulk.csv / block.csv -> rows. Header: Date, Symbol, Security Name, Client Name, Buy/Sell,
    Quantity Traded, Trade Price / Wght. Avg. Price[, Remarks]. 'NO RECORDS' means none today."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows or "symbol" not in ",".join(rows[0]).lower():
        raise DealsError("the %s deals file is not the shape this tool knows" % kind)
    hdr = [h.strip().lower() for h in rows[0]]

    def col(*names):
        for n in names:
            for i, h in enumerate(hdr):
                if h.startswith(n):
                    return i
        return None
    di, si, ni, ci, bi, qi, pi = (col("date"), col("symbol"), col("security"), col("client"), col("buy"),
                                  col("quantity"), col("trade price", "price"))
    ri = col("remarks")
    out = []
    for r in rows[1:]:
        if not r or len(r) <= max(x for x in (di, si, ci, bi, qi, pi) if x is not None):
            continue
        if r[di].strip().upper().startswith("NO RECORDS") or not r[si].strip():
            continue
        q, p = _f(r[qi]), _f(r[pi])
        out.append({"kind": kind, "date": r[di].strip(), "symbol": r[si].strip().upper(),
                    "name": r[ni].strip() if ni is not None else "", "client": " ".join(r[ci].split()),
                    "side": r[bi].strip().upper(), "qty": int(q) if q else 0, "price": p,
                    "value": round(q * p, 2) if q and p else None,
                    "remarks": (r[ri].strip() if ri is not None and len(r) > ri else "")})
    return out


def filter_rows(rows, symbols=None, client=None, min_cr=None):
    out = []
    for r in rows:
        if symbols and r["symbol"] not in symbols:
            continue
        if client and client.lower() not in r.get("client", "").lower():
            continue
        if min_cr and (r.get("value") or 0) < min_cr * CRORE:
            continue
        out.append(r)
    return out


def summarise(rows):
    """Per symbol: net quantity and value bought minus sold by the disclosed clients."""
    per = {}
    for r in rows:
        d = per.setdefault(r["symbol"], {"buy": 0.0, "sell": 0.0, "n": 0, "name": r.get("name")})
        d["n"] += 1
        if r["side"] == "BUY":
            d["buy"] += r.get("value") or 0
        else:
            d["sell"] += r.get("value") or 0
    return per


def cr(v):
    return "-" if v is None else "\u20b9{:,.2f} cr".format(v / CRORE)


def render_deals(rows, errors, label):
    out = ["%s: %d deal%s." % (label, len(rows), "" if len(rows) == 1 else "s")]
    rows = sorted(rows, key=lambda r: -(r.get("value") or 0))
    for r in rows:
        out.append("  %-5s %-11s %-4s %12s @ %-10s %13s  %s%s" % (
            r["kind"], r["symbol"], r["side"], "{:,}".format(r["qty"]), "%.2f" % r["price"] if r["price"] else "-",
            cr(r.get("value")), r["client"][:48], ("  (%s)" % r["remarks"]) if r.get("remarks") not in ("", "-") else ""))
    per = summarise(rows)
    big = sorted(per.items(), key=lambda kv: -abs(kv[1]["buy"] - kv[1]["sell"]))[:10]
    if big:
        out.append("Net by symbol (disclosed buys minus sells, biggest first):")
        for s, d in big:
            out.append("  %-11s %+.2f cr  (%d deal%s)" % (s, (d["buy"] - d["sell"]) / CRORE, d["n"], "" if d["n"] == 1 else "s"))
    for e in errors:
        out.append("note: " + e)
    out.append(NOTE)
    return "\n".join(out)


# ---------------------------------------------------------------- SAST / PIT

def parse_sast(doc):
    rows = doc.get("data") if isinstance(doc, dict) else doc
    out = []
    for r in rows or []:
        out.append({"kind": "sast", "symbol": str(r.get("symbol") or "").upper(), "company": r.get("company"),
                    "who": r.get("acquirerName"), "what": r.get("acqSaleType"), "mode": r.get("acquisitionMode"),
                    "promoter": str(r.get("promoterType") or "").upper() == "Y", "reg": r.get("regType"),
                    "shares_acq": _f(r.get("noOfShareAcq")), "shares_sold": _f(r.get("noOfShareSale")),
                    "after_pct": _f(r.get("totAftShare")), "period": r.get("acquirerDate"),
                    "filed": r.get("timestamp") or r.get("sysTime"), "link": r.get("attachement")})
    return out


def parse_pit(doc):
    rows = doc.get("data") if isinstance(doc, dict) else doc
    out = []
    for r in rows or []:
        out.append({"kind": "pit", "symbol": str(r.get("symbol") or "").upper(), "company": r.get("company"),
                    "who": r.get("acqName"), "category": r.get("personCategory"), "type": r.get("tdpTransactionType"),
                    "mode": r.get("acqMode"), "shares": _f(r.get("secAcq")), "value": _f(r.get("secVal")),
                    "before": _f(r.get("befAcqSharesNo")), "after": _f(r.get("afterAcqSharesNo")),
                    "from": r.get("acqfromDt"), "to": r.get("acqtoDt"), "filed": r.get("date"), "link": r.get("xbrl")})
    return out


def market_trade(r):
    """A PIT row that is an on-market buy or sell (not a pledge, gift, ESOP or off-market move)."""
    return bool(re.search(r"market (purchase|sale)", str(r.get("mode") or ""), re.I))


def render_sast(rows, label):
    out = ["%s: %d disclosure%s." % (label, len(rows), "" if len(rows) == 1 else "s")]
    for r in rows:
        out.append("  %-17s %-11s %-12s %-28s %s%s after: %s%%  %s" % (
            r["filed"] or "-", r["symbol"], (r["what"] or "-")[:12], (r["who"] or "-")[:28], r["reg"] or "",
            " promoter" if r["promoter"] else "", "-" if r["after_pct"] is None else "%g" % r["after_pct"],
            r.get("mode") or ""))
    out.append(NOTE)
    return "\n".join(out)


def render_pit(rows, label, only_market=False):
    shown = [r for r in rows if market_trade(r)] if only_market else rows
    out = ["%s: %d disclosure%s%s." % (label, len(shown), "" if len(shown) == 1 else "s",
                                     " (on-market trades only)" if only_market else "")]
    for r in shown:
        out.append("  %-17s %-11s %-13s %-14s %12s sh %14s  %-26s %s" % (
            r["filed"] or "-", r["symbol"], (r["type"] or "-")[:13], (r["mode"] or "-")[:14],
            "{:,.0f}".format(r["shares"] or 0), cr(r["value"]) if r["value"] else "-", (r["who"] or "-")[:26],
            r.get("category") or ""))
    out.append("Modes: 'Market Purchase/Sale' is an on-market trade; pledges, revocations, gifts, ESOPs and "
               "'Off Market' moves are not a view on the price.")
    out.append(NOTE)
    return "\n".join(out)


# ---------------------------------------------------------------- state

def fp(r):
    key = "|".join(str(r.get(k)) for k in ("kind", "symbol", "date", "filed", "client", "who", "side", "type", "qty",
                                           "shares", "price"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def load_state(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"seen": {}}


def save_state(path, st, now):
    cutoff = (now - _dt.timedelta(days=45)).isoformat()
    st["seen"] = {k: v for k, v in st.get("seen", {}).items() if v >= cutoff}
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------- commands

def symbols_of(a):
    syms = set(s.strip().upper() for s in re.split(r"[,\s]+", a.symbols or "") if s.strip())
    if getattr(a, "watchlist", None) and os.path.exists(a.watchlist):
        with open(a.watchlist, encoding="utf-8") as fh:
            doc = json.load(fh)
        syms |= {str(h.get("symbol")).upper() for h in doc.get("hits", []) if h.get("symbol")}
    return syms or None


def get_deals(f, errors):
    rows = []
    for url, name, kind in ((BULK_URL, "bulk.csv", "bulk"), (BLOCK_URL, "block.csv", "block")):
        try:
            rows += parse_deals_csv(f.get(url, name), kind)
        except DealsError as e:
            errors.append("%s deals: %s" % (kind, e))
    return rows


def cmd_deals(a, f, now):
    errors = []
    rows = filter_rows(get_deals(f, errors), symbols_of(a), a.client, a.min_cr)
    if a.json:
        print(json.dumps({"deals": rows, "notes": errors}, indent=2, ensure_ascii=False))
    else:
        day = rows[0]["date"] if rows else now.astimezone(IST).strftime("%d-%b-%Y").upper()
        print(render_deals(rows, errors, "NSE bulk and block deals, %s" % day))
    return 0 if rows else 1


def cmd_sast(a, f, now):
    frm = (now - _dt.timedelta(days=a.days)).astimezone(IST).strftime("%d-%m-%Y")
    to = now.astimezone(IST).strftime("%d-%m-%Y")
    rows = parse_sast(f.json(SAST_URL % (frm, to), "sast.json"))
    syms = symbols_of(a)
    if syms:
        rows = [r for r in rows if r["symbol"] in syms]
    if a.promoters:
        rows = [r for r in rows if r["promoter"]]
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(render_sast(rows, "SAST Reg 29 disclosures %s to %s" % (frm, to)))
    return 0 if rows else 1


def cmd_insider(a, f, now):
    rows = []
    for s in a.symbols_pos:
        sym = s.upper()
        rows += parse_pit(f.json(PIT_URL % urllib.parse.quote(sym), "pit-%s.json" % sym))
    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print(render_pit(rows, "SEBI PIT disclosures for %s" % ", ".join(x.upper() for x in a.symbols_pos),
                         a.market_only))
    return 0 if rows else 1


def cmd_new(a, f, now):
    st = load_state(a.state)
    seen = st.setdefault("seen", {})
    errors = []
    rows = filter_rows(get_deals(f, errors), symbols_of(a), a.client, a.min_cr)
    try:
        frm = (now - _dt.timedelta(days=3)).astimezone(IST).strftime("%d-%m-%Y")
        sast = parse_sast(f.json(SAST_URL % (frm, now.astimezone(IST).strftime("%d-%m-%Y")), "sast.json"))
        syms = symbols_of(a)
        rows += [r for r in sast if not syms or r["symbol"] in syms]
    except DealsError as e:
        errors.append("SAST: %s" % e)
    new = [r for r in rows if fp(r) not in seen]
    stamp = now.isoformat()
    for r in rows:
        seen.setdefault(fp(r), stamp)
    if not a.dry_run:
        save_state(a.state, st, now)
    deals = [r for r in new if r["kind"] in ("bulk", "block")]
    sast = [r for r in new if r["kind"] == "sast"]
    print(render_deals(deals, errors, "New bulk and block deals since the last check"))
    if sast:
        print(render_sast(sast, "New SAST disclosures"))
    return 0 if new else 1


def main(argv=None):
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Bulk Deals and Insider Tracker (trader-bulkdeals, NSE). Educational only.")
    ap.add_argument("--offline", metavar="DIR", help="read bulk.csv, block.csv, sast.json, pit-<SYM>.json from DIR")
    ap.add_argument("--now", help="ISO time (UTC if bare), for reproducible runs")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--symbols", help="comma-separated NSE symbols")
        p.add_argument("--watchlist", help="trader/watchlist.json: its hits' symbols")
        p.add_argument("--json", action="store_true")
    p = sub.add_parser("deals", help="today's bulk and block deals")
    common(p)
    p.add_argument("--client", help="only deals by a client whose name contains this")
    p.add_argument("--min-cr", type=float, help="only deals worth at least this many crore")
    p = sub.add_parser("sast", help="SAST Reg 29 disclosures")
    common(p)
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--promoters", action="store_true", help="promoter disclosures only")
    p = sub.add_parser("insider", help="SEBI PIT disclosures for symbols")
    p.add_argument("symbols_pos", nargs="+", metavar="SYMBOL")
    p.add_argument("--market-only", action="store_true", help="on-market buys and sells only")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("new", help="what is new since the last check")
    common(p)
    p.add_argument("--client")
    p.add_argument("--min-cr", type=float)
    p.add_argument("--state", default="trader/state/deals.json")
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 2
    now = _dt.datetime.now(_dt.timezone.utc)
    if a.now:
        try:
            now = _dt.datetime.fromisoformat(a.now.replace("Z", "+00:00"))
        except ValueError:
            print("deals: --now wants an ISO time", file=sys.stderr)
            return 2
        if now.tzinfo is None:
            now = now.replace(tzinfo=_dt.timezone.utc)
    f = Fetcher(offline=a.offline)
    try:
        return {"deals": cmd_deals, "sast": cmd_sast, "insider": cmd_insider, "new": cmd_new}[a.cmd](a, f, now)
    except DealsError as e:
        print("deals: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
