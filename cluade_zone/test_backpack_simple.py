"""Backpack API 간단한 테스트"""
import asyncio
import aiohttp
import os

async def test_public_api():
    """공개 API 테스트"""
    async with aiohttp.ClientSession() as session:
        # 마켓 정보 조회 (인증 불필요)
        async with session.get("https://api.backpack.exchange/api/v1/markets") as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Available markets: {len(data)}")
            for market in data[:5]:
                print(f"  - {market.get('symbol', 'N/A')}")

asyncio.run(test_public_api())
