# -*- coding: utf-8 -*-
"""
GRVT Perpetuals - Place Market / Limit Orders via REST API

Requirements:
    pip install requests eth-account python-dotenv

Environment variables:
    GRVT_ENV=mainnet|testnet                # default: mainnet
    GRVT_API_KEY=<your_api_key>             # from GRVT UI
    GRVT_API_PRIVATE_KEY=<0x...>            # ETH private key tagged to the API key (for EIP-712 order signing)
    GRVT_SUB_ACCOUNT_ID=<your_trading_sub_account_id>   # trading account id (sub account)

Usage examples:
    # Market BUY 0.01 BTC perp
    python grvt_place_order.py market BTC 0.01 BUY

    # Limit SELL 0.5 ETH perp @ $2500, GTT
    python grvt_place_order.py limit ETH 0.5 SELL --price 2500

    # As library
    from grvt_place_order import place_market_order, place_limit_order
"""

import os
import json
import time
import random
import argparse
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data
from dotenv import load_dotenv

load_dotenv()

# ---------- ENV / ENDPOINTS ----------
ENV = os.getenv("GRVT_ENV", "mainnet").lower()
if ENV not in ("mainnet", "testnet"):
    ENV = "mainnet"


ENDPOINTS = {
    "mainnet": {
        "edge": "https://edge.grvt.io",
        "trades": "https://trades.grvt.io",
        "market_data": "https://market-data.grvt.io",
        "chain_id": 325,  # GRVT L2 chain id (EIP-712 domain)
    },
    "testnet": {
        "edge": "https://edge.testnet.grvt.io",
        "trades": "https://trades.testnet.grvt.io",
        "market_data": "https://market-data.testnet.grvt.io",
        "chain_id": 326,
    },
}

API_KEY = os.getenv("GRVT_API_KEY", "")
API_PRIVKEY = os.getenv("GRVT_API_PRIVATE_KEY", "")
SUB_ACCOUNT_ID = os.getenv("GRVT_SUB_ACCOUNT_ID", "")  # trading account id (sub-account)

if not API_KEY or not API_PRIVKEY or not SUB_ACCOUNT_ID:
    # 실행시 점검 메시지 (라이브러리 사용 시엔 무시 가능)
    print("[WARN] Missing envs: GRVT_API_KEY / GRVT_API_PRIVATE_KEY / GRVT_SUB_ACCOUNT_ID")

# ---------- HELPERS ----------
def _auth_session() -> tuple[requests.Session, str]:
    s = requests.Session()
    url = f"{ENDPOINTS[ENV]['edge']}/auth/api_key/login"
    resp = s.post(
        url,
        json={"api_key": API_KEY},
        headers={"Content-Type": "application/json", "Cookie": "rm=true;"},
        allow_redirects=True,  # 리다이렉트 따라가되
        timeout=15,
    )
    resp.raise_for_status()

    # 최종 응답과 리다이렉트 히스토리에서 모두 탐색
    def pick_account_id(r: requests.Response) -> str | None:
        h = r.headers
        return (
            h.get("X-Grvt-Account-Id")
            or h.get("x-grvt-account-id")
            or h.get("X-GRVT-Account-Id")
        )

    grvt_account_id = pick_account_id(resp)
    if not grvt_account_id:
        for r in resp.history:
            grvt_account_id = pick_account_id(r)
            if grvt_account_id:
                break

    if not grvt_account_id:
        raise RuntimeError(
            f"Login ok ({resp.status_code}), but missing X-Grvt-Account-Id header. "
            f"Check GRVT_ENV ({ENV}) matches your API key env (testnet vs mainnet), "
            "and that your API key is active."
        )
    return s, grvt_account_id

def _instrument_name_from_ticker(ticker: str) -> str:
    # 'BTC', 'BTC-USDT', 'BTC_USDT', 'BTC/USDT', 'BTC_USDT_Perp' 모두 허용
    t = ticker.replace("/", "_").replace("-", "_")
    parts = t.split("_")
    base = parts[0].upper()
    quote = parts[1].upper() if len(parts) > 1 else "USDT"
    # GRVT 표기: BTC_USDT_Perp  (Perp의 P만 대문자)
    return f"{base}_{quote}_Perp"



