"""Telegram alerts for new Trading Lab triggers. EDUCATIONAL ONLY, not investment advice.
શૈક્ષણિક હેતુ માટે, રોકાણ સલાહ નથી.

    TELEGRAM_TOKEN=... python3 lab/alert.py            # send new triggers (once each)
    python3 lab/alert.py --dry-run                     # print, send nothing

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
import core  # noqa: E402
import lab  # noqa: E402

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")
MIN_N = int(os.environ.get("MIN_N", "8"))
MIN_WIN = float(os.environ.get("MIN_WIN", "60"))
MIN_EXP = float(os.environ.get("MIN_EXP", "0.15"))
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
    return ("🔔 %s %s %s %s\nentry %s | stop %s | target %s | last %s\ntest: %d trades, %.0f%% win, avg %+.2f%%"
            % (h["symbol"], h["setup"].upper(), h["side"], h["time"], h["entry"], h["stop"], tgt, h["last"],
               h["test"]["n"], h["test"]["win"], h["test"]["exp"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Telegram alerts (educational)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--day", help="YYYY-MM-DD, for testing on a past session")
    ap.add_argument("--at", help="HH:MM IST, for testing")
    ap.add_argument("--memory", default=lab.MEMORY)
    ap.add_argument("--state", default=STATE)
    a = ap.parse_args(argv)
    now = dt.datetime.now(core.IST)
    day = a.day or now.date().isoformat()
    at = None
    if a.at:
        hh, mm = a.at.split(":")
        at = int(hh) * 60 + int(mm)
    mem = lab.load_memory(a.memory)
    state = json.load(open(a.state)) if os.path.exists(a.state) else {}
    sent = set(state.get(day, []))
    new, gaps = [], {}
    for sym, info in sorted(mem["stocks"].items()):
        if not any(v["best"] for v in info["setups"].values()):
            continue
        try:
            hits, g = lab.scan_one(sym, info, day, at)
        except Exception as e:
            print("%s: data error (%s)" % (sym, type(e).__name__))
            continue
        for h in pick(hits):
            if h.get("day") != day:
                continue
            key = "%s|%s|%s|%s" % (h["symbol"], h["setup"], h["side"], h["time"])
            if key not in sent:
                new.append(h)
                sent.add(key)
                if g:
                    gaps[sym] = g
    if not new:
        print("%s: no new quality trigger" % day)
        return 0
    new.sort(key=lambda h: h["time"])
    parts = [line(h) for h in new]
    if gaps:
        parts.append("⚠️ missing 5-min bars: " + "; ".join("%s %s" % (s, ",".join(g)) for s, g in gaps.items()))
    parts.append(FOOT)
    text = "\n\n".join(parts)
    if a.dry_run:
        print(text)
        return 0
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        print("no TELEGRAM_TOKEN: add it as a GitHub repo secret. Nothing sent.")
        return 0
    cid = chat_id(token)
    if not cid:
        print("no chat found: open your bot in Telegram and send /start, then it works. Nothing sent.")
        return 0
    for k in range(0, len(text), 3900):
        tg(token, "sendMessage", {"chat_id": cid, "text": text[k:k + 3900]})
    state = {d: v for d, v in state.items() if d >= (now.date() - dt.timedelta(days=5)).isoformat()}
    state[day] = sorted(sent)
    with open(a.state, "w") as fh:
        json.dump(state, fh)
    print("%s: sent %d new trigger(s)" % (day, len(new)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
