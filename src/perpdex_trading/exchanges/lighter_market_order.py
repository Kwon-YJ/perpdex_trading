# -*- coding: utf-8 -*-
"""
Lighter Exchange - Place Market and Limit Orders via REST API

Requirements:
    pip install lighter-sdk python-dotenv

Environment Variables:
    LIGHTER_BASE_URL         : API base URL (mainnet: https://mainnet.zklighter.elliot.ai)
    LIGHTER_PRIVATE_KEY      : ETH private key (0x...)
    LIGHTER_API_KEY_INDEX    : API key index (default: 0)
    LIGHTER_ACCOUNT_INDEX    : Account index (default: 0)

Examples:
    # Market order - Buy 0.01 BTC at market price
    python lighter_market_order.py market BTC BUY 0.01

    # Limit order - Buy 0.001 BTC at $110,000
    python lighter_market_order.py limit BTC BUY 0.001 --price 110000

    # Market order - Buy 0.1 ETH
    python lighter_market_order.py market ETH BUY 0.1

    # Testnet
    python lighter_market_order.py market BTC BUY 0.001 --testnet

    # Function usage
    from lighter_market_order import place_market_order, place_limit_order
    result = await place_market_order(ticker='BTC', side='BUY', qty=0.01)
    result = await place_limit_order(ticker='BTC', side='BUY', qty=0.001, price=110000)
"""

import asyncio
import os
import sys
import argparse
import time
from typing import Optional, Dict, Any
from decimal import Decimal
from dotenv import load_dotenv

MAINNET_URL = "https://mainnet.zklighter.elliot.ai"
TESTNET_URL = "https://testnet.zklighter.elliot.ai"

# Market indices (active markets as of Jan 2025)
MARKET_INDICES = {
    "0G": 84,
    "1000BONK": 18,
    "1000FLOKI": 19,
    "1000PEPE": 4,
    "1000SHIB": 17,
    "1000TOSHI": 81,
    "AAVE": 27,
    "ADA": 39,
    "AERO": 65,
    "AI16Z": 22,
    "APEX": 86,
    "APT": 31,
    "ARB": 50,
    "ASTER": 83,
    "AVAX": 9,
    "AVNT": 82,
    "BCH": 58,
    "BERA": 20,
    "BNB": 25,
    "BTC": 1,
    "CRO": 73,
    "CRV": 36,
    "DOGE": 3,
    "DOLO": 75,
    "DOT": 11,
    "DYDX": 62,
    "EIGEN": 49,
    "ENA": 29,
    "ETH": 0,
    "ETHFI": 64,
    "FARTCOIN": 21,
    "FF": 87,
    "GMX": 61,
    "GRASS": 52,
    "HBAR": 59,
    "HYPE": 24,
    "IP": 34,
    "JUP": 26,
    "KAITO": 33,
    "LAUNCHCOIN": 54,
    "LDO": 46,
    "LINEA": 76,
    "LINK": 8,
    "LTC": 35,
    "MNT": 63,
    "MORPHO": 68,
    "MYX": 80,
    "NEAR": 10,
    "NMR": 74,
    "ONDO": 38,
    "OP": 55,
    "PAXG": 48,
    "PENDLE": 37,
    "PENGU": 47,
    "POL": 14,
    "POPCAT": 23,
    "PROVE": 57,
    "PUMP": 45,
    "PYTH": 78,
    "RESOLV": 51,
    "S": 40,
    "SEI": 32,
    "SKY": 79,
    "SOL": 2,
    "SPX": 42,
    "STBL": 85,
    "SUI": 16,
    "SYRUP": 44,
    "TAO": 13,
    "TIA": 67,
    "TON": 12,
    "TRUMP": 15,
    "TRX": 43,
    "UNI": 30,
    "USELESS": 66,
    "VIRTUAL": 41,
    "VVV": 69,
    "WIF": 5,
    "WLD": 6,
    "WLFI": 72,
    "XMR": 77,
    "XPL": 71,
    "XRP": 7,
    "YZY": 70,
    "ZK": 56,
    "ZORA": 53,
    "ZRO": 60,
}


