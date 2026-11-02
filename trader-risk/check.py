#!/usr/bin/env python3
"""Pre-trade risk check for trader-risk (NSE/BSE port). Standard library only; no network
except the optional `bands` command.

Reads the proposed orders (trader/orders.json) and checks every one against your rules
(trader/config.json), your account (trader/portfolio.json), prices (trader/prices.json),
what was placed today (trader/state/broker.json), today's realized P&L
(trader/state/pnl.json) and the kill switch (trader/state/killswitch.json). Each order gets
PASS or BLOCK with the reasons. Orders are checked in file order as if each PASS had filled.

    python3 check.py                                 # the trader/ files, writes trader/state/risk.json
    python3 check.py --now "2026-11-02 10:00"        # pin the clock (IST)
    python3 check.py --orders trader/orders.json --json
    python3 check.py bands                           # NSE price bands -> trader/bands.json (circuits)

Entries and exits. An ENTRY opens or adds to a position (a BUY). An EXIT only reduces what
you hold. Getting out must always be possible: an exit is checked for format, asset and
short sales only; every other rule becomes a warning for it.

What blocks any order:
  format      symbol, exchange (NSE/BSE), segment, product (MIS intraday, CNC delivery,
              NRML F&O), side, a whole qty that is a multiple of the lot size (F&O),
              order type (LIMIT, MARKET, SL, SL-M), a LIMIT price, a price off the tick
  asset       F&O unless "allow_fno": true; options unless "allow_options": true
  short       selling more than you hold, unless "allow_short": true
  market      a MARKET order in live mode (NSE's retail-algo rules do not permit market
              orders through an API algo; Angel One converts them to limit orders anyway)

What blocks an entry (on top):
  kill switch today's realized net loss reached max_daily_loss_inr, or you ran
              `ticket.py kill`: no new entries until tomorrow
  blocked     a symbol on your "blocked" list
  size        under min_order_inr, over max_order_inr
  position    over max_position_pct of the account
  cash        the buy plus its charges would dip into the cash buffer (no MIS leverage)
  duplicate   the same symbol and side twice in this batch, or already placed today
  daily limit max_orders_per_day orders placed today
  trades      max_trades_per_day entries already placed today
  stop        no stop while "require_stop": true; a stop on the wrong side
  loss        qty x (entry - stop) PLUS the round-trip charges over max_loss_per_trade_inr
  reward:risk after charges (net at the target / net loss at the stop) under min_reward_risk
  daily loss  the net max losses of today's entries plus this one over max_daily_loss_inr,
              on top of any loss already realized today
  window      NSE closed (weekend, holiday), outside 9:15 to 15:30 IST (Muhurat 14:20 to
              15:30), or outside no_entries_before / no_entries_after
  circuit     the entry price outside the stock's price band (needs trader/bands.json and
              the previous close in trader/prices.json); a target beyond the band only warns

Charges as in nse.py (rates read 2026-11-02 from zerodha.com/charges and nseindia.com).
Exit code 0 when every order passes, 1 when any order is blocked. The verdicts go to
trader/state/risk.json with a fingerprint of each order, so trader-broker only treats an
order as ready if THIS exact order passed today. Educational only, not investment advice.
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nse  # noqa: E402

DEFAULTS = {
    "budget": None,
    "cash_buffer_pct": 10,
    "max_position_pct": 75,
    "max_order_inr": 200000,
    "min_order_inr": 500,
    "max_loss_per_trade_inr": 500,
    "max_daily_loss_inr": 1500,
    "max_trades_per_day": 3,
    "max_orders_per_day": 10,
    "min_reward_risk": 1.0,
    "rr_after_costs": True,
    "require_stop": True,
    "no_entries_before": "09:30",
    "no_entries_after": "14:45",
    "mode": "paper",
    "blocked": [],
    "allow_fno": False,
    "allow_options": False,
    "allow_short": False,
}
SEGMENTS = {"equity_intraday": {"MIS"}, "equity_delivery": {"CNC"}, "futures": {"NRML", "MIS"},
            "options": {"NRML", "MIS"}}
ORDER_TYPES = {"LIMIT", "MARKET", "SL", "SL-M"}
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,29}$")
FRESH_MINUTES = 15
SEC_LIST_URL = "https://archives.nseindia.com/content/equities/sec_list.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


class RiskError(Exception):
    pass


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def mode_of(cfg):
    m = str(cfg.get("mode") or "").lower()
    if m in ("paper", "live"):
        return m
    return "paper" if cfg.get("paper", True) else "live"


def account(cfg, portfolio, prices):
    """(cash, {SYM: qty}, {SYM: value}). No portfolio = a fresh account funded with the budget."""
    if portfolio is None:
        budget = _f(cfg.get("budget"))
        if not budget:
            raise RiskError("no trader/portfolio.json and no budget in the config: nothing to check against")
        return budget, {}, {}
    cash = _f(portfolio.get("cash"))
    if cash is None:
        raise RiskError("portfolio.json needs a \"cash\" number (rupees)")
    shares, values = {}, {}
    for p in portfolio.get("positions", []):
        t = str(p.get("symbol") or p.get("ticker") or "").upper()
        if not t:
            continue
        n = _f(p.get("qty", p.get("shares"))) or 0
        shares[t] = shares.get(t, 0) + n
        px = prices.get(t) or _f(p.get("avg_price")) or 0
        values[t] = shares[t] * px
    return cash, shares, values


def rec_day(rec):
    return str(rec.get("date") or str(rec.get("at", ""))[:10])


def placed_today(state, today):
    return [r for r in (state or {}).get("orders", [])
            if r.get("status") in ("placed", "filled") and rec_day(r) == today]


def realized_today(pnl, today):
    if isinstance(pnl, dict) and pnl.get("date") == today:
        return _f(pnl.get("realized_net")) or 0.0
    return 0.0


def window_check(now_ist, cfg):
    """[] or the reasons the clock blocks a new entry."""
    d = now_ist.date()
    ok, why = nse.trading_day(d)
    if not ok:
        return ["NSE is closed on %s (%s)" % (d.isoformat(), why)]
    o, c = nse.session(d)
    if now_ist.time() < o or now_ist.time() >= c:
        return ["outside the session: it is %s IST and NSE trades %s to %s today"
                % (now_ist.strftime("%H:%M"), o.strftime("%H:%M"), c.strftime("%H:%M"))]
    before, after = nse.session_window(d, nse.hhmm(cfg["no_entries_before"], "no_entries_before"),
                                       nse.hhmm(cfg["no_entries_after"], "no_entries_after"))
    if now_ist < before:
        return ["before %s IST, your first time for new entries (no_entries_before)" % before.strftime("%H:%M")]
    if now_ist > after:
        return ["after %s IST, your last time for new entries (no_entries_after)" % after.strftime("%H:%M")]
    return []


def format_check(o, cfg):
    """(reasons, normalized) for one order."""
    r = []
    sym = str(o.get("symbol") or "").upper()
    if not SYMBOL.match(sym):
        r.append("format: the symbol %r is not an NSE/BSE trading symbol" % o.get("symbol"))
    ex = str(o.get("exchange") or "").upper()
    if ex not in ("NSE", "BSE"):
        r.append("format: exchange must be NSE or BSE, not %r" % o.get("exchange"))
    seg = o.get("segment")
    if seg not in SEGMENTS:
        r.append("format: segment must be one of %s" % ", ".join(sorted(SEGMENTS)))
    elif str(o.get("product") or "").upper() not in SEGMENTS[seg]:
        r.append("format: product %r does not fit %s (use %s)" % (o.get("product"), seg, "/".join(sorted(SEGMENTS[seg]))))
    side = str(o.get("side") or "").upper()
    if side not in ("BUY", "SELL"):
        r.append("format: side must be BUY or SELL")
    q = o.get("qty")
    if isinstance(q, bool) or not isinstance(q, int) or q <= 0:
        if not (isinstance(q, str) and q.isdigit() and int(q) > 0):
            r.append("format: qty must be a whole number above 0, not %r" % q)
    qty = int(q) if (isinstance(q, int) and not isinstance(q, bool)) or (isinstance(q, str) and q.isdigit()) else 0
    lot = nse.lot_size(sym, seg, cfg) if seg in SEGMENTS else 1
    lot = int(o.get("lot_size") or lot or 0)
    if seg in ("futures", "options"):
        if not lot:
            r.append("format: no lot size known for %s; F&O orders need whole lots" % sym)
        elif qty % lot:
            r.append("format: qty %d is not a whole number of lots (lot size %d)" % (qty, lot))
    ot = str(o.get("order_type") or "").upper()
    if ot not in ORDER_TYPES:
        r.append("format: order_type must be LIMIT, MARKET, SL or SL-M")
    price = _f(o.get("price"))
    if ot in ("LIMIT", "SL") and (price is None or price <= 0):
        r.append("format: a %s order needs a price" % ot)
    if ot in ("SL", "SL-M") and not _f(o.get("trigger_price")):
        r.append("format: a %s order needs a trigger_price" % ot)
    tick = _f((o.get("plan") or {}).get("tick_size")) or _f((cfg.get("tick_sizes") or {}).get(sym)) \
        or _f(cfg.get("tick_size"))
    for k in ("price", "trigger_price", "stop_loss", "target"):
        v = _f(o.get(k))
        if v is not None and tick and not nse.on_tick(v, tick):
            r.append("format: %s %s is not on the %s tick" % (k, o[k], ("%g" % tick)))
    if str(o.get("validity") or "DAY").upper() not in ("DAY", "IOC"):
        r.append("format: validity must be DAY or IOC")
    return r, {"symbol": sym, "exchange": ex, "segment": seg, "side": side, "qty": qty, "lot": lot,
               "order_type": ot, "price": price}


def check(orders, cfg, portfolio=None, prices=None, state=None, today=None, now=None, price_times=None,
          pnl=None, killswitch=(False, ""), bands=None, prev_close=None):
    """Pure function. Returns {"results": [...], "pass": n, "block": n, "warnings": [...], "realized_today": x}.

    now          naive UTC; its IST date is "today"
    price_times  {SYM: naive UTC of that price}; None = every price counts as fresh
    killswitch   (tripped, reason), from nse.killswitch()
    bands        {SYM: band percent or "No Band"}; prev_close {SYM: previous close}"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    prices = {str(k).upper(): float(v) for k, v in (prices or {}).items() if _f(v)}
    now = now or nse.utc_now()
    now_ist = nse.to_ist(now)
    today = today or now_ist.date().isoformat()
    mode = mode_of(c)
    cash, shares, values = account(c, portfolio, prices)
    budget = _f(c.get("budget")) or (cash + sum(values.values()))
    equity = cash + sum(values.values()) if portfolio is not None else budget
    buffer_ = equity * float(c.get("cash_buffer_pct") or 0) / 100.0
    done = placed_today(state, today)
    entries_today = [r for r in done if (r.get("kind") or ("entry" if str(r.get("side")).upper() == "BUY" else "exit")) == "entry"]
    loss_today = sum(_f(r.get("max_loss")) or 0 for r in entries_today)
    realized = realized_today(pnl, today)
    n_orders = len(done)
    n_trades = len(entries_today)
    seen = {(str(r.get("symbol")).upper(), str(r.get("side")).upper()) for r in done}
    win = window_check(now_ist, c)
    results, top_warn = [], []
    if realized:
        top_warn.append("realized net P&L today: %s" % nse.inr(realized))
    for i, o in enumerate(orders):
        reasons, n = format_check(o, c)
        warns = []
        sym, seg, side, qty = n["symbol"], n["segment"], n["side"], n["qty"]
        if seg in ("futures", "options") and not c.get("allow_fno"):
            reasons.append("asset: F&O is off (\"allow_fno\": false)")
        if seg == "options" and not c.get("allow_options"):
            reasons.append("asset: options are off (\"allow_options\": false)")
        held = shares.get(sym, 0)
        kind = "entry" if side == "BUY" or (side == "SELL" and qty > held) else "exit"
        if side == "SELL" and qty > held and not c.get("allow_short"):
            reasons.append("short: selling %d %s but you hold %d (\"allow_short\": false)" % (qty, sym, held))
        if mode == "live" and n["order_type"] == "MARKET":
            reasons.append("market: no MARKET orders in live mode (NSE's retail-algo rules); use a LIMIT price")
        plan = o.get("plan") or {}
        # the entry it is checked at: the limit price, else the higher of the plan's and a fresh price
        ref = n["price"] if n["order_type"] == "LIMIT" else None
        fresh = prices.get(sym)
        if fresh is not None and price_times is not None:
            t = price_times.get(sym)
            if t is None or not -60 <= (now - t).total_seconds() <= FRESH_MINUTES * 60:
                fresh = None
        if ref is None:
            ref = max([x for x in (_f(plan.get("entry")), fresh) if x] or [0]) or None
        stop, target = _f(o.get("stop_loss")) or _f(plan.get("stop")), _f(o.get("target")) or _f(plan.get("target"))
        ex = n["exchange"] if n["exchange"] in ("NSE", "BSE") else "NSE"
        seg_ok = seg if seg in nse.RATES else "equity_intraday"
        ent = []  # entry-only rules: block an entry, warn on an exit
        if killswitch and killswitch[0]:
            ent.append("kill switch: " + killswitch[1])
        if sym in {str(b).upper() for b in (c.get("blocked") or [])}:
            ent.append("blocked: %s is on your blocked list" % sym)
        notional = (ref or 0) * qty
        if ref:
            if notional < float(c.get("min_order_inr") or 0) - 0.005:
                ent.append("size: %s is under your %s minimum order" % (nse.inr(notional), nse.inr(c["min_order_inr"])))
            if _f(c.get("max_order_inr")) and notional > float(c["max_order_inr"]) + 0.005:
                ent.append("size: %s is over your %s max order" % (nse.inr(notional), nse.inr(c["max_order_inr"])))
            cap = equity * float(c.get("max_position_pct") or 100) / 100.0
            if values.get(sym, 0) + notional > cap + 0.005:
                ent.append("position: %s would be %s, over %s%% of the account (%s)"
                           % (sym, nse.inr(values.get(sym, 0) + notional), ("%g" % float(c["max_position_pct"])),
                              nse.inr(cap)))
            buy_ch = nse.charges(notional, 0, seg_ok, ex, c)["total"]
            if side == "BUY" and notional + buy_ch > cash - buffer_ + 0.005:
                ent.append("cash: %s plus %s charges needs more than the %s cash above your buffer (no MIS "
                           "leverage)" % (nse.inr(notional), nse.inr(buy_ch), nse.inr(max(cash - buffer_, 0))))
        else:
            ent.append("loss: no entry price to check the risk at (a LIMIT price or the plan's entry)")
        key = (sym, side)
        if key in seen:
            ent.append("duplicate: a %s %s was already placed today or is earlier in this batch" % (side, sym))
        if n_orders >= int(c.get("max_orders_per_day") or 10**6):
            ent.append("daily limit: %d orders already placed today (max_orders_per_day)" % n_orders)
        if n_trades >= int(c.get("max_trades_per_day") or 10**6):
            ent.append("trades: %d entries already today (max_trades_per_day)" % n_trades)
        net_loss = None
        if side == "BUY":
            if stop is None:
                if c.get("require_stop", True):
                    ent.append("stop: no stop_loss (\"require_stop\": true)")
            elif ref and stop >= ref:
                ent.append("stop: the stop %s is not below the entry %s" % (nse.num(stop), nse.num(ref)))
            elif ref and qty:
                at_stop = nse.round_trip(qty, ref, stop, seg_ok, ex, c)
                net_loss = -at_stop["net"]
                ml = _f(c.get("max_loss_per_trade_inr"))
                if ml and net_loss > ml + 0.005:
                    ent.append("loss: %d x (%s - %s) + %s charges = %s, over your %s max loss per trade"
                               % (qty, nse.num(ref), nse.num(stop), nse.inr(at_stop["charges"]), nse.inr(net_loss),
                                  nse.inr(ml)))
                mrr = _f(c.get("min_reward_risk"))
                if mrr and target:
                    at_t = nse.round_trip(qty, ref, target, seg_ok, ex, c)
                    rr = at_t["net"] / net_loss if net_loss > 0 else None
                    if not c.get("rr_after_costs", True):
                        rr = (target - ref) / (ref - stop)
                    if rr is None or rr < mrr - 1e-9:
                        ent.append("reward:risk %s %s, under your minimum %s"
                                   % ("%.2f" % rr if rr is not None else "n/a",
                                      "after charges" if c.get("rr_after_costs", True) else "before charges", "%g" % mrr))
                elif mrr and not target and c.get("require_stop", True):
                    warns.append("no target: reward:risk not checked")
                mdl = _f(c.get("max_daily_loss_inr"))
                if mdl and loss_today + net_loss - min(realized, 0) > mdl + 0.005:
                    ent.append("daily loss: today's entries risk %s, this one %s%s: over your %s daily max"
                               % (nse.inr(loss_today), nse.inr(net_loss),
                                  (", after %s already lost" % nse.inr(-realized)) if realized < 0 else "",
                                  nse.inr(mdl)))
        ent += ["window: " + w for w in win]
        band = (bands or {}).get(sym)
        pc = (prev_close or {}).get(sym)
        lim = nse.band_limits(pc, band) if band not in (None, "No Band") else None
        if lim and ref:
            lo, hi = lim
            if not lo <= ref <= hi:
                ent.append("circuit: the entry %s is outside today's %s%% band %s to %s (prev close %s)"
                           % (nse.num(ref), band, nse.num(lo), nse.num(hi), nse.num(pc)))
            if target and target > hi:
                warns.append("circuit: the target %s is above the %s%% upper circuit %s: it may never fill there"
                             % (nse.num(target), band, nse.num(hi)))
        elif band == "No Band":
            warns.append("circuit: %s has no fixed price band (F&O stocks have dynamic bands)" % sym)
        if kind == "entry":
            reasons += ent
        else:
            warns += ["(exit, not blocked) " + x for x in ent]
        verdict = "BLOCK" if reasons else "PASS"
        res = {"index": i + 1, "symbol": sym, "side": side, "qty": qty, "kind": kind, "verdict": verdict,
               "reasons": reasons, "warnings": warns, "fingerprint": nse.fingerprint(o),
               "entry_checked_at": ref, "max_loss": round(net_loss, 2) if net_loss is not None else None}
        results.append(res)
        if verdict == "PASS":  # as if it filled
            seen.add(key)
            n_orders += 1
            if kind == "entry":
                n_trades += 1
                loss_today += net_loss or 0
                cash -= notional + (nse.charges(notional, 0, seg_ok, ex, c)["total"] if ref else 0)
                values[sym] = values.get(sym, 0) + notional
                shares[sym] = shares.get(sym, 0) + qty
            else:
                shares[sym] = held - qty
    return {"date": today, "checked_at": nse.iso_z(now), "mode": mode, "results": results,
            "pass": sum(1 for r in results if r["verdict"] == "PASS"),
            "block": sum(1 for r in results if r["verdict"] == "BLOCK"), "warnings": top_warn,
            "realized_today": realized}


