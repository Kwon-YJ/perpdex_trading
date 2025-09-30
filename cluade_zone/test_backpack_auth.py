"""Test Backpack authentication"""
import asyncio
import time
import hmac
import hashlib
import base64
import os
from dotenv import load_dotenv
import aiohttp

load_dotenv()

api_key = os.getenv("BACKPACK_PUBLIC_KEY")
secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

print(f"API Key: {api_key}")
print(f"Secret Key: {secret_key[:20]}...")

async def test_auth():
    """Test authentication"""
    timestamp = str(int(time.time() * 1000))
    window = "5000"

    method = "GET"
    endpoint = "/api/v1/capital"
    instruction = "balanceQuery"

    sign_str = f"instruction={instruction}&timestamp={timestamp}&window={window}"

    print(f"\nTimestamp: {timestamp}")
    print(f"Window: {window}")
    print(f"Instruction: {instruction}")
    print(f"Sign string: {sign_str}")

    # Generate signature
    secret_bytes = base64.b64decode(secret_key)
    print(f"Secret bytes length: {len(secret_bytes)}")

    signature = base64.b64encode(
        hmac.new(
            secret_bytes,
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).digest()
    ).decode('utf-8')

    print(f"Signature: {signature}")

    # Make request
    url = f"https://api.backpack.exchange{endpoint}"
    headers = {
        "X-API-Key": api_key,
        "X-Signature": signature,
        "X-Timestamp": timestamp,
        "X-Window": window,
        "Content-Type": "application/json"
    }

    print(f"\nURL: {url}")
    print(f"Headers: {headers}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            print(f"\nStatus: {resp.status}")
            text = await resp.text()
            print(f"Response: {text[:500]}")

if __name__ == "__main__":
    asyncio.run(test_auth())