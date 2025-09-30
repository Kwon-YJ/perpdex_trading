"""Paradex Exchange REST API 클라이언트"""
import asyncio
import time
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except ImportError:
    Account = None
    encode_defunct = None

from base import (
    ExchangeClient, Asset, Balance, Order, OrderResult,
    Position, OrderSide, OrderType
)


class ParadexClient(ExchangeClient):
    """Paradex Exchange API 클라이언트"""

    BASE_URL = "https://api.prod.paradex.trade/v1"

    def __init__(self, l1_address: str, l1_private_key: str):
        super().__init__("Paradex")
        self.l1_address = l1_address
        self.l1_private_key = l1_private_key

        if Account is None:
            raise ImportError("eth-account 라이브러리가 필요합니다")

        # Ethereum account 생성
        self.account = Account.from_key(l1_private_key)

        self.session: Optional[aiohttp.ClientSession] = None
        self.jwt_token: Optional[str] = None
        self.jwt_expiry: Optional[float] = None

    async def _get_jwt_token(self) -> str:
        """JWT 토큰 획득 또는 갱신"""
        # 토큰이 있고 만료되지 않았으면 재사용
        if self.jwt_token and self.jwt_expiry:
            if time.time() < self.jwt_expiry - 60:  # 1분 여유
                return self.jwt_token

        # Paradex는 복잡한 Starknet 온보딩 프로세스가 필요
        # 여기서는 간단히 에러를 발생시킴 - 실제로는 Python SDK 사용 필요
        raise NotImplementedError(
            "Paradex JWT 인증은 Starknet 온보딩이 필요합니다. "
            "paradex-py SDK 사용을 권장합니다."
        )

    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if aiohttp is None:
            print("✗ aiohttp가 설치되지 않았습니다")
            return False

        self.session = aiohttp.ClientSession()

        try:
            # 공개 API만 테스트 (마켓 정보 조회)
            await self.get_available_assets()
            print("✓ Paradex 공개 API 연결 성공")
            print("⚠️ 주의: 거래 기능은 Starknet 온보딩 및 paradex-py SDK가 필요합니다")
            return True
        except Exception as e:
            print(f"Paradex 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def _request(
        self,
        method: str,
        endpoint: str,
        signed: bool = False,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Dict:
        """API 요청 헬퍼"""
        if self.session is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        if signed:
            jwt_token = await self._get_jwt_token()
            headers["Authorization"] = f"Bearer {jwt_token}"

        if method == "GET":
            async with self.session.get(url, headers=headers, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method == "POST":
            async with self.session.post(url, headers=headers, json=json_data) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method == "DELETE":
            async with self.session.delete(url, headers=headers, json=json_data) as resp:
                resp.raise_for_status()
                return await resp.json()
        else:
            raise ValueError(f"지원하지 않는 HTTP 메소드: {method}")

    async def get_available_assets(self) -> List[Asset]:
        """거래 가능한 자산 목록 조회"""
        data = await self._request("GET", "/markets")

        assets = []
        if "results" in data:
            markets = data["results"]
        else:
            markets = data if isinstance(data, list) else []

        for market in markets:
            symbol = market.get("symbol", "")
            # 영구 선물 필터링
            if "PERP" in symbol or market.get("type") == "PERP":
                assets.append(Asset(
                    symbol=symbol,
                    base_asset=market.get("base_currency", symbol.split("-")[0]),
                    quote_asset=market.get("quote_currency", "USD"),
                    min_size=float(market.get("min_order_size", 0.001)),
                    price_precision=int(market.get("price_precision", 2)),
                    size_precision=int(market.get("size_precision", 3))
                ))

        return assets

    async def get_balance(self) -> Balance:
        """계정 잔고 조회"""
        data = await self._request("GET", "/account", signed=True)

        # USDC 또는 USD 잔고 찾기
        total = 0.0
        free = 0.0
        locked = 0.0

        if "results" in data:
            account_data = data["results"]
        else:
            account_data = data

        # 잔고 파싱 (구조는 실제 API 응답에 따라 조정 필요)
        if isinstance(account_data, dict):
            equity = float(account_data.get("equity", 0))
            margin_used = float(account_data.get("margin_balance", 0))
            total = equity
            locked = margin_used
            free = equity - margin_used

        return Balance(
            asset='USDC',
            free=free,
            locked=locked,
            total=total
        )

    async def get_current_price(self, symbol: str) -> float:
        """현재 시장가 조회"""
        data = await self._request("GET", f"/markets/{symbol}")

        if "results" in data:
            market_data = data["results"]
        else:
            market_data = data

        # 최근 거래가 또는 중간가
        last_price = float(market_data.get("last_price", 0))
        if last_price > 0:
            return last_price

        # 대체: bid/ask 중간값
        best_bid = float(market_data.get("best_bid", 0))
        best_ask = float(market_data.get("best_ask", 0))
        if best_bid > 0 and best_ask > 0:
            return (best_bid + best_ask) / 2

        return 0.0

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Tuple[float, float]]:
        """과거 가격 데이터 조회"""
        # Paradex는 /candles 또는 /klines 엔드포인트 사용 (문서 확인 필요)
        # 여기서는 간단한 구현
        try:
            params = {
                "symbol": symbol,
                "resolution": interval,
                "limit": limit
            }
            data = await self._request("GET", "/candles", params=params)

            results = data.get("results", [])
            return [(float(c["timestamp"]), float(c["close"])) for c in results]
        except:
            # 지원하지 않으면 빈 리스트 반환
            return []

    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행"""
        # Paradex 주문 파라미터 구성
        params = {
            "market": order.symbol,
            "side": "BUY" if order.side == OrderSide.LONG else "SELL",
            "type": "MARKET" if order.order_type == OrderType.MARKET else "LIMIT",
            "size": str(order.size),
            "client_id": f"order_{int(time.time() * 1000)}"  # 고유 ID
        }

        if order.price is not None:
            params["price"] = str(order.price)

        # 주문 서명 (Starknet 서명 필요 - 간단화 버전)
        timestamp = int(time.time() * 1000)
        params["timestamp"] = timestamp

        data = await self._request(
            "POST",
            "/orders",
            signed=True,
            json_data=params
        )

        # 응답 파싱
        if "results" in data:
            order_data = data["results"]
        else:
            order_data = data

        return OrderResult(
            order_id=str(order_data.get("id", "")),
            symbol=order.symbol,
            side=order.side,
            size=float(order_data.get("size", order.size)),
            filled_price=float(order_data.get("average_price", order.price or 0)),
            status=order_data.get("status", "unknown"),
            timestamp=time.time()
        )

    async def get_positions(self) -> List[Position]:
        """현재 보유 포지션 조회"""
        data = await self._request("GET", "/positions", signed=True)

        positions = []
        results = data.get("results", [])

        for pos in results:
            size = float(pos.get("size", 0))
            if size == 0:
                continue

            # 롱/숏 판별
            side = OrderSide.LONG if size > 0 else OrderSide.SHORT

            positions.append(Position(
                exchange=self.name,
                symbol=pos.get("market", ""),
                side=side,
                size=abs(size),
                entry_price=float(pos.get("entry_price", 0)),
                current_price=float(pos.get("mark_price", 0)),
                unrealized_pnl=float(pos.get("unrealized_pnl", 0)),
                leverage=float(pos.get("leverage", 1)),
                liquidation_price=float(pos.get("liquidation_price")) if pos.get("liquidation_price") else None
            ))

        return positions

    async def close_position(self, symbol: str) -> OrderResult:
        """포지션 청산"""
        # 현재 포지션 확인
        positions = await self.get_positions()
        target_pos = None
        for pos in positions:
            if pos.symbol == symbol:
                target_pos = pos
                break

        if target_pos is None:
            raise ValueError(f"포지션을 찾을 수 없음: {symbol}")

        # 반대 방향 시장가 주문
        opposite_side = OrderSide.SHORT if target_pos.side == OrderSide.LONG else OrderSide.LONG

        close_order = Order(
            symbol=symbol,
            side=opposite_side,
            order_type=OrderType.MARKET,
            size=target_pos.size
        )

        return await self.place_order(close_order)

    async def close_all_positions(self) -> List[OrderResult]:
        """모든 포지션 청산"""
        positions = await self.get_positions()
        results = []

        for pos in positions:
            try:
                result = await self.close_position(pos.symbol)
                results.append(result)
            except Exception as e:
                print(f"포지션 청산 실패 {pos.symbol}: {e}")

        return results

    async def check_liquidation_risk(self) -> bool:
        """강제 청산 위험 체크"""
        positions = await self.get_positions()

        for pos in positions:
            if pos.liquidation_price is None:
                continue

            # 현재가가 청산가에 5% 이내로 접근하면 위험
            if pos.side == OrderSide.LONG:
                if pos.current_price <= pos.liquidation_price * 1.05:
                    return True
            else:  # SHORT
                if pos.current_price >= pos.liquidation_price * 0.95:
                    return True

        return False

    async def close(self):
        """클라이언트 종료"""
        if self.session:
            await self.session.close()


# 테스트 코드
async def test_paradex():
    """Paradex 클라이언트 테스트"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    l1_address = os.getenv("PARADEX_PUB_KEY")
    l1_private_key = os.getenv("PARADEX_SEC_KEY")

    if not l1_address or not l1_private_key:
        print("API 키가 설정되지 않았습니다")
        return

    client = ParadexClient(l1_address, l1_private_key)

    try:
        # 초기화
        if not await client.initialize():
            print("초기화 실패")
            return

        print("✓ 초기화 성공")

        # 잔고 조회
        balance = await client.get_balance()
        print(f"✓ 잔고: {balance.total} USDC (가용: {balance.free})")

        # 자산 목록
        assets = await client.get_available_assets()
        print(f"✓ 거래 가능한 자산: {len(assets)}개")
        for asset in assets[:5]:
            print(f"  - {asset.symbol}")

        # 현재 가격
        if assets:
            symbol = assets[0].symbol
            price = await client.get_current_price(symbol)
            print(f"✓ {symbol} 현재가: ${price}")

        # 포지션 조회
        positions = await client.get_positions()
        print(f"✓ 현재 포지션: {len(positions)}개")
        for pos in positions:
            print(f"  - {pos.symbol} {pos.side.value} {pos.size} @ ${pos.entry_price}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_paradex())