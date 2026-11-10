"""
Turns Schwab API responses into the small, display-ready snapshot the dashboard page shows.

Everything here is read-only: the only client methods used are linked-account, balance,
position, order-history, quote and market-hours lookups. Account numbers are masked and
account hashes are never included in the snapshot.
"""
import collections
import datetime
import re
import threading
import time

_UTC = datetime.timezone.utc
_SYMBOL = re.compile(r"^[A-Za-z0-9$./^ -]{1,24}$")
MAX_SYMBOLS = 30
ORDER_DAYS = 7
REAUTH_MARGIN = 3700  # seconds; below this the library would start an interactive sign-in
OPEN_STATUSES = frozenset({
    "AWAITING_PARENT_ORDER", "AWAITING_CONDITION", "AWAITING_STOP_CONDITION", "AWAITING_MANUAL_REVIEW",
    "ACCEPTED", "PENDING_ACTIVATION", "QUEUED", "WORKING", "NEW", "AWAITING_RELEASE_TIME",
    "PENDING_ACKNOWLEDGEMENT", "PENDING_CANCEL", "PENDING_REPLACE"})


def clean_symbols(raw) -> list[str]:
    """Parse a comma-separated watchlist; drops anything that is not a plausible symbol."""
    if isinstance(raw, str):
        raw = raw.split(",")
    out = []
    for item in raw or []:
        sym = str(item).strip().upper()
        if sym and _SYMBOL.match(sym) and sym not in out:
            out.append(sym)
    return out[:MAX_SYMBOLS]


def mask_account(number) -> str:
    """'12345678' -> '…5678' (the full number never leaves the server)."""
    text = str(number or "")
    return "…" + text[-4:] if text else "…"


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _iso(value):
    """Normalize Schwab timestamps ('2024-03-05T14:30:00+0000') to ISO 8601 that browsers parse."""
    try:
        return datetime.datetime.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return None


def shape_accounts(payload) -> list[dict]:
    accounts = []
    for entry in payload if isinstance(payload, list) else []:
        acct = (entry or {}).get("securitiesAccount") or {}
        balances = acct.get("currentBalances") or {}
        positions = []
        for pos in acct.get("positions") or []:
            instrument = pos.get("instrument") or {}
            quantity = (_num(pos.get("longQuantity")) or 0) - (_num(pos.get("shortQuantity")) or 0)
            positions.append({
                "symbol": str(instrument.get("symbol") or "?"),
                "description": str(instrument.get("description") or ""),
                "asset_type": str(instrument.get("assetType") or ""),
                "quantity": quantity,
                "average_price": _num(pos.get("averagePrice")),
                "market_value": _num(pos.get("marketValue")),
                "day_pl": _num(pos.get("currentDayProfitLoss")),
                "day_pl_pct": _num(pos.get("currentDayProfitLossPercentage")),
                "open_pl": _num(pos.get("longOpenProfitLoss")) if quantity >= 0 else _num(pos.get("shortOpenProfitLoss")),
            })
        positions.sort(key=lambda p: abs(p["market_value"] or 0), reverse=True)
        accounts.append({
            "label": mask_account(acct.get("accountNumber")),
            "type": str(acct.get("type") or ""),
            "value": _num(balances.get("liquidationValue")),
            "cash": _num(balances.get("cashBalance")),
            "buying_power": _num(balances.get("buyingPower")),
            "day_pl": sum(p["day_pl"] or 0 for p in positions),
            "positions": positions,
        })
    return accounts


def shape_orders(payload) -> list[dict]:
    orders = []
    for order in payload if isinstance(payload, list) else []:
        legs = order.get("orderLegCollection") or []
        first = legs[0] if legs else {}
        symbol = str((first.get("instrument") or {}).get("symbol") or "?")
        if len(legs) > 1:
            symbol += f" +{len(legs) - 1} more"
        status = str(order.get("status") or "UNKNOWN")
        orders.append({
            "entered": _iso(order.get("enteredTime")),
            "account": mask_account(order.get("accountNumber")),
            "symbol": symbol,
            "instruction": str(first.get("instruction") or ""),
            "quantity": _num(order.get("quantity")),
            "filled": _num(order.get("filledQuantity")),
            "type": str(order.get("orderType") or ""),
            "price": _num(order.get("price")),
            "status": status,
            "open": status in OPEN_STATUSES,
        })
    orders.sort(key=lambda o: o["entered"] or "", reverse=True)
    return orders


