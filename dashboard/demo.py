"""A stand-in client that returns made-up, Schwab-shaped responses (for `--demo`; no network, no credentials)."""
import datetime

_UTC = datetime.timezone.utc


class _Response:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _position(symbol, description, qty, avg, price, day, asset="EQUITY"):
    value = round(qty * price, 2)
    return {"longQuantity": qty, "shortQuantity": 0, "averagePrice": avg, "marketValue": value,
            "currentDayProfitLoss": day, "currentDayProfitLossPercentage": round(day / (value - day) * 100, 2),
            "longOpenProfitLoss": round(value - qty * avg, 2),
            "instrument": {"symbol": symbol, "description": description, "assetType": asset}}


class _DemoTokens:
    def status(self):
        return {"access_token_seconds_left": 1500, "refresh_token_seconds_left": 5 * 24 * 3600, "encrypted": True}


class DemoClient:
    tokens = _DemoTokens()

    def account_details_all(self, fields=None):
        return _Response([
            {"securitiesAccount": {
                "type": "MARGIN", "accountNumber": "10004821",
                "currentBalances": {"liquidationValue": 148920.44, "cashBalance": 12480.10, "buyingPower": 61250.00},
                "positions": [
                    _position("VTI", "Vanguard Total Stock Market ETF", 180, 221.40, 289.15, 412.20, "COLLECTIVE_INVESTMENT"),
                    _position("AAPL", "Apple Inc", 120, 151.20, 228.60, -186.00),
                    _position("MSFT", "Microsoft Corp", 60, 310.05, 431.90, 254.40),
                    _position("NVDA", "NVIDIA Corp", 90, 61.75, 138.20, 611.10),
                    _position("SCHD", "Schwab US Dividend Equity ETF", 400, 24.90, 27.85, -44.00, "COLLECTIVE_INVESTMENT"),
                ]}},
            {"securitiesAccount": {
                "type": "CASH", "accountNumber": "20007316",
                "currentBalances": {"liquidationValue": 42310.75, "cashBalance": 3120.75, "buyingPower": 3120.75},
                "positions": [
                    _position("BND", "Vanguard Total Bond Market ETF", 300, 72.10, 73.40, 21.00, "COLLECTIVE_INVESTMENT"),
                    _position("VXUS", "Vanguard Total International Stock ETF", 270, 55.30, 63.60, -97.20, "COLLECTIVE_INVESTMENT"),
                ]}},
        ])

    def account_orders_all(self, fromEnteredTime, toEnteredTime, maxResults=None, status=None):
        now = datetime.datetime.now(_UTC).replace(microsecond=0)

        def order(hours_ago, account, symbol, instruction, qty, filled, order_type, price, state):
            return {"enteredTime": (now - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
                    "accountNumber": account, "quantity": qty, "filledQuantity": filled, "orderType": order_type,
                    "price": price, "status": state,
                    "orderLegCollection": [{"instruction": instruction, "quantity": qty,
                                            "instrument": {"symbol": symbol}}]}
        return _Response([
            order(2, 10004821, "AAPL", "SELL", 20, 0, "LIMIT", 235.00, "WORKING"),
            order(26, 10004821, "NVDA", "BUY", 10, 10, "LIMIT", 136.50, "FILLED"),
            order(51, 20007316, "BND", "BUY", 50, 50, "MARKET", None, "FILLED"),
            order(99, 10004821, "MSFT", "BUY", 5, 0, "LIMIT", 405.00, "CANCELED"),
        ])

    def market_hours(self, symbols, date=None):
        today = datetime.datetime.now(_UTC).date().isoformat()
        hours = {"regularMarket": [{"start": f"{today}T09:30:00-05:00", "end": f"{today}T16:00:00-05:00"}]}
        return _Response({
            "equity": {"EQ": {"productName": "equity", "isOpen": True, "sessionHours": hours}},
            "option": {"EQO": {"productName": "equity option", "isOpen": True, "sessionHours": hours}},
        })

    def quotes(self, symbols, fields=None, indicative=False):
        book = {"SPY": ("SPDR S&P 500 ETF", 598.12, 2.41), "QQQ": ("Invesco QQQ Trust", 512.77, -1.08),
                "AAPL": ("Apple Inc", 228.60, -1.55), "MSFT": ("Microsoft Corp", 431.90, 4.24),
                "NVDA": ("NVIDIA Corp", 138.20, 6.79)}
        out = {}
        for symbol in symbols:
            if symbol in book:
                name, last, change = book[symbol]
                out[symbol] = {"symbol": symbol, "reference": {"description": name},
                               "quote": {"lastPrice": last, "netChange": change,
                                         "netPercentChange": round(change / (last - change) * 100, 2),
                                         "bidPrice": round(last - 0.01, 2), "askPrice": round(last + 0.01, 2),
                                         "totalVolume": int(last * 91000)}}
        return _Response(out)
