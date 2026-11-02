"""Angel One SmartAPI adapter for trader-broker (live mode), plus a Zerodha Kite stub.
Standard library only: urllib for HTTP, hmac + base64 for the TOTP.

UNVERIFIED LIVE. This adapter was built from Angel One's public SmartAPI documentation
(https://smartapi.angelbroking.com/docs, read 2026-11-02) and tested offline against mocked
HTTP answers only. It has never sent an order to a real account. Paper-trade first, then
try ONE tiny live order you are ready to lose, and check it in the Angel One app.

Endpoints (root https://apiconnect.angelone.in):
  POST /rest/auth/angelbroking/user/v1/loginByPassword   {clientcode, password (your PIN), totp}
  POST /rest/secure/angelbroking/order/v1/placeOrder      variety, tradingsymbol, symboltoken, ...
  POST /rest/secure/angelbroking/order/v1/cancelOrder     {variety, orderid}
  GET  /rest/secure/angelbroking/order/v1/getOrderBook
  GET  /rest/secure/angelbroking/order/v1/getTradeBook
  POST /rest/secure/angelbroking/user/v1/logout           {clientcode}
  Instrument master: https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json
Every request carries X-PrivateKey (the API key), X-UserType USER, X-SourceID WEB,
X-ClientLocalIP, X-ClientPublicIP and X-MACAddress; every call after the login carries
"Authorization: Bearer <jwtToken>". Angel One's static-IP API keys only accept place,
modify and cancel requests from the IP you registered (SEBI's retail-algo framework).

Credentials come ONLY from environment variables or a local file you fill in yourself:
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET
  or trader/secrets/angel.json {"api_key": ..., "client_code": ..., "pin": ..., "totp_secret": ...}
They are never written anywhere, never printed, and scrubbed from every error message.
"""

import base64
import hashlib
import hmac
import json
import os
import socket
import struct
import time
import urllib.error
import urllib.request
import uuid

ROOT = "https://apiconnect.angelone.in"
LOGIN = "/rest/auth/angelbroking/user/v1/loginByPassword"
LOGOUT = "/rest/secure/angelbroking/user/v1/logout"
PLACE = "/rest/secure/angelbroking/order/v1/placeOrder"
CANCEL = "/rest/secure/angelbroking/order/v1/cancelOrder"
ORDER_BOOK = "/rest/secure/angelbroking/order/v1/getOrderBook"
TRADE_BOOK = "/rest/secure/angelbroking/order/v1/getTradeBook"
SCRIP_MASTER = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
ENV = {"api_key": "ANGEL_API_KEY", "client_code": "ANGEL_CLIENT_CODE", "pin": "ANGEL_PIN",
       "totp_secret": "ANGEL_TOTP_SECRET"}
PRODUCT = {"MIS": "INTRADAY", "CNC": "DELIVERY", "NRML": "CARRYFORWARD"}
ORDER_TYPE = {"LIMIT": "LIMIT", "MARKET": "MARKET", "SL": "STOPLOSS_LIMIT", "SL-M": "STOPLOSS_MARKET"}
SEG_EXCH = {("NSE", "equity_intraday"): "NSE", ("NSE", "equity_delivery"): "NSE",
            ("BSE", "equity_intraday"): "BSE", ("BSE", "equity_delivery"): "BSE",
            ("NSE", "futures"): "NFO", ("NSE", "options"): "NFO", ("BSE", "futures"): "BFO",
            ("BSE", "options"): "BFO"}
TAG = "ndts"   # ordertag prefix (Angel One: under 20 characters)


class BrokerError(Exception):
    pass


# ---------------------------------------------------------------- TOTP (RFC 6238)

def totp(secret_b32, at=None, step=30, digits=6):
    """The 6-digit code your authenticator app shows, from the base32 secret Angel One gives
    when you enable TOTP (smartapi.angelbroking.com/enable-totp)."""
    s = "".join(str(secret_b32).split()).upper()
    s += "=" * (-len(s) % 8)
    try:
        key = base64.b32decode(s)
    except (ValueError, TypeError):
        raise BrokerError("ANGEL_TOTP_SECRET is not a base32 secret")
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


