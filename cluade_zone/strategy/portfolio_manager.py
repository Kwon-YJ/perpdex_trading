"""델타 중립 포트폴리오 관리자"""
import random
from typing import List, Dict, Tuple
from dataclasses import dataclass
import asyncio

import sys
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')

from base import ExchangeClient, Asset, Order, OrderSide, OrderType, Position


@dataclass
class PortfolioBasket:
    """포트폴리오 바스켓 (롱 또는 숏)"""
    side: OrderSide
    exchanges: List[str]
    orders: List[Order]
    target_delta: float


class PortfolioManager:
    """델타 중립 포트폴리오 매니저"""

    def __init__(self, clients: List[ExchangeClient]):
        self.clients = clients
        self.clients_map = {c.name: c for c in clients}

    async def create_delta_neutral_portfolio(
        self,
        total_capital_per_side: float = 100.0,
        assets_per_exchange: int = 3
    ) -> Tuple[PortfolioBasket, PortfolioBasket]:
        """
        델타 중립 포트폴리오 생성

        Args:
            total_capital_per_side: 한 쪽(롱 또는 숏)당 총 자본
            assets_per_exchange: 거래소당 자산 수 (3~5개)

        Returns:
            (long_basket, short_basket) 튜플
        """
        # 1. 거래소를 랜덤으로 롱/숏 그룹으로 분할
        exchanges = list(self.clients_map.keys())
        random.shuffle(exchanges)
        mid = len(exchanges) // 2

        long_exchanges = exchanges[:mid]
        short_exchanges = exchanges[mid:]

        print(f"롱 거래소: {long_exchanges}")
        print(f"숏 거래소: {short_exchanges}")

        # 2. 각 거래소에서 거래 가능한 자산 조회
        long_orders = await self._create_basket_orders(
            long_exchanges,
            OrderSide.LONG,
            total_capital_per_side,
            assets_per_exchange
        )

        short_orders = await self._create_basket_orders(
            short_exchanges,
            OrderSide.SHORT,
            total_capital_per_side,
            assets_per_exchange
        )

        # 3. 델타 계산 및 균형 맞추기
        long_delta = await self._calculate_basket_delta(long_orders)
        short_delta = await self._calculate_basket_delta(short_orders)

        print(f"초기 롱 델타: ${long_delta:.2f}")
        print(f"초기 숏 델타: ${short_delta:.2f}")

        # 숏 델타를 롱 델타에 맞춰 조정
        if abs(short_delta) > 0:
            adjustment_factor = abs(long_delta / short_delta)
            short_orders = self._adjust_order_sizes(short_orders, adjustment_factor)
            short_delta = await self._calculate_basket_delta(short_orders)

        print(f"조정된 숏 델타: ${short_delta:.2f}")
        print(f"순 델타: ${long_delta + short_delta:.2f}")

        long_basket = PortfolioBasket(
            side=OrderSide.LONG,
            exchanges=long_exchanges,
            orders=long_orders,
            target_delta=long_delta
        )

        short_basket = PortfolioBasket(
            side=OrderSide.SHORT,
            exchanges=short_exchanges,
            orders=short_orders,
            target_delta=short_delta
        )

        return long_basket, short_basket

    async def _create_basket_orders(
        self,
        exchanges: List[str],
        side: OrderSide,
        total_capital: float,
        assets_per_exchange: int
    ) -> List[Order]:
        """바스켓 주문 생성"""
        orders = []
        capital_per_exchange = total_capital / len(exchanges)

        for exchange_name in exchanges:
            client = self.clients_map[exchange_name]

            # 거래 가능한 자산 조회
            try:
                available_assets = await client.get_available_assets()
            except Exception as e:
                print(f"{exchange_name} 자산 조회 실패: {e}")
                continue

            if not available_assets:
                print(f"{exchange_name}에 거래 가능한 자산이 없습니다")
                continue

            # 랜덤으로 3~5개 자산 선택
            num_assets = min(
                random.randint(3, 5),
                len(available_assets),
                assets_per_exchange
            )
            selected_assets = random.sample(available_assets, num_assets)

            # 각 자산에 균등 배분
            capital_per_asset = capital_per_exchange / num_assets

            for asset in selected_assets:
                try:
                    # 현재 가격 조회
                    price = await client.get_current_price(asset.symbol)

                    # 주문 크기 계산 (델타 = size * price)
                    size = capital_per_asset / price

                    # 최소 주문 크기 체크
                    if size < asset.min_size:
                        print(f"{asset.symbol} 주문 크기가 너무 작음: {size} < {asset.min_size}")
                        continue

                    # 정밀도에 맞춰 반올림
                    size = round(size, asset.size_precision)

                    orders.append(Order(
                        symbol=asset.symbol,
                        side=side,
                        order_type=OrderType.MARKET,
                        size=size,
                        price=None,
                        exchange=exchange_name
                    ))

                except Exception as e:
                    print(f"{asset.symbol} 주문 생성 실패: {e}")
                    continue

        return orders

    async def _calculate_basket_delta(self, orders: List[Order]) -> float:
        """바스켓의 총 델타 계산"""
        total_delta = 0.0

        for order in orders:
            # 각 자산의 현재 가격 조회
            client = self._get_client_for_order(order)
            if client is None:
                continue

            try:
                price = await client.get_current_price(order.symbol)
                delta = order.size * price

                if order.side == OrderSide.SHORT:
                    delta = -delta

                total_delta += delta
            except Exception as e:
                print(f"{order.symbol} 델타 계산 실패: {e}")
                continue

        return total_delta

    def _adjust_order_sizes(
        self,
        orders: List[Order],
        factor: float
    ) -> List[Order]:
        """주문 크기 조정"""
        adjusted_orders = []

        for order in orders:
            adjusted_size = order.size * factor
            adjusted_orders.append(Order(
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                size=adjusted_size,
                price=order.price,
                exchange=order.exchange
            ))

        return adjusted_orders

    def _get_client_for_order(self, order: Order) -> ExchangeClient:
        """주문에 대한 거래소 클라이언트 찾기"""
        if order.exchange and order.exchange in self.clients_map:
            return self.clients_map[order.exchange]

        # 대체: 첫 번째 클라이언트 반환
        if self.clients:
            return self.clients[0]

        return None

    async def execute_basket(
        self,
        basket: PortfolioBasket
    ) -> List[Position]:
        """바스켓 주문 실행"""
        positions = []

        for order in basket.orders:
            client = self._get_client_for_order(order)
            if client is None:
                print(f"{order.symbol} 거래소를 찾을 수 없음")
                continue

            try:
                result = await client.place_order(order)
                print(f"✓ {result.symbol} {result.side.value} {result.size} @ ${result.filled_price}")

                # 포지션 객체 생성
                position = Position(
                    exchange=client.name,
                    symbol=result.symbol,
                    side=result.side,
                    size=result.size,
                    entry_price=result.filled_price,
                    current_price=result.filled_price,
                    unrealized_pnl=0.0,
                    leverage=1.0
                )
                positions.append(position)

            except Exception as e:
                print(f"✗ {order.symbol} 주문 실패: {e}")
                continue

        return positions

    async def get_total_pnl(self) -> Tuple[float, List[Position]]:
        """모든 포지션의 총 손익 계산"""
        all_positions = []

        for client in self.clients:
            try:
                positions = await client.get_positions()
                all_positions.extend(positions)
            except Exception as e:
                print(f"{client.name} 포지션 조회 실패: {e}")
                continue

        total_pnl = sum(pos.unrealized_pnl for pos in all_positions)

        return total_pnl, all_positions

    async def check_liquidation_risk(self) -> bool:
        """강제 청산 위험 체크"""
        for client in self.clients:
            try:
                at_risk = await client.check_liquidation_risk()
                if at_risk:
                    print(f"⚠️  {client.name}에서 청산 위험 감지!")
                    return True
            except Exception as e:
                print(f"{client.name} 청산 위험 체크 실패: {e}")
                continue

        return False

    async def close_all_positions(self) -> Dict[str, List]:
        """모든 포지션 청산"""
        results = {}

        for client in self.clients:
            try:
                close_results = await client.close_all_positions()
                results[client.name] = close_results
                print(f"✓ {client.name} 포지션 청산 완료: {len(close_results)}개")
            except Exception as e:
                print(f"✗ {client.name} 포지션 청산 실패: {e}")
                results[client.name] = []

        return results