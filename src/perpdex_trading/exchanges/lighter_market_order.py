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

    # Limit order - Sell 0.5 ETH at $2500
    python lighter_market_order.py limit ETH SELL 0.5 --price 2500.0

    # Function usage
    from lighter_market_order import place_market_order, place_limit_order
    result = await place_market_order(ticker='BTC', side='BUY', qty=0.01)
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

# Market indices - update these based on your markets
MARKET_INDICES = {
    "BTC": 0,
    "ETH": 1,
    "SOL": 2,
    # Add more markets as needed
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
    Place a market order on Lighter exchange.

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

    # Initialize clients
    api_client = lighter.ApiClient()
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

        # Quantize quantity to lot size
        base_amount_dec = Decimal(str(qty))
        base_amount_dec = (base_amount_dec // lot_size) * lot_size
        base_amount = int(base_amount_dec * Decimal("1e18"))  # Convert to wei-like units

        if base_amount <= 0:
            raise ValueError(f"Quantity {qty} too small. Minimum lot size: {lot_size}")

        # Get current price for reference
        if market_info["last_price"]:
            mid_price = Decimal(str(market_info["last_price"]))
        else:
            raise RuntimeError("Could not determine market price (no last_trade_price)")

        avg_execution_price = int(mid_price * Decimal("1e18"))

        # Generate unique client order index
        client_order_index = int(time.time() * 1000) % 2**32

        print(f"Placing MARKET order: {side} {qty} {ticker}")
        print(f"  Market Index: {market_index}")
        print(f"  Base Amount: {base_amount_dec}")
        print(f"  Estimated Price: {mid_price}")

        # Place market order
        try:
            create_order, tx_hash, order_id = await signer.create_market_order(
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=base_amount,
                avg_execution_price=avg_execution_price,
                is_ask=is_ask,
                reduce_only=False,
            )

            # Check if there was an error (order_id contains error message)
            if isinstance(order_id, str) and order_id:
                raise RuntimeError(f"Order failed: {order_id}")

            print(f"✓ Order placed successfully")
            print(f"  TX Hash: {tx_hash}")
            if order_id:
                print(f"  Order ID: {order_id}")

            return {
                "ticker": ticker,
                "side": side,
                "qty": str(base_amount_dec),
                "market_index": market_index,
                "tx_hash": tx_hash if tx_hash else "N/A",
                "order_id": order_id if order_id else "N/A",
                "client_order_index": client_order_index,
            }
        except AttributeError as e:
            # SDK has a bug with response handling, but order may have been sent
            print(f"⚠ Warning: SDK response error (order may still be placed): {e}")
            print(f"  Client Order Index: {client_order_index}")
            print(f"  Check your account to verify order status")

            return {
                "ticker": ticker,
                "side": side,
                "qty": str(base_amount_dec),
                "market_index": market_index,
                "client_order_index": client_order_index,
                "status": "sent_but_unconfirmed",
                "warning": str(e),
            }

    finally:
        await api_client.close()
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
    Place a limit order on Lighter exchange.

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

    # Initialize clients
    api_client = lighter.ApiClient()
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

        # Quantize quantity to lot size
        base_amount_dec = Decimal(str(qty))
        base_amount_dec = (base_amount_dec // lot_size) * lot_size
        base_amount = int(base_amount_dec * Decimal("1e18"))

        if base_amount <= 0:
            raise ValueError(f"Quantity {qty} too small. Minimum lot size: {lot_size}")

        # Quantize price to tick size
        price_dec = Decimal(str(price))
        price_dec = (price_dec // tick_size) * tick_size
        limit_price = int(price_dec * Decimal("1e18"))

        if limit_price <= 0:
            raise ValueError(f"Price {price} too small. Minimum tick size: {tick_size}")

        # Generate unique client order index
        client_order_index = int(time.time() * 1000) % 2**32

        print(f"Placing LIMIT order: {side} {qty} {ticker} @ {price}")
        print(f"  Market Index: {market_index}")
        print(f"  Base Amount: {base_amount_dec}")
        print(f"  Limit Price: {price_dec}")

        # Place limit order
        try:
            create_order, tx_hash, order_id = await signer.create_order(
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=base_amount,
                price=limit_price,
                is_ask=is_ask,
                order_type=signer.ORDER_TYPE_LIMIT,
                time_in_force=signer.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                reduce_only=False,
            )

            # Check if there was an error (order_id contains error message)
            if isinstance(order_id, str) and order_id:
                raise RuntimeError(f"Order failed: {order_id}")

            print(f"✓ Order placed successfully")
            print(f"  TX Hash: {tx_hash}")
            if order_id:
                print(f"  Order ID: {order_id}")

            return {
                "ticker": ticker,
                "side": side,
                "qty": str(base_amount_dec),
                "price": str(price_dec),
                "market_index": market_index,
                "tx_hash": tx_hash if tx_hash else "N/A",
                "order_id": order_id if order_id else "N/A",
                "client_order_index": client_order_index,
            }
        except AttributeError as e:
            # SDK has a bug with response handling, but order may have been sent
            print(f"⚠ Warning: SDK response error (order may still be placed): {e}")
            print(f"  Client Order Index: {client_order_index}")
            print(f"  Check your account to verify order status")

            return {
                "ticker": ticker,
                "side": side,
                "qty": str(base_amount_dec),
                "price": str(price_dec),
                "market_index": market_index,
                "client_order_index": client_order_index,
                "status": "sent_but_unconfirmed",
                "warning": str(e),
            }

    finally:
        await api_client.close()
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
    asyncio.run(main())