# ---------------------------------------------------------------- credentials

def load_credentials(path=None, env=None):
    """{api_key, client_code, pin, totp_secret} from the environment, else the local file.
    Raises BrokerError naming what is missing (never the values)."""
    env = os.environ if env is None else env
    creds = {k: (env.get(v) or "").strip() for k, v in ENV.items()}
    if not all(creds.values()) and path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            raise BrokerError("could not read the credentials file %s (is it valid JSON?)" % path)
        for k in creds:
            if not creds[k]:
                creds[k] = str(doc.get(k) or doc.get(ENV[k]) or "").strip()
        try:
            if os.name == "posix" and os.stat(path).st_mode & 0o077:
                creds["_warning"] = "%s is readable by other users: chmod 600 it" % path
        except OSError:
            pass
    missing = [ENV[k] for k in ENV if not creds.get(k)]
    if missing:
        raise BrokerError("live mode needs %s (environment variables, or %s)" % (", ".join(missing),
                                                                               path or "a credentials file"))
    return creds


def scrub(text, creds):
    """Remove every secret (and the session tokens) from a message before it is shown."""
    out = str(text)
    for k, v in (creds or {}).items():
        if k.startswith("_") or not v or len(str(v)) < 3:
            continue
        out = out.replace(str(v), "***")
    return out


# ---------------------------------------------------------------- HTTP