def shape_quotes(payload, symbols) -> list[dict]:
    quotes = []
    payload = payload if isinstance(payload, dict) else {}
    for symbol in symbols:
        item = payload.get(symbol)
        if not isinstance(item, dict):
            quotes.append({"symbol": symbol, "found": False})
            continue
        quote = item.get("quote") or {}
        quotes.append({
            "symbol": symbol,
            "found": True,
            "description": str((item.get("reference") or {}).get("description") or ""),
            "last": _num(quote.get("lastPrice")),
            "change": _num(quote.get("netChange")),
            "change_pct": _num(quote.get("netPercentChange")),
            "bid": _num(quote.get("bidPrice")),
            "ask": _num(quote.get("askPrice")),
            "volume": _num(quote.get("totalVolume")),
        })
    return quotes


def shape_market_hours(payload) -> list[dict]:
    markets = []
    for market, products in (payload if isinstance(payload, dict) else {}).items():
        for product in (products or {}).values():
            if not isinstance(product, dict):
                continue
            regular = ((product.get("sessionHours") or {}).get("regularMarket") or [{}])[0]
            markets.append({
                "market": str(market),
                "name": str(product.get("productName") or product.get("marketType") or market),
                "open_today": bool(product.get("isOpen")),
                "start": _iso(regular.get("start")),
                "end": _iso(regular.get("end")),
            })
            break  # one line per market is enough
    return markets


class Dashboard:
    """Fetches (and briefly caches) a snapshot, and keeps a log of every API call it made."""

    def __init__(self, client, mode: str = "live", cache_seconds: float = 15):
        self._client = client
        self._mode = mode
        self._cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._cache = {}  # symbols tuple -> (monotonic time, snapshot)
        self._activity = collections.deque(maxlen=100)

    def _call(self, label: str, func):
        """Run one API call, record it in the activity log, and return parsed JSON (or raise)."""
        started = time.monotonic()
        entry = {"time": datetime.datetime.now(_UTC).isoformat(), "call": label, "ok": False, "result": "error"}
        try:
            response = func()
            entry["result"] = f"HTTP {response.status_code}"
            if not response.ok:
                raise RuntimeError(f"Schwab answered HTTP {response.status_code}")
            entry["ok"] = True
            return response.json()
        except RuntimeError:
            raise
        except Exception as e:  # network errors etc.; never surface raw bodies or tokens
            entry["result"] = type(e).__name__
            raise RuntimeError(f"request failed ({type(e).__name__})") from None
        finally:
            entry["ms"] = int((time.monotonic() - started) * 1000)
            self._activity.appendleft(entry)

    def _connection(self) -> dict:
        try:
            status = self._client.tokens.status()
        except Exception:
            status = {}
        refresh_left = status.get("refresh_token_seconds_left")
        return {
            "mode": self._mode,
            "access_seconds_left": status.get("access_token_seconds_left"),
            "refresh_seconds_left": refresh_left,
            "encrypted": status.get("encrypted"),
            "reauth_required": refresh_left is not None and refresh_left < REAUTH_MARGIN,
        }

    def snapshot(self, symbols) -> dict:
        symbols = clean_symbols(symbols)
        key = tuple(symbols)
        with self._lock:  # one refresh at a time keeps us far below Schwab's rate limit
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < self._cache_seconds:
                return cached[1]
            snap = self._build(symbols)
            self._cache = {key: (time.monotonic(), snap)}
            return snap

    def _build(self, symbols) -> dict:
        client = self._client
        connection = self._connection()
        snap = {"generated_at": datetime.datetime.now(_UTC).isoformat(), "connection": connection,
                "accounts": [], "orders": [], "quotes": [], "markets": [], "errors": [],
                "order_days": ORDER_DAYS}
        if connection["reauth_required"]:
            # Signing in again needs the terminal; do not let a page refresh trigger that prompt.
            snap["errors"].append("Your Schwab sign-in has expired (it lasts 7 days). "
                                  "Stop the dashboard and start it again to sign in.")
            snap["activity"] = list(self._activity)
            return snap

        now = datetime.datetime.now(_UTC)
        sections = [
            ("accounts", "Accounts and positions", "GET accounts (balances + positions)",
             lambda: client.account_details_all(fields="positions"), shape_accounts),
            ("orders", "Orders", f"GET orders (last {ORDER_DAYS} days)",
             lambda: client.account_orders_all(now - datetime.timedelta(days=ORDER_DAYS), now), shape_orders),
            ("markets", "Market hours", "GET market hours (equity, option)",
             lambda: client.market_hours(["equity", "option"]), shape_market_hours),
        ]
        if symbols:
            sections.append(("quotes", "Watchlist", f"GET quotes ({len(symbols)} symbols)",
                             lambda: client.quotes(symbols), lambda data: shape_quotes(data, symbols)))
        for key, title, label, fetch, shape in sections:
            try:
                snap[key] = shape(self._call(label, fetch))
            except Exception as e:
                snap["errors"].append(f"{title}: {e if isinstance(e, RuntimeError) else 'unexpected response'}")
        snap["connection"]["ok"] = any(entry["ok"] for entry in list(self._activity)[:len(sections)])
        snap["activity"] = list(self._activity)
        return snap
