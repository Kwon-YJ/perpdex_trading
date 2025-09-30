"""Test single Backpack order placement"""
import asyncio
import os
import sys

sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')

from dotenv import load_dotenv
load_dotenv()

from backpack_client import BackpackClient
from base import Order, OrderSide, OrderType


async def test_order():
    """Test placing a single order"""
    api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not api_key or not secret_key:
        print("API keys not found")
        return

    client = BackpackClient(api_key, secret_key)

    try:
        # Initialize
        if not await client.initialize():
            print("Initialization failed")
            return

        print("✓ Initialization successful")

        # Get balance
        balance = await client.get_balance()
        print(f"✓ Balance: {balance.total} USDT (available: {balance.free})")

        # Get available assets
        assets = await client.get_available_assets()
        print(f"✓ Available assets: {len(assets)}")

        if not assets:
            print("No assets available")
            return

        # Try to find SOL_USDC_PERP
        sol_asset = None
        for asset in assets:
            if 'SOL' in asset.symbol and 'USDC' in asset.symbol:
                sol_asset = asset
                break

        if not sol_asset:
            sol_asset = assets[0]

        print(f"\nTesting with: {sol_asset.symbol}")
        print(f"  Min size: {sol_asset.min_size}")
        print(f"  Size precision: {sol_asset.size_precision}")

        # Get current price
        price = await client.get_current_price(sol_asset.symbol)
        print(f"  Current price: ${price}")

        # Calculate a small order size ($10 worth)
        order_value = 10.0
        size = order_value / price

        # Round to precision, but also make sure it's not longer than min_size
        # Backpack is very strict about decimal places
        size_precision = min(sol_asset.size_precision, 2)  # Max 2 decimals for safety
        size = round(size, size_precision)

        # Make sure we meet minimum size
        if size < sol_asset.min_size:
            size = sol_asset.min_size

        print(f"\nAttempting to place order:")
        print(f"  Symbol: {sol_asset.symbol}")
        print(f"  Side: LONG (Buy)")
        print(f"  Type: MARKET")
        print(f"  Size: {size} (precision: {size_precision})")
        print(f"  Value: ${size * price:.2f}")

        # Place market buy order
        order = Order(
            symbol=sol_asset.symbol,
            side=OrderSide.LONG,
            order_type=OrderType.MARKET,
            size=size
        )

        try:
            result = await client.place_order(order)
            print(f"\n✓ Order successful!")
            print(f"  Order ID: {result.order_id}")
            print(f"  Filled: {result.size}")
            print(f"  Price: ${result.filled_price}")
            print(f"  Status: {result.status}")
        except Exception as e:
            print(f"\n✗ Order failed: {e}")

            # Try to get more details
            import traceback
            print("\nFull error:")
            traceback.print_exc()

            # Check if it's an HTTP error
            if hasattr(e, 'status'):
                print(f"HTTP Status: {e.status}")
            if hasattr(e, 'message'):
                print(f"Message: {e.message}")
            if hasattr(e, 'url'):
                print(f"URL: {e.url}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_order())