def _fetch_instrument(instr: str) -> Dict[str, Any]:
    """
    Fetch instrument metadata (tick_size, min_size, decimals...). No auth required.
    """
    url = f"{ENDPOINTS[ENV]['market_data']}/full/v1/instruments"
    body = {
        "kind": ["PERPETUAL"],
        "base": [instr.split("_")[0]],
        "quote": [instr.split("_")[1]],
        "is_active": True,
        "limit": 500,
    }
    r = requests.post(url, json=body, timeout=10)
    r.raise_for_status()
    data = r.json()
    # API returns a list of instruments; pick matching instrument string precisely
    instruments = data.get("result") or data.get("r") or []
    for it in instruments:
        # full variant uses full field names; ensure both are handled
        name = it.get("instrument") or it.get("i")
        if str(name).upper() == instr:
            return it
    # fallback: if only 1 instrument returned, use it
    if len(instruments) == 1:
        return instruments[0]
    raise RuntimeError(f"Instrument not found: {instr}")

def _round_to_tick(price: float, tick_size_str: str, side: str) -> float:
    """
    Round price to tick size (floor for BUY, ceil for SELL to be conservative).
    tick_size is string like '1', '0.1', '0.5'
    """
    ts = float(tick_size_str)
    if ts <= 0:
        return price
    q = price / ts
    if side.upper() == "BUY":
        q = int(q)  # floor
    else:
        # sell: round up to next tick to avoid post-only rejection/overfill surprises
        q = int(q) if abs(q - int(q)) < 1e-12 else int(q) + 1
    return q * ts

def _ensure_min_size(qty: float, min_size_str: str) -> float:
    ms = float(min_size_str)
    if qty < ms:
        return ms
    return qty

def _rand_u32() -> int:
    return random.randint(0, 2**32 - 1)

def _ns_from_hours(hours: float) -> int:
    return int(time.time_ns() + hours * 3600 * 1e9)

# ----- EIP-712 order signing (based on GRVT order schema) -----
# Docs: Order schema + Create Order endpoint; price is expressed in 9 decimals; signature requires scaled integers. :contentReference[oaicite:5]{index=5}
PRICE_MULTIPLIER = 1_000_000_000

@dataclass
class OrderLeg:
    instrument: str     # e.g., BTC_USDT_Perp
    size: float         # in base asset units (decimal)
    limit_price: Optional[float]  # None for market; otherwise decimal
    is_buy: bool

def _encode_asset_id_from_instrument(instr: str) -> str:
    """
    Encode assetID (uint256 hex string) from instrument string.
    For PERP: 3 bytes: [quoteId, underlyingId, kind=1], then hex-encode (left as short hex).
    Currency enum ids per docs (USD=1, USDC=2, USDT=3, ETH=4, BTC=5, ...). :contentReference[oaicite:6]{index=6}
    This minimalist encoder covers PERPETUALs for common pairs (BTC/ETH/etc.). For full coverage,
    prefer using instrument_hash if/when the API exposes it in the instrument payload (instrument_hash). :contentReference[oaicite:7]{index=7}
    """
    base, quote, suffix = instr.split("_")
    # mapping for common currencies
    CUR = {
        "USD": 1, "USDC": 2, "USDT": 3, "ETH": 4, "BTC": 5, "SOL": 6, "ARB": 7, "BNB": 8, "ZK": 9,
        "POL": 10, "OP": 11, "ATOM": 12, "KPEPE": 13, "TON": 14, "XRP": 15, "TRUMP": 20, "SUI": 21,
    }  # extend if needed
    if suffix.upper() != "PERP":
        raise ValueError("Only PERP instruments are supported by this helper")
    if base not in CUR or quote not in CUR:
        raise ValueError(f"Unsupported currency mapping for {instr}. Add to CUR map.")
    kind_perp = 1
    msg = bytearray(3)
    msg[2] = kind_perp
    msg[1] = CUR[base]
    msg[0] = CUR[quote]
    return "0x" + msg.hex()

