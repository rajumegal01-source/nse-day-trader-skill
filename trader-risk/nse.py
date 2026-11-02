"""Shared NSE/BSE helpers for trader-budget, trader-risk and trader-broker. Standard library only.

Each of those three skill folders carries an identical copy of this file, so every skill
can be installed (or uploaded to claude.ai) on its own. tests/test_repo.py checks the
copies are byte for byte the same.

What is in here:
  the calendar   NSE trading holidays 2026 and the Muhurat special session, IST clock
  the costs      Indian intraday charges: brokerage, STT, exchange transaction charges,
                 SEBI turnover fee, GST and stamp duty (rates and sources below)
  lots and ticks F&O lot sizes, tick sizes, circuit (price band) checks
  the order      the order fields and their fingerprint (trader-risk and trader-broker
                 must agree on exactly which order was checked)
  kill switch    the daily max-loss kill switch, trader/state/killswitch.json
  money          rupees with Indian digit grouping: Rs 1,23,456.78 is printed as ₹1,23,456.78

Educational only, not investment advice.
"""

import datetime
import hashlib
import json
import math
import os
import re

# ---------------------------------------------------------------- calendar (IST, no tz files)

NSE_HOLIDAYS = {  # NSE equity + F&O trading holidays 2026 (NSE circular NSE/CMTR/71775 of 2025-12-12,
    # plus the 2026-01-15 Maharashtra municipal election holiday; list as on niftyindices.com, read 2026-11-02)
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
}
NSE_SPECIAL_SESSIONS = {  # date: (name, open, close) IST. Muhurat: NSE circular NSE/CMTR/76941 (2026-10-19)
    "2026-11-08": ("Muhurat trading (Diwali Laxmi Pujan)", datetime.time(14, 20), datetime.time(15, 30)),
}
CALENDAR_YEARS = (2026,)
PRE_OPEN = (datetime.time(9, 0), datetime.time(9, 8))   # order entry 9:00 to 9:08, matching to 9:15
OPEN = datetime.time(9, 15)
CLOSE = datetime.time(15, 30)
IST = datetime.timedelta(hours=5, minutes=30)           # India has no daylight saving


class NSEError(Exception):
    pass


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)


def to_ist(utc):
    return utc.replace(tzinfo=None) + IST


def ist_to_utc(local):
    return local.replace(tzinfo=None) - IST


def parse_now(text):
    """--now -> naive UTC. "2026-11-02 10:00" (or just 10:00 for today) is IST; Z or an
    offset makes it absolute."""
    if not text:
        return utc_now()
    t = str(text).strip()
    if t.upper().endswith(" IST"):
        t = t[:-4].strip()
    if re.match(r"^\d{1,2}:\d{2}$", t):
        t = "%s %s" % (to_ist(utc_now()).date().isoformat(), t.zfill(5))
    t = t.replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise NSEError('--now wants an IST time like "2026-11-02 10:00" (or ...Z for UTC)')
    if dt.tzinfo is None:
        return ist_to_utc(dt)
    return (dt - dt.utcoffset()).replace(tzinfo=None)


def parse_utc(text):
    """An ISO stamp (Z or offset; a bare one is UTC) -> naive UTC, or None."""
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = (dt - dt.utcoffset()).replace(tzinfo=None)
    return dt


def iso_z(utc):
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def hhmm(value, key):
    m = re.match(r"^\s*([01]?\d|2[0-3]):([0-5]\d)\s*$", str(value or ""))
    if not m:
        raise NSEError("%s wants an IST time like 14:45, not %r" % (key, value))
    return datetime.time(int(m.group(1)), int(m.group(2)))


def trading_day(d):
    """(is_trading_day, reason). Weekends and the NSE holiday list; a special session
    (Muhurat trading) opens a day that would otherwise be closed."""
    sp = NSE_SPECIAL_SESSIONS.get(d.isoformat())
    if sp:
        return True, "special session: " + sp[0]
    if d.weekday() >= 5:
        return False, "weekend"
    name = NSE_HOLIDAYS.get(d.isoformat())
    if name:
        return False, "NSE holiday: " + name
    return True, ""


def session(d):
    """(open_time, close_time) in IST, or None if closed all day."""
    ok, _ = trading_day(d)
    if not ok:
        return None
    sp = NSE_SPECIAL_SESSIONS.get(d.isoformat())
    if sp:
        return sp[1], sp[2]
    return OPEN, CLOSE


def session_window(day, before_t, after_t):
    """(no_entries_before, no_entries_after) as datetimes. On a special session they keep
    their distance from its open and close: 09:30 -> 14:35 on Muhurat, 14:45 stays 14:45.
    If that leaves no window, the cutoff is 15 minutes before the close."""
    s = session(day)
    b = datetime.datetime.combine(day, before_t)
    a = datetime.datetime.combine(day, after_t)
    if not s or (s[0], s[1]) == (OPEN, CLOSE):
        return b, a
    o = datetime.datetime.combine(day, s[0])
    c = datetime.datetime.combine(day, s[1])
    b = o + max(datetime.timedelta(0), b - datetime.datetime.combine(day, OPEN))
    a = c - max(datetime.timedelta(0), datetime.datetime.combine(day, CLOSE) - a)
    if a <= b:
        a = c - datetime.timedelta(minutes=15)
    return b, a


