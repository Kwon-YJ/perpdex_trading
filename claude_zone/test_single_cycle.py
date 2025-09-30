"""단일 거래 사이클 테스트 (자동 실행)"""
import asyncio
import sys
import os
from datetime import datetime

# 경로 추가
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/strategy')

from dotenv import load_dotenv
load_dotenv()

from backpack_client import BackpackClient
from portfolio_manager import PortfolioManager


async def main():
    """메인 테스트 함수"""
    print("=" * 60)
    print("단일 거래 사이클 테스트 (자동 실행)")
    print(f"시작 시간: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Backpack 클라이언트 설정
    backpack_api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    backpack_secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not backpack_api_key or not backpack_secret_key:
        print("❌ Backpack API 키가 설정되지 않았습니다")
        return

    # 클라이언트 생성
    client = BackpackClient(backpack_api_key, backpack_secret_key)

    try:
        # 초기화
        print("\n1. Backpack 클라이언트 초기화...")
        initialized = await client.initialize()
        if not initialized:
            print("❌ 초기화 실패")
            return
        print("✓ 초기화 완료")

        # 잔고 확인
        balance = await client.get_balance()
        print(f"✓ 현재 잔고: {balance.total} {balance.asset}")

        # 포트폴리오 매니저 생성
        portfolio_manager = PortfolioManager([client], use_correlation=False)

        # 델타 중립 포트폴리오 생성
        print("\n2. 델타 중립 포트폴리오 생성...")
        print("   화이트리스트 심볼: SOL_USDC_PERP, BTC_USDC_PERP, ETH_USDC_PERP")
        print("   자본: 한쪽당 $200")

        long_basket, short_basket = await portfolio_manager.create_delta_neutral_portfolio(
            total_capital_per_side=200.0,
            assets_per_exchange=3
        )

        print(f"\n롱 바스켓: {len(long_basket.orders)}개 주문, 델타: ${long_basket.target_delta:.2f}")
        for order in long_basket.orders:
            print(f"  • {order.symbol} {order.side.value} {order.size}")

        print(f"\n숏 바스켓: {len(short_basket.orders)}개 주문, 델타: ${short_basket.target_delta:.2f}")
        for order in short_basket.orders:
            print(f"  • {order.symbol} {order.side.value} {order.size}")

        print(f"\n순 델타: ${long_basket.target_delta + short_basket.target_delta:.2f}")

        if len(long_basket.orders) == 0 or len(short_basket.orders) == 0:
            print("\n⚠️  주문이 생성되지 않았습니다. 테스트 종료.")
            return

        # 포지션 진입
        print("\n3. 포지션 진입...")
        long_positions = await portfolio_manager.execute_basket(long_basket)
        print(f"롱 포지션: {len(long_positions)}개 진입")

        short_positions = await portfolio_manager.execute_basket(short_basket)
        print(f"숏 포지션: {len(short_positions)}개 진입")

        total_positions = len(long_positions) + len(short_positions)
        print(f"\n✓ 총 {total_positions}개 포지션 진입 완료")

        if total_positions == 0:
            print("⚠️  포지션 진입 실패")
            return

        # 10분 대기
        wait_time = 600
        print(f"\n4. {wait_time}초 ({wait_time//60}분) 대기 중...")
        await asyncio.sleep(wait_time)

        # 손익 확인
        print("\n5. 손익 확인...")
        total_pnl, positions = await portfolio_manager.get_total_pnl()
        print(f"현재 총 손익: ${total_pnl:.4f}")
        print(f"포지션 수: {len(positions)}")

        # 청산
        print("\n6. 모든 포지션 청산...")
        close_results = await portfolio_manager.close_all_positions()
        for exchange, results in close_results.items():
            print(f"{exchange}: {len(results)}개 포지션 청산")

        # 최종 잔고 확인
        print("\n7. 최종 잔고 확인...")
        final_balance = await client.get_balance()
        print(f"최종 잔고: {final_balance.total} {final_balance.asset}")

        pnl_realized = final_balance.total - balance.total
        print(f"실현 손익: {pnl_realized:.2f} {balance.asset}")

        print("\n" + "=" * 60)
        print("✓ 단일 사이클 테스트 완료")
        print(f"종료 시간: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("=" * 60)

        # 결과 파일 저장
        output_file = f"./claude_zone/{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_single_cycle_result.txt"
        with open(output_file, "w") as f:
            f.write(f"단일 거래 사이클 테스트 결과\n")
            f.write(f"=" * 60 + "\n")
            f.write(f"시작 시간: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"초기 잔고: {balance.total} {balance.asset}\n")
            f.write(f"최종 잔고: {final_balance.total} {final_balance.asset}\n")
            f.write(f"실현 손익: {pnl_realized:.2f} {balance.asset}\n")
            f.write(f"롱 포지션: {len(long_positions)}개\n")
            f.write(f"숏 포지션: {len(short_positions)}개\n")
            f.write(f"총 포지션: {total_positions}개\n")

        print(f"\n결과 저장: {output_file}")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

        # 긴급 청산 시도
        try:
            print("\n긴급 청산 시도...")
            await client.close_all_positions()
            print("✓ 긴급 청산 완료")
        except Exception as cleanup_error:
            print(f"✗ 긴급 청산 실패: {cleanup_error}")

    finally:
        # 클라이언트 종료
        try:
            await client.close()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(main())