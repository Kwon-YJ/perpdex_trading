"""트레이딩 메인 루프"""
import asyncio
import time
from datetime import datetime
from typing import List
import os
import sys

sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/strategy')

from base import ExchangeClient
from portfolio_manager import PortfolioManager


class TradingBot:
    """델타 중립 트레이딩 봇"""

    def __init__(
        self,
        clients: List[ExchangeClient],
        profit_target: float = 1.0,  # 1원 이상 순이익
        wait_time: int = 600  # 10분 (초)
    ):
        self.clients = clients
        self.portfolio_manager = PortfolioManager(clients)
        self.profit_target = profit_target
        self.wait_time = wait_time

        self.log_file = "/home/kyj1435/project/perpdex_trading/cluade_zone/trading_result.txt"
        self.exchange_guide_file = "/home/kyj1435/project/perpdex_trading/cluade_zone/exchange_guide.txt"

    def log(self, message: str):
        """로그 출력 및 파일 저장"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        log_line = f"[{timestamp}] {message}\n"

        print(log_line.strip())

        # 파일에 저장
        try:
            with open(self.log_file, "a") as f:
                f.write(log_line)
        except Exception as e:
            print(f"로그 저장 실패: {e}")

    async def run_cycle(self):
        """트레이딩 사이클 1회 실행"""
        cycle_start = time.time()
        self.log("=" * 60)
        self.log("트레이딩 사이클 시작")

        try:
            # 1. 델타 중립 포트폴리오 생성
            self.log("1단계: 델타 중립 포트폴리오 생성")
            long_basket, short_basket = await self.portfolio_manager.create_delta_neutral_portfolio(
                total_capital_per_side=100.0,  # 한 쪽당 $100
                assets_per_exchange=3
            )

            self.log(f"롱 바스켓: {len(long_basket.orders)}개 주문, 목표 델타: ${long_basket.target_delta:.2f}")
            self.log(f"숏 바스켓: {len(short_basket.orders)}개 주문, 목표 델타: ${short_basket.target_delta:.2f}")

            # 2. 포지션 진입
            self.log("2단계: 포지션 진입")
            long_positions = await self.portfolio_manager.execute_basket(long_basket)
            short_positions = await self.portfolio_manager.execute_basket(short_basket)

            total_positions = len(long_positions) + len(short_positions)
            self.log(f"포지션 진입 완료: {total_positions}개 (롱 {len(long_positions)}, 숏 {len(short_positions)})")

            if total_positions == 0:
                self.log("⚠️  포지션 진입 실패, 사이클 종료")
                return

            # 3. 10분 대기
            self.log(f"3단계: {self.wait_time}초 대기 중...")
            await asyncio.sleep(self.wait_time)

            # 4. 청산 조건 모니터링
            self.log("4단계: 청산 조건 모니터링")
            liquidated = False

            while not liquidated:
                # 청산 조건 1: 순이익 1원 이상
                total_pnl, positions = await self.portfolio_manager.get_total_pnl()
                self.log(f"현재 총 손익: ${total_pnl:.2f}")

                if total_pnl >= self.profit_target:
                    self.log(f"✓ 목표 달성! 순이익: ${total_pnl:.2f}")
                    break

                # 청산 조건 2: 강제 청산 위험
                at_risk = await self.portfolio_manager.check_liquidation_risk()
                if at_risk:
                    self.log("⚠️  강제 청산 위험 감지, 즉시 청산")
                    break

                # 1초 대기 후 재확인
                await asyncio.sleep(1)

            # 5. 모든 포지션 청산
            self.log("5단계: 모든 포지션 청산")
            close_results = await self.portfolio_manager.close_all_positions()

            for exchange, results in close_results.items():
                self.log(f"{exchange}: {len(results)}개 포지션 청산")

            # 6. 최종 손익 계산
            final_pnl, _ = await self.portfolio_manager.get_total_pnl()
            self.log(f"최종 손익: ${final_pnl:.2f}")

            # 7. 현재 자본 업데이트
            await self.update_exchange_guide()

        except Exception as e:
            self.log(f"✗ 사이클 실행 중 오류: {e}")
            import traceback
            self.log(traceback.format_exc())

            # 오류 발생 시에도 모든 포지션 청산 시도
            try:
                self.log("오류 발생, 긴급 청산 시도")
                await self.portfolio_manager.close_all_positions()
            except Exception as cleanup_error:
                self.log(f"긴급 청산 실패: {cleanup_error}")

        cycle_end = time.time()
        cycle_duration = cycle_end - cycle_start
        self.log(f"사이클 완료 (소요 시간: {cycle_duration:.1f}초)")
        self.log("=" * 60)

        # 10분 대기 후 다음 사이클
        self.log(f"{self.wait_time}초 대기 후 다음 사이클 시작...")
        await asyncio.sleep(self.wait_time)

    async def update_exchange_guide(self):
        """exchange_guide.txt의 현재자본 업데이트"""
        try:
            for client in self.clients:
                balance = await client.get_balance()
                self.log(f"{client.name} 현재 자본: {balance.total} {balance.asset}")

                # exchange_guide.txt 업데이트
                # TODO: CSV 파일 파싱 및 업데이트 구현
                # 현재는 로그만 출력

        except Exception as e:
            self.log(f"자본 업데이트 실패: {e}")

    async def run(self):
        """봇 메인 루프 (무한 반복)"""
        self.log("트레이딩 봇 시작")

        # 클라이언트 초기화
        for client in self.clients:
            try:
                initialized = await client.initialize()
                if initialized:
                    self.log(f"✓ {client.name} 초기화 완료")
                else:
                    self.log(f"✗ {client.name} 초기화 실패")
            except Exception as e:
                self.log(f"✗ {client.name} 초기화 오류: {e}")

        # 무한 트레이딩 사이클
        cycle_count = 0
        while True:
            cycle_count += 1
            self.log(f"\n사이클 #{cycle_count} 시작")

            try:
                await self.run_cycle()
            except Exception as e:
                self.log(f"사이클 실행 중 치명적 오류: {e}")
                import traceback
                self.log(traceback.format_exc())

                # 1분 대기 후 재시도
                self.log("1분 대기 후 재시도...")
                await asyncio.sleep(60)


async def main():
    """메인 함수"""
    from dotenv import load_dotenv
    load_dotenv()

    # Backpack 클라이언트만 사용 (테스트)
    sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
    from backpack_client import BackpackClient

    backpack_api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    backpack_secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not backpack_api_key or not backpack_secret_key:
        print("Backpack API 키가 설정되지 않았습니다")
        return

    # 클라이언트 생성
    clients = [
        BackpackClient(backpack_api_key, backpack_secret_key)
    ]

    # 봇 생성 및 실행
    bot = TradingBot(
        clients=clients,
        profit_target=1.0,  # $1 이상 순이익
        wait_time=600  # 10분
    )

    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())