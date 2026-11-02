#!/usr/bin/env python3
"""Order tickets, paper trading and live orders for trader-broker (NSE/BSE port).
Standard library only.

Two modes, chosen in trader/config.json:
  "mode": "paper"   (the default) orders are simulated: a LIMIT entry fills at its price,
                    the stop and the target close it when trader/prices.json shows them hit.
  "mode": "live"    REAL MONEY through Angel One SmartAPI (angel.py). UNVERIFIED LIVE: built
                    from the public docs and tested only against mocked HTTP answers.

Nothing is ever sent without your yes for THAT order:
  show      the full ticket: symbol, exchange, side, quantity (lots for F&O), price and
            order type, product (MIS / CNC / NRML), stop-loss, target, validity, the
            estimated charges and the net loss at the stop, PAPER or LIVE. An order is
            READY only if trader-risk passed THIS exact order today (fingerprint), the
            kill switch is off, and nobody has decided on it yet.
  approve   needs --reply with your words. It refuses "ok", "sure", "yes to all", a yes with
            a condition, a yes that names another stock or number, and (live) a yes that
            does not name the symbol: type "yes RELIANCE". Then, paper: it fills on paper.
            Live: it logs in (PIN + TOTP), places the LIMIT entry, waits for the fill and
            places the protective SELL stop-loss shown on the ticket, then logs out.
  decline   records a no.
  protect   (live) places the protective stop-loss for an entry that filled later.
  status    (live) the order book; (paper) the open paper positions.
  cancel    (live) cancels an open order by id, again only with your yes.
  mark      (paper) closes paper positions whose stop or target trader/prices.json shows hit.
  flatten   writes a SELL ticket for an open position (it goes through trader-risk and your
            yes like any order); live, approving it also cancels that symbol's open stop-loss.
  pnl       today's realized net P&L (paper book, or Angel One's trade book), written to
            trader/state/pnl.json; trips the kill switch at max_daily_loss_inr.
  kill      turns the kill switch on for the rest of today (no new entries anywhere).
  log       today's decisions.

    python3 ticket.py show
    python3 ticket.py approve --index 1 --reply "yes"            # paper
    python3 ticket.py approve --index 1 --reply "yes RELIANCE"   # live: name the symbol
    python3 ticket.py pnl
    python3 ticket.py kill --reason "done for today"

Credentials (live): ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET in the
environment, or the file named by "angel_credentials_file" (trader/secrets/angel.json).
Never in the chat, never in a repo, never printed. Everything else is written to
trader/state/ (broker.json append only). Dates are IST; --now pins the clock.
Educational only, not investment advice. Not a SEBI-registered adviser.
"""

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nse  # noqa: E402
import angel  # noqa: E402

YES_WORDS = ("yes", "y", "haan", "ha")
BATCH_WORDS = {"all", "every", "everything", "rest", "remaining", "them", "both", "batch", "each"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later", "hold",
               "unless", "if", "nahi", "mat"}
DEFAULTS = {"mode": "paper", "broker": "angelone", "angel_credentials_file": "trader/secrets/angel.json",
            "angel_public_ip": "", "max_orders_per_second": 1, "sl_limit_buffer_pct": 0.5, "fill_wait_seconds": 20,
            "max_daily_loss_inr": 1500, "brokerage_per_order": 20, "brokerage_pct": 0.03}


class TicketError(Exception):
    pass


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_cfg(path):
    c = dict(DEFAULTS)
    doc = nse.read_json(path, "config", required=False)
    if doc:
        c.update(doc)
    m = str((doc or {}).get("mode") or "").lower()
    if m not in ("paper", "live"):
        m = "paper" if (doc or {}).get("paper", True) else "live"
    c["mode"] = m   # "mode" wins over the older "paper": true/false
    return c


# ---------------------------------------------------------------- the order in words

def charges_of(order, cfg, exit_px):
    seg = order.get("segment") or "equity_intraday"
    ex = order.get("exchange") or "NSE"
    entry = _f(order.get("price")) or _f((order.get("plan") or {}).get("entry"))
    if not entry or not exit_px:
        return None
    return nse.round_trip(int(order["qty"]), entry, float(exit_px), seg, ex, cfg)