# ---------------------------------------------------------------- costs
#
# Rates as published on 2026-11-02 (read that day):
#   zerodha.com/charges: intraday brokerage 0.03% or Rs 20 per executed order, whichever is
#     lower; STT 0.025% on the sell side (equity intraday); NSE transaction charge 0.00307%,
#     BSE 0.00375%; SEBI Rs 10 per crore; stamp 0.003% on the buy side (intraday);
#     GST 18% on brokerage + SEBI fee + transaction charges. Futures: STT 0.05% sell (from
#     2026-04-01, Budget 2026-27), NSE txn 0.00183%, stamp 0.002%. Options: STT 0.15% of the
#     premium on the sell side, NSE txn 0.03553% of the premium, stamp 0.003%, flat Rs 20.
#   nseindia.com "SEBI Turnover Fees, STT and Other levies": SEBI fee 0.0001% (Rs 10/crore);
#     stamp duty by instrument, payable by the buyer.
# Brokerage is YOUR broker's: set it in trader/config.json ("brokerage_per_order",
# "brokerage_pct"). Statutory rates change with each Budget: check your contract note.

RATES = {
    "equity_intraday": {"stt_sell": 0.025, "stt_buy": 0.0, "stamp_buy": 0.003,
                        "txn": {"NSE": 0.00307, "BSE": 0.00375}, "brokerage": "pct_or_flat"},
    "equity_delivery": {"stt_sell": 0.1, "stt_buy": 0.1, "stamp_buy": 0.015,
                        "txn": {"NSE": 0.00307, "BSE": 0.00375}, "brokerage": "delivery"},
    "futures": {"stt_sell": 0.05, "stt_buy": 0.0, "stamp_buy": 0.002,
                "txn": {"NSE": 0.00183, "BSE": 0.0}, "brokerage": "pct_or_flat"},
    "options": {"stt_sell": 0.15, "stt_buy": 0.0, "stamp_buy": 0.003,
                "txn": {"NSE": 0.03553, "BSE": 0.0325}, "brokerage": "flat"},
}
SEBI_PER_CRORE = 10.0
GST_PCT = 18.0
COST_DEFAULTS = {"brokerage_per_order": 20.0, "brokerage_pct": 0.03, "brokerage_delivery": 0.0}
RATES_AS_OF = "2026-11-02"
PRODUCT_OF = {"equity_intraday": "MIS", "equity_delivery": "CNC", "futures": "NRML", "options": "NRML"}


def _r2(x):
    return math.floor(float(x) * 100 + 0.5 + 1e-9) / 100.0


def brokerage(value, segment="equity_intraday", cfg=None):
    """Brokerage for ONE executed order of this value."""
    c = dict(COST_DEFAULTS)
    c.update({k: v for k, v in (cfg or {}).items() if k in COST_DEFAULTS and v is not None})
    if value <= 0:
        return 0.0
    kind = RATES[segment]["brokerage"]
    flat = float(c["brokerage_per_order"])
    if kind == "flat":
        return flat
    if kind == "delivery":
        return float(c["brokerage_delivery"])
    return min(flat, value * float(c["brokerage_pct"]) / 100.0)


def charges(buy_value, sell_value, segment="equity_intraday", exchange="NSE", cfg=None):
    """Every charge on a buy leg and a sell leg (either may be 0), in rupees.
    Returns {"brokerage", "stt", "txn", "sebi", "gst", "stamp", "total", "turnover"}.
    Rounded to the paisa per component, as a contract note does (brokers round slightly
    differently, so expect a rupee or so of difference)."""
    if segment not in RATES:
        raise NSEError("segment is one of %s, not %r" % (", ".join(sorted(RATES)), segment))
    ex = str(exchange or "NSE").upper()
    if ex not in ("NSE", "BSE"):
        raise NSEError("exchange is NSE or BSE, not %r" % exchange)
    r = RATES[segment]
    bv, sv = max(0.0, float(buy_value or 0)), max(0.0, float(sell_value or 0))
    turnover = bv + sv
    brk = brokerage(bv, segment, cfg) + brokerage(sv, segment, cfg)
    stt = bv * r["stt_buy"] / 100.0 + sv * r["stt_sell"] / 100.0
    txn = turnover * r["txn"].get(ex, 0.0) / 100.0
    sebi = turnover * SEBI_PER_CRORE / 1e7
    gst = (brk + txn + sebi) * GST_PCT / 100.0
    stamp = bv * r["stamp_buy"] / 100.0
    out = {"brokerage": _r2(brk), "stt": _r2(stt), "txn": _r2(txn), "sebi": _r2(sebi), "gst": _r2(gst),
           "stamp": _r2(stamp)}
    out["total"] = _r2(sum(out.values()))
    out["turnover"] = _r2(turnover)
    return out


