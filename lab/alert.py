"""Telegram alerts for new Trading Lab triggers. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    TELEGRAM_TOKEN=... python3 lab/alert.py            # send new triggers (once each)
    python3 lab/alert.py --dry-run                     # print, send nothing
    python3 lab/alert.py --result                      # after 15:15: how today's picks ended

At most MAX_PER_DAY (2) picks a day: when several pass at once, the best test average goes first
(SCORE_RANK=1: the highest confluence score, 0-10 from lab/score.py, first). Every alert shows
its score, e.g. "score 7/10".
Phase B setups (lab/setups2.py) are picked only when they pass the same quality bar.
No new picks after MAX_STOPS (2) of today's picks hit their stop (daily loss limit).
Optional TARGET_R (e.g. TARGET_R=0.5): every pick's target = entry +/- TARGET_R x risk (also for
15:15-exit setups), saved with the pick and used by --result. It does not move the stop. Unset = off.

Optional rules (lab/filters.py, lab/risk.py):  --filters nifty,gap   (the default)
    filters: sideways nifty relvol vwap time gap     exits: trail partial tstop     none = off
Only nifty + gap are on by default: in lab/evalfilters.py they were the only ones that raised the
test-half average of the remembered settings, and only slightly (see README). A gap day of
1%+ is flagged in the message when the gap filter is off.

Setup (once): make a bot with @BotFather in Telegram, send your bot /start, and save the bot
token as the GitHub repo secret TELEGRAM_TOKEN. The chat id is found from your /start message
(or set TELEGRAM_CHAT_ID). The token is read only from the environment and never printed.

Only quality triggers are sent: the best remembered setting of each setup, still live, with at
least MIN_N test trades, MIN_WIN % (60) test wins and MIN_EXP % test average. Each trigger is sent
once (state in lab/alert_state.json, kept by the workflow's cache, not committed).
"""

import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import calendar_nse  # noqa: E402
import core  # noqa: E402
import filters  # noqa: E402
import lab  # noqa: E402
import risk  # noqa: E402

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")
MIN_N = int(os.environ.get("MIN_N", "8"))
MIN_WIN = float(os.environ.get("MIN_WIN", "60"))
MIN_EXP = float(os.environ.get("MIN_EXP", "0.15"))
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "2"))   # only the best 2 setups a day
# Rank picks by confluence score (score.py) first, then test average: OFF by default. In
# lab/evalscore.py (2026-11-05, all Nifty 100) the pooled TEST-half average rose bucket by bucket
# with the score, but the TRAIN half did not (flat; falling for the original four setups), so the
# effect is not clear enough to act on. The score is shown in every alert. SCORE_RANK=1 turns it on.
SCORE_RANK = os.environ.get("SCORE_RANK", "0") == "1"
DEFAULT_RULES = os.environ.get("ALERT_FILTERS", ",".join(filters.DEFAULT))
# Optional 'sector strong' hook (lab/sector.py): keep only picks in the top SECTOR_TOP sectors by
# 1-month relative strength. OFF by default (not tested out of sample). SECTOR_STRONG=1 turns it on.
SECTOR_STRONG = os.environ.get("SECTOR_STRONG", "0") == "1"
# Optional regime selector (lab/regime.py): keep only setups whose walk-forward OOS average was > 0
# in today's NIFTY regime (backtest_out/regime_table.json). OFF by default: in the 2026-11-06
# walk-forward it did not clearly help out of sample. REGIME_SELECT=1 turns it on.
REGIME_SELECT = os.environ.get("REGIME_SELECT", "0") == "1"


def target_r_env(text=None):
    """TARGET_R env (e.g. 0.5): every pick's target = entry +/- TARGET_R x |entry - stop|, also for
    setups that normally exit at 15:15. Unset or empty: each setting's own target (no change).
    It does NOT move the stop. See README 'Smaller targets (TARGET_R)' for the OOS test."""
    text = os.environ.get("TARGET_R", "") if text is None else text
    if not text.strip():
        return None
    r = float(text)
    if r <= 0:
        raise ValueError("TARGET_R must be > 0")
    return r


