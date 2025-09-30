"""델타 중립 포트폴리오 관리자"""
import random
from typing import List, Dict, Tuple, Callable, Optional
from dataclasses import dataclass
import asyncio

import sys
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/strategy')

from base import ExchangeClient, Asset, Order, OrderSide, OrderType, Position
from correlation import CorrelationCalculator


@dataclass
class PortfolioBasket:
    """포트폴리오 바스켓 (롱 또는 숏)"""
    side: OrderSide
    exchanges: List[str]
    orders: List[Order]
    target_delta: float


class PortfolioManager:
    """델타 중립 포트폴리오 매니저"""

    def __init__(
        self,
        clients: List[ExchangeClient],
        use_correlation: bool = True,
        logger: Optional[Callable[[str], None]] = None
    ):
        self.clients = clients
        self.clients_map = {c.name: c for c in clients}
        self.use_correlation = use_correlation
        self.correlation_calculator = CorrelationCalculator(clients) if use_correlation else None
        self.logger = logger

    def _log(self, message: str):
        """로깅 헬퍼"""
        if self.logger:
            self.logger(message)
        else:
            print(message)

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

        # 특별 케이스: 단일 거래소인 경우 롱/숏 모두 같은 거래소 사용
        if len(exchanges) == 1:
            long_exchanges = exchanges
            short_exchanges = exchanges
            self._log(f"⚠️ 단일 거래소 환경 감지: {exchanges[0]}")
            self._log("   롱/숏 포지션을 동일 거래소에서 처리합니다")
        else:
            random.shuffle(exchanges)
            mid = len(exchanges) // 2
            long_exchanges = exchanges[:mid]
            short_exchanges = exchanges[mid:]

            # 한쪽이 비어 있으면 균형 조정
            if not long_exchanges and short_exchanges:
                long_exchanges.append(short_exchanges.pop())
            elif not short_exchanges and long_exchanges:
                short_exchanges.append(long_exchanges.pop())

            self._log(f"롱 그룹 거래소: {long_exchanges}")
            self._log(f"숏 그룹 거래소: {short_exchanges}")

        # 2. 상관계수 기반 자산 선택 (또는 랜덤)
        if self.use_correlation and self.correlation_calculator:
            self._log("상관계수 기반 자산을 선정합니다")
            long_assets_map, short_assets_map = await self.correlation_calculator.select_best_correlated_assets(
                long_exchanges,
                short_exchanges,
                target_assets_per_exchange=assets_per_exchange
            )
        else:
            self._log("상관계수 계산 비활성화: 무작위 자산을 사용합니다")
            long_assets_map = None
            short_assets_map = None

        # 3. 각 거래소에서 거래 가능한 자산 조회 및 주문 생성
        long_orders = await self._create_basket_orders(
            long_exchanges,
            OrderSide.LONG,
            total_capital_per_side,
            assets_per_exchange,
            preselected_assets=long_assets_map
        )

        used_symbols = {order.symbol for order in long_orders}

        short_orders = await self._create_basket_orders(
            short_exchanges,
            OrderSide.SHORT,
            total_capital_per_side,
            assets_per_exchange,
            preselected_assets=short_assets_map,
            excluded_symbols=used_symbols
        )

        # 3. 델타 계산 및 균형 맞추기
        long_orders, short_orders, long_delta, short_delta = await self._balance_baskets(
            long_orders,
            short_orders
        )

        self._log(f"롱 델타 추정값: ${long_delta:.2f}")
        self._log(f"숏 델타 추정값: ${short_delta:.2f}")
        self._log(f"총 델타: ${long_delta + short_delta:.2f}")

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
        assets_per_exchange: int,
        preselected_assets: Dict[str, List[Asset]] = None,
        excluded_symbols: Optional[set] = None
    ) -> List[Order]:
        """바스켓 주문 생성"""
        orders = []
        capital_per_exchange = total_capital / len(exchanges) if exchanges else 0

        # 화이트리스트: 검증된 메이저 심볼만 사용
        WHITELISTED_SYMBOLS = [
            'SOL_USDC_PERP',
            'BTC_USDC_PERP',
            'ETH_USDC_PERP'
        ]

        for exchange_name in exchanges:
            client = self.clients_map[exchange_name]

            # 사전 선택된 자산이 있으면 사용, 없으면 화이트리스트 기반 선택
            if preselected_assets and exchange_name in preselected_assets:
                selected_assets = [
                    asset for asset in preselected_assets[exchange_name]
                    if not excluded_symbols or asset.symbol not in excluded_symbols
                ]
                self._log(f"{exchange_name}: 상관계수 기반 자산 {len(selected_assets)}개 확보")
                if not selected_assets:
                    self._log(f"{exchange_name}: 제외 조건으로 사용 가능한 자산이 없어 스킵")
                    continue
            else:
                # 거래 가능한 자산 조회
                try:
                    available_assets = await client.get_available_assets()
                except Exception as e:
                    self._log(f"{exchange_name}: 자산 목록 조회 실패 {e}")
                    continue

                if not available_assets:
                    self._log(f"{exchange_name}: 거래 가능한 자산이 없습니다")
                    continue

                # 화이트리스트에서 사용 가능한 자산만 필터링
                whitelisted_assets = [
                    asset for asset in available_assets
                    if asset.symbol in WHITELISTED_SYMBOLS
                ]

                if excluded_symbols:
                    whitelisted_assets = [
                        asset for asset in whitelisted_assets
                        if asset.symbol not in excluded_symbols
                    ]

                if not whitelisted_assets:
                    self._log(f"{exchange_name}: 허용된 자산을 찾지 못했습니다")
                    continue

                # 화이트리스트에서 랜덤으로 3~5개 자산 선택 (최대 가능한 만큼)
                num_assets = min(
                    random.randint(3, 5),
                    len(whitelisted_assets),
                    assets_per_exchange
                )
                if num_assets == 0:
                    self._log(f"{exchange_name}: 제외 조건으로 선택 가능한 자산이 없습니다")
                    continue
                selected_assets = random.sample(whitelisted_assets, num_assets)
                self._log(
                    f"{exchange_name}: 화이트리스트 자산 {len(selected_assets)}개 선정 { [a.symbol for a in selected_assets] }"
                )

            # 각 자산에 균등 배분
            num_assets = len(selected_assets)
            if num_assets == 0:
                continue
            capital_per_asset = capital_per_exchange / num_assets

            for asset in selected_assets:
                try:
                    # 현재 가격 조회
                    price = await client.get_current_price(asset.symbol)

                    # 주문 크기 계산 (델타 = size * price)
                    size = capital_per_asset / price

                    # Backpack은 decimal precision이 엄격하므로 최대 2자리로 제한
                    safe_precision = min(asset.size_precision, 2)

                    # 최소 주문 크기 체크 - 여유를 두고 2배로 설정
                    min_required = asset.min_size * 2.0

                    # 최소 크기 미달 시 최소 크기의 2배로 설정
                    if size < min_required:
                        self._log(f"{asset.symbol}: 주문 수량을 {size:.6f}→{min_required:.6f}로 조정")
                        size = min_required

                    # 정밀도에 맞춰 반올림
                    size = round(size, safe_precision)

                    # 다시 최소 크기 체크 (반올림 후)
                    if size < asset.min_size:
                        self._log(f"{asset.symbol}: 주문 수량이 최소치 미만이라 건너뜀 ({size} < {asset.min_size})")
                        continue

                    orders.append(Order(
                        symbol=asset.symbol,
                        side=side,
                        order_type=OrderType.MARKET,
                        size=size,
                        price=None,
                        exchange=exchange_name
                    ))

                except Exception as e:
                    self._log(f"{asset.symbol}: 주문 생성 실패 {e}")
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
                self._log(f"{order.symbol}: 델타 계산 실패 {e}")
                continue

        return total_delta

    async def _balance_baskets(
        self,
        long_orders: List[Order],
        short_orders: List[Order],
        tolerance: float = 0.5
    ) -> Tuple[List[Order], List[Order], float, float]:
        """롱/숏 바스켓의 델타를 균형 맞춤"""
        long_delta = await self._calculate_basket_delta(long_orders)
        short_delta = await self._calculate_basket_delta(short_orders)

        if not long_orders or not short_orders:
            return long_orders, short_orders, long_delta, short_delta

        attempts = 0
        while attempts < 5 and abs(long_delta + short_delta) > tolerance:
            long_abs = abs(long_delta)
            short_abs = abs(short_delta)

            if long_abs < 1e-9 or short_abs < 1e-9:
                break

            if long_abs > short_abs:
                factor = short_abs / long_abs
                long_orders = self._adjust_order_sizes(long_orders, factor)
            else:
                factor = long_abs / short_abs
                short_orders = self._adjust_order_sizes(short_orders, factor)

            long_delta = await self._calculate_basket_delta(long_orders)
            short_delta = await self._calculate_basket_delta(short_orders)
            attempts += 1

        if abs(long_delta + short_delta) > tolerance:
            self._log(
                f"⚠️ 델타 불균형이 남아 있습니다 (잔여 델타 ${long_delta + short_delta:.2f})"
            )

        return long_orders, short_orders, long_delta, short_delta

    def _adjust_order_sizes(
        self,
        orders: List[Order],
        factor: float
    ) -> List[Order]:
        """주문 크기 조정"""
        if factor <= 0:
            return orders

        adjusted_orders = []

        for order in orders:
            adjusted_size = round(order.size * factor, 6)
            if adjusted_size <= 0:
                adjusted_size = max(order.size * 0.1, 1e-6)

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
                self._log(f"{order.symbol}: 연결된 거래소를 찾지 못해 주문을 건너뜀")
                continue

            try:
                result = await client.place_order(order)
                side_label = "롱" if result.side == OrderSide.LONG else "숏"
                self._log(
                    f"✓ {client.name} | {result.symbol} {side_label} {result.size} @ ${result.filled_price}"
                )

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
                self._log(f"✗ {client.name} | {order.symbol} 주문 실패: {e}")
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
                self._log(f"{client.name}: 포지션 조회 실패 {e}")
                continue

        total_pnl = sum(pos.unrealized_pnl for pos in all_positions)

        return total_pnl, all_positions

    async def check_liquidation_risk(self) -> bool:
        """강제 청산 위험 체크"""
        for client in self.clients:
            try:
                at_risk = await client.check_liquidation_risk()
                if at_risk:
                    self._log(f"⚠️ {client.name}: 청산 위험 감지")
                    return True
            except Exception as e:
                self._log(f"{client.name}: 청산 위험 점검 실패 {e}")
                continue

        return False

    async def close_all_positions(self) -> Dict[str, List]:
        """모든 포지션 청산"""
        results = {}

        for client in self.clients:
            try:
                close_results = await client.close_all_positions()
                results[client.name] = close_results
                self._log(f"✓ {client.name}: 포지션 {len(close_results)}개 청산 완료")
            except Exception as e:
                self._log(f"✗ {client.name}: 포지션 청산 실패 {e}")
                results[client.name] = []

        return results