def round_trip(qty, entry, exit_px, segment="equity_intraday", exchange="NSE", cfg=None):
    """A long bought at entry and sold at exit_px: gross, charges and net P&L."""
    bv, sv = qty * float(entry), qty * float(exit_px)
    ch = charges(bv, sv, segment, exchange, cfg)
    gross = _r2(sv - bv)
    return {"gross": gross, "charges": ch["total"], "net": _r2(gross - ch["total"]), "detail": ch}


def breakeven_move(qty, entry, segment="equity_intraday", exchange="NSE", cfg=None):
    """Points the price must rise for a long to cover its round-trip charges."""
    if qty <= 0:
        return None
    ch = charges(qty * entry, qty * entry, segment, exchange, cfg)["total"]
    return _r2(ch / qty)


# ---------------------------------------------------------------- lots, ticks, circuits

# F&O lot sizes from Angel One's instrument master (OpenAPIScripMaster.json), read 2026-11-02.
# Lot sizes change at NSE's periodic revisions: a "lot_sizes" map in trader/config.json wins.
LOT_SIZES = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120,
             "RELIANCE": 500, "TCS": 225, "SBIN": 750}
LOT_SIZES_AS_OF = "2026-11-02"


def lot_size(symbol, segment, cfg=None):
    """1 for cash equity; the contract's lot for futures and options, or None if unknown."""
    if segment in ("equity_intraday", "equity_delivery"):
        return 1
    root = re.sub(r"\d.*$", "", str(symbol).upper())  # RELIANCE25JAN27FUT -> RELIANCE
    custom = {str(k).upper(): v for k, v in ((cfg or {}).get("lot_sizes") or {}).items()}
    v = custom.get(str(symbol).upper()) or custom.get(root) or LOT_SIZES.get(root)
    return int(v) if v else None


def on_tick(price, tick):
    """Is the price a whole number of ticks?"""
    if not tick:
        return True
    n = float(price) / float(tick)
    return abs(n - round(n)) < 1e-6


def band_limits(prev_close, band_pct):
    """(lower, upper) circuit limits for a price band in percent (2, 5, 10, 20), or None."""
    try:
        pc, b = float(prev_close), float(band_pct)
    except (TypeError, ValueError):
        return None
    if pc <= 0 or b <= 0:
        return None
    return _r2(pc * (1 - b / 100.0)), _r2(pc * (1 + b / 100.0))


# ---------------------------------------------------------------- the order

ORDER_FIELDS = ("symbol", "exchange", "segment", "product", "side", "qty", "lot_size", "order_type",
                "price", "trigger_price", "stop_loss", "target", "validity")


def fingerprint(order):
    """The exact order that was checked: trader-risk writes it, trader-broker matches it."""
    core = {k: order[k] for k in ORDER_FIELDS if k in order and order[k] is not None}
    blob = json.dumps(core, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- files

def read_json(path, what, required=True):
    if not path or not os.path.exists(path):
        if required:
            raise NSEError("no %s at %s" % (what, path))
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as e:
        raise NSEError("%s is not valid JSON: %s" % (path, e))


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- kill switch

def killswitch(path, today, max_daily_loss=None, realized_net=None):
    """(tripped, reason). Tripped for the rest of `today` (IST date) when the file says so
    for today (a manual `ticket.py kill`, or an earlier trip), or when today's realized net
    P&L is at or below -max_daily_loss. A trip is written to the file and never undone
    the same day; it lapses by itself on the next date."""
    doc = read_json(path, "kill switch", required=False) or {}
    if doc.get("date") == today and doc.get("tripped"):
        return True, doc.get("reason") or "the kill switch is on for today"
    if max_daily_loss and realized_net is not None and realized_net <= -float(max_daily_loss) + 1e-9:
        reason = ("today's realized loss %s reached your max_daily_loss_inr %s: no new entries until tomorrow"
                  % (inr(-realized_net), inr(max_daily_loss)))
        write_json(path, {"date": today, "tripped": True, "reason": reason, "realized_net": realized_net,
                          "at": iso_z(utc_now())})
        return True, reason
    return False, ""


def trip(path, today, reason):
    write_json(path, {"date": today, "tripped": True, "reason": reason, "at": iso_z(utc_now())})


# ---------------------------------------------------------------- money

def inr(x, paise=True):
    """Indian digit grouping: 123456.5 -> ₹1,23,456.50 (lakh, crore)."""
    x = float(x)
    neg = x < 0
    x = abs(x)
    whole = int(math.floor(x + 1e-9))
    frac = int(round((x - whole) * 100))
    if frac == 100:
        whole, frac = whole + 1, 0
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    out = "\u20b9" + s + (".%02d" % frac if paise else "")
    return "-" + out if neg else out


def num(x):
    """358.3 -> "358.30"; prices as strings with two decimals."""
    return "%.2f" % _r2(x)


DISCLAIMER = ("Educational only, not investment advice. Not a SEBI-registered investment adviser. "
              "SEBI found that 7 out of 10 individual intraday traders in the equity cash segment "
              "made losses in FY 2022-23.")
