#!/usr/bin/env python3
"""
Aster Perpetual (Pro) REST trader

Submit BUY/SELL orders to Aster Perpetual (orderbook futures) via REST.

Prereqs
- Python 3.9+
- pip install requests python-dotenv
- Create a .env file with:
    ASTER_API_KEY=your_key
    ASTER_API_SECRET=your_secret

Examples
- Market buy 0.001 BTCUSDT (and sync server time first):
    python aster_order.py order --symbol BTCUSDT --side BUY --type MARKET --qty 0.001 --sync-time

- Limit sell 0.02 ETHUSDT @ 2600 GTC:
    python aster_order.py order --symbol ETHUSDT --side SELL --type LIMIT --qty 0.02 --price 2600 --tif GTC

- Set leverage to 10x for BTCUSDT:
    python aster_order.py leverage --symbol BTCUSDT --leverage 10

- Query an order:
    python aster_order.py get --symbol BTCUSDT --orderId 123456789

- Cancel an order:
    python aster_order.py cancel --symbol BTCUSDT --orderId 123456789

Notes
- Base URL: https://fapi.asterdex.com
- Auth header: X-MBX-APIKEY
- SIGNED endpoints require timestamp, optional recvWindow (default 5000 ms), and HMAC SHA256 signature of the query/body using your API secret.
- If you see a timing/recvWindow error, use --sync-time and/or increase --recvWindow.
- If your account is in Hedge Mode, pass --posSide LONG/SHORT; otherwise default BOTH is used.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv


class AsterClient:
    BASE_URL = "https://fapi.asterdex.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str | None = None,
        timeout: int = 10,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("API key/secret are required. Set ASTER_API_KEY and ASTER_API_SECRET in your environment or .env file.")
        self.api_key = api_key
        self.api_secret = api_secret.encode()
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key, "Content-Type": "application/x-www-form-urlencoded"})
        self._time_offset_ms = 0

    # ----- time -----
    def sync_time(self) -> int:
        """Sync local clock with server and return offset in ms (server - local)."""
        url = f"{self.base_url}/fapi/v1/time"
        r = self.session.get(url, timeout=self.timeout)
        r.raise_for_status()
        server_time = int(r.json()["serverTime"])  # ms
        local_time = int(time.time() * 1000)
        self._time_offset_ms = server_time - local_time
        return self._time_offset_ms

    def _timestamp(self) -> int:
        return int(time.time() * 1000) + int(self._time_offset_ms)

    # ----- signing & request -----
    def _sign(self, params: Dict[str, Any]) -> str:
        query = urlencode(params, doseq=True)
        signature = hmac.new(self.api_secret, query.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{query}&signature={signature}"

    def _request(self, method: str, path: str, params: Optional[Dict[str, Any]] = None, signed: bool = False) -> Any:
        url = f"{self.base_url}{path}"
        params = params or {}
        if signed:
            params.setdefault("recvWindow", 5000)
            params["timestamp"] = self._timestamp()
            payload = self._sign(params)
            if method in ("GET", "DELETE"):
                url = f"{url}?{payload}"
                data = None
            else:
                data = payload
        else:
            if method in ("GET", "DELETE") and params:
                url = f"{url}?{urlencode(params, doseq=True)}"
                data = None
            else:
                data = urlencode(params, doseq=True) if params else None

        r = self.session.request(method, url, data=data, timeout=self.timeout)
        # try to surface API error messages cleanly
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            try:
                err = r.json()
                msg = err.get("msg") or err
            except Exception:
                msg = r.text
            raise SystemExit(f"HTTP {r.status_code}: {msg}") from e
        return r.json() if r.text else {}

    # ----- public -----
    def ping(self) -> Any:
        return self._request("GET", "/fapi/v1/ping", signed=False)

    # ----- trading -----
    def new_order(
        self,
        *,
        symbol: str,
        side: str,
        type: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        time_in_force: Optional[str] = None,
        position_side: Optional[str] = None,  # BOTH|LONG|SHORT
        reduce_only: Optional[bool] = None,
        stop_price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        recv_window: Optional[int] = None,
    ) -> Any:
        path = "/fapi/v1/order"
        params: Dict[str, Any] = {
            "symbol": normalize_symbol(symbol),
            "side": side.upper(),
            "type": type.upper(),
        }
        if position_side:
            params["positionSide"] = position_side.upper()
        if quantity is not None:
            params["quantity"] = format_number(quantity)
        if price is not None:
            params["price"] = format_number(price)
        if stop_price is not None:
            params["stopPrice"] = format_number(stop_price)
        if time_in_force:
            params["timeInForce"] = time_in_force.upper()
        if reduce_only is not None:
            # API expects string true/false in some implementations
            params["reduceOnly"] = str(bool(reduce_only)).lower()
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if recv_window is not None:
            params["recvWindow"] = int(recv_window)

        return self._request("POST", path, params=params, signed=True)

    def cancel_order(
        self,
        *,
        symbol: str,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
        recv_window: Optional[int] = None,
    ) -> Any:
        if not order_id and not orig_client_order_id:
            raise ValueError("Either order_id or orig_client_order_id must be provided")
        params: Dict[str, Any] = {"symbol": normalize_symbol(symbol)}
        if order_id:
            params["orderId"] = int(order_id)
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        if recv_window is not None:
            params["recvWindow"] = int(recv_window)
        return self._request("DELETE", "/fapi/v1/order", params=params, signed=True)

    def get_order(
        self,
        *,
        symbol: str,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
        recv_window: Optional[int] = None,
    ) -> Any:
        if not order_id and not orig_client_order_id:
            raise ValueError("Either order_id or orig_client_order_id must be provided")
        params: Dict[str, Any] = {"symbol": normalize_symbol(symbol)}
        if order_id:
            params["orderId"] = int(order_id)
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        if recv_window is not None:
            params["recvWindow"] = int(recv_window)
        return self._request("GET", "/fapi/v1/order", params=params, signed=True)

    def set_leverage(self, *, symbol: str, leverage: int, recv_window: Optional[int] = None) -> Any:
        if leverage < 1 or leverage > 125:
            raise ValueError("leverage must be between 1 and 125")
        params: Dict[str, Any] = {
            "symbol": normalize_symbol(symbol),
            "leverage": int(leverage),
        }
        if recv_window is not None:
            params["recvWindow"] = int(recv_window)
        return self._request("POST", "/fapi/v1/leverage", params=params, signed=True)

    def set_margin_type(self, *, symbol: str, margin_type: str, recv_window: Optional[int] = None) -> Any:
        m = margin_type.upper()
        if m not in {"ISOLATED", "CROSSED"}:
            raise ValueError("margin_type must be ISOLATED or CROSSED")
        params: Dict[str, Any] = {"symbol": normalize_symbol(symbol), "marginType": m}
        if recv_window is not None:
            params["recvWindow"] = int(recv_window)
        return self._request("POST", "/fapi/v1/marginType", params=params, signed=True)


# -------- helpers --------

def normalize_symbol(symbol: str) -> str:
    """Convert common forms like 'BTC/USDT' to 'BTCUSDT'. Leaves already-normalized symbols alone."""
    s = symbol.strip().upper().replace("-", "").replace(":USDT", "")
    if "/" in s:
        base, quote = s.split("/", 1)
        return f"{base}{quote}"
    return s


def format_number(x: float | int | str) -> str:
    """Return a string without scientific notation, trimming trailing zeros."""
    if isinstance(x, str):
        return x
    s = ("%f" % float(x)).rstrip("0").rstrip(".")
    return s if s else "0"


# -------- CLI --------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Aster Perpetual (Pro) REST trader")
    p.add_argument("--base-url", default=AsterClient.BASE_URL, help="Override base URL if needed")
    p.add_argument("--timeout", type=int, default=10, help="HTTP timeout seconds")
    p.add_argument("--recvWindow", type=int, default=None, help="recvWindow in ms for signed endpoints")
    p.add_argument("--sync-time", action="store_true", help="Sync server time before requests")

    sub = p.add_subparsers(dest="cmd", required=True)

    # order
    o = sub.add_parser("order", help="Place a new order")
    o.add_argument("--symbol", required=True)
    o.add_argument("--side", required=True, choices=["BUY", "SELL", "buy", "sell"]) 
    o.add_argument("--type", required=True, choices=[
        "MARKET", "LIMIT", "STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET",
        "market", "limit", "stop", "stop_market", "take_profit", "take_profit_market",
    ])
    o.add_argument("--qty", type=float, required=False, help="Order quantity (base asset)")
    o.add_argument("--price", type=float, help="Price for LIMIT/STOP/TP orders")
    o.add_argument("--stopPrice", type=float, help="Trigger price for STOP/TAKE_PROFIT orders")
    o.add_argument("--tif", dest="timeInForce", choices=["GTC", "IOC", "FOK", "GTX"], help="Time in force for LIMIT orders")
    o.add_argument("--posSide", choices=["BOTH", "LONG", "SHORT"], help="Position side (Hedge Mode requires LONG/SHORT)")
    o.add_argument("--reduceOnly", action="store_true", help="Mark order as reduceOnly")
    o.add_argument("--clientId", help="Custom client order ID")

    # get
    g = sub.add_parser("get", help="Get order status")
    g.add_argument("--symbol", required=True)
    g.add_argument("--orderId", type=int)
    g.add_argument("--origClientOrderId")

    # cancel
    c = sub.add_parser("cancel", help="Cancel an order")
    c.add_argument("--symbol", required=True)
    c.add_argument("--orderId", type=int)
    c.add_argument("--origClientOrderId")

    # leverage
    l = sub.add_parser("leverage", help="Set initial leverage")
    l.add_argument("--symbol", required=True)
    l.add_argument("--leverage", type=int, required=True)

    # margin type
    m = sub.add_parser("margin", help="Set margin type (ISOLATED/CROSSED)")
    m.add_argument("--symbol", required=True)
    m.add_argument("--type", required=True, choices=["ISOLATED", "CROSSED", "isolated", "crossed"]) 

    return p


def main() -> None:
    load_dotenv()
    api_key = os.getenv("ASTER_PUB_KEY")
    api_secret = os.getenv("ASTER_SEC_KEY")

    parser = build_parser()
    args = parser.parse_args()

    client = AsterClient(api_key=api_key or "", api_secret=api_secret or "", base_url=args.base_url, timeout=args.timeout)

    if args.sync_time:
        offset = client.sync_time()
        print(json.dumps({"_info": f"time_offset_ms={offset}"}, ensure_ascii=False))

    if args.cmd == "order":
        resp = client.new_order(
            symbol=args.symbol,
            side=args.side,
            type=args.type,
            quantity=args.qty,
            price=args.price,
            time_in_force=args.timeInForce,
            position_side=args.posSide,
            reduce_only=bool(args.reduceOnly),
            stop_price=args.stopPrice,
            client_order_id=args.clientId,
            recv_window=args.recvWindow,
        )
        print(json.dumps(resp, indent=2, ensure_ascii=False))

    elif args.cmd == "get":
        resp = client.get_order(
            symbol=args.symbol,
            order_id=args.orderId,
            orig_client_order_id=args.origClientOrderId,
            recv_window=args.recvWindow,
        )
        print(json.dumps(resp, indent=2, ensure_ascii=False))

    elif args.cmd == "cancel":
        resp = client.cancel_order(
            symbol=args.symbol,
            order_id=args.orderId,
            orig_client_order_id=args.origClientOrderId,
            recv_window=args.recvWindow,
        )
        print(json.dumps(resp, indent=2, ensure_ascii=False))

    elif args.cmd == "leverage":
        resp = client.set_leverage(symbol=args.symbol, leverage=args.leverage, recv_window=args.recvWindow)
        print(json.dumps(resp, indent=2, ensure_ascii=False))

    elif args.cmd == "margin":
        resp = client.set_margin_type(symbol=args.symbol, margin_type=args.type, recv_window=args.recvWindow)
        print(json.dumps(resp, indent=2, ensure_ascii=False))

    else:
        parser.error("Unknown command")


if __name__ == "__main__":
    main()
