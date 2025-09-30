"""GRVT Exchange API 클라이언트"""
import asyncio
import os
from typing import Dict, List, Optional, Tuple
import time

try:
    from grvt_pysdk.grvt_ccxt_pro import GrvtCcxtPro
except ImportError:
    try:
        from grvt_pysdk import GrvtCcxtPro
    except ImportError:
        GrvtCcxtPro = None

from base import (
    ExchangeClient, Asset, Balance, Order, OrderResult,
    Position, OrderSide, OrderType
)


class GrvtClient(ExchangeClient):
    """GRVT Exchange API 클라이언트"""

    def __init__(self, api_key: str, private_key: str, trading_account_id: str = None):
        super().__init__("GRVT")

        # 환경 변수 설정
        os.environ['GRVT_API_KEY'] = api_key
        os.environ['GRVT_PRIVATE_KEY'] = private_key
        if trading_account_id:
            os.environ['GRVT_TRADING_ACCOUNT_ID'] = trading_account_id
        os.environ['GRVT_ENV'] = 'prod'  # 또는 'testnet'

        self.client: Optional[GrvtCcxtPro] = None

    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if GrvtCcxtPro is None:
            raise ImportError("grvt-pysdk가 설치되지 않았습니다")

        try:
            self.client = GrvtCcxtPro(env='prod')

            # API 연결 테스트
            await self.client.load_markets()
            return True
        except Exception as e:
            print(f"GRVT 초기화 실패: {e}")
            return False

    async def get_available_assets(self) -> List[Asset]:
        """거래 가능한 자산 목록 조회"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        markets = await self.client.load_markets()
        assets = []

        for symbol, market in markets.items():
            # 영구 선물 (perpetual swap) 필터링
            if market.get('type') == 'swap' or 'PERP' in symbol:
                assets.append(Asset(
                    symbol=symbol,
                    base_asset=market.get('base', ''),
                    quote_asset=market.get('quote', 'USDT'),
                    min_size=float(market.get('limits', {}).get('amount', {}).get('min', 0.001)),
                    price_precision=market.get('precision', {}).get('price', 2),
                    size_precision=market.get('precision', {}).get('amount', 3)
                ))

        return assets

    async def get_balance(self) -> Balance:
        """계정 잔고 조회"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        balance_data = await self.client.fetch_balance()

        # USDT 잔고 찾기
        if 'USDT' in balance_data:
            usdt = balance_data['USDT']
            return Balance(
                asset='USDT',
                free=float(usdt.get('free', 0)),
                locked=float(usdt.get('used', 0)),
                total=float(usdt.get('total', 0))
            )

        # total 또는 free 키가 직접 있는 경우
        total = float(balance_data.get('total', {}).get('USDT', 0))
        free = float(balance_data.get('free', {}).get('USDT', 0))
        used = float(balance_data.get('used', {}).get('USDT', 0))

        return Balance(
            asset='USDT',
            free=free,
            locked=used,
            total=total if total > 0 else free + used
        )

    async def get_current_price(self, symbol: str) -> float:
        """현재 시장가 조회"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        ticker = await self.client.fetch_ticker(symbol)
        return float(ticker.get('last', ticker.get('close', 0)))

    async def get_historical_prices(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Tuple[float, float]]:
        """과거 가격 데이터 조회"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        ohlcv = await self.client.fetch_ohlcv(symbol, timeframe=interval, limit=limit)

        # OHLCV 형식: [timestamp, open, high, low, close, volume]
        return [(candle[0], candle[4]) for candle in ohlcv]

    async def place_order(self, order: Order) -> OrderResult:
        """주문 실행"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        # CCXT side 변환
        side = 'buy' if order.side == OrderSide.LONG else 'sell'
        order_type = 'market' if order.order_type == OrderType.MARKET else 'limit'

        params = {}
        if order.leverage and order.leverage > 1:
            params['leverage'] = order.leverage

        result = await self.client.create_order(
            symbol=order.symbol,
            type=order_type,
            side=side,
            amount=order.size,
            price=order.price,
            params=params
        )

        return OrderResult(
            order_id=str(result.get('id', '')),
            symbol=order.symbol,
            side=order.side,
            size=float(result.get('filled', order.size)),
            filled_price=float(result.get('average', result.get('price', 0))),
            status=result.get('status', 'unknown'),
            timestamp=float(result.get('timestamp', time.time() * 1000)) / 1000
        )

    async def get_positions(self) -> List[Position]:
        """현재 보유 포지션 조회"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

        positions_data = await self.client.fetch_positions()
        positions = []

        for pos in positions_data:
            # 포지션이 없으면 스킵
            contracts = float(pos.get('contracts', 0))
            if contracts == 0:
                continue

            # 롱/숏 판별
            side = OrderSide.LONG if pos.get('side') == 'long' else OrderSide.SHORT

            positions.append(Position(
                exchange=self.name,
                symbol=pos.get('symbol', ''),
                side=side,
                size=abs(contracts),
                entry_price=float(pos.get('entryPrice', 0)),
                current_price=float(pos.get('markPrice', pos.get('lastPrice', 0))),
                unrealized_pnl=float(pos.get('unrealizedPnl', 0)),
                leverage=float(pos.get('leverage', 1)),
                liquidation_price=float(pos.get('liquidationPrice')) if pos.get('liquidationPrice') else None
            ))

        return positions

    async def close_position(self, symbol: str) -> OrderResult:
        """포지션 청산"""
        if self.client is None:
            raise RuntimeError("클라이언트가 초기화되지 않았습니다")

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
        if self.client:
            await self.client.close()


# 테스트 코드
async def test_grvt():
    """GRVT 클라이언트 테스트"""
    from dotenv import load_dotenv

    load_dotenv()

    api_key = os.getenv("GRVT_PUB_KEY")
    private_key = os.getenv("GRVT_SEC_KEY")

    if not api_key or not private_key:
        print("GRVT API 키가 설정되지 않았습니다")
        return

    client = GrvtClient(api_key, private_key)

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
    asyncio.run(test_grvt())