TARGET_R = target_r_env()
FOOT = "નિયમનું output છે, buy/sell સલાહ નથી. શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી."


def tg(token, method, params=None):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30))
    except Exception as e:  # never print the url: it holds the token
        raise RuntimeError("Telegram %s failed: %s" % (method, type(e).__name__))


def chat_id(token):
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if cid:
        return cid
    res = tg(token, "getUpdates").get("result") or []
    for u in reversed(res):
        msg = u.get("message") or u.get("channel_post") or {}
        if msg.get("chat", {}).get("id"):
            return str(msg["chat"]["id"])
    return None


def pick(hits):
    """Quality filter: best setting (rank 1) of its setup, live, good test record."""
    return [h for h in hits if h["rank"] == 1 and h["status"] == "live" and h["test"]["n"] >= MIN_N
            and h["test"]["win"] >= MIN_WIN and h["test"]["exp"] >= MIN_EXP]


def line(h):
    tgt = h["target"] if h["target"] is not None else "15:15 exit"
    if h.get("target_r") is not None:
        tgt = "%s (%gR)" % (tgt, h["target_r"])
    txt = ("🔔 %s %s %s %s\nentry %s | stop %s | target %s | last %s\ntest: %d trades, %.0f%% win, avg %+.2f%%"
           % (h["symbol"], h["setup"].upper(), h["side"], h["time"], h["entry"], h["stop"], tgt, h["last"],
              h["test"]["n"], h["test"]["win"], h["test"]["exp"]))
    if h.get("score") is not None:
        txt += " | score %d/10" % h["score"]
    g = h.get("gap_pct")
    if g is not None and abs(g) >= filters.GAP_PCT:
        txt += "\n⚠️ gap day %+.1f%%" % g
    return txt


def rank_key(h):
    """Sort key for picks: score first (when SCORE_RANK), then test average, then test win %."""
    sc = (h.get("score") or 0) if SCORE_RANK else 0
    return (-sc, -h["test"]["exp"], -h["test"]["win"])


def split_rules(text):
    """'nifty,gap,trail' -> (['nifty', 'gap'], ['trail']); unknown names raise ValueError."""
    names = filters.parse_names(text)
    bad = [n for n in names if n not in filters.NAMES and n not in risk.EXIT_NAMES]
    if bad:
        raise ValueError("unknown rule(s): %s" % ",".join(bad))
    return [n for n in names if n in filters.NAMES], [n for n in names if n in risk.EXIT_NAMES]


def nifty_bars(flt):
    if "nifty" not in flt:
        return None
    try:
        return core.sessions(core.fetch("^NSEI", "5d", "5m"))[0]
    except Exception as e:  # no index data: the nifty filter then lets every trigger through
        print("^NSEI: data error (%s), nifty filter off this run" % type(e).__name__)
        return []


def sector_filter(hits, rank=None):
    """Keep hits in a strong sector. Any data error: keep every hit (the filter steps aside)."""
    try:
        import sector
        return sector.filter_picks(hits, rank if rank is not None else sector.today_rank())
    except Exception as e:
        print("sector filter: data error (%s), off this run" % type(e).__name__)
        return hits


def regime_filter(hits, day, regime_name=None, table=None):
    """Keep hits whose setup was positive in the regime known before `day`. Any error: keep all."""
    try:
        import regime
        if table is None:
            with open(regime.TABLE) as fh:
                table = json.load(fh)["table"]
        if regime_name is None:
            regime_name = regime.regime_before(regime.classify(core.fetch("^NSEI", "2y", "1d")), day)
        return regime.filter_picks(hits, regime_name, table)
    except Exception as e:
        print("regime selector: not available (%s), off this run" % type(e).__name__)
        return hits


