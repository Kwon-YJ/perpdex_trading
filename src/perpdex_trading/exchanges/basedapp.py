# -*- coding: utf-8 -*-
"""
BASED (Hyperliquid) - REST 방식 주문 Python 파일
- 시장가: place_market_order()
- 지정가: place_limit_order()

환경변수(.env):
    HL_PRIVATE_KEY=0x...           # 메인 월렛 or API 월렛 프라이빗키
    HL_ACCOUNT_ADDRESS=0x...       # 월렛 주소 (비우면 키에서 자동 추출)
    HL_NETWORK=mainnet|testnet     # 기본 mainnet

    # BASED 전용(미설정 시 기본값 사용)
    BASED_BUILDER_ADDRESS=0x1924b8561eef20e70ede628a296175d358be80e5
    BASED_CLIENT_ID=0xba5ed11067f2cc08ba5ed10000ba5ed1
    BASED_BUILDER_FEE_TENTHS_BP=25   # 0.025% = 2.5bp = 25 (tenths of a bp)
"""
import os
import json
import logging
import requests
from typing import Literal, Optional

from dotenv import load_dotenv
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

Side = Literal["BUY", "SELL"]

# BASED 기본값 (Docs 참고)
BASED_DEFAULT_BUILDER = "0x1924b8561eef20e70ede628a296175d358be80e5"
BASED_DEFAULT_CLOID = "0xba5ed11067f2cc08ba5ed10000ba5ed1"
DEFAULT_BUILDER_FEE_TENTHS_BP = 25  # 0.025% (perp)


