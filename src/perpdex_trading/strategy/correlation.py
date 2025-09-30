"""상관계수 계산 모듈"""
import asyncio
from typing import List, Dict, Tuple, Optional, Callable
from dataclasses import dataclass
import time

import sys
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')

from base import ExchangeClient, Asset


@dataclass
class PriceData:
    """가격 데이터"""
    symbol: str
    exchange: str
    prices: List[float]  # 시계열 가격 데이터
    timestamps: List[float]


@dataclass
class AssetPair:
    """상관관계가 높은 자산 페어"""
    long_asset: Asset
    long_exchange: str
    short_asset: Asset
    short_exchange: str
    correlation: float


class CorrelationCalculator:
    """상관계수 계산기"""

    def __init__(
        self,
        clients: List[ExchangeClient],
        logger: Optional[Callable[[str], None]] = None
    ):
        self.clients = clients
        self.clients_map = {c.name: c for c in clients}
        self.logger = logger

    def _log(self, message: str):
        """로깅 헬퍼"""
        if self.logger:
            self.logger(message)
        else:
            # 기본 출력은 사용자 지침에 따라 최소화
            pass

    async def fetch_price_history(
        self,
        symbol: str,
        exchange_name: str,
        duration: int = 300,  # 5분
        interval: int = 10  # 10초마다 샘플링
    ) -> Optional[PriceData]:
        """가격 히스토리 수집 (실시간 샘플링)"""
        client = self.clients_map.get(exchange_name)
        if not client:
            return None

        prices = []
        timestamps = []

        samples = duration // interval

        for i in range(samples):
            try:
                price = await client.get_current_price(symbol)
                prices.append(price)
                timestamps.append(time.time())

                if i < samples - 1:  # 마지막 샘플이 아니면 대기
                    await asyncio.sleep(interval)
            except Exception as e:
                self._log(f"{exchange_name}의 {symbol} 가격 조회 중 오류 발생: {e}")
                continue

        if len(prices) < 2:
            return None

        return PriceData(
            symbol=symbol,
            exchange=exchange_name,
            prices=prices,
            timestamps=timestamps
        )

    def calculate_correlation(
        self,
        price_data1: PriceData,
        price_data2: PriceData
    ) -> float:
        """두 자산 간 피어슨 상관계수 계산"""
        if not price_data1.prices or not price_data2.prices:
            return 0.0

        # 가격 변화율 계산
        returns1 = self._calculate_returns(price_data1.prices)
        returns2 = self._calculate_returns(price_data2.prices)

        if len(returns1) < 2 or len(returns2) < 2:
            return 0.0

        # 길이 맞추기
        min_len = min(len(returns1), len(returns2))
        returns1 = returns1[:min_len]
        returns2 = returns2[:min_len]

        # 피어슨 상관계수
        n = len(returns1)
        if n == 0:
            return 0.0

        mean1 = sum(returns1) / n
        mean2 = sum(returns2) / n

        numerator = sum((returns1[i] - mean1) * (returns2[i] - mean2) for i in range(n))

        std1 = (sum((x - mean1) ** 2 for x in returns1) / n) ** 0.5
        std2 = (sum((x - mean2) ** 2 for x in returns2) / n) ** 0.5

        if std1 == 0 or std2 == 0:
            return 0.0

        correlation = numerator / (n * std1 * std2)

        return correlation

    def _calculate_returns(self, prices: List[float]) -> List[float]:
        """가격 변화율 계산"""
        if len(prices) < 2:
            return []

        returns = []
        for i in range(1, len(prices)):
            if prices[i - 1] != 0:
                ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                returns.append(ret)

        return returns

    async def find_correlated_pairs_fast(
        self,
        long_assets: List[Tuple[Asset, str]],  # (asset, exchange)
        short_assets: List[Tuple[Asset, str]],
        min_correlation: float = 0.9,
        sample_duration: int = 60,  # 1분만 샘플링
        sample_interval: int = 5  # 5초마다
    ) -> List[AssetPair]:
        """빠른 상관관계 페어 찾기 (단축 버전)"""
        self._log(
            f"상관관계 분석 시작 (샘플링 {sample_duration}초, 간격 {sample_interval}초, 임계값 {min_correlation:.2f})"
        )

        # 롱 자산들의 가격 히스토리 수집
        long_price_data = []
        for asset, exchange in long_assets[:5]:  # 최대 5개만 샘플링
            price_data = await self.fetch_price_history(
                asset.symbol,
                exchange,
                duration=sample_duration,
                interval=sample_interval
            )
            if price_data:
                long_price_data.append((asset, exchange, price_data))

        # 숏 자산들의 가격 히스토리 수집
        short_price_data = []
        for asset, exchange in short_assets[:5]:  # 최대 5개만 샘플링
            price_data = await self.fetch_price_history(
                asset.symbol,
                exchange,
                duration=sample_duration,
                interval=sample_interval
            )
            if price_data:
                short_price_data.append((asset, exchange, price_data))

        # 상관계수 계산 및 페어 생성
        pairs = []
        for long_asset, long_ex, long_data in long_price_data:
            for short_asset, short_ex, short_data in short_price_data:
                correlation = self.calculate_correlation(long_data, short_data)

                if abs(correlation) >= min_correlation:
                    pairs.append(AssetPair(
                        long_asset=long_asset,
                        long_exchange=long_ex,
                        short_asset=short_asset,
                        short_exchange=short_ex,
                        correlation=correlation
                    ))
                    self._log(
                        f"높은 상관관계 식별: {long_asset.symbol}@{long_ex} ↔ {short_asset.symbol}@{short_ex} (r={correlation:.3f})"
                    )

        # 상관계수가 높은 순으로 정렬
        pairs.sort(key=lambda p: abs(p.correlation), reverse=True)

        return pairs

    async def select_best_correlated_assets(
        self,
        long_exchanges: List[str],
        short_exchanges: List[str],
        target_assets_per_exchange: int = 3
    ) -> Tuple[Dict[str, List[Asset]], Dict[str, List[Asset]]]:
        """
        최고 상관관계를 가진 자산들 선택

        Returns:
            (long_assets_by_exchange, short_assets_by_exchange)
        """
        # 각 거래소에서 사용 가능한 자산 수집
        long_assets_list = []
        for exchange in long_exchanges:
            client = self.clients_map.get(exchange)
            if not client:
                continue
            try:
                assets = await client.get_available_assets()
                for asset in assets[:10]:  # 거래소당 최대 10개만
                    long_assets_list.append((asset, exchange))
            except Exception as e:
                print(f"{exchange} 자산 조회 실패: {e}")

        short_assets_list = []
        for exchange in short_exchanges:
            client = self.clients_map.get(exchange)
            if not client:
                continue
            try:
                assets = await client.get_available_assets()
                for asset in assets[:10]:  # 거래소당 최대 10개만
                    short_assets_list.append((asset, exchange))
            except Exception as e:
                print(f"{exchange} 자산 조회 실패: {e}")

        # 빠른 상관관계 분석
        correlated_pairs = await self.find_correlated_pairs_fast(
            long_assets_list,
            short_assets_list,
            min_correlation=0.7,
            sample_duration=60,  # 1분
            sample_interval=5  # 5초
        )

        if not correlated_pairs:
            self._log("⚠️ 높은 상관관계 페어를 찾지 못해 무작위 선택으로 대체합니다")
            # 폴백: 랜덤 선택
            return await self._fallback_random_selection(
                long_exchanges,
                short_exchanges,
                target_assets_per_exchange
            )

        # 페어를 거래소별로 그룹화
        long_assets_by_exchange = {ex: [] for ex in long_exchanges}
        short_assets_by_exchange = {ex: [] for ex in short_exchanges}

        used_long_symbols = set()
        used_short_symbols = set()

        for pair in correlated_pairs:
            # 중복 방지 및 제한
            if pair.long_asset.symbol in used_long_symbols:
                continue
            if pair.short_asset.symbol in used_short_symbols:
                continue

            if len(long_assets_by_exchange[pair.long_exchange]) >= target_assets_per_exchange:
                continue
            if len(short_assets_by_exchange[pair.short_exchange]) >= target_assets_per_exchange:
                continue

            long_assets_by_exchange[pair.long_exchange].append(pair.long_asset)
            short_assets_by_exchange[pair.short_exchange].append(pair.short_asset)

            used_long_symbols.add(pair.long_asset.symbol)
            used_short_symbols.add(pair.short_asset.symbol)

        return long_assets_by_exchange, short_assets_by_exchange

    async def _fallback_random_selection(
        self,
        long_exchanges: List[str],
        short_exchanges: List[str],
        target_assets_per_exchange: int
    ) -> Tuple[Dict[str, List[Asset]], Dict[str, List[Asset]]]:
        """폴백: 랜덤 선택"""
        import random

        long_assets_by_exchange = {}
        for exchange in long_exchanges:
            client = self.clients_map.get(exchange)
            if not client:
                long_assets_by_exchange[exchange] = []
                continue
            try:
                assets = await client.get_available_assets()
                selected = random.sample(assets, min(target_assets_per_exchange, len(assets)))
                long_assets_by_exchange[exchange] = selected
            except Exception as e:
                self._log(f"{exchange} 거래소 자산 조회 실패: {e}")
                long_assets_by_exchange[exchange] = []

        short_assets_by_exchange = {}
        for exchange in short_exchanges:
            client = self.clients_map.get(exchange)
            if not client:
                short_assets_by_exchange[exchange] = []
                continue
            try:
                assets = await client.get_available_assets()
                selected = random.sample(assets, min(target_assets_per_exchange, len(assets)))
                short_assets_by_exchange[exchange] = selected
            except Exception as e:
                self._log(f"{exchange} 거래소 자산 조회 실패: {e}")
                short_assets_by_exchange[exchange] = []

        return long_assets_by_exchange, short_assets_by_exchange