def report(res):
    out = []
    for r in res["results"]:
        out.append("%s  order %d: %s %d %s (%s)" % (r["verdict"], r["index"], r["side"], r["qty"], r["symbol"], r["kind"]))
        if r.get("max_loss") is not None:
            out.append("      net loss at the stop, charges included: %s" % nse.inr(r["max_loss"]))
        for x in r["reasons"]:
            out.append("      BLOCK: " + x)
        for x in r["warnings"]:
            out.append("      note: " + x)
    for w in res["warnings"]:
        out.append("note: " + w)
    out.append("%d passed, %d blocked (%s mode). A PASS is a rules check, not a recommendation." % (
        res["pass"], res["block"], res["mode"].upper()))
    out.append(nse.DISCLAIMER)
    return "\n".join(out)


def load_prices(pdoc):
    """trader/prices.json -> (prices, times, prev_close)."""
    prices, times, prev = {}, {}, {}
    if not isinstance(pdoc, dict):
        return prices, None, prev
    for k, v in (pdoc.get("prices") or {}).items():
        if _f(v):
            prices[str(k).upper()] = float(v)
    for k, d in (pdoc.get("detail") or {}).items():
        if not isinstance(d, dict):
            continue
        t = nse.parse_utc(d.get("time")) or nse.parse_utc(d.get("fetched"))
        if t:
            times[str(k).upper()] = t
        if _f(d.get("prev_close")):
            prev[str(k).upper()] = float(d["prev_close"])
    asof = nse.parse_utc(pdoc.get("as_of"))
    for k in prices:
        if k not in times and asof:
            times[k] = asof
    return prices, times, prev