async def get_market_info(base_url: str) -> Dict[str, Any]:
    """Get market information from exchange via direct REST call."""
    import aiohttp

    url = f"{base_url}/api/v1/orderBookDetails"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"Failed to get market info: HTTP {response.status}")

            data = await response.json()

            market_map = {}
            for market in data.get("order_book_details", []):
                # Skip inactive markets to avoid SDK validation issues
                if market.get("status") != "active":
                    continue

                symbol = market.get("symbol", "").upper()
                market_map[symbol] = {
                    "index": market.get("market_id"),
                    "tick_size": float(10 ** -market.get("price_decimals", 2)),
                    "lot_size": float(10 ** -market.get("size_decimals", 4)),
                    "min_base_amount": float(market.get("min_base_amount", "0")),
                    "min_quote_amount": float(market.get("min_quote_amount", "0")),
                    "price_decimals": market.get("price_decimals", 2),
                    "size_decimals": market.get("size_decimals", 4),
                    "last_price": float(market.get("last_trade_price", 0)) if market.get("last_trade_price") else None,
                }

            return market_map


async def place_market_order(
    ticker: str,
    side: str,
    qty: float,
    base_url: Optional[str] = None,
    private_key: Optional[str] = None,
    api_key_index: int = 0,
    account_index: int = 0,
) -> Dict[str, Any]:
    """
    Place a market order on Lighter exchange using direct sign + send method.

    Args:
        ticker: Trading pair symbol (e.g., 'BTC', 'ETH', 'SOL')
        side: Order side - 'BUY' or 'SELL'
        qty: Order quantity in base asset
        base_url: API base URL (defaults to LIGHTER_BASE_URL env var)
        private_key: ETH private key (defaults to LIGHTER_PRIVATE_KEY env var)
        api_key_index: API key index (defaults to LIGHTER_API_KEY_INDEX env var or 0)
        account_index: Account index (defaults to LIGHTER_ACCOUNT_INDEX env var or 0)

    Returns:
        Dict containing order response from exchange

    Raises:
        ValueError: If credentials are missing or invalid parameters
        RuntimeError: If order placement fails
    """
    try:
        import lighter
    except ImportError:
        raise ImportError(
            "lighter-sdk not installed. Install with: pip install lighter-sdk"
        )

    # Get credentials
    url = base_url or os.getenv("LIGHTER_BASE_URL", MAINNET_URL)
    pk = private_key or os.getenv("LIGHTER_PRIVATE_KEY")
    api_idx = int(os.getenv("LIGHTER_API_KEY_INDEX", api_key_index))
    acc_idx = int(os.getenv("LIGHTER_ACCOUNT_INDEX", account_index))

    if not pk:
        raise ValueError(
            "Private key required. Set LIGHTER_PRIVATE_KEY environment variable or pass as argument."
        )

    # Validate parameters
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Invalid side '{side}'. Must be 'BUY' or 'SELL'.")

    ticker = ticker.upper()
    is_ask = (side == "SELL")

    # Initialize signer
    signer = lighter.SignerClient(
        url=url,
        private_key=pk,
        api_key_index=api_idx,
        account_index=acc_idx,
    )

    try:
        # Get market info
        market_map = await get_market_info(url)

        if ticker not in market_map:
            raise ValueError(f"Market '{ticker}' not found. Available: {list(market_map.keys())}")

        market_info = market_map[ticker]
        market_index = market_info["index"]
        lot_size = Decimal(str(market_info["lot_size"]))
        size_decimals = market_info["size_decimals"]

        # Quantize quantity to lot size
        base_amount_dec = Decimal(str(qty))
        base_amount_dec = (base_amount_dec // lot_size) * lot_size

        # Convert to exchange units using size_decimals (NOT 1e18!)
        base_amount = int(base_amount_dec * Decimal(10 ** size_decimals))

        if base_amount <= 0:
            raise ValueError(f"Quantity {qty} too small. Minimum lot size: {lot_size}")

        # Get current price for reference
        if market_info["last_price"]:
            mid_price = Decimal(str(market_info["last_price"]))
        else:
            raise RuntimeError("Could not determine market price (no last_trade_price)")

        # Convert price using price_decimals
        price_decimals = market_info["price_decimals"]
        avg_execution_price = int(mid_price * Decimal(10 ** price_decimals))

        # Generate unique client order index
        client_order_index = int(time.time() * 1000) % 2**32

        print(f"Placing MARKET order: {side} {qty} {ticker}")
        print(f"  Market Index: {market_index}")
        print(f"  Base Amount: {base_amount_dec}")
        print(f"  Estimated Price: {mid_price}")

        # Sign and send market order directly
        tx_info, err = signer.sign_create_order(
            market_index=market_index,
            client_order_index=client_order_index,
            base_amount=base_amount,
            price=avg_execution_price,
            is_ask=int(is_ask),
            order_type=signer.ORDER_TYPE_MARKET,
            time_in_force=signer.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
            reduce_only=0,
            trigger_price=signer.NIL_TRIGGER_PRICE,
            order_expiry=signer.DEFAULT_IOC_EXPIRY,
            nonce=-1,
        )

        if err:
            raise RuntimeError(f"Failed to sign order: {err}")

        resp = await signer.send_tx(
            tx_type=signer.TX_TYPE_CREATE_ORDER,
            tx_info=tx_info
        )

        print(f"✓ Order placed successfully")
        print(f"  Response Code: {resp.code}")
        print(f"  Message: {resp.message}")
        print(f"  TX Hash: {resp.tx_hash}")

        return {
            "ticker": ticker,
            "side": side,
            "qty": str(base_amount_dec),
            "market_index": market_index,
            "client_order_index": client_order_index,
            "tx_hash": resp.tx_hash if resp.tx_hash else "N/A",
            "response_code": resp.code,
            "response_message": resp.message,
        }

    finally:
        await signer.close()


async def place_limit_order(
    ticker: str,
    side: str,
    qty: float,
    price: float,
    base_url: Optional[str] = None,
    private_key: Optional[str] = None,
    api_key_index: int = 0,
    account_index: int = 0,
) -> Dict[str, Any]:
    """
    Place a limit order on Lighter exchange using direct sign + send method.

    Args:
        ticker: Trading pair symbol (e.g., 'BTC', 'ETH', 'SOL')
        side: Order side - 'BUY' or 'SELL'
        qty: Order quantity in base asset
        price: Limit price
        base_url: API base URL (defaults to LIGHTER_BASE_URL env var)
        private_key: ETH private key (defaults to LIGHTER_PRIVATE_KEY env var)
        api_key_index: API key index (defaults to LIGHTER_API_KEY_INDEX env var or 0)
        account_index: Account index (defaults to LIGHTER_ACCOUNT_INDEX env var or 0)

    Returns:
        Dict containing order response from exchange

    Raises:
        ValueError: If credentials are missing or invalid parameters
        RuntimeError: If order placement fails
    """
    try:
        import lighter
    except ImportError:
        raise ImportError(
            "lighter-sdk not installed. Install with: pip install lighter-sdk"
        )

    # Get credentials
    url = base_url or os.getenv("LIGHTER_BASE_URL", MAINNET_URL)
    pk = private_key or os.getenv("LIGHTER_PRIVATE_KEY")
    api_idx = int(os.getenv("LIGHTER_API_KEY_INDEX", api_key_index))
    acc_idx = int(os.getenv("LIGHTER_ACCOUNT_INDEX", account_index))

    if not pk:
        raise ValueError(
            "Private key required. Set LIGHTER_PRIVATE_KEY environment variable or pass as argument."
        )

    # Validate parameters
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"Invalid side '{side}'. Must be 'BUY' or 'SELL'.")

    ticker = ticker.upper()
    is_ask = (side == "SELL")

    # Initialize signer
    signer = lighter.SignerClient(
        url=url,
        private_key=pk,
        api_key_index=api_idx,
        account_index=acc_idx,
    )

    try:
        # Get market info
        market_map = await get_market_info(url)

        if ticker not in market_map:
            raise ValueError(f"Market '{ticker}' not found. Available: {list(market_map.keys())}")

        market_info = market_map[ticker]
        market_index = market_info["index"]
        lot_size = Decimal(str(market_info["lot_size"]))
        tick_size = Decimal(str(market_info["tick_size"]))
        size_decimals = market_info["size_decimals"]
        price_decimals = market_info["price_decimals"]

        # Quantize quantity to lot size
        base_amount_dec = Decimal(str(qty))
        base_amount_dec = (base_amount_dec // lot_size) * lot_size

        # Convert to exchange units using size_decimals (NOT 1e18!)
        base_amount = int(base_amount_dec * Decimal(10 ** size_decimals))

        if base_amount <= 0:
            raise ValueError(f"Quantity {qty} too small. Minimum lot size: {lot_size}")

        # Quantize price to tick size
        price_dec = Decimal(str(price))
        price_dec = (price_dec // tick_size) * tick_size

        # Convert price using price_decimals (NOT 1e18!)
        limit_price = int(price_dec * Decimal(10 ** price_decimals))

        if limit_price <= 0:
            raise ValueError(f"Price {price} too small. Minimum tick size: {tick_size}")

        # Generate unique client order index
        client_order_index = int(time.time() * 1000) % 2**32

        print(f"Placing LIMIT order: {side} {qty} {ticker} @ {price}")
        print(f"  Market Index: {market_index}")
        print(f"  Base Amount: {base_amount_dec}")
        print(f"  Limit Price: {price_dec}")

        # Sign and send limit order directly
        tx_info, err = signer.sign_create_order(
            market_index=market_index,
            client_order_index=client_order_index,
            base_amount=base_amount,
            price=limit_price,
            is_ask=int(is_ask),
            order_type=signer.ORDER_TYPE_LIMIT,
            time_in_force=signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
            reduce_only=0,
            trigger_price=signer.NIL_TRIGGER_PRICE,
            order_expiry=-1,
            nonce=-1,
        )

        if err:
            raise RuntimeError(f"Failed to sign order: {err}")

        resp = await signer.send_tx(
            tx_type=signer.TX_TYPE_CREATE_ORDER,
            tx_info=tx_info
        )

        print(f"✓ Order placed successfully")
        print(f"  Response Code: {resp.code}")
        print(f"  Message: {resp.message}")
        print(f"  TX Hash: {resp.tx_hash}")

        return {
            "ticker": ticker,
            "side": side,
            "qty": str(base_amount_dec),
            "price": str(price_dec),
            "market_index": market_index,
            "client_order_index": client_order_index,
            "tx_hash": resp.tx_hash if resp.tx_hash else "N/A",
            "response_code": resp.code,
            "response_message": resp.message,
        }

    finally:
        await signer.close()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Place market or limit orders on Lighter exchange",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Market order - Buy 0.01 BTC
  %(prog)s market BTC BUY 0.01

  # Limit order - Sell 0.5 ETH at $2500
  %(prog)s limit ETH SELL 0.5 --price 2500.0

  # Use testnet
  %(prog)s market SOL BUY 1 --testnet
        """
    )

    parser.add_argument(
        "order_type",
        choices=["market", "limit"],
        help="Order type"
    )
    parser.add_argument(
        "ticker",
        help="Trading pair symbol (e.g., BTC, ETH, SOL)"
    )
    parser.add_argument(
        "side",
        choices=["BUY", "SELL", "buy", "sell"],
        help="Order side"
    )
    parser.add_argument(
        "qty",
        type=float,
        help="Order quantity"
    )
    parser.add_argument(
        "--price",
        type=float,
        help="Limit price (required for limit orders)"
    )
    parser.add_argument(
        "--private-key",
        default=os.getenv("LIGHTER_PRIVATE_KEY"),
        help="ETH private key (default: LIGHTER_PRIVATE_KEY env var)"
    )
    parser.add_argument(
        "--api-key-index",
        type=int,
        default=int(os.getenv("LIGHTER_API_KEY_INDEX", "0")),
        help="API key index (default: 0)"
    )
    parser.add_argument(
        "--account-index",
        type=int,
        default=int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0")),
        help="Account index (default: 0)"
    )
    parser.add_argument(
        "--testnet",
        action="store_true",
        help="Use testnet instead of mainnet"
    )

    return parser.parse_args()


async def main():
    """Main CLI entry point."""
    load_dotenv()
    args = parse_args()

    base_url = TESTNET_URL if args.testnet else MAINNET_URL

    try:
        if args.order_type == "market":
            result = await place_market_order(
                ticker=args.ticker,
                side=args.side,
                qty=args.qty,
                base_url=base_url,
                private_key=args.private_key,
                api_key_index=args.api_key_index,
                account_index=args.account_index,
            )
        else:  # limit
            if args.price is None:
                print("Error: --price is required for limit orders", file=sys.stderr)
                sys.exit(1)

            result = await place_limit_order(
                ticker=args.ticker,
                side=args.side,
                qty=args.qty,
                price=args.price,
                base_url=base_url,
                private_key=args.private_key,
                api_key_index=args.api_key_index,
                account_index=args.account_index,
            )

        print("\n=== Order Result ===")
        import json
        print(json.dumps(result, indent=2, default=str))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # CLI 사용
    asyncio.run(main())
