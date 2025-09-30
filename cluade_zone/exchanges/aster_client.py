"""Aster Exchange REST API 클라이언트"""
import asyncio
import time
import json
import math
from typing import Dict, List, Optional, Tuple

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from eth_abi import encode as eth_encode
    from web3 import Web3
except ImportError:
    Account = None
    encode_defunct = None
    eth_encode = None
    Web3 = None

from base import (
    ExchangeClient, Asset, Balance, Order, OrderResult,
    Position, OrderSide, OrderType
)


class AsterClient(ExchangeClient):
    """Aster Exchange API 클라이언트"""

    BASE_URL = "https://fapi.asterdex.com"

    def __init__(self, user_address: str, signer_address: str, private_key: str):
        super().__init__("Aster")
        self.user_address = user_address
        self.signer_address = signer_address
        self.private_key = private_key

        if Account is None or Web3 is None:
            raise ImportError("eth-account, eth-abi, web3 라이브러리가 필요합니다")

        # Ethereum account
        self.account = Account.from_key(private_key)

        self.session: Optional[aiohttp.ClientSession] = None

    def _generate_signature(self, params: Dict, nonce: int) -> Dict:
        """
        Aster API 서명 생성
        """
        # recvWindow와 timestamp 추가
        params['recvWindow'] = 50000
        params['timestamp'] = int(time.time() * 1000)

        # None 값 제거 및 문자열 변환
        trimmed_params = self._trim_dict(params.copy())

        # JSON 문자열 생성 (정렬, 공백 제거)
        json_str = json.dumps(trimmed_params, sort_keys=True).replace(' ', '').replace("'", '"')

        # ABI 인코딩
        encoded = eth_encode(
            ['string', 'address', 'address', 'uint256'],
            [json_str, self.user_address, self.signer_address, nonce]
        )

        # Keccak256 해시
        keccak_hex = Web3.keccak(encoded).hex()

        # EIP-191 서명
        signable_msg = encode_defunct(hexstr=keccak_hex)
        signed_message = Account.sign_message(signable_message=signable_msg, private_key=self.private_key)

        # 서명 파라미터 추가
        params['nonce'] = nonce
        params['user'] = self.user_address
        params['signer'] = self.signer_address
        params['signature'] = '0x' + signed_message.signature.hex()

        return params

    def _trim_dict(self, d: Dict) -> Dict:
        """딕셔너리 값을 문자열로 변환"""
        for key in d:
            value = d[key]
            if isinstance(value, list):
                new_value = []
                for item in value:
                    if isinstance(item, dict):
                        new_value.append(json.dumps(self._trim_dict(item)))
                    else:
                        new_value.append(str(item))
                d[key] = json.dumps(new_value)
                continue
            if isinstance(value, dict):
                d[key] = json.dumps(self._trim_dict(value))
                continue
            d[key] = str(value)
        return d

    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if aiohttp is None:
            print("✗ aiohttp가 설치되지 않았습니다")
            return False

        self.session = aiohttp.ClientSession()

        try:
            # 공개 API 테스트 - 서버 시간 조회
            await self._request("GET", "/fapi/v3/time")

            # 거래 가능한 자산 조회
            await self.get_available_assets()

            return True
        except Exception as e:
            print(f"Aster 초기화 실패: {e}")
            import traceback
            traceback.print_exc()
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
        headers = {
            'User-Agent': 'PythonApp/1.0'
        }

        if params is None:
            params = {}

        # None 값 제거
        params = {k: v for k, v in params.items() if v is not None}

        if signed:
            # 서명 생성
            nonce = math.trunc(time.time() * 1000000)
            params = self._generate_signature(params, nonce)
            headers['Content-Type'] = 'application/x-www-form-urlencoded'

        if method == "GET":
            async with self.session.get(url, headers=headers, params=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method == "POST":
            async with self.session.post(url, headers=headers, data=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        elif method == "DELETE":
            async with self.session.delete(url, headers=headers, data=params) as resp:
                resp.raise_for_status()
                return await resp.json()
        else:
            raise ValueError(f"지원하지 않는 HTTP 메소드: {method}")

    async def get_available_assets(self) -> List[Asset]:
        """거래 가능한 자산 목록 조회"""
        data = await self._request("GET", "/fapi/v3/exchangeInfo")

        assets = []
        symbols = data.get('symbols', [])

        for symbol_info in symbols:
            symbol = symbol_info.get('symbol', '')
            # 거래 중인 영구 선물만
            if symbol_info.get('status') == 'TRADING' and symbol_info.get('contractType') == 'PERPETUAL':
                # 필터에서 최소 주문 크기 찾기
                min_size = 0.001
                price_precision = 2
                size_precision = 3

                for f in symbol_info.get('filters', []):
                    if f.get('filterType') == 'LOT_SIZE':
                        min_size = float(f.get('minQty', min_size))
                        size_precision = len(str(min_size).split('.')[-1]) if '.' in str(min_size) else 0
                    elif f.get('filterType') == 'PRICE_FILTER':
                        tick_size = float(f.get('tickSize', 0.01))
                        price_precision = len(str(tick_size).split('.')[-1]) if '.' in str(tick_size) else 2

                assets.append(Asset(
                    symbol=symbol,
                    base_asset=symbol_info.get('baseAsset', ''),
                    quote_asset=symbol_info.get('quoteAsset', 'USDT'),
                    min_size=min_size,
                    price_precision=price_precision,
                    size_precision=size_precision
                ))

        return assets

    async def get_balance(self) -> Balance:
        """계정 잔고 조회"""
        data = await self._request("GET", "/fapi/v3/balance", signed=True)

        # USDT 잔고 찾기
        for balance in data:
            if balance.get('asset') == 'USDT':
                return Balance(
                    asset='USDT',
                    free=float(balance.get('availableBalance', 0)),
                    locked=float(balance.get('balance', 0)) - float(balance.get('availableBalance', 0)),
                    total=float(balance.get('balance', 0))
                )

        return Balance(asset='USDT', free=0.0, locked=0.0, total=0.0)

    async def get_current_price(self, symbol: str) -> float:
        """현재 시장가 조회"""
        data = await self._request("GET", "/fapi/v3/ticker/price", params={"symbol": symbol})
        return float(data.get('price', 0))

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Tuple[float, float]]:
        """과거 가격 데이터 조회"""
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        data = await self._request("GET", "/fapi/v3/klines", params=params)

        # OHLCV 형식: [timestamp, open, high, low, close, volume, ...]
        return [(float(candle[0]), float(candle[4])) for candle in data]

    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행"""
        params = {
            "symbol": order.symbol,
            "side": "BUY" if order.side == OrderSide.LONG else "SELL",
            "type": "MARKET" if order.order_type == OrderType.MARKET else "LIMIT",
            "quantity": str(order.size),
            "positionSide": "BOTH"  # One-way 모드
        }

        if order.order_type == OrderType.LIMIT:
            params["timeInForce"] = "GTC"
            params["price"] = str(order.price)

        data = await self._request("POST", "/fapi/v3/order", signed=True, params=params)

        return OrderResult(
            order_id=str(data.get('orderId', '')),
            symbol=order.symbol,
            side=order.side,
            size=float(data.get('executedQty', order.size)),
            filled_price=float(data.get('avgPrice', order.price or 0)),
            status=data.get('status', 'unknown'),
            timestamp=float(data.get('updateTime', time.time()))
        )

    async def get_positions(self) -> List[Position]:
        """현재 보유 포지션 조회"""
        data = await self._request("GET", "/fapi/v3/positionRisk", signed=True)

        positions = []
        for pos in data:
            size = float(pos.get('positionAmt', 0))
            if size == 0:
                continue

            # 롱/숏 판별
            side = OrderSide.LONG if size > 0 else OrderSide.SHORT

            positions.append(Position(
                exchange=self.name,
                symbol=pos.get('symbol', ''),
                side=side,
                size=abs(size),
                entry_price=float(pos.get('entryPrice', 0)),
                current_price=float(pos.get('markPrice', 0)),
                unrealized_pnl=float(pos.get('unRealizedProfit', 0)),
                leverage=float(pos.get('leverage', 1)),
                liquidation_price=float(pos.get('liquidationPrice')) if pos.get('liquidationPrice') else None
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
async def test_aster():
    """Aster 클라이언트 테스트"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    user_address = os.getenv("ASTER_PUB_KEY")
    signer_address = os.getenv("ASTER_PUB_KEY")  # 동일한 주소 사용
    private_key = os.getenv("ASTER_SEC_KEY")

    if not user_address or not private_key:
        print("API 키가 설정되지 않았습니다")
        return

    # 0x 접두사 추가
    if not user_address.startswith('0x'):
        user_address = '0x' + user_address
    if not signer_address.startswith('0x'):
        signer_address = '0x' + signer_address
    if not private_key.startswith('0x'):
        private_key = '0x' + private_key

    client = AsterClient(user_address, signer_address, private_key)

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
    asyncio.run(test_aster())