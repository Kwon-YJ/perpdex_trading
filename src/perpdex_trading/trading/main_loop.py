"""트레이딩 메인 루프"""
import asyncio
import time
from datetime import datetime
from typing import List
import sys
from pathlib import Path

sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/strategy')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/utils')

from base import ExchangeClient
from portfolio_manager import PortfolioManager
from exchange_guide_updater import ExchangeGuideUpdater


class TradingBot:
    """델타 중립 트레이딩 봇"""

    def __init__(
        self,
        clients: List[ExchangeClient],
        profit_target: float = 0.01,  # $0.01 이상 순이익
        capital_per_side: float = 100.0,  # 한쪽당 자본
        wait_time: int = 600,  # 10분 (초)
        use_correlation: bool = True
    ):
        self.clients = clients
        self.profit_target = profit_target
        self.capital_per_side = capital_per_side
        self.wait_time = wait_time

        self.base_dir = Path("/home/kyj1435/project/perpdex_trading/cluade_zone")
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self.session_log_file = self.base_dir / f"{timestamp}.txt"
        self.session_log_file.touch(exist_ok=True)

        self.log_file = self.base_dir / "trading_result.txt"
        self.exchange_guide_file = self.base_dir / "exchange_guide.txt"
        self.exchange_guide_updater = ExchangeGuideUpdater(
            str(self.exchange_guide_file),
            logger=self.log
        )

        self.portfolio_manager = PortfolioManager(
            clients,
            use_correlation=use_correlation,
            logger=self.log
        )

    def log(self, message: str):
        """로그 출력 및 파일 저장"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        log_line = f"[{timestamp}] {message}\n"

        target_paths = [self.log_file, self.session_log_file]

        for path in target_paths:
            try:
                with path.open("a", encoding="utf-8") as fp:
                    fp.write(log_line)
            except Exception:
                # 파일 기록 실패 시 세션 로그에만 남김
                if path != self.session_log_file:
                    try:
                        with self.session_log_file.open("a", encoding="utf-8") as fallback:
                            fallback.write(f"[{timestamp}] 로그 파일 저장 실패: {message}\n")
                    except Exception:
                        pass

    async def run_cycle(self):
        """트레이딩 사이클 1회 실행"""
        cycle_start = time.time()
        self.log("=" * 60)
        self.log("트레이딩 사이클 시작")

        try:
            # 1. 델타 중립 포트폴리오 생성
            self.log("1단계: 델타 중립 바스켓 구성")
            long_basket, short_basket = await self.portfolio_manager.create_delta_neutral_portfolio(
                total_capital_per_side=self.capital_per_side,
                assets_per_exchange=5
            )

            self.log(
                f"롱 바스켓: 주문 {len(long_basket.orders)}개, 목표 델타 ${long_basket.target_delta:.2f}"
            )
            self.log(
                f"숏 바스켓: 주문 {len(short_basket.orders)}개, 목표 델타 ${short_basket.target_delta:.2f}"
            )

            # 2. 포지션 진입
            self.log("2단계: 포지션 진입")
            long_positions = await self.portfolio_manager.execute_basket(long_basket)
            short_positions = await self.portfolio_manager.execute_basket(short_basket)

            total_positions = len(long_positions) + len(short_positions)
            self.log(
                f"포지션 진입 완료: 총 {total_positions}건 (롱 {len(long_positions)}건, 숏 {len(short_positions)}건)"
            )

            if total_positions == 0:
                self.log("⚠️ 포지션 진입에 실패하여 사이클을 종료합니다")
                self.log(f"10분 대기 후 재시도합니다")
                await asyncio.sleep(self.wait_time)
                return

            # 3. 10분 대기
            self.log(f"3단계: {self.wait_time}초 대기")
            await asyncio.sleep(self.wait_time)

            # 4. 청산 조건 모니터링
            self.log("4단계: 청산 조건 모니터링")
            monitoring_interval = 10  # 10초마다 체크
            elapsed_time = 0
            forced_liquidation = False

            while True:
                # 청산 조건 1: 순이익 목표 달성
                total_pnl, positions = await self.portfolio_manager.get_total_pnl()
                self.log(f"[{elapsed_time}초] 누적 손익: ${total_pnl:.4f}")

                if total_pnl >= self.profit_target:
                    self.log(f"✓ 목표 손익 달성: ${total_pnl:.4f}")
                    break

                # 청산 조건 2: 강제 청산 위험
                at_risk = await self.portfolio_manager.check_liquidation_risk()
                if at_risk:
                    self.log("⚠️ 강제 청산 또는 강제 청산 위험 감지, 즉시 청산 절차 진행")
                    forced_liquidation = True
                    break

                # 10초 대기 후 재확인
                await asyncio.sleep(monitoring_interval)
                elapsed_time += monitoring_interval

            # 5. 모든 포지션 청산
            self.log("5단계: 모든 포지션 청산")
            close_results = await self.portfolio_manager.close_all_positions()

            for exchange, results in close_results.items():
                self.log(f"{exchange}: 청산 완료 {len(results)}건")

            if forced_liquidation:
                await self._convert_all_assets_to_cash()
                self.log("강제 청산 경보 후 현금화 루틴을 실행했습니다")

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
        self.log(f"사이클 완료 (소요 시간 {cycle_duration:.1f}초)")
        self.log("=" * 60)

        # 10분 대기 후 다음 사이클
        self.log(f"다음 사이클까지 {self.wait_time}초 대기")
        await asyncio.sleep(self.wait_time)

    async def update_exchange_guide(self):
        """exchange_guide.txt의 현재자본 업데이트"""
        try:
            capital_map = {}

            for client in self.clients:
                try:
                    balance = await client.get_balance()
                    self.log(f"{client.name} 현재 자본: {balance.total} {balance.asset}")
                    capital_map[client.name] = balance.total
                except Exception as e:
                    self.log(f"{client.name} 잔고 조회 실패: {e}")

            # exchange_guide.txt 업데이트
            if capital_map:
                results = self.exchange_guide_updater.update_multiple_capitals(capital_map)
                for exchange, success in results.items():
                    if success:
                        self.log(f"✓ {exchange} exchange_guide.txt 업데이트 완료")
                    else:
                        self.log(f"✗ {exchange} exchange_guide.txt 업데이트 실패")

        except Exception as e:
            self.log(f"자본 업데이트 실패: {e}")

    async def _convert_all_assets_to_cash(self):
        """강제 청산 발생 시 현금화 루틴"""
        for client in self.clients:
            try:
                # 모든 포지션이 닫힌 상태인지 확인
                await client.close_all_positions()
                balance = await client.get_balance()
                self.log(
                    f"{client.name}: 잔여 자산 {balance.total} {balance.asset} 현금 보유 상태 확인"
                )
            except Exception as e:
                self.log(f"{client.name}: 현금화 절차 실패 {e}")

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
            self.log("")
            self.log(f"사이클 #{cycle_count} 시작")

            try:
                await self.run_cycle()
            except Exception as e:
                self.log(f"사이클 실행 중 치명적 오류: {e}")
                import traceback
                self.log(traceback.format_exc())

                # 1분 대기 후 재시도
                self.log("1분 대기 후 재시도...")
                await asyncio.sleep(60)
