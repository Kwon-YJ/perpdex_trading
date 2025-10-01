#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Place a MARKET order on Ostium via the official Python SDK,
while using REST endpoints to check trading hours and (optionally) display latest prices.

Requirements
------------
pip install ostium-python-sdk python-dotenv requests eth-account

Env Vars
--------
OSTIUM_PRIVATE_KEY   : EVM private key (hex, 0x...)
OSTIUM_RPC_URL       : Arbitrum RPC (e.g., https://arb-mainnet.g.alchemy.com/v2/XXXX or Sepolia)

Examples
--------
# 100 USDC 담보에 10배 레버리지로 BTC-USD 롱 (메인넷)
python ostium_place_market_order.py BTC BUY --collateral 100 --leverage 10 --network mainnet

# 명목 USD(=담보*레버리지)로 2,000 USD 숏 (담보 자동계산)
python ostium_place_market_order.py EURUSD SELL --notional-usd 2000 --leverage 20 --network mainnet

# 장외 시간 경고 무시(--force), 커스텀 슬리피지 0.75%
python ostium_place_market_order.py XAUUSD BUY --collateral 50 --leverage 5 --slippage-pct 0.75 --force
"""
import argparse
import asyncio
import os
import sys
import time
from typing import Dict, Optional, Tuple

import requests
from dotenv import load_dotenv
from eth_account import Account  # only to print your public address
from ostium_python_sdk import OstiumSDK, NetworkConfig  # official SDK

from decimal import Decimal

REST_BASE = "https://metadata-backend.ostium.io"

# Fallback static mapping (as of May 2025, subject to change)
# If dynamic lookup via subgraph fails, we fall back to these indices.
FALLBACK_PAIR_ID: Dict[str, int] = {
    "BTC-USD": 0, "ETH-USD": 1, "EUR-USD": 2, "GBP-USD": 3, "USD-JPY": 4,
    "XAU-USD": 5, "HG-USD": 6,  "CL-USD": 7, "XAG-USD": 8, "SOL-USD": 9,
    "SPX-USD": 10, "DJI-USD": 11, "NDX-USD": 12, "NIK-JPY": 13, "FTSE-GBP": 14,
    "DAX-EUR": 15, "USD-CAD": 16, "USD-MXN": 17, "NVDA-USD": 18, "GOOG-USD": 19,
    "AMZN-USD": 20, "META-USD": 21, "TSLA-USD": 22, "AAPL-USD": 23, "MSFT-USD": 24,
}

FX_QUOTES = {"USD", "EUR", "JPY", "GBP", "CAD", "MXN"}
CRYPTO_DEFAULT_QUOTE = "USD"


def normalize_symbol(user_sym: str) -> str:
    """Return canonical 'BASE-QUOTE' (e.g., BTC-USD, EUR-USD, USD-JPY, XAU-USD)."""
    s = user_sym.strip().upper().replace("/", "-").replace(":", "-").replace("_", "-")
    if "-" in s:
        base, quote = s.split("-", 1)
        return f"{base}-{quote}"
    # Guess split for FX like EURUSD / USDJPY
    for q in sorted(FX_QUOTES, key=len, reverse=True):
        if s.endswith(q) and len(s) > len(q):
            base = s[:-len(q)]
            return f"{base}-{q}"
    # Stocks/crypto tickers default to -USD
    return f"{s}-{CRYPTO_DEFAULT_QUOTE}"


def to_asset_code_for_rest(sym_norm: str) -> str:
    """REST expects 'EURUSD', 'BTCUSD' (no dash)."""
    return sym_norm.replace("-", "")


def get_trading_hours(sym_norm: str, timeout=6) -> Tuple[bool, Optional[dict]]:
    """Check whether the asset is currently tradable (isOpenNow) via REST."""
    code = to_asset_code_for_rest(sym_norm)
    url = f"{REST_BASE}/trading-hours/asset-schedule"
    try:
        r = requests.get(url, params={"asset": code}, timeout=timeout)
        if r.ok:
            data = r.json()
            return bool(data.get("isOpenNow", True)), data
    except Exception:
        pass
    # If REST fails, default to open (SDK tx will revert if actually blocked)
    return True, None


async def resolve_pair_id(sdk: OstiumSDK, sym_norm: str) -> int:
    """Try to resolve pair id dynamically from subgraph, otherwise fallback."""
    wanted = {sym_norm, sym_norm.replace("-", ""), sym_norm.replace("-", "/")}
    try:
        pairs = await sdk.subgraph.get_pairs()
        for p in pairs:
            # collect candidate strings
            candidates = []
            for k in ("symbol", "pairSymbol", "ticker", "name", "pairName"):
                v = p.get(k)
                if isinstance(v, str):
                    candidates.append(v.upper())
            # reconstruct from 'from'/'to' if present
            if "from" in p and "to" in p:
                base = str(p["from"]).upper()
                quote = str(p["to"]).upper()
                candidates += [f"{base}-{quote}", f"{base}{quote}", f"{base}/{quote}"]
            for cand in candidates:
                cset = {normalize_symbol(cand), cand.replace("-", ""), cand.replace("-", "/")}
                if wanted & cset:
                    # id can be "id" or similar; ensure int
                    for id_key in ("id", "pairId", "pairIndex", "asset_type", "assetTypeId"):
                        if id_key in p:
                            return int(p[id_key])
        # fallback
    except Exception:
        pass
    if sym_norm in FALLBACK_PAIR_ID:
        return FALLBACK_PAIR_ID[sym_norm]
    raise ValueError(f"Could not resolve pair id for symbol='{sym_norm}'. Try a different spelling.")


async def get_latest_price(sdk: OstiumSDK, sym_norm: str) -> float:
    """Use SDK price feed (returns (price, _, _))."""
    base, quote = sym_norm.split("-")
    price, _, _ = await sdk.price.get_price(base, quote)
    if price is None:
        raise RuntimeError(f"Failed to fetch latest price for {sym_norm}")
    return float(price)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Place a MARKET order on Ostium via SDK.")
    p.add_argument("symbol", help="e.g., BTC, BTC-USD, EURUSD, XAUUSD, TSLA")
    p.add_argument("side", choices=["BUY", "SELL", "LONG", "SHORT"], help="BUY/LONG or SELL/SHORT")
    gsize = p.add_mutually_exclusive_group(required=True)
    gsize.add_argument("--collateral", type=float, help="Collateral in USDC (e.g., 100)")
    gsize.add_argument("--notional-usd", type=float, help="Position notional in USD (collateral = notional/leverage)")
    p.add_argument("--leverage", type=float, required=True, help="Leverage (e.g., 10)")
    p.add_argument("--tp-price", type=float, default=None, help="Optional Take Profit price")
    p.add_argument("--sl-price", type=float, default=None, help="Optional Stop Loss price")
    p.add_argument("--slippage-pct", type=float, default=1.0, help="Max slippage percent (default: 1.0)")
    p.add_argument("--network", choices=["mainnet", "testnet"], default="mainnet")
    p.add_argument("--rpc-url", default=os.getenv("OSTIUM_RPC_URL"), help="Override RPC URL (else uses OSTIUM_RPC_URL env)")
    p.add_argument("--private-key", default=os.getenv("OSTIUM_PRIVATE_KEY"), help="Override private key (else uses OSTIUM_PRIVATE_KEY env)")
    p.add_argument("--force", action="store_true", help="Ignore trading-hours closed warning")
    p.add_argument("--dry-run", action="store_true", help="Compute & print, but do NOT send transaction")
    return p.parse_args()


async def main():
    args = parse_args()

    sym_norm = normalize_symbol(args.symbol)
    direction_long = args.side in ("BUY", "LONG")

    if args.private_key is None or args.rpc_url is None:
        print("ERROR: Provide OSTIUM_PRIVATE_KEY and OSTIUM_RPC_URL (or use --private-key/--rpc-url).", file=sys.stderr)
        sys.exit(2)

    # Network config
    config = NetworkConfig.mainnet() if args.network == "mainnet" else NetworkConfig.testnet()
    sdk = OstiumSDK(config, args.private_key, args.rpc_url, verbose=True)

    # Check trading hours via REST
    is_open, hours_payload = get_trading_hours(sym_norm)
    if not is_open and not args.force:
        print(f"[ABORT] Market seems CLOSED for {sym_norm}. Use --force to override.\nPayload={hours_payload}", file=sys.stderr)
        sys.exit(3)

    # Resolve pair id & latest price
    pair_id = await resolve_pair_id(sdk, sym_norm)
    last_price = await get_latest_price(sdk, sym_norm)

    # Determine collateral
    if args.notional_usd is not None:
        collateral = float(args.notional_usd) / float(args.leverage)
    else:
        collateral = float(args.collateral)

    print("=== Order Preview ===")
    print(f"Symbol        : {sym_norm}")
    print(f"Side          : {'LONG' if direction_long else 'SHORT'}")
    print(f"Collateral    : {collateral} USDC")
    print(f"Leverage      : {args.leverage}x")
    print(f"Notional(≈)   : {collateral * args.leverage:.4f} USD")
    print(f"Latest Price  : {last_price}")
    print(f"Pair ID       : {pair_id}")
    if args.tp_price: print(f"TP Price      : {args.tp_price}")
    if args.sl_price: print(f"SL Price      : {args.sl_price}")
    print(f"Slippage Max  : {args.slippage_pct}%")
    print(f"Network       : {args.network}")
    acct = Account.from_key(args.private_key)
    print(f"Trader Addr   : {acct.address}")
    print("====================")

    if args.dry_run:
        print("[DRY-RUN] Not sending transaction.")
        return

    # Build trade params and place MARKET order
    trade_params = {
        "collateral": collateral,
        "leverage": float(args.leverage),
        "asset_type": int(pair_id),         # pair id
        "direction": bool(direction_long),  # True: Long, False: Short
        "order_type": "MARKET",
    }
    if args.tp_price is not None:
        trade_params["tp"] = float(args.tp_price)
    if args.sl_price is not None:
        trade_params["sl"] = float(args.sl_price)

    # set slippage and execute at current price
    # sdk.ostium.set_slippage_percentage(float(args.slippage_pct))
    sdk.ostium.set_slippage_percentage(Decimal(str(args.slippage_pct)))
    print(f"Slippage set to: {sdk.ostium.get_slippage_percentage()}%")

    print("Submitting transaction...")
    t0 = time.time()
    receipt = sdk.ostium.perform_trade(trade_params, at_price=last_price)
    t1 = time.time()
    tx_hash = receipt.get("transactionHash")
    if hasattr(tx_hash, "hex"):
        tx_hash = tx_hash.hex()

    print("\n=== Submitted ===")
    print(f"TX Hash       : {tx_hash}")
    print(f"Elapsed       : {t1 - t0:.2f}s")
    print("Note: Check your block explorer for confirmation and status.")
    print("=================")


if __name__ == "__main__":
    load_dotenv()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user.")