def urllib_transport(method, url, headers, body, timeout=20):
    """(status, text). Tests swap this for a fake."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "replace")
        finally:
            e.close()
    except (urllib.error.URLError, OSError) as e:
        raise BrokerError("could not reach Angel One: %s" % getattr(e, "reason", e))


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return "127.0.0.1"


def mac_address():
    n = uuid.getnode()
    return ":".join("%02x" % ((n >> s) & 0xFF) for s in range(40, -1, -8))


class AngelOne(object):
    """One logged-in SmartAPI session. Use as a context manager: it logs out at the end."""

    name = "Angel One SmartAPI"

    def __init__(self, creds, public_ip="", transport=None, clock=None, sleep=None, min_gap=1.0):
        self.creds = creds
        self.public_ip = public_ip or ""
        self.transport = transport or urllib_transport
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        self.min_gap = float(min_gap)          # seconds between order calls: far below SEBI's 10 per second
        self.jwt = None
        self._last_order_call = 0.0

    # -- plumbing
    def headers(self, auth=True):
        h = {"Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER",
             "X-SourceID": "WEB", "X-ClientLocalIP": local_ip(), "X-ClientPublicIP": self.public_ip or local_ip(),
             "X-MACAddress": mac_address(), "X-PrivateKey": self.creds["api_key"]}
        if auth:
            if not self.jwt:
                raise BrokerError("not logged in")
            h["Authorization"] = "Bearer " + self.jwt
        return h

    def call(self, method, path, body=None, auth=True):
        status, text = self.transport(method, ROOT + path, self.headers(auth), body)
        try:
            doc = json.loads(text) if text else {}
        except ValueError:
            raise BrokerError("Angel One answered HTTP %s with something that is not JSON" % status)
        if status >= 400 or not doc.get("status", False):
            msg = doc.get("message") or doc.get("errorcode") or ("HTTP %s" % status)
            code = doc.get("errorcode") or ""
            raise BrokerError(scrub("Angel One refused %s: %s%s" % (path.rsplit("/", 1)[-1], msg,
                                                                   (" (%s)" % code) if code else ""),
                                    dict(self.creds, jwt=self.jwt or "")))
        return doc.get("data")

    def _throttle(self):
        wait = self._last_order_call + self.min_gap - self.clock()
        if wait > 0:
            self.sleep(wait)
        self._last_order_call = self.clock()

    # -- session
    def login(self):
        body = {"clientcode": self.creds["client_code"], "password": self.creds["pin"],
                "totp": totp(self.creds["totp_secret"], self.clock())}
        data = self.call("POST", LOGIN, body, auth=False) or {}
        if not data.get("jwtToken"):
            raise BrokerError("Angel One's login answer had no session token")
        self.jwt = data["jwtToken"]
        return True

    def logout(self):
        if self.jwt:
            try:
                self.call("POST", LOGOUT, {"clientcode": self.creds["client_code"]})
            except BrokerError:
                pass
            self.jwt = None

    def __enter__(self):
        self.login()
        return self

    def __exit__(self, *exc):
        self.logout()
        return False

    # -- orders
    def place(self, params):
        self._throttle()
        data = self.call("POST", PLACE, params) or {}
        oid = data.get("orderid")
        if not oid:
            raise BrokerError("Angel One accepted the request but sent no order id")
        return {"orderid": str(oid), "uniqueorderid": data.get("uniqueorderid")}

    def cancel(self, orderid, variety="NORMAL"):
        self._throttle()
        data = self.call("POST", CANCEL, {"variety": variety, "orderid": str(orderid)}) or {}
        return {"orderid": str(data.get("orderid") or orderid)}

    def order_book(self):
        return self.call("GET", ORDER_BOOK) or []

    def trade_book(self):
        return self.call("GET", TRADE_BOOK) or []


# ---------------------------------------------------------------- mapping our order -> SmartAPI

def find_instrument(rows, symbol, exchange, segment):
    """The scrip-master row for an NSE/BSE cash symbol (RELIANCE -> RELIANCE-EQ, token 2885)
    or an F&O trading symbol (RELIANCE25JAN27FUT). None if not found."""
    ex = SEG_EXCH.get((exchange, segment), exchange)
    sym = str(symbol).upper()
    want = (sym + "-EQ") if segment.startswith("equity") and exchange == "NSE" else sym
    for r in rows:
        if r.get("exch_seg") != ex:
            continue
        if r.get("symbol") == want or (exchange == "BSE" and segment.startswith("equity") and r.get("symbol") == sym):
            return r
    return None


def scrip_rows(cache_path, today, download=None):
    """NSE/BSE cash rows (and NFO/BFO) of Angel One's instrument master, cached for the day."""
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if doc.get("date") == today:
                return doc["rows"]
        except (OSError, ValueError, KeyError):
            pass
    if download is None:
        def download():
            req = urllib.request.Request(SCRIP_MASTER, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", "replace")
    try:
        rows = json.loads(download())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise BrokerError("could not read Angel One's instrument master: %s" % getattr(e, "reason", e))
    keep = [{k: r.get(k) for k in ("token", "symbol", "name", "lotsize", "tick_size", "exch_seg", "instrumenttype",
                                   "expiry")}
            for r in rows if r.get("exch_seg") in ("NSE", "BSE", "NFO", "BFO")]
    if cache_path:
        d = os.path.dirname(cache_path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump({"date": today, "source": SCRIP_MASTER, "rows": keep}, fh)
    return keep


def tick_of(row):
    """Angel One lists tick_size in paise: "10.000000" = Rs 0.10."""
    try:
        t = float(row.get("tick_size") or 0) / 100.0
        return t if t > 0 else None
    except (TypeError, ValueError):
        return None


def entry_params(order, inst, tag):
    ot = ORDER_TYPE[str(order["order_type"]).upper()]
    p = {"variety": "STOPLOSS" if ot.startswith("STOPLOSS") else "NORMAL", "tradingsymbol": inst["symbol"],
         "symboltoken": str(inst["token"]), "transactiontype": str(order["side"]).upper(),
         "exchange": inst["exch_seg"], "ordertype": ot, "producttype": PRODUCT[str(order["product"]).upper()],
         "duration": str(order.get("validity") or "DAY").upper(), "price": str(order.get("price") or "0"),
         "triggerprice": str(order.get("trigger_price") or "0"), "squareoff": "0", "stoploss": "0",
         "quantity": str(int(order["qty"])), "ordertag": tag[:19]}
    return p


def stop_params(order, inst, tag, limit_buffer_pct=0.5, tick=0.05):
    """The protective SELL stop-loss (limit) for a filled long: trigger at the stop, limit a
    little under it so it still fills in a fast market."""
    stop = float(order["stop_loss"])
    lim = stop * (1 - float(limit_buffer_pct) / 100.0)
    t = tick or 0.05
    lim = int(lim / t) * t
    return {"variety": "STOPLOSS", "tradingsymbol": inst["symbol"], "symboltoken": str(inst["token"]),
            "transactiontype": "SELL", "exchange": inst["exch_seg"], "ordertype": "STOPLOSS_LIMIT",
            "producttype": PRODUCT[str(order["product"]).upper()], "duration": "DAY",
            "price": "%.2f" % lim, "triggerprice": "%.2f" % stop, "squareoff": "0", "stoploss": "0",
            "quantity": str(int(order["qty"])), "ordertag": (tag + "s")[:19]}


def order_status(book, orderid):
    for r in book or []:
        if str(r.get("orderid")) == str(orderid):
            return str(r.get("orderstatus") or r.get("status") or "").lower(), r
    return None, None


def realized_from_trades(trades, charges_fn=None):
    """Today's realized gross P&L from the trade book: for each symbol, the matched
    quantity's sell value minus its buy value. Open (unmatched) quantity is ignored.
    charges_fn(buy_value, sell_value, exchange) -> estimated charges for the matched part."""
    per = {}
    for t in trades or []:
        sym = t.get("tradingsymbol") or t.get("symbol")
        ex = t.get("exchange") or "NSE"
        q = float(t.get("fillsize") or t.get("quantity") or 0)
        px = float(t.get("fillprice") or t.get("price") or 0)
        side = str(t.get("transactiontype") or "").upper()
        d = per.setdefault((sym, ex), {"bq": 0.0, "bv": 0.0, "sq": 0.0, "sv": 0.0})
        if side == "BUY":
            d["bq"] += q
            d["bv"] += q * px
        elif side == "SELL":
            d["sq"] += q
            d["sv"] += q * px
    gross = net = 0.0
    for (sym, ex), d in per.items():
        m = min(d["bq"], d["sq"])
        if m <= 0:
            continue
        bv = d["bv"] * m / d["bq"]
        sv = d["sv"] * m / d["sq"]
        gross += sv - bv
        net += sv - bv - (charges_fn(bv, sv, ex) if charges_fn else 0.0)
    return round(gross, 2), round(net, 2)


# ---------------------------------------------------------------- Zerodha Kite (stub)

class KiteConnect(object):
    """NOT IMPLEMENTED: a place to add Zerodha Kite Connect later.

    What it would need (https://kite.trade/docs/connect/v3/, not verified here):
      * a Kite Connect app (api_key, api_secret); the Personal plan is free, Connect is
        Rs 500 a month (zerodha.com/charges, read 2026-11-02)
      * a daily login in the browser that returns a request_token, then
        POST https://api.kite.trade/session/token with api_key, request_token and
        checksum = sha256(api_key + request_token + api_secret) -> access_token
      * orders: POST https://api.kite.trade/orders/regular (form fields tradingsymbol,
        exchange, transaction_type, order_type, quantity, product, price, validity, tag),
        headers "X-Kite-Version: 3" and "Authorization: token api_key:access_token"
      * the same static-IP registration under SEBI's retail-algo framework
    Until someone writes and tests it, live mode supports Angel One only."""

    name = "Zerodha Kite Connect (stub)"

    def __init__(self, *a, **k):
        raise BrokerError("the Zerodha Kite adapter is a stub: live mode supports \"broker\": \"angelone\" only. "
                          "See KiteConnect in angel.py for what it would take.")
