#!/usr/bin/env python3
"""Position sizing for trader-budget (NSE/BSE port). Standard library only, no network.

Sizes ONE day trade from trader/plan.json (written by trader-exit) to your budget and
your max loss per trade, WITH the Indian intraday costs counted, then writes one
order (entry, stop-loss, target) to trader/orders.json. It never places anything:
trader-risk checks the order and trader-broker shows you the ticket and asks yes or no.

    python3 size.py                                  # trader/plan.json + trader/config.json
    python3 size.py --write                          # write trader/orders.json
    python3 size.py --budget 50000 --max-loss 500    # override the config
    python3 size.py --limit 1234.50 --write          # a limit order at 1234.50 (the default is
                                                     # a limit at the plan's entry)
    python3 size.py --segment futures --lot-size 500 # F&O: whole lots only
    python3 size.py --now "2026-11-02 10:00" --json  # pin the clock (IST)

How many shares (or lots). The loss at the stop COUNTS THE CHARGES:

    loss(q) = q x (entry - stop) + charges(buy q at entry, sell q at stop)
    q = the largest whole number (a multiple of the lot for F&O) with
      max loss       loss(q) <= max_loss_per_trade_inr
      position cap   q x entry <= budget x max_position_pct
      max order      q x entry <= max_order_inr
      cash           q x entry + buy-side charges <= budget minus the cash buffer
                     (and no more than the cash in trader/portfolio.json, if you have one)

Charges (nse.py, rates read 2026-11-02, zerodha.com/charges and nseindia.com): brokerage
min(Rs 20, 0.03%) per executed order (configurable), STT 0.025% of the sell value,
exchange transaction charge (NSE 0.00307%, BSE 0.00375%), SEBI fee Rs 10 per crore, GST
18% on brokerage + transaction + SEBI, stamp duty 0.003% of the buy value.

Reward:risk is checked AFTER costs ("rr_after_costs": true, the default): the net
profit at the target over the net loss at the stop must reach min_reward_risk. A 1R
target never passes after costs; plan 1.5R or 2R.

No leverage: MIS margin is not used to size (allow_margin false), no shorts, no F&O
unless "allow_fno": true. Zero shares is a plain refusal: no order is written.
Educational only, not investment advice. Not a SEBI-registered adviser.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nse  # noqa: E402

DEFAULTS = {
    "budget": None,
    "currency": "INR",
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
    "flat_by": "15:10",
    "segment": "equity_intraday",
    "exchange": "NSE",
    "order_type": "LIMIT",
    "brokerage_per_order": 20.0,
    "brokerage_pct": 0.03,
    "mode": "paper",
    "paper": True,
    "broker": "angelone",
    "blocked": [],
    "allow_fno": False,
    "allow_options": False,
    "allow_margin": False,
    "allow_short": False,
}
FRESH_MINUTES = 15
SETUP_WORDS = {"orb": "opening-range breakout", "level": "close above a level", "flag": "flag",
               "bounce": "oversold bounce"}


class SizeError(Exception):
    pass


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        try:
            doc = nse.read_json(path, "config")
        except nse.NSEError as e:
            raise SizeError(str(e))
        cfg.update(doc)
    return cfg


def split_symbol(sym):
    """RELIANCE -> (RELIANCE, NSE); RELIANCE.BO -> (RELIANCE, BSE); RELIANCE.NS -> (RELIANCE, NSE)."""
    s = str(sym or "").strip().upper()
    if s.endswith(".BO"):
        return s[:-3], "BSE"
    if s.endswith(".NS"):
        return s[:-3], "NSE"
    return s, None


def fresh_price(doc, sym, now_utc, minutes=FRESH_MINUTES):
    """(price, fresh) for sym from a trader/prices.json doc (trader-alerts writes it)."""
    if not isinstance(doc, dict):
        return None, False
    p = _f((doc.get("prices") or {}).get(sym))
    if p is None or p <= 0:
        return None, False
    det = (doc.get("detail") or {}).get(sym) or {}
    t = nse.parse_utc(det.get("time")) or nse.parse_utc(det.get("fetched")) or nse.parse_utc(doc.get("as_of"))
    if t is None:
        return p, False
    age = (now_utc - t).total_seconds()
    return p, -60 <= age <= minutes * 60


def loss_at_stop(q, entry, stop, seg, ex, cfg):
    rt = nse.round_trip(q, entry, stop, seg, ex, cfg)
    return -rt["net"], rt


def size_trade(plan, cfg, budget=None, limit=None, price=None, cash=None, today=None, segment=None,
               lot=None, max_loss=None):
    """Pure function: one plan + your rules -> the sizing (a dict). qty may be 0 (refusal set).

    limit  the limit price (None = the plan's entry, as a limit order; "MARKET" in the config
           makes a market order sized at the higher of the plan's entry and a fresh price)
    price  a FRESH latest price
    cash   the cash in trader/portfolio.json, if there is one
    today  IST date (YYYY-MM-DD); a plan for another day is refused"""
    c = dict(DEFAULTS)
    c.update(cfg or {})
    if not isinstance(plan, dict):
        raise SizeError("the plan is not a JSON object")
    sym, ex = split_symbol(plan.get("symbol"))
    if not sym:
        raise SizeError("the plan has no symbol (run trader-exit)")
    ex = ex or str(plan.get("exchange") or c.get("exchange") or "NSE").upper()
    side = str(plan.get("side") or "buy").strip().lower()
    if side != "buy":
        raise SizeError("this pack sizes long (buy) day trades only; the plan says %r" % side)
    if today and plan.get("date") and str(plan["date"]) != today:
        raise SizeError("the plan is for %s and today is %s (IST): make a new plan with trader-exit"
                        % (plan["date"], today))
    seg = segment or plan.get("segment") or c.get("segment") or "equity_intraday"
    if seg not in nse.RATES:
        raise SizeError("segment is one of %s" % ", ".join(sorted(nse.RATES)))
    if seg in ("futures", "options") and not c.get("allow_fno"):
        raise SizeError("F&O is off: set \"allow_fno\": true in trader/config.json if you really mean it "
                        "(SEBI found 93% of individual F&O traders made losses in FY22 to FY24, PR No. 22/2024)")
    if seg == "options" and not c.get("allow_options"):
        raise SizeError("options are off: \"allow_options\": true in the config turns them on")
    entry_plan, stop, target = _f(plan.get("entry")), _f(plan.get("stop")), _f(plan.get("target"))
    for name, v in (("entry", entry_plan), ("stop", stop), ("target", target)):
        if v is None or v <= 0:
            raise SizeError("the plan needs a positive %s (run trader-exit)" % name)
    blocked = {str(b).upper() for b in (c.get("blocked") or [])}
    if sym in blocked:
        raise SizeError("%s is on your blocked list" % sym)
    lot_n = int(lot) if lot else nse.lot_size(sym, seg, c)
    if not lot_n:
        raise SizeError("no lot size known for %s %s: pass --lot-size or add it to \"lot_sizes\" in the config"
                        % (sym, seg))

    budget = float(budget if budget is not None else (c.get("budget") or 0))
    if budget <= 0:
        raise SizeError("no budget: pass --budget or set \"budget\" (in rupees) in trader/config.json")
    buf_pct = float(c.get("cash_buffer_pct") or 0)
    if not 0 <= buf_pct < 100:
        raise SizeError("cash_buffer_pct must be between 0 and 100")

    otype = str(c.get("order_type") or "LIMIT").upper()
    if limit is not None:
        ref, ref_from, otype = nse._r2(limit), "limit", "LIMIT"
    elif otype == "MARKET" and price is not None and nse._r2(price) > nse._r2(entry_plan):
        ref, ref_from = nse._r2(price), "price"
    else:
        ref, ref_from = nse._r2(entry_plan), "plan"
    stop, target = nse._r2(stop), nse._r2(target)
    if stop >= ref:
        raise SizeError("the stop %s is not below the entry %s; a long trade needs its stop underneath"
                        % (nse.num(stop), nse.num(ref)))
    if target <= ref:
        raise SizeError("the target %s is not above the entry %s: the move has already happened. Skip it "
                        "or make a new plan with trader-exit" % (nse.num(target), nse.num(ref)))
    risk = nse._r2(ref - stop)

    cash_buffer = nse._r2(budget * buf_pct / 100.0)
    available = budget - cash_buffer
    cash_note = "budget %s minus the %s cash buffer" % (nse.inr(budget), nse.inr(cash_buffer))
    if cash is not None and cash - cash_buffer < available - 0.005:
        available = cash - cash_buffer
        cash_note = "cash %s in trader/portfolio.json minus the %s buffer" % (nse.inr(cash), nse.inr(cash_buffer))
    available = max(nse._r2(available), 0.0)

    def down_to_lot(q):
        return int(q // lot_n) * lot_n

    limits = []
    ml = _f(max_loss) if max_loss is not None else _f(c.get("max_loss_per_trade_inr"))
    if ml:
        q = down_to_lot(int(ml // risk)) if risk > 0 else 0
        while q > 0 and loss_at_stop(q, ref, stop, seg, ex, c)[0] > ml + 1e-9:
            q -= lot_n
        limits.append({"name": "max loss", "inr": ml, "qty": max(q, 0),
                       "how": "%s max loss / (%s risk a share + charges)" % (nse.inr(ml), nse.num(risk))})
    cap_pct = _f(c.get("max_position_pct"))
    if cap_pct:
        cap = nse._r2(budget * cap_pct / 100.0)
        limits.append({"name": "position cap", "inr": cap, "qty": down_to_lot(int(cap // ref)),
                       "how": "%s%% of %s = %s / %s" % (("%g" % cap_pct), nse.inr(budget), nse.inr(cap), nse.num(ref))})
    mo = _f(c.get("max_order_inr"))
    if mo:
        limits.append({"name": "max order", "inr": mo, "qty": down_to_lot(int(mo // ref)),
                       "how": "%s / %s" % (nse.inr(mo), nse.num(ref))})
    q = down_to_lot(int(available // ref))
    while q > 0 and q * ref + nse.charges(q * ref, 0, seg, ex, c)["total"] > available + 1e-9:
        q -= lot_n
    limits.append({"name": "cash", "inr": available, "qty": max(q, 0),
                   "how": "%s = %s / %s (with the buy-side charges)" % (cash_note, nse.inr(available), nse.num(ref))})

    qty = max(0, min(l["qty"] for l in limits))
    bound = [l["name"] for l in limits if l["qty"] == qty][0]
    for l in limits:
        l["binds"] = l["name"] == bound
    cost = nse._r2(qty * ref)
    at_stop = nse.round_trip(qty, ref, stop, seg, ex, c) if qty else None
    at_target = nse.round_trip(qty, ref, target, seg, ex, c) if qty else None
    gross_rr = nse._r2((target - ref) / risk)
    net_rr = nse._r2(at_target["net"] / -at_stop["net"]) if qty and at_stop["net"] < 0 else None
    refusal = None
    mrr = _f(c.get("min_reward_risk"))
    use_rr = net_rr if c.get("rr_after_costs", True) else gross_rr
    if qty == 0:
        if bound == "max loss":
            one = loss_at_stop(lot_n, ref, stop, seg, ex, c)[0]
            refusal = ("one %s risks %s at the stop with charges (entry %s, stop %s), more than your %s max loss "
                       "per trade. No order. Skip this trade, or plan a closer stop with trader-exit."
                       % ("share" if lot_n == 1 else "lot of %d" % lot_n, nse.inr(one), nse.num(ref), nse.num(stop),
                          nse.inr(ml)))
        else:
            refusal = ("one %s of %s costs %s, more than your %s limit. No order."
                       % ("share" if lot_n == 1 else "lot", sym, nse.inr(ref * lot_n), bound))
    elif mrr and (use_rr is None or use_rr < mrr - 1e-9):
        refusal = ("reward:risk after charges is %s (net %s at the target vs net %s at the stop; %s before "
                   "charges), under your minimum %s, so trader-risk would block it. No order. Plan a further "
                   "target (2R) or skip it."
                   % ("%.2f" % use_rr if use_rr is not None else "n/a", nse.inr(at_target["net"]),
                      nse.inr(at_stop["net"]), "%.2f" % gross_rr, "%g" % mrr))
    elif cost < float(c.get("min_order_inr") or 0) - 0.005:
        refusal = "%d share%s of %s is %s, under your %s minimum order. No order." % (
            qty, "" if qty == 1 else "s", sym, nse.inr(cost), nse.inr(c["min_order_inr"]))
    return {
        "symbol": sym, "exchange": ex, "segment": seg, "product": nse.PRODUCT_OF[seg], "lot_size": lot_n,
        "side": "buy", "setup": plan.get("setup", ""), "date": plan.get("date"),
        "entry_time": plan.get("entry_time", ""), "entry_plan": nse._r2(entry_plan),
        "entry": ref, "entry_from": ref_from, "order_type": otype, "stop": stop, "target": target,
        "risk_per_share": risk, "reward_risk_gross": gross_rr, "reward_risk_net": net_rr,
        "stop_label": plan.get("stop_label", ""), "target_label": plan.get("target_label", ""),
        "budget": budget, "cash_buffer": cash_buffer, "cash_available": available,
        "max_loss_per_trade_inr": ml, "limits": limits, "qty": qty, "bound_by": bound, "cost": cost,
        "at_stop": at_stop, "at_target": at_target,
        "breakeven_points": nse.breakeven_move(qty, ref, seg, ex, c) if qty else None,
        "flat_by": plan.get("flat_by") or c.get("flat_by"), "tick_size": plan.get("tick_size"),
        "refusal": refusal,
    }


def build_order(s):
    """The one proposed order in this pack's broker-neutral shape (trader-broker maps it to
    Angel One SmartAPI fields, or simulates it on paper)."""
    if s["refusal"] or s["qty"] <= 0:
        return None
    o = {"symbol": s["symbol"], "exchange": s["exchange"], "segment": s["segment"], "product": s["product"],
         "side": "BUY", "qty": int(s["qty"]), "lot_size": s["lot_size"], "order_type": s["order_type"],
         "price": nse.num(s["entry"]) if s["order_type"] == "LIMIT" else None,
         "stop_loss": nse.num(s["stop"]), "target": nse.num(s["target"]), "validity": "DAY"}
    o = {k: v for k, v in o.items() if v is not None}
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "day trade")
    o["why"] = ("%s on %s: %d shares, bound by your %s (net loss %s at the stop, charges included)"
                % (setup, s["symbol"], s["qty"], s["bound_by"], nse.inr(-s["at_stop"]["net"])))
    o["estimate"] = {
        "turnover_entry": s["cost"],
        "charges_if_stopped": s["at_stop"]["charges"], "net_if_stopped": s["at_stop"]["net"],
        "charges_if_target": s["at_target"]["charges"], "net_if_target": s["at_target"]["net"],
        "breakeven_points": s["breakeven_points"], "rates_as_of": nse.RATES_AS_OF,
    }
    o["plan"] = {"entry": s["entry"], "stop": s["stop"], "target": s["target"], "risk_per_share": s["risk_per_share"],
                 "max_loss": -s["at_stop"]["net"], "setup": s["setup"], "entry_time": s["entry_time"],
                 "flat_by": s["flat_by"], "tick_size": s["tick_size"], "date": s["date"]}
    return o


def report(s, order, notes=()):
    lines = []
    setup = SETUP_WORDS.get(s["setup"], s["setup"] or "setup")
    lines.append("%s (%s) buy, %s, entry %s%s" % (s["symbol"], s["exchange"], setup, nse.num(s["entry_plan"]),
                                                  (" at " + s["entry_time"]) if s["entry_time"] else ""))
    lines.append("Stop %s%s. Target %s%s." % (nse.num(s["stop"]), (": " + s["stop_label"]) if s["stop_label"] else "",
                                             nse.num(s["target"]), (": " + s["target_label"]) if s["target_label"] else ""))
    for n in notes:
        lines.append(n)
    src = {"plan": "the plan's entry", "price": "the latest price, above the plan's entry",
           "limit": "your limit price"}[s["entry_from"]]
    lines.append("Sized at %s (%s), %s order, %s product (%s). Risk %s a share."
                 % (nse.num(s["entry"]), src, s["order_type"], s["product"], s["segment"].replace("_", " "),
                    nse.num(s["risk_per_share"])))
    lines.append("")
    lines.append("Limits (whole %s; the smallest one wins):" % ("shares" if s["lot_size"] == 1 else "lots of %d" % s["lot_size"]))
    for l in s["limits"]:
        lines.append("  %-13s %-70s %5d%s" % (l["name"], l["how"], l["qty"], "  <- binds" if l["binds"] else ""))
    lines.append("")
    if order is None:
        lines.append("No order: " + s["refusal"])
        lines.append(nse.DISCLAIMER)
        return "\n".join(lines)
    st, tg = s["at_stop"], s["at_target"]
    lines.append("Size: %d shares of %s = %s at %s." % (s["qty"], s["symbol"], nse.inr(s["cost"]), nse.num(s["entry"])))
    lines.append("If the stop fills at %s: %s gross, %s charges, %s net." % (
        nse.num(s["stop"]), nse.inr(st["gross"]), nse.inr(st["charges"]), nse.inr(st["net"])))
    lines.append("If the target fills at %s: %s gross, %s charges, %s net." % (
        nse.num(s["target"]), nse.inr(tg["gross"]), nse.inr(tg["charges"]), nse.inr(tg["net"])))
    d = st["detail"]
    lines.append("  charges at the stop: brokerage %s, STT %s, exchange %s, SEBI %s, GST %s, stamp %s"
                 % tuple(nse.inr(d[k]) for k in ("brokerage", "stt", "txn", "sebi", "gst", "stamp")))
    lines.append("Reward:risk %.2f before charges, %s after. Break-even: the price must rise %s just to pay the charges."
                 % (s["reward_risk_gross"], "%.2f" % s["reward_risk_net"] if s["reward_risk_net"] is not None else "n/a",
                    nse.num(s["breakeven_points"])))
    lines.append("A stop is an order, not a promise: a gap or a circuit freeze can fill it below %s." % nse.num(s["stop"]))
    lines.append("")
    lines.append("Proposed order (nothing has been placed):")
    how = "limit %s" % order["price"] if order["order_type"] == "LIMIT" else "market"
    lines.append("  BUY %d %s on %s, %s, %s, day, stop-loss %s, target %s"
                 % (order["qty"], order["symbol"], order["exchange"], how, order["product"], order["stop_loss"],
                    order["target"]))
    if s["flat_by"]:
        lines.append("Flat by %s IST: anything still open then gets closed (trader-alerts rings, trader-broker "
                     "flatten), before the broker's own MIS square-off." % s["flat_by"])
    lines.append("")
    lines.append("Next: trader-risk checks it, then trader-broker shows the ticket and asks you yes or no.")
    lines.append(nse.DISCLAIMER)
    return "\n".join(lines)


def write_orders(path, orders, cfg, source="", now_utc=None):
    doc = {"created_by": "trader-budget", "created_at": nse.iso_z(now_utc or nse.utc_now()), "status": "proposed",
           "currency": "INR", "mode": str(cfg.get("mode") or ("paper" if cfg.get("paper", True) else "live")),
           "note": ("Proposals only. Nothing is placed until trader-risk passes each order and you type yes "
                    "for it in the chat."),
           "source": source, "orders": orders}
    nse.write_json(path, doc)


def run(a):
    cfg = load_config(a.config)
    now = nse.parse_now(a.now)
    today = nse.to_ist(now).date().isoformat()
    plan = nse.read_json(a.plan, "plan (run /trader-exit first)")
    pdoc = nse.read_json(a.prices, "prices", required=False) if a.prices else None
    sym, _ = split_symbol(plan.get("symbol"))
    price, fresh = fresh_price(pdoc, sym, now) if pdoc else (None, False)
    notes = []
    if price is not None and not fresh:
        notes.append("The price in %s is older than %d minutes: not used." % (a.prices, FRESH_MINUTES))
        price = None
    pf = nse.read_json(a.portfolio, "portfolio", required=False) if a.portfolio else None
    cash = _f(pf.get("cash")) if isinstance(pf, dict) else None
    s = size_trade(plan, cfg, a.budget, a.limit, price, cash, None if a.any_day else today, a.segment, a.lot_size,
                   a.max_loss)
    order = build_order(s)
    if a.write and order:
        write_orders(a.out, [order], cfg, "%s (%s %s %s)" % (a.plan, s["symbol"], s["setup"], s["date"]), now)
    if a.json:
        print(json.dumps({"sizing": s, "order": order}, indent=2, ensure_ascii=False))
    else:
        print(report(s, order, notes))
        if a.write and order:
            print("Wrote %s." % a.out)
    return 0 if order else 1


def _utf8_out():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv=None):
    _utf8_out()
    ap = argparse.ArgumentParser(description="Budget Manager (trader-budget, NSE/BSE): size one day trade to your "
                                             "budget and max loss, charges included. Educational only.")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--prices", default="trader/prices.json")
    ap.add_argument("--portfolio", default="trader/portfolio.json")
    ap.add_argument("--budget", type=float, help="rupees (default: config budget)")
    ap.add_argument("--max-loss", type=float, help="rupees per trade (default: config max_loss_per_trade_inr)")
    ap.add_argument("--limit", type=float, nargs="?", const=None, help="limit price (default: the plan's entry)")
    ap.add_argument("--segment", choices=sorted(nse.RATES), help="default: config segment, equity_intraday")
    ap.add_argument("--lot-size", type=int, help="F&O lot size (default: config lot_sizes, then the bundled table)")
    ap.add_argument("--any-day", action="store_true", help="size a plan for another day (a replay)")
    ap.add_argument("--now", help='pretend it is this IST time, e.g. "2026-11-02 10:00"')
    ap.add_argument("--write", action="store_true", help="write the order to --out")
    ap.add_argument("--out", default="trader/orders.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        return run(a)
    except (SizeError, nse.NSEError) as e:
        print("size.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