def parse_sec_list(text):
    """NSE sec_list.csv (Symbol, Series, Security Name, Band, Remarks) -> {SYM: band}."""
    import csv
    import io
    out = {}
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows or "symbol" not in rows[0][0].lower():
        raise RiskError("not NSE's sec_list.csv")
    hdr = [h.strip().lower() for h in rows[0]]
    si, bi = hdr.index("symbol"), hdr.index("band")
    for r in rows[1:]:
        if len(r) > bi and r[si].strip():
            b = r[bi].strip()
            try:
                out[r[si].strip().upper()] = float(b)
            except ValueError:
                out[r[si].strip().upper()] = "No Band" if "no" in b.lower() else b
    return out


def cmd_bands(a):
    if a.offline:
        with open(a.offline, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    else:
        try:
            req = urllib.request.Request(SEC_LIST_URL, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=60) as r:
                text = r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            raise RiskError("could not read NSE's sec_list.csv: %s" % getattr(e, "reason", e))
    bands = parse_sec_list(text)
    nse.write_json(a.out, {"source": SEC_LIST_URL, "as_of": nse.iso_z(nse.utc_now()), "bands": bands})
    print("NSE price bands: %d symbols with a fixed band (stocks not listed have no fixed band, e.g. F&O stocks "
          "with dynamic bands). Wrote %s." % (len(bands), a.out))
    return 0


def cmd_check(a):
    cfg = dict(DEFAULTS)
    doc = nse.read_json(a.config, "config", required=False)
    if doc:
        cfg.update(doc)
    od = nse.read_json(a.orders, "orders (run /trader-budget first)")
    orders = od.get("orders", []) if isinstance(od, dict) else od
    if not orders:
        raise RiskError("%s has no orders" % a.orders)
    pf = nse.read_json(a.portfolio, "portfolio", required=False)
    prices, times, prev = load_prices(nse.read_json(a.prices, "prices", required=False))
    for kv in a.prev_close or []:
        k, _, v = kv.partition("=")
        if _f(v):
            prev[k.strip().upper()] = float(v)
    bd = nse.read_json(a.bands, "bands", required=False) or {}
    state = nse.read_json(a.state, "broker state", required=False)
    pnl = nse.read_json(a.pnl, "pnl", required=False)
    now = nse.parse_now(a.now)
    today = nse.to_ist(now).date().isoformat()
    ks = nse.killswitch(a.killswitch, today, _f(cfg.get("max_daily_loss_inr")), realized_today(pnl, today))
    res = check(orders, cfg, pf, prices, state, today, now, times if times else None, pnl, ks,
                bd.get("bands"), prev)
    if not a.no_write:
        nse.write_json(a.out, res)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(report(res))
        if not a.no_write:
            print("Wrote %s." % a.out)
    return 0 if res["block"] == 0 else 1


def _utf8_out():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv=None):
    _utf8_out()
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="Risk Manager (trader-risk, NSE/BSE): PASS or BLOCK every order. "
                                             "Educational only, not investment advice.")
    if argv and argv[0] == "bands":
        ap.add_argument("cmd")
        ap.add_argument("--out", default="trader/bands.json")
        ap.add_argument("--offline", help="a saved sec_list.csv")
        a = ap.parse_args(argv)
        fn = cmd_bands
    else:
        ap.add_argument("--orders", default="trader/orders.json")
        ap.add_argument("--config", default="trader/config.json")
        ap.add_argument("--portfolio", default="trader/portfolio.json")
        ap.add_argument("--prices", default="trader/prices.json")
        ap.add_argument("--bands", default="trader/bands.json")
        ap.add_argument("--prev-close", action="append", metavar="SYM=PRICE", help="previous close for the circuit check")
        ap.add_argument("--state", default="trader/state/broker.json")
        ap.add_argument("--pnl", default="trader/state/pnl.json")
        ap.add_argument("--killswitch", default="trader/state/killswitch.json")
        ap.add_argument("--out", default="trader/state/risk.json")
        ap.add_argument("--now", help='pretend it is this IST time, e.g. "2026-11-02 10:00"')
        ap.add_argument("--no-write", action="store_true")
        ap.add_argument("--json", action="store_true")
        a = ap.parse_args(argv)
        fn = cmd_check
    try:
        return fn(a)
    except (RiskError, nse.NSEError) as e:
        print("check.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