class BasedTrader:
    def __init__(self):
        load_dotenv()
        secret_key = os.environ["HL_PRIVATE_KEY"]
        self.wallet = Account.from_key(secret_key)
        self.address = os.environ.get("HL_ACCOUNT_ADDRESS", self.wallet.address)
        self.address = self.address.lower()

        net = os.environ.get("HL_NETWORK", "mainnet").lower()
        self.base_url = constants.TESTNET_API_URL if net in ("testnet", "test") else constants.MAINNET_API_URL

        # 공개 Info, 서명 필요 Exchange 클라이언트
        self.info = Info(self.base_url, skip_ws=True)
        # SDK 권장 초기화 (공식 문서 예시 시그니처)
        self.exchange = Exchange(self.wallet, self.base_url, account_address=self.address)

        # BASED builder 정보(환경변수로 덮어쓰기 가능)
        self.builder_addr = os.environ.get("BASED_BUILDER_ADDRESS", BASED_DEFAULT_BUILDER).lower()
        self.cloid = os.environ.get("BASED_CLIENT_ID", BASED_DEFAULT_CLOID)
        self.builder_fee_tenths_bp = int(os.environ.get("BASED_BUILDER_FEE_TENTHS_BP", str(DEFAULT_BUILDER_FEE_TENTHS_BP)))

        logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    def _check_builder_fee(self) -> None:
        """maxBuilderFee(승인 한도) 조회해서 부족하면 경고. (Info 엔드포인트는 공개라 requests로 간단히 호출)"""
        try:
            r = requests.post(
                f"{self.base_url}/info",
                json={"type": "maxBuilderFee", "user": self.address, "builder": self.builder_addr},
                timeout=10,
            )
            r.raise_for_status()
            approved = int(r.json())
            if approved < self.builder_fee_tenths_bp:
                logging.warning(
                    f"[BASED] Builder fee 승인 부족: approved={approved} < need={self.builder_fee_tenths_bp}. "
                    "Hyperliquid 설정(또는 API)에서 builder fee 승인 후 XP/수수료 공유가 반영됩니다."
                )
        except Exception as e:
            logging.warning(f"[BASED] maxBuilderFee 조회 실패: {e}")

    def place_market_order(
        self,
        ticker: str,
        qty: float,
        side: Side,
        slippage: float = 0.01,
        reduce_only: bool = False,
    ) -> dict:
        """
        시장가 주문: 내부적으로 IOC 지정가를 계산해 즉시 체결 (SDK의 market_open 사용)
        - ticker 예: "BTC", "ETH" (perp). Spot은 "HYPE/USDC" 등 심볼 규칙 참고.
        - slippage: 0.01 = 1% 허용 슬리피지
        """
        is_buy = side.upper() == "BUY"
        self._check_builder_fee()

        # SDK 제공 편의 함수 (체결 보장 위해 IOC limit를 자동 계산)
        # market_open(coin, is_buy, sz, cloid, slippage)
        try:
            res = self.exchange.market_open(ticker, is_buy, qty, self.cloid, slippage)
            return res
        except TypeError:
            # 구버전 SDK 호환: cloid 파라미터 미지원 시 Fallback → 수동 IOC 지정가 주문
            # mid를 받아 1% 슬리피지로 가격 산출
            mids = requests.post(f"{self.base_url}/info", json={"type": "allMids"}, timeout=10).json()
            if ticker not in mids:
                raise RuntimeError(f"allMids에 {ticker} 가 없습니다. 심볼을 확인하세요.")
            mid = float(mids[ticker])
            px = mid * (1 + slippage if is_buy else 1 - slippage)
            return self.place_limit_order(ticker, qty, side, price=px, tif="Ioc", reduce_only=reduce_only)

    def place_limit_order(
        self,
        ticker: str,
        qty: float,
        side: Side,
        price: float,
        tif: Literal["Gtc", "Ioc", "Alo"] = "Gtc",
        reduce_only: bool = False,
    ) -> dict:
        """
        지정가 주문
        - tif: Gtc(기본), Ioc(즉시체결 후 잔량 취소), Alo(PostOnly)
        """
        is_buy = side.upper() == "BUY"
        order_type = {"limit": {"tif": tif}}

        # 최신 SDK는 reduce_only, cloid, builder 인자를 키워드로 허용
        try:
            return self.exchange.order(
                ticker,
                is_buy,
                qty,
                price,
                order_type,
                reduce_only=reduce_only,
                cloid=self.cloid,
                builder={"b": self.builder_addr, "f": self.builder_fee_tenths_bp},
            )
        except TypeError:
            # 구버전 호환: 키워드 미지원 시 최소 인자만 전송
            logging.warning("[BASED] 구버전 SDK 감지: cloid/builder/reduceOnly 없이 주문을 전송합니다.")
            return self.exchange.order(ticker, is_buy, qty, price, order_type)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BASED(Hyperliquid) REST 주문 도구")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("market", help="시장가 주문")
    pm.add_argument("ticker")
    pm.add_argument("side", choices=["BUY", "SELL"])
    pm.add_argument("qty", type=float)
    pm.add_argument("--slippage", type=float, default=0.01, help="허용 슬리피지 (기본 1%)")
    pm.add_argument("--reduce-only", action="store_true")

    pl = sub.add_parser("limit", help="지정가 주문")
    pl.add_argument("ticker")
    pl.add_argument("side", choices=["BUY", "SELL"])
    pl.add_argument("qty", type=float)
    pl.add_argument("--price", type=float, required=True)
    pl.add_argument("--tif", choices=["Gtc", "Ioc", "Alo"], default="Gtc")
    pl.add_argument("--reduce-only", action="store_true")

    args = parser.parse_args()
    trader = BasedTrader()

    if args.cmd == "market":
        out = trader.place_market_order(
            ticker=args.ticker,
            qty=args.qty,
            side=args.side,
            slippage=args.slippage,
            reduce_only=args.reduce_only,
        )
    else:
        out = trader.place_limit_order(
            ticker=args.ticker,
            qty=args.qty,
            side=args.side,
            price=args.price,
            tif=args.tif,
            reduce_only=args.reduce_only,
        )

    print(json.dumps(out, indent=2, ensure_ascii=False))