def send(text):
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("no TELEGRAM_TOKEN: add it as a GitHub repo secret. Nothing sent.")
        return False
    cid = chat_id(token)
    if not cid:
        print("no chat found: open your bot in Telegram and send /start, then it works. Nothing sent.")
        return False
    for k in range(0, len(text), 3900):
        tg(token, "sendMessage", {"chat_id": cid, "text": text[k:k + 3900]})
    return True


def result(a, mem, day, picks, state=None):
    """End of day: how each of today's picks ended (target / stop / 15:15 close). Unless --dry-run,
    the outcomes are kept in the state file as '<day>#results' for `lab/report.py weekly`."""
    if not picks:
        print("%s: no picks today" % day)
        return 0
    out = ["📊 %s result (paper)" % day]
    nbs, kept = {}, []
    for p in picks:
        st = "data missing"
        try:
            flt, ex = split_rules(p.get("rules", a.filters))   # grade with the rules it was picked under
            if tuple(flt) not in nbs:
                nbs[tuple(flt)] = nifty_bars(flt)
            tr = p["target_r"] if "target_r" in p else TARGET_R   # grade with the target it was sent with
            hits, g = lab.scan_one(p["symbol"], mem["stocks"][p["symbol"]], day, None, flt, ex, nbs[tuple(flt)],
                                   **({"target_r": tr} if tr is not None else {}))
            for h in hits:
                if (h["setup"], h["side"], h["time"]) == (p["setup"], p["side"], p["time"]):
                    if h["status"] == "live":   # day over but last bar(s) missing: close at last price
                        sd = 1 if h["side"] == "LONG" else -1
                        pct = sd * (h["last"] - h["entry"]) / h["entry"] * 100 - 0.05
                        st = "close %+.2f%% (last price %s, approx)" % (pct, h["last"])
                        kept.append(dict(symbol=p["symbol"], setup=p["setup"], side=p["side"], time=p["time"],
                                         result="close", pct=round(pct, 3), approx=True))
                    else:
                        kept.append(dict(symbol=p["symbol"], setup=p["setup"], side=p["side"], time=p["time"],
                                         result=h["status"], pct=h["pct"] or 0, exit_time=h["exit_time"]))
                        st = "%s %+.2f%% (exit %s)" % (h["status"], h["pct"] or 0, h["exit_time"] or "-")
                    if g:
                        st += " ⚠️ missing bars %s" % ",".join(g)
                    break
        except Exception as e:
            st = "data error (%s)" % type(e).__name__
        out.append("%s %s %s %s: entry %s stop %s target %s → %s" % (
            p["symbol"], p["setup"].upper(), p["side"], p["time"], p["entry"], p["stop"],
            p["target"] if p["target"] is not None else "15:15 exit", st))
    out.append(FOOT)
    text = "\n".join(out)
    if a.dry_run or a.local:
        print(text)
    else:
        send(text)
    if state is not None and kept and not a.dry_run:
        state[day + "#results"] = kept
        with open(a.state, "w") as fh:
            json.dump(state, fh)
    return 0


def prune(state, today, sent_days=5, pick_days=40):
    """Keep sent-trigger keys 5 days, '<day>#picks' / '<day>#results' 40 days (weekly report)."""
    keep = {}
    for k, v in state.items():
        n = pick_days if "#" in k else sent_days
        if k[:10] >= (today - dt.timedelta(days=n)).isoformat():
            keep[k] = v
    return keep


def main(argv=None):
    ap = argparse.ArgumentParser(description="Telegram alerts (educational)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--local", action="store_true", help="print instead of Telegram, but remember picks")
    ap.add_argument("--day", help="YYYY-MM-DD, for testing on a past session")
    ap.add_argument("--at", help="HH:MM IST, for testing")
    ap.add_argument("--memory", default=lab.MEMORY)
    ap.add_argument("--state", default=STATE)
    ap.add_argument("--result", action="store_true", help="after 15:15: send how today's picks ended")
    ap.add_argument("--filters", default=DEFAULT_RULES,
                    help="comma list of %s / %s, or none (default %s)" % (
                        ",".join(filters.NAMES), ",".join(risk.EXIT_NAMES), DEFAULT_RULES))
    ap.add_argument("--max-stops", type=int, default=risk.MAX_STOPS, help="no new picks after this many stop-outs today")
    a = ap.parse_args(argv)
    try:
        flt, ex = split_rules(a.filters)
    except ValueError as e:
        ap.error(str(e))
    now = dt.datetime.now(core.IST)
    if not a.day and not calendar_nse.is_trading_day(now.date()):     # NSE holiday or weekend: skip quietly
        print("%s: NSE closed (%s), nothing to do" % (now.date(), calendar_nse.holiday_name(now.date()) or "weekend"))
        return 0
    day = a.day or now.date().isoformat()
    at = None
    if a.at:
        hh, mm = a.at.split(":")
        at = int(hh) * 60 + int(mm)
    mem = lab.load_memory(a.memory)
    state = json.load(open(a.state)) if os.path.exists(a.state) else {}
    sent = set(state.get(day, []))
    picks = state.get(day + "#picks", [])
    if a.result:
        return result(a, mem, day, picks, state)
    if len(picks) >= MAX_PER_DAY:
        print("%s: already %d pick(s) today" % (day, len(picks)))
        return 0
    new, gaps, every = [], {}, []
    NB = nifty_bars(flt)
    for sym, info in sorted(mem["stocks"].items()):
        if not any(v["best"] for v in info["setups"].values()):
            continue
        try:
            hits, g = lab.scan_one(sym, info, day, at, flt, ex, NB,
                                   **({"target_r": TARGET_R} if TARGET_R is not None else {}))
        except Exception as e:
            print("%s: data error (%s)" % (sym, type(e).__name__))
            continue
        every += hits
        for h in pick(hits):
            if TARGET_R is not None:
                h["target_r"] = TARGET_R
            if h.get("day") != day:
                continue
            key = "%s|%s|%s|%s" % (h["symbol"], h["setup"], h["side"], h["time"])
            if key not in sent:
                new.append(h)
                sent.add(key)
                if g:
                    gaps[sym] = g
    stops = risk.stopouts(picks, every)
    if picks and stops >= a.max_stops:
        print("%s: %d pick(s) stopped out today, daily loss limit reached: no new picks" % (day, stops))
        return 0
    if new and SECTOR_STRONG:
        new = sector_filter(new)
        if not new:
            print("%s: no new quality trigger in a strong sector" % day)
            return 0
    if new and REGIME_SELECT:
        new = regime_filter(new, day)
        if not new:
            print("%s: no new quality trigger that suits today's regime" % day)
            return 0
    if not new:
        print("%s: no new quality trigger" % day)
        return 0
    new.sort(key=rank_key)
    new = new[:MAX_PER_DAY - len(picks)]
    picks += [dict(symbol=h["symbol"], setup=h["setup"], side=h["side"], time=h["time"], entry=h["entry"],
                   stop=h["stop"], target=h["target"], rules=",".join(flt + ex),
                   **({"target_r": TARGET_R} if TARGET_R is not None else {})) for h in new]
    new.sort(key=lambda h: h["time"])
    parts = [line(h) for h in new]
    if gaps:
        parts.append("⚠️ missing 5-min bars: " + "; ".join("%s %s" % (s, ",".join(g)) for s, g in gaps.items()))
    parts.append(FOOT)
    text = "\n\n".join(parts)
    if a.dry_run:
        print(text)
        return 0
    if a.local:
        print(text)
    elif not send(text):
        return 0
    state = prune(state, now.date())
    state[day] = sorted(sent)
    state[day + "#picks"] = picks
    with open(a.state, "w") as fh:
        json.dump(state, fh)
    print("%s: sent %d new trigger(s)" % (day, len(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