def plain(order):
    """BUY 30 RELIANCE (NSE), LIMIT 1234.50, MIS, DAY / stop-loss 1223.10 / target 1257.30"""
    side = str(order.get("side", "")).upper()
    lot = int(order.get("lot_size") or 1)
    q = int(order.get("qty") or 0)
    qty = "%d" % q if lot == 1 else "%d (%d lot%s of %d)" % (q, q // lot, "" if q // lot == 1 else "s", lot)
    how = "LIMIT %s" % order["price"] if str(order.get("order_type")).upper() == "LIMIT" else str(order.get("order_type"))
    parts = ["%s %s %s (%s), %s, %s, %s" % (side, qty, order.get("symbol"), order.get("exchange"), how,
                                            order.get("product"), order.get("validity", "DAY"))]
    if order.get("stop_loss") and side == "BUY":
        parts.append("stop-loss %s" % order["stop_loss"])
    if order.get("target") and side == "BUY":
        parts.append("target %s" % order["target"])
    return " / ".join(parts)


def ticket_lines(order, cfg):
    """The full ticket, every number the user is saying yes to."""
    mode = cfg["mode"]
    side = str(order.get("side", "")).upper()
    entry = _f(order.get("price")) or _f((order.get("plan") or {}).get("entry"))
    q = int(order.get("qty") or 0)
    seg = order.get("segment") or "equity_intraday"
    ex = order.get("exchange") or "NSE"
    lines = ["  Symbol        %s on %s (%s)" % (order.get("symbol"), ex, seg.replace("_", " ")),
             "  Side          %s" % side,
             "  Quantity      %s" % (q if int(order.get("lot_size") or 1) == 1 else
                                     "%d = %d lots of %d" % (q, q // int(order["lot_size"]), int(order["lot_size"]))),
             "  Price / type  %s" % ("LIMIT %s" % order["price"] if str(order.get("order_type")).upper() == "LIMIT"
                                     else str(order.get("order_type"))),
             "  Product       %s%s" % (order.get("product"), {"MIS": " (intraday, the broker squares it off ~15:15-15:25)",
                                                              "CNC": " (delivery)", "NRML": " (F&O carry forward)"}
                                       .get(str(order.get("product")).upper(), "")),
             "  Validity      %s" % order.get("validity", "DAY")]
    if side == "BUY":
        lines.append("  Stop-loss     %s%s" % (order.get("stop_loss") or "NONE",
                                              " (a SELL SL order placed right after the entry fills)" if mode == "live"
                                              else " (paper: closes the position when the price touches it)"))
        lines.append("  Target        %s%s" % (order.get("target") or "none",
                                              " (NOT sent to the exchange: trader-alerts rings, then you approve a sell)"
                                              if mode == "live" else ""))
    if entry and q:
        buy_ch = nse.charges(q * entry, 0, seg, ex, cfg)
        lines.append("  Cost          %s for the shares + about %s charges on the buy" % (nse.inr(q * entry),
                                                                                       nse.inr(buy_ch["total"])))
        if side == "BUY" and order.get("stop_loss"):
            st = charges_of(order, cfg, order["stop_loss"])
            lines.append("  At the stop   %s net (%s charges incl. STT, exchange, SEBI, GST, stamp)" % (
                nse.inr(st["net"]), nse.inr(st["charges"])))
        if side == "BUY" and order.get("target"):
            tg = charges_of(order, cfg, order["target"])
            lines.append("  At the target %s net (%s charges)" % (nse.inr(tg["net"]), nse.inr(tg["charges"])))
    lines.append("  Account       %s" % ("LIVE, REAL MONEY, Angel One" if mode == "live" else "PAPER (simulated)"))
    lines.append("  Fingerprint   %s" % nse.fingerprint(order))
    return lines


def amount_numbers(order, cfg):
    nums = [float(order.get("qty") or 0)]
    for k in ("price", "stop_loss", "target", "trigger_price"):
        v = _f(order.get(k))
        if v is not None:
            nums.append(v)
    if int(order.get("lot_size") or 1) > 1:
        nums.append(float(int(order["qty"]) // int(order["lot_size"])))
    st = charges_of(order, cfg, order.get("stop_loss")) if order.get("stop_loss") else None
    if st:
        nums.append(abs(st["net"]))
    return nums


def parse_yes(reply, order, batch_symbols=(), need_symbol=False, cfg=None):
    """Is this reply an explicit yes for THIS one order? Returns (ok, why)."""
    raw = (reply or "").strip()
    if not raw:
        return False, "the reply is empty"
    if "?" in raw:
        return False, "the reply is a question, not a yes"
    words = re.findall(r"[a-z']+", raw.lower())
    if not words or words[0] not in YES_WORDS:
        return False, "only a reply that starts with \"yes\" counts (not ok, sure, go, do it)"
    if BATCH_WORDS & set(words):
        return False, "a yes covers one order at a time, not a batch"
    if DOUBT_WORDS & set(words[1:]):
        return False, "the reply has a condition or a doubt in it; ask again"
    sym = str(order.get("symbol", "")).upper()
    tokens = set(re.findall(r"[A-Z][A-Z0-9&\-]{1,29}", raw.upper())) - {"YES", "HAAN", "HA"}
    others = {s.upper() for s in batch_symbols} - {sym}
    named = tokens & others
    if named:
        return False, "the reply names %s, but this order is for %s" % (", ".join(sorted(named)), sym)
    if need_symbol and sym not in tokens:
        return False, "a LIVE order needs the symbol in your yes: type \"yes %s\"" % sym
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", raw)]
    if nums:
        want = amount_numbers(order, cfg or {})
        if not any(abs(n - w) < 0.005 for n in nums for w in want):
            return False, "the reply says %s, but this order is %s" % (", ".join("%g" % n for n in nums), plain(order))
    return True, "explicit yes for %s" % plain(order)


# ---------------------------------------------------------------- state

class Paths(object):
    def __init__(self, a):
        self.orders = a.orders
        self.config = a.config
        self.risk = a.risk
        st = a.state_dir
        self.broker = os.path.join(st, "broker.json")
        self.paper = os.path.join(st, "paper.json")
        self.pnl = os.path.join(st, "pnl.json")
        self.kill = os.path.join(st, "killswitch.json")
        self.scrips = os.path.join(st, "angel_scrips.json")
        self.prices = a.prices


def load_state(path):
    return nse.read_json(path, "broker state", required=False) or {"orders": []}


def log(paths, rec):
    st = load_state(paths.broker)
    st.setdefault("orders", []).append(rec)
    nse.write_json(paths.broker, st)


def latest(state, fp, today):
    found = None
    for rec in state.get("orders", []):
        if rec.get("fingerprint") == fp and str(rec.get("date")) == today:
            found = rec
    return found


def risk_verdict(risk, fp, today):
    if not risk:
        return None, "trader-risk has not checked these orders (run check.py)"
    if risk.get("date") != today:
        return None, "the risk check is from %s, not today; run check.py again" % risk.get("date")
    for r in risk.get("results", []):
        if r.get("fingerprint") == fp:
            return r, None
    return None, "this exact order was not in the last risk check (it changed or is new); run check.py again"


def status_of(order, risk, state, today, ks):
    """(ready, label, risk_result)"""
    fp = nse.fingerprint(order)
    rv, why = risk_verdict(risk, fp, today)
    if rv is None:
        return False, "NOT READY: " + why, None
    if rv.get("verdict") != "PASS":
        return False, "BLOCKED by trader-risk: " + "; ".join(rv.get("reasons", [])), rv
    if ks[0] and rv.get("kind", "entry") == "entry":
        return False, "BLOCKED by the kill switch: " + ks[1], rv
    rec = latest(state, fp, today)
    if rec:
        return False, "DONE: %s at %s" % (rec.get("status"), rec.get("at")), rv
    return True, "READY: trader-risk PASS, waiting for your yes", rv


def today_of(a):
    now = nse.parse_now(a.now)
    return now, nse.to_ist(now).date().isoformat()


def load_orders(paths):
    od = nse.read_json(paths.orders, "orders (run /trader-budget first)")
    orders = od.get("orders", []) if isinstance(od, dict) else od
    if not orders:
        raise TicketError("%s has no orders" % paths.orders)
    return orders


def pick(orders, index):
    if index is None:
        if len(orders) == 1:
            return 1, orders[0]
        raise TicketError("there are %d orders: pass --index N" % len(orders))
    if not 1 <= index <= len(orders):
        raise TicketError("--index %d is not between 1 and %d" % (index, len(orders)))
    return index, orders[index - 1]


def ks_now(paths, cfg, today):
    pnl = nse.read_json(paths.pnl, "pnl", required=False) or {}
    realized = _f(pnl.get("realized_net")) if pnl.get("date") == today else None
    return nse.killswitch(paths.kill, today, _f(cfg.get("max_daily_loss_inr")), realized)


# ---------------------------------------------------------------- paper engine

def paper_book(paths, today):
    pb = nse.read_json(paths.paper, "paper book", required=False) or {"positions": {}, "closed": []}
    pb.setdefault("positions", {})
    pb.setdefault("closed", [])
    return pb


def write_pnl(paths, today, mode, realized_net, gross=None, source=""):
    nse.write_json(paths.pnl, {"date": today, "mode": mode, "realized_net": round(realized_net, 2),
                               "realized_gross": None if gross is None else round(gross, 2), "source": source,
                               "as_of": nse.iso_z(nse.utc_now())})


def paper_realized(pb, today):
    rows = [c for c in pb["closed"] if c.get("date") == today]
    return sum(c["net"] for c in rows), sum(c["gross"] for c in rows)


def paper_close(pb, sym, px, why, today, cfg, qty=None):
    pos = pb["positions"].get(sym)
    if not pos:
        raise TicketError("no open paper position in %s" % sym)
    q = int(qty or pos["qty"])
    rt = nse.round_trip(q, pos["avg"], px, pos.get("segment", "equity_intraday"), pos.get("exchange", "NSE"), cfg)
    pb["closed"].append({"date": today, "symbol": sym, "qty": q, "entry": pos["avg"], "exit": float(px),
                         "gross": rt["gross"], "charges": rt["charges"], "net": rt["net"], "why": why})
    pos["qty"] -= q
    if pos["qty"] <= 0:
        del pb["positions"][sym]
    return rt


# ---------------------------------------------------------------- live

def live_session(cfg, transport=None):
    if str(cfg.get("broker", "angelone")).lower() in ("kite", "zerodha"):
        angel.KiteConnect()
    creds = angel.load_credentials(cfg.get("angel_credentials_file"))
    gap = 1.0 / max(0.1, min(float(cfg.get("max_orders_per_second") or 1), 10.0))
    return angel.AngelOne(creds, cfg.get("angel_public_ip") or "", transport=transport, min_gap=gap), creds


def instrument(paths, order, today, download=None):
    rows = angel.scrip_rows(paths.scrips, today, download)
    inst = angel.find_instrument(rows, order["symbol"], order["exchange"], order.get("segment", "equity_intraday"))
    if not inst:
        raise TicketError("%s %s is not in Angel One's instrument master" % (order["exchange"], order["symbol"]))
    lot = int(float(inst.get("lotsize") or 1))
    if int(order["qty"]) % lot:
        raise TicketError("Angel One's lot size for %s is %d; the order's qty %d is not whole lots"
                          % (inst["symbol"], lot, int(order["qty"])))
    tick = angel.tick_of(inst)
    for k in ("price", "stop_loss", "trigger_price"):
        v = _f(order.get(k))
        if v is not None and tick and not nse.on_tick(v, tick):
            raise TicketError("%s %s is not on %s's tick of %s: re-plan with --tick %s"
                              % (k, order[k], inst["symbol"], ("%g" % tick), ("%g" % tick)))
    return inst, tick


# ---------------------------------------------------------------- commands

def cmd_show(a, paths, cfg):
    now, today = today_of(a)
    orders = load_orders(paths)
    risk = nse.read_json(paths.risk, "risk check", required=False)
    state = load_state(paths.broker)
    ks = ks_now(paths, cfg, today)
    out, any_ready = [], False
    idxs = [a.index] if a.index else range(1, len(orders) + 1)
    js = []
    for i in idxs:
        _, o = pick(orders, i)
        ready, label, rv = status_of(o, risk, state, today, ks)
        any_ready = any_ready or ready
        if a.json:
            js.append({"index": i, "ready": ready, "status": label, "plain": plain(o), "mode": cfg["mode"],
                       "fingerprint": nse.fingerprint(o), "ticket": [l.strip() for l in ticket_lines(o, cfg)]})
            continue
        out.append("ORDER %d of %d, %s" % (i, len(orders), "LIVE, REAL MONEY (Angel One)" if cfg["mode"] == "live"
                                          else "PAPER"))
        out += ticket_lines(o, cfg)
        if o.get("why"):
            out.append("  why: " + o["why"])
        out.append("  " + label)
        for w in (rv or {}).get("warnings", []):
            out.append("  note: " + w)
        if ready:
            if cfg["mode"] == "live":
                out.append("  Type \"yes %s\" to send this ONE order to Angel One with real money, or \"no\"." % o["symbol"])
                out.append("  UNVERIFIED LIVE: this adapter has only been tested against mocked answers.")
            else:
                out.append("  Reply \"yes\" to paper-trade this one order, or \"no\" to skip it.")
        out.append("")
    if a.json:
        print(json.dumps(js, indent=2, ensure_ascii=False))
    else:
        print("\n".join(out).rstrip())
        print(nse.DISCLAIMER)
    return 0 if any_ready else 1


def cmd_approve(a, paths, cfg, transport=None, download=None, sleep=time.sleep):
    now, today = today_of(a)
    orders = load_orders(paths)
    idx, o = pick(orders, a.index)
    risk = nse.read_json(paths.risk, "risk check", required=False)
    state = load_state(paths.broker)
    ks = ks_now(paths, cfg, today)
    ready, label, rv = status_of(o, risk, state, today, ks)
    if not ready:
        raise TicketError("order %d is not ready: %s" % (idx, label))
    live = cfg["mode"] == "live"
    ok, why = parse_yes(a.reply, o, [x.get("symbol") for x in orders], need_symbol=live, cfg=cfg)
    fp = nse.fingerprint(o)
    kind = (rv or {}).get("kind") or ("entry" if str(o["side"]).upper() == "BUY" else "exit")
    base = {"fingerprint": fp, "date": today, "at": nse.iso_z(now), "symbol": o["symbol"], "side": o["side"],
            "qty": int(o["qty"]), "kind": kind, "mode": cfg["mode"], "reply": a.reply,
            "max_loss": (rv or {}).get("max_loss")}
    if not ok:
        print("Not approved: %s. Nothing was sent." % why)
        return 1
    if not live:
        pb = paper_book(paths, today)
        px = _f(o.get("price")) or _f((o.get("plan") or {}).get("entry"))
        if str(o["side"]).upper() == "BUY":
            pos = pb["positions"].get(o["symbol"])
            if pos:
                tot = pos["qty"] + int(o["qty"])
                pos["avg"] = round((pos["avg"] * pos["qty"] + px * int(o["qty"])) / tot, 4)
                pos["qty"] = tot
            else:
                pb["positions"][o["symbol"]] = {"qty": int(o["qty"]), "avg": px, "stop": _f(o.get("stop_loss")),
                                                "target": _f(o.get("target")), "segment": o.get("segment"),
                                                "exchange": o.get("exchange"), "opened": today}
            msg = "PAPER: bought %d %s at %s (a limit order is assumed filled at its price)." % (int(o["qty"]), o["symbol"],
                                                                                                nse.num(px))
        else:
            rt = paper_close(pb, o["symbol"], px, "sell", today, cfg, int(o["qty"]))
            msg = "PAPER: sold %d %s at %s: %s net after %s charges." % (int(o["qty"]), o["symbol"], nse.num(px),
                                                                        nse.inr(rt["net"]), nse.inr(rt["charges"]))
        nse.write_json(paths.paper, pb)
        net, gross = paper_realized(pb, today)
        write_pnl(paths, today, "paper", net, gross, "paper book")
        log(paths, dict(base, status="filled", price=px, broker_id="paper-%s" % fp[:8]))
        print(msg)
        print("Recorded in %s. %s" % (paths.broker, nse.DISCLAIMER))
        return 0
    # ---- LIVE
    sess, creds = live_session(cfg, transport)
    tag = "%s%s" % (angel.TAG, fp[:8])
    inst, tick = instrument(paths, o, today, download)
    rec = dict(base, status="sending", tradingsymbol=inst["symbol"])
    try:
        with sess:
            if kind == "exit":
                for r in sess.order_book():
                    if (r.get("tradingsymbol") == inst["symbol"] and str(r.get("transactiontype")).upper() == "SELL"
                            and str(r.get("ordertag") or "").startswith(angel.TAG)
                            and str(r.get("orderstatus") or r.get("status")).lower() in ("trigger pending", "open")):
                        sess.cancel(r["orderid"], r.get("variety") or "STOPLOSS")
                        print("Cancelled the open stop-loss %s for %s first." % (r["orderid"], inst["symbol"]))
            placed = sess.place(angel.entry_params(o, inst, tag))
            rec.update(status="placed", broker_id=placed["orderid"])
            log(paths, rec)
            print("LIVE: Angel One accepted %s, order id %s." % (plain(o), placed["orderid"]))
            if kind == "entry" and o.get("stop_loss"):
                waited, st = 0.0, None
                while waited <= float(cfg.get("fill_wait_seconds") or 0):
                    st, row = angel.order_status(sess.order_book(), placed["orderid"])
                    if st in ("complete", "rejected", "cancelled"):
                        break
                    sleep(2)
                    waited += 2
                if st == "complete":
                    slp = sess.place(angel.stop_params(o, inst, tag, cfg.get("sl_limit_buffer_pct", 0.5), tick))
                    log(paths, dict(base, status="placed", kind="stop", side="SELL", broker_id=slp["orderid"],
                                    parent=placed["orderid"], fingerprint=fp + "-sl"))
                    print("LIVE: entry filled; protective SELL stop-loss at %s placed, order id %s."
                          % (o["stop_loss"], slp["orderid"]))
                elif st in ("rejected", "cancelled"):
                    print("LIVE: the entry was %s by Angel One: %s. No stop-loss needed." % (
                        st, (row or {}).get("text") or "no reason given"))
                else:
                    print("LIVE: the entry is not filled yet (%s). When it fills, run: ticket.py protect --index %d. "
                          "Until then there is NO stop-loss on the exchange." % (st or "unknown", idx))
    except angel.BrokerError as e:
        if rec.get("status") == "sending":
            log(paths, dict(rec, status="failed", error=angel.scrub(e, creds)))
        raise TicketError(angel.scrub(e, creds))
    print("UNVERIFIED LIVE adapter: check the order in the Angel One app now. " + nse.DISCLAIMER)
    return 0


def cmd_protect(a, paths, cfg, transport=None, download=None):
    now, today = today_of(a)
    if cfg["mode"] != "live":
        raise TicketError("protect is for live mode; paper positions carry their stop already")
    _, o = pick(load_orders(paths), a.index)
    fp = nse.fingerprint(o)
    state = load_state(paths.broker)
    parent = latest(state, fp, today)
    if not parent or parent.get("status") != "placed":
        raise TicketError("this order was not placed live today")
    if latest(state, fp + "-sl", today):
        raise TicketError("its stop-loss is already placed")
    sess, creds = live_session(cfg, transport)
    inst, tick = instrument(paths, o, today, download)
    try:
        with sess:
            st, _ = angel.order_status(sess.order_book(), parent["broker_id"])
            if st != "complete":
                raise TicketError("the entry %s is %s, not filled: nothing to protect yet" % (parent["broker_id"], st))
            slp = sess.place(angel.stop_params(o, inst, "%s%s" % (angel.TAG, fp[:8]),
                                               cfg.get("sl_limit_buffer_pct", 0.5), tick))
    except angel.BrokerError as e:
        raise TicketError(angel.scrub(e, creds))
    log(paths, {"fingerprint": fp + "-sl", "date": today, "at": nse.iso_z(now), "symbol": o["symbol"], "side": "SELL",
                "qty": int(o["qty"]), "kind": "stop", "mode": "live", "status": "placed", "broker_id": slp["orderid"],
                "parent": parent["broker_id"]})
    print("LIVE: protective SELL stop-loss at %s placed, order id %s." % (o["stop_loss"], slp["orderid"]))
    return 0


def cmd_decline(a, paths, cfg):
    now, today = today_of(a)
    idx, o = pick(load_orders(paths), a.index)
    log(paths, {"fingerprint": nse.fingerprint(o), "date": today, "at": nse.iso_z(now), "symbol": o["symbol"],
                "side": o["side"], "qty": int(o["qty"]), "status": "declined", "mode": cfg["mode"], "reply": a.reply or ""})
    print("Declined order %d (%s). Nothing was sent." % (idx, plain(o)))
    return 0


def cmd_status(a, paths, cfg, transport=None):
    now, today = today_of(a)
    if cfg["mode"] != "live":
        pb = paper_book(paths, today)
        if not pb["positions"]:
            print("PAPER: no open positions.")
        for s, p in sorted(pb["positions"].items()):
            print("PAPER: %s %d @ %s, stop %s, target %s" % (s, p["qty"], nse.num(p["avg"]),
                                                             p.get("stop"), p.get("target")))
        return 0
    sess, creds = live_session(cfg, transport)
    try:
        with sess:
            book = sess.order_book()
    except angel.BrokerError as e:
        raise TicketError(angel.scrub(e, creds))
    for r in book:
        print("%s  %-18s %-4s %5s @ %-8s %-16s %s" % (r.get("orderid"), r.get("tradingsymbol"), r.get("transactiontype"),
                                                     r.get("quantity"), r.get("price"), r.get("orderstatus") or r.get("status"),
                                                     r.get("text") or ""))
    if not book:
        print("LIVE: the order book is empty today.")
    return 0


def cmd_cancel(a, paths, cfg, transport=None):
    now, today = today_of(a)
    if cfg["mode"] != "live":
        raise TicketError("cancel is for live mode")
    raw = (a.reply or "").strip().lower()
    if not raw.startswith("yes") or "?" in raw or str(a.order_id) not in raw:
        print("Not cancelled: type \"yes cancel %s\" to cancel that order." % a.order_id)
        return 1
    sess, creds = live_session(cfg, transport)
    try:
        with sess:
            sess.cancel(a.order_id, a.variety)
    except angel.BrokerError as e:
        raise TicketError(angel.scrub(e, creds))
    log(paths, {"fingerprint": "cancel-%s" % a.order_id, "date": today, "at": nse.iso_z(now), "status": "cancelled",
                "broker_id": a.order_id, "mode": "live", "reply": a.reply})
    print("LIVE: cancel request for %s accepted." % a.order_id)
    return 0


def cmd_mark(a, paths, cfg):
    now, today = today_of(a)
    if cfg["mode"] != "paper":
        raise TicketError("mark is for paper mode; live stops sit on the exchange")
    pdoc = nse.read_json(paths.prices, "prices (run trader-alerts quote)")
    prices = {str(k).upper(): float(v) for k, v in (pdoc.get("prices") or {}).items() if _f(v)}
    pb = paper_book(paths, today)
    hit = 0
    for sym, p in list(pb["positions"].items()):
        px = prices.get(sym)
        if px is None:
            continue
        if p.get("stop") and px <= p["stop"]:
            rt = paper_close(pb, sym, p["stop"], "stop", today, cfg)
            print("PAPER: %s stop %s hit (last %s): %s net." % (sym, nse.num(p["stop"]), nse.num(px), nse.inr(rt["net"])))
            hit += 1
        elif p.get("target") and px >= p["target"]:
            rt = paper_close(pb, sym, p["target"], "target", today, cfg)
            print("PAPER: %s target %s hit (last %s): %s net." % (sym, nse.num(p["target"]), nse.num(px), nse.inr(rt["net"])))
            hit += 1
    nse.write_json(paths.paper, pb)
    net, gross = paper_realized(pb, today)
    write_pnl(paths, today, "paper", net, gross, "paper book")
    ks = nse.killswitch(paths.kill, today, _f(cfg.get("max_daily_loss_inr")), net)
    print("PAPER: realized today %s net.%s" % (nse.inr(net), (" KILL SWITCH ON: " + ks[1]) if ks[0] else ""))
    return 0 if hit else 1


def cmd_flatten(a, paths, cfg):
    now, today = today_of(a)
    if cfg["mode"] == "paper":
        pos = paper_book(paths, today)["positions"].get(a.symbol.upper())
        qty = a.qty or (pos or {}).get("qty")
        seg, ex = (pos or {}).get("segment") or "equity_intraday", (pos or {}).get("exchange") or "NSE"
    else:
        qty, seg, ex = a.qty, a.segment, a.exchange
    if not qty:
        raise TicketError("how many to sell? pass --qty (no open paper position in %s)" % a.symbol.upper())
    if not a.price:
        raise TicketError("flatten needs --price (a LIMIT; live mode allows no MARKET orders)")
    order = {"symbol": a.symbol.upper(), "exchange": ex, "segment": seg, "product": nse.PRODUCT_OF.get(seg, "MIS"),
             "side": "SELL", "qty": int(qty), "lot_size": nse.lot_size(a.symbol, seg, cfg) or 1, "order_type": "LIMIT",
             "price": nse.num(a.price), "validity": "DAY", "why": "flat by %s: close the position" % (cfg.get("flat_by") or "15:10")}
    nse.write_json(paths.orders, {"created_by": "trader-broker", "created_at": nse.iso_z(now), "status": "proposed",
                                  "currency": "INR", "mode": cfg["mode"], "orders": [order],
                                  "note": "A sell to flatten. trader-risk checks it, then your yes."})
    print("Wrote a SELL ticket to %s: %s. Next: check.py, then ticket.py show." % (paths.orders, plain(order)))
    return 0


def cmd_pnl(a, paths, cfg, transport=None):
    now, today = today_of(a)
    if cfg["mode"] == "paper":
        net, gross = paper_realized(paper_book(paths, today), today)
        src = "paper book"
    else:
        sess, creds = live_session(cfg, transport)
        try:
            with sess:
                trades = sess.trade_book()
        except angel.BrokerError as e:
            raise TicketError(angel.scrub(e, creds))
        gross, net = angel.realized_from_trades(
            trades, lambda bv, sv, ex: nse.charges(bv, sv, "equity_intraday", ex if ex in ("NSE", "BSE") else "NSE", cfg)["total"])
        src = "Angel One trade book (charges estimated)"
    write_pnl(paths, today, cfg["mode"], net, gross, src)
    ks = nse.killswitch(paths.kill, today, _f(cfg.get("max_daily_loss_inr")), net)
    print("%s realized today: %s gross, %s net (%s)." % (cfg["mode"].upper(), nse.inr(gross), nse.inr(net), src))
    print("Kill switch: %s" % ("ON: " + ks[1] if ks[0] else "off (max daily loss %s)" % nse.inr(cfg.get("max_daily_loss_inr") or 0)))
    return 0


def cmd_kill(a, paths, cfg):
    now, today = today_of(a)
    nse.trip(paths.kill, today, a.reason or "you turned the kill switch on")
    print("Kill switch ON for %s: trader-risk blocks every new entry and trader-broker sends none until tomorrow. "
          "Exits (selling what you hold) still work." % today)
    return 0


def cmd_log(a, paths, cfg):
    now, today = today_of(a)
    rows = [r for r in load_state(paths.broker).get("orders", []) if r.get("date") == today]
    if not rows:
        print("No decisions recorded today (%s)." % today)
    for r in rows:
        print("%s  %-9s %-5s %-4s %4s %-12s %s" % (r.get("at"), r.get("status"), r.get("mode"), r.get("side"), r.get("qty"),
                                                  r.get("symbol"), r.get("broker_id") or ""))
    return 0


def _utf8_out():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(errors="replace")
        except Exception:
            pass


def main(argv=None, transport=None, download=None, sleep=time.sleep):
    _utf8_out()
    ap = argparse.ArgumentParser(description="Order Executor (trader-broker, NSE/BSE): paper by default, live via "
                                             "Angel One SmartAPI, never without your yes. Educational only.")
    ap.add_argument("--orders", default="trader/orders.json")
    ap.add_argument("--config", default="trader/config.json")
    ap.add_argument("--risk", default="trader/state/risk.json")
    ap.add_argument("--prices", default="trader/prices.json")
    ap.add_argument("--state-dir", default="trader/state")
    ap.add_argument("--now", help='pretend it is this IST time, e.g. "2026-11-02 10:00"')
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("show"); p.add_argument("--index", type=int); p.add_argument("--json", action="store_true")
    p = sub.add_parser("approve"); p.add_argument("--index", type=int); p.add_argument("--reply", required=True)
    p = sub.add_parser("decline"); p.add_argument("--index", type=int); p.add_argument("--reply")
    p = sub.add_parser("protect"); p.add_argument("--index", type=int)
    sub.add_parser("status")
    p = sub.add_parser("cancel"); p.add_argument("--order-id", required=True); p.add_argument("--reply", required=True)
    p.add_argument("--variety", default="NORMAL")
    sub.add_parser("mark")
    p = sub.add_parser("flatten"); p.add_argument("--symbol", required=True); p.add_argument("--qty", type=int)
    p.add_argument("--price", type=float); p.add_argument("--segment", default="equity_intraday")
    p.add_argument("--exchange", default="NSE")
    sub.add_parser("pnl")
    p = sub.add_parser("kill"); p.add_argument("--reason")
    sub.add_parser("log")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    paths = Paths(a)
    try:
        cfg = load_cfg(paths.config)
        fn = {"show": cmd_show, "decline": cmd_decline, "mark": cmd_mark, "flatten": cmd_flatten, "kill": cmd_kill,
              "log": cmd_log}.get(a.cmd)
        if fn:
            return fn(a, paths, cfg)
        if a.cmd == "approve":
            return cmd_approve(a, paths, cfg, transport, download, sleep)
        if a.cmd == "protect":
            return cmd_protect(a, paths, cfg, transport, download)
        return {"status": cmd_status, "cancel": cmd_cancel, "pnl": cmd_pnl}[a.cmd](a, paths, cfg, transport)
    except (TicketError, nse.NSEError, angel.BrokerError) as e:
        print("ticket.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