def _build_signable_eip712(order_dict: Dict[str, Any]) -> Any:
    """
    Build EIP-712 typed data for the Order object (Full variant).
    """
    typed_types = {
        "Order": [
            {"name": "subAccountID", "type": "uint64"},
            {"name": "isMarket", "type": "bool"},
            {"name": "timeInForce", "type": "uint8"},
            {"name": "postOnly", "type": "bool"},
            {"name": "reduceOnly", "type": "bool"},
            {"name": "legs", "type": "OrderLeg[]"},
            {"name": "nonce", "type": "uint32"},
            {"name": "expiration", "type": "int64"},
        ],
        "OrderLeg": [
            {"name": "assetID", "type": "uint256"},
            {"name": "contractSize", "type": "uint64"},
            {"name": "limitPrice", "type": "uint64"},
            {"name": "isBuyingContract", "type": "bool"},
        ],
    }

    # Map TIF string to enum (GOOD_TILL_TIME=1, IMMEDIATE_OR_CANCEL=3, FILL_OR_KILL=4) :contentReference[oaicite:8]{index=8}
    tif_map = {"GOOD_TILL_TIME": 1, "IMMEDIATE_OR_CANCEL": 3, "FILL_OR_KILL": 4}
    tif_value = tif_map[order_dict["time_in_force"]]

    legs_typed = []
    for leg in order_dict["legs"]:
        asset_id = _encode_asset_id_from_instrument(leg["instrument"])
        # For signature: size and price are scaled to 9 decimals (docs/gist) :contentReference[oaicite:9]{index=9}
        contract_size = int(round(float(leg["size"]) * 1_000_000_000))
        limit_price = int(round(float(leg["limit_price"] or 0.0) * PRICE_MULTIPLIER))
        legs_typed.append(
            {
                "assetID": asset_id,
                "contractSize": contract_size,
                "limitPrice": limit_price,
                "isBuyingContract": bool(leg["is_buying_asset"]),
            }
        )

    message = {
        "subAccountID": int(order_dict["sub_account_id"]),
        "isMarket": bool(order_dict["is_market"]),
        "timeInForce": tif_value,
        "postOnly": bool(order_dict["post_only"]),
        "reduceOnly": bool(order_dict["reduce_only"]),
        "legs": legs_typed,
        "nonce": int(order_dict["signature"]["nonce"]),
        "expiration": int(order_dict["signature"]["expiration"]),
    }
    domain = {"name": "GRVT Exchange", "version": "0", "chainId": ENDPOINTS[ENV]["chain_id"]}
    return encode_typed_data(domain, typed_types, message)

