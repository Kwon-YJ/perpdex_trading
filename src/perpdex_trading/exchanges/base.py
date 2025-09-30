"""공통 거래소 인터페이스 정의"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class OrderSide(Enum):
    """주문 방향"""
    LONG = "long"
    SHORT = "short"


class OrderType(Enum):
    """주문 타입"""
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class Asset:
    """거래 자산 정보"""
    symbol: str  # 예: BTC-PERP, ETH-USD-PERP
    base_asset: str  # 예: BTC, ETH
    quote_asset: str  # 예: USD, USDC
    min_size: float
    price_precision: int
    size_precision: int


@dataclass
class Position:
    """포지션 정보"""
    exchange: str
    symbol: str
    side: OrderSide
    size: float  # 포지션 크기
    entry_price: float  # 진입 가격
    current_price: float  # 현재 가격
    unrealized_pnl: float  # 미실현 손익
    leverage: float
    liquidation_price: Optional[float] = None  # 청산 가격


@dataclass
class Order:
    """주문 정보"""
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None  # 시장가 주문은 None
    leverage: float = 1.0
    exchange: Optional[str] = None  # 거래소 이름


@dataclass
class OrderResult:
    """주문 실행 결과"""
    order_id: str
    symbol: str
    side: OrderSide
    size: float
    filled_price: float
    status: str
    timestamp: float


@dataclass
class Balance:
    """잔고 정보"""
    asset: str
    free: float
    locked: float
    total: float


class ExchangeClient(ABC):
    """거래소 API 공통 인터페이스"""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    async def initialize(self) -> bool:
        """
        거래소 클라이언트 초기화
        API 연결 테스트 및 초기 설정
        """
        pass

    @abstractmethod
    async def get_available_assets(self) -> List[Asset]:
        """
        거래 가능한 자산 목록 조회
        """
        pass

    @abstractmethod
    async def get_balance(self) -> Balance:
        """
        계정 잔고 조회
        """
        pass

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """
        현재 시장가 조회
        """
        pass

    @abstractmethod
    async def get_historical_prices(
        self,
        symbol: str,
        interval: str = "1h",
        limit: int = 100
    ) -> List[Tuple[float, float]]:
        """
        과거 가격 데이터 조회
        Returns: List of (timestamp, close_price)
        """
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """
        주문 실행
        """
        pass

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """
        현재 보유 포지션 조회
        """
        pass

    @abstractmethod
    async def close_position(self, symbol: str) -> OrderResult:
        """
        포지션 청산
        """
        pass

    @abstractmethod
    async def close_all_positions(self) -> List[OrderResult]:
        """
        모든 포지션 청산
        """
        pass

    @abstractmethod
    async def check_liquidation_risk(self) -> bool:
        """
        강제 청산 위험 체크
        Returns: True if at risk of liquidation
        """
        pass

    async def get_delta(self, position: Position) -> float:
        """
        포지션의 델타 계산
        Delta = position_size * current_price
        롱: 양수, 숏: 음수
        """
        delta = position.size * position.current_price
        return delta if position.side == OrderSide.LONG else -delta

    async def close(self):
        """
        클라이언트 종료 및 리소스 정리
        """
        pass