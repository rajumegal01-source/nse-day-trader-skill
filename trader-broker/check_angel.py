"""Read-only Angel One check: log in, read the order book, log out. Places NO order.

Run:  python check_angel.py
It reads ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET from the environment,
and asks for any that are missing (the PIN and TOTP secret are typed hidden). Nothing is saved
or printed.
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import angel  # noqa: E402

ASK = [("api_key", "API Key", False), ("client_code", "Client ID", False),
       ("pin", "PIN", True), ("totp_secret", "TOTP secret (the long code, not 6 digits)", True)]


def main():
    creds = {}
    for key, label, hidden in ASK:
        val = (os.environ.get(angel.ENV[key]) or "").strip()
        if not val:
            val = (getpass.getpass if hidden else input)(label + ": ").strip()
        creds[key] = val
    if not all(creds.values()):
        print("Missing a value. Nothing was sent.")
        return 2
    try:
        angel.totp(creds["totp_secret"])
    except angel.BrokerError as e:
        print("TOTP secret problem:", e)
        return 2
    try:
        with angel.AngelOne(creds) as s:
            print("LOGIN OK")
            book = s.order_book()
            print("ORDER BOOK OK: %d orders today" % len(book))
            for o in book[:10]:
                print(" ", o.get("tradingsymbol"), o.get("transactiontype"), o.get("quantity"),
                      o.get("price"), o.get("orderstatus"))
        print("LOGGED OUT. No order was placed.")
        return 0
    except angel.BrokerError as e:
        print("FAILED:", angel.scrub(str(e), creds))
        return 1
    except Exception as e:  # network etc.
        print("FAILED:", angel.scrub("%s: %s" % (type(e).__name__, e), creds))
        return 1


if __name__ == "__main__":
    sys.exit(main())
