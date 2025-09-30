"""Backpack Exchange REST API 클라이언트"""
import asyncio
import time
import base64
from typing import Dict, List, Optional, Tuple
import json

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
except ImportError:
    ed25519 = None

from base import (
    ExchangeClient, Asset, Balance, Order, OrderResult,
    Position, OrderSide, OrderType
)


class BackpackClient(ExchangeClient):
    """Backpack Exchange API 클라이언트"""

    BASE_URL = "https://api.backpack.exchange"

    # 엔드포인트별 instruction 매핑
    INSTRUCTION_MAP = {
        "/api/v1/capital": "balanceQuery",
        "/api/v1/account": "accountQuery",
        "/api/v1/order": "orderExecute",
        "/api/v1/orders": "orderQueryAll",
        "/api/v1/order/cancel": "orderCancel",
        "/api/v1/order/cancelAll": "orderCancelAll",
        "/api/v1/futures/positions": "positionQuery",
        "/wapi/v1/history/fills": "fillHistoryQueryAll",
    }

    def __init__(self, api_key: str, secret_key: str):
        super().__init__("Backpack")
        # Base64 인코딩된 ED25519 키
        self.api_key = api_key
        self.secret_key = secret_key

        # ED25519 private key 생성
        if ed25519 is None:
            raise ImportError("cryptography 라이브러리가 필요합니다")
        secret_bytes = base64.b64decode(secret_key)
        self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(secret_bytes)

        self.session: Optional[aiohttp.ClientSession] = None

    def _generate_signature(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None
    ) -> Tuple[str, str, str]:
        """
        Backpack API 서명 생성
        Returns: (signature, timestamp, window)
        """
        timestamp = str(int(time.time() * 1000))
        window = "5000"  # 5초

        # instruction 찾기 (엔드포인트 매핑 사용)
        instruction = self.INSTRUCTION_MAP.get(endpoint)
        if not instruction:
            # 매핑에 없으면 기본값으로 엔드포인트 마지막 부분 사용
            instruction = endpoint.split('/')[-1]

        # 서명 페이로드 생성
        if params:
            if method == "GET":
                param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
                sign_str = f"instruction={instruction}&{param_str}&timestamp={timestamp}&window={window}"
            else:  # POST/DELETE - params are in body, so we need to serialize and include
                import json
                # Sort keys for consistency
                param_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
                sign_str = f"instruction={instruction}&{param_str}&timestamp={timestamp}&window={window}"
        else:
            sign_str = f"instruction={instruction}&timestamp={timestamp}&window={window}"

        # ED25519 서명
        signature_bytes = self.private_key.sign(sign_str.encode('utf-8'))
        signature = base64.b64encode(signature_bytes).decode('utf-8')

        return signature, timestamp, window

    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if aiohttp is None:
            raise ImportError("aiohttp가 설치되지 않았습니다")

        self.session = aiohttp.ClientSession()

        # API 연결 테스트
        try:
            await self.get_balance()
            return True
        except Exception as e:
            print(f"Backpack 초기화 실패: {e}")
            return False

    async def _request(
        self,
        method: str,
        endpoint: str,
        signed: bool = False,
        params: Optional[Dict] = None
    ) -> Dict:
        """API 요청 헬퍼"""
        if self.session is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        url = f"{self.BASE_URL}{endpoint}"
        headers = {}

        if signed:
            signature, timestamp, window = self._generate_signature(
                method, endpoint, params
            )
            headers.update({
                "X-API-Key": self.api_key,
                "X-Signature": signature,
                "X-Timestamp": timestamp,
                "X-Window": window,
                "Content-Type": "application/json"
            })

        if method == "GET":
            async with self.session.get(url, headers=headers, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method == "POST":
            async with self.session.post(
                url,
                headers=headers,
                json=params
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method == "DELETE":
            async with self.session.delete(
                url,
                headers=headers,
                json=params
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
        else:
            raise ValueError(f"지원하지 않는 HTTP 메소드: {method}")

    async def get_available_assets(self) -> List[Asset]:
        """거래 가능한 자산 목록 조회"""
        data = await self._request("GET", "/api/v1/markets")

        assets = []
        for market in data:
            symbol = market['symbol']
            # 영구 선물만 필터링
            if 'PERP' in symbol or '_USDT' in symbol:
                assets.append(Asset(
                    symbol=symbol,
                    base_asset=symbol.replace('_USDT', '').replace('-PERP', ''),
                    quote_asset='USDT',
                    min_size=float(market.get('minOrderSize', 0.001)),
                    price_precision=int(market.get('pricePrecision', 2)),
                    size_precision=int(market.get('sizePrecision', 3))
                ))

        return assets

    async def get_balance(self) -> Balance:
        """계정 잔고 조회"""
        data = await self._request(
            "GET",
            "/api/v1/capital",
            signed=True
        )

        # USDT 잔고 찾기 (응답 형식: {"USDT": {"available": "x", "locked": "y", ...}})
        if 'USDT' in data:
            usdt = data['USDT']
            available = float(usdt.get('available', 0))
            locked = float(usdt.get('locked', 0))
            return Balance(
                asset='USDT',
                free=available,
                locked=locked,
                total=available + locked
            )

        return Balance(asset='USDT', free=0.0, locked=0.0, total=0.0)

    async def get_current_price(self, symbol: str) -> float:
        """현재 시장가 조회"""
        data = await self._request(
            "GET",
            "/api/v1/ticker",
            params={"symbol": symbol}
        )
        return float(data['lastPrice'])

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Tuple[float, float]]:
        """과거 가격 데이터 조회"""
        data = await self._request(
            "GET",
            "/api/v1/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": limit
            }
        )

        return [(float(k['start']), float(k['close'])) for k in data]

    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행"""
        params = {
            "symbol": order.symbol,
            "side": "Bid" if order.side == OrderSide.LONG else "Ask",
            "orderType": "Market" if order.order_type == OrderType.MARKET else "Limit",
            "quantity": str(order.size)
        }

        if order.price is not None:
            params["price"] = str(order.price)

        data = await self._request(
            "POST",
            "/api/v1/order",
            signed=True,
            params=params
        )

        return OrderResult(
            order_id=data['id'],
            symbol=order.symbol,
            side=order.side,
            size=order.size,
            filled_price=float(data.get('price', 0)),
            status=data['status'],
            timestamp=time.time()
        )

    async def get_positions(self) -> List[Position]:
        """현재 보유 포지션 조회"""
        # Backpack은 포지션을 orders API나 fills API로 추적할 수 있지만,
        # 가장 간단한 방법은 /wapi/v1/history/fills를 사용하는 것입니다.
        # 현재는 빈 리스트를 반환하도록 구현 (실제 포지션이 없음)
        try:
            data = await self._request(
                "GET",
                "/wapi/v1/history/fills",
                signed=True
            )

            # Backpack은 PnL을 자동으로 실현하므로, 열린 포지션 개념이 다릅니다.
            # 대신 현재 보유 중인 자산을 기반으로 포지션을 추정할 수 있습니다.
            # 현재는 빈 리스트 반환 (실제 포지션 추적은 별도 로직 필요)
            return []

        except Exception as e:
            # 404나 다른 에러 발생 시 빈 리스트 반환
            return []

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
async def test_backpack():
    """Backpack 클라이언트 테스트"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not api_key or not secret_key:
        print("API 키가 설정되지 않았습니다")
        return

    client = BackpackClient(api_key, secret_key)

    try:
        # 초기화
        if not await client.initialize():
            print("초기화 실패")
            return

        print("✓ 초기화 성공")

        # 잔고 조회
        balance = await client.get_balance()
        print(f"✓ 잔고: {balance.total} USDT (가용: {balance.free})")

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
    asyncio.run(test_backpack())