def _sign_order(full_order_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sign EIP-712 order; fill r,s,v,signer in 'signature'.
    """
    signable = _build_signable_eip712(full_order_payload)
    signed = Account.sign_message(signable, private_key=API_PRIVKEY)
    r = "0x" + hex(signed.r)[2:].zfill(64)
    s = "0x" + hex(signed.s)[2:].zfill(64)
    v = signed.v
    full_order_payload["signature"].update({
        "r": r, "s": s, "v": v, "signer": Account.from_key(API_PRIVKEY).address.lower()
    })
    return full_order_payload


def _prepare_order_payload(*, instrument: str, side: str, qty: float,
                           is_market: bool, price: Optional[float],
                           tif: str, post_only: bool=False, reduce_only: bool=False) -> Dict[str, Any]:
    sig = {
        "expiration": str(_ns_from_hours(3)),
        "nonce": _rand_u32(),
        "r": "0x0", "s": "0x0", "v": 0, "signer": "0x0",
    }
    leg = {
        "instrument": instrument,
        "size": str(qty),
        # 마켓주문은 null 대신 "0" 사용(더 호환성 좋음)
        "limit_price": "0" if is_market else str(price),
        "is_buying_asset": True if side.upper() == "BUY" else False,
    }
    return {
        "sub_account_id": str(SUB_ACCOUNT_ID),
        "is_market": bool(is_market),
        "time_in_force": tif,  # "IMMEDIATE_OR_CANCEL" 등
        "post_only": bool(post_only),
        "reduce_only": bool(reduce_only),
        "legs": [leg],
        "signature": {**sig},
        "metadata": {"client_order_id": str(_rand_u32())},
    }




def _submit_order(order_payload: Dict[str, Any]) -> Dict[str, Any]:
    session, grvt_account_id = _auth_session()
    # edge 로그인에서 받은 세션 쿠키(gravity)를 trades에도 명시적으로 전달
    gravity = session.cookies.get("gravity")
    headers = {
        "Content-Type": "application/json",
        "X-Grvt-Account-Id": grvt_account_id,
    }
    if gravity:
        headers["Cookie"] = f"gravity={gravity}"

    url = f"{ENDPOINTS[ENV]['trades']}/full/v1/create_order"
    resp = session.post(url, json={"order": order_payload}, headers=headers, timeout=15)

    # 4xx/5xx에서 원인 파악을 위해 서버 메시지 노출
    if not resp.ok:
        try:
            err = resp.json()
        except Exception:
            err = {"raw": resp.text}
        raise RuntimeError(f"[{resp.status_code}] create_order failed: {err}")

    return resp.json()



def _precheck_and_quantize(instrument: str, qty: float, price: Optional[float], side: str) -> Tuple[float, Optional[float]]:
    """
    Use instrument metadata to enforce min_size and tick_size alignment.
    """
    meta = _fetch_instrument(instrument)
    # full variant fields
    tick_size = meta.get("tick_size") or meta.get("ts") or "0"
    min_size  = meta.get("min_size") or meta.get("ms") or "0"
    qty_adj = _ensure_min_size(qty, min_size)
    if price is None:
        return qty_adj, None
    price_adj = _round_to_tick(float(price), str(tick_size), side)
    return qty_adj, price_adj

# ---------- PUBLIC API ----------
def place_market_order(ticker: str, qty: float, side: str, reduce_only: bool=False) -> Dict[str, Any]:
    """
    Market order (IOC by default)
    :param ticker: e.g. 'BTC', 'BTC-USDT', 'BTC_USDT_Perp'
    :param qty: base size (e.g. 0.01)
    :param side: 'BUY' or 'SELL'
    :param reduce_only: optional
    """
    instrument = _instrument_name_from_ticker(ticker)
    qty_adj, _ = _precheck_and_quantize(instrument, qty, None, side)
    order = _prepare_order_payload(
        instrument=instrument,
        side=side,
        qty=qty_adj,
        is_market=True,
        price=None,
        tif="IMMEDIATE_OR_CANCEL",  # IOC for market orders :contentReference[oaicite:13]{index=13}
        post_only=False,
        reduce_only=reduce_only,
    )
    order = _sign_order(order)
    return _submit_order(order)

def place_limit_order(ticker: str, qty: float, side: str, price: float,
                      tif: str="GOOD_TILL_TIME", post_only: bool=False, reduce_only: bool=False) -> Dict[str, Any]:
    """
    Limit order
    :param tif: 'GOOD_TILL_TIME' (GTT), 'IMMEDIATE_OR_CANCEL' (IOC), or 'FILL_OR_KILL' (FOK)
    """
    instrument = _instrument_name_from_ticker(ticker)
    qty_adj, price_adj = _precheck_and_quantize(instrument, qty, price, side)
    order = _prepare_order_payload(
        instrument=instrument,
        side=side,
        qty=qty_adj,
        is_market=False,
        price=price_adj,
        tif=tif,
        post_only=post_only,
        reduce_only=reduce_only,
    )
    order = _sign_order(order)
    return _submit_order(order)

# ---------- CLI ----------
def _build_cli():
    p = argparse.ArgumentParser(description="GRVT Perps order submitter")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("market", help="Place market order (IOC)")
    m.add_argument("ticker", type=str, help="e.g. BTC, BTC-USDT, BTC_USDT_Perp")
    m.add_argument("qty", type=float, help="base size, e.g. 0.01")
    m.add_argument("side", choices=["BUY", "SELL"])

    l = sub.add_parser("limit", help="Place limit order")
    l.add_argument("ticker", type=str)
    l.add_argument("qty", type=float)
    l.add_argument("side", choices=["BUY", "SELL"])
    l.add_argument("--price", type=float, required=True)
    l.add_argument("--tif", type=str, default="GOOD_TILL_TIME", choices=["GOOD_TILL_TIME", "IMMEDIATE_OR_CANCEL", "FILL_OR_KILL"])
    l.add_argument("--post-only", action="store_true")
    l.add_argument("--reduce-only", action="store_true")

    return p

if __name__ == "__main__":
    args = _build_cli().parse_args()
    if args.cmd == "market":
        res = place_market_order(args.ticker, args.qty, args.side)
    else:
        res = place_limit_order(args.ticker, args.qty, args.side, args.price, tif=args.tif,
                                post_only=args.post_only, reduce_only=args.reduce_only)
    print(json.dumps(res, indent=2, ensure_ascii=False))


