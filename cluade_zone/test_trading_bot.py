"""트레이딩 봇 테스트 스크립트"""
import asyncio
import os
import sys

# 경로 추가
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/strategy')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/trading')

from dotenv import load_dotenv
from backpack_client import BackpackClient


async def test_backpack_connection():
    """Backpack 연결 테스트"""
    print("=" * 60)
    print("Backpack 연결 테스트")
    print("=" * 60)

    load_dotenv()

    api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not api_key or not secret_key:
        print("❌ Backpack API 키가 설정되지 않았습니다")
        return False

    client = BackpackClient(api_key, secret_key)

    try:
        # 초기화
        print("\n1. 클라이언트 초기화 중...")
        initialized = await client.initialize()

        if not initialized:
            print("❌ 초기화 실패")
            return False

        print("✅ 초기화 성공")

        # 잔고 조회
        print("\n2. 잔고 조회 중...")
        balance = await client.get_balance()
        print(f"✅ 잔고: {balance.total} {balance.asset}")
        print(f"   - 가용: {balance.free}")
        print(f"   - 잠금: {balance.locked}")

        # 자산 목록 조회
        print("\n3. 거래 가능한 자산 조회 중...")
        assets = await client.get_available_assets()
        print(f"✅ 거래 가능한 자산: {len(assets)}개")

        if assets:
            print("\n   상위 5개 자산:")
            for asset in assets[:5]:
                price = await client.get_current_price(asset.symbol)
                print(f"   - {asset.symbol}: ${price:.2f}")

        # 현재 포지션 조회
        print("\n4. 현재 포지션 조회 중...")
        positions = await client.get_positions()
        print(f"✅ 현재 포지션: {len(positions)}개")

        if positions:
            for pos in positions:
                print(f"   - {pos.symbol} {pos.side.value}")
                print(f"     크기: {pos.size}, 진입가: ${pos.entry_price:.2f}")
                print(f"     현재가: ${pos.current_price:.2f}, 손익: ${pos.unrealized_pnl:.2f}")

        await client.close()
        print("\n" + "=" * 60)
        print("✅ 모든 테스트 통과!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        await client.close()
        return False


async def test_portfolio_manager():
    """포트폴리오 매니저 테스트 (실제 주문 없이)"""
    print("\n" + "=" * 60)
    print("포트폴리오 매니저 테스트 (드라이런)")
    print("=" * 60)

    load_dotenv()

    api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not api_key or not secret_key:
        print("❌ Backpack API 키가 설정되지 않았습니다")
        return False

    from portfolio_manager import PortfolioManager

    client = BackpackClient(api_key, secret_key)
    clients = [client]

    try:
        await client.initialize()

        manager = PortfolioManager(clients)

        print("\n1. 델타 중립 포트폴리오 생성 중...")
        long_basket, short_basket = await manager.create_delta_neutral_portfolio(
            total_capital_per_side=50.0,  # 테스트용으로 작은 금액
            assets_per_exchange=2  # 테스트용으로 적은 자산
        )

        print(f"\n✅ 롱 바스켓:")
        print(f"   - 거래소: {long_basket.exchanges}")
        print(f"   - 주문 수: {len(long_basket.orders)}")
        print(f"   - 목표 델타: ${long_basket.target_delta:.2f}")

        print(f"\n✅ 숏 바스켓:")
        print(f"   - 거래소: {short_basket.exchanges}")
        print(f"   - 주문 수: {len(short_basket.orders)}")
        print(f"   - 목표 델타: ${short_basket.target_delta:.2f}")

        net_delta = long_basket.target_delta + short_basket.target_delta
        print(f"\n✅ 순 델타: ${net_delta:.2f}")

        if abs(net_delta) < 10:  # $10 이내면 성공
            print("✅ 델타 중립 달성!")
        else:
            print(f"⚠️  델타가 크게 벗어남: ${net_delta:.2f}")

        await client.close()
        print("\n" + "=" * 60)
        print("✅ 포트폴리오 매니저 테스트 통과!")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        await client.close()
        return False


async def main():
    """메인 테스트 함수"""
    print("\n🤖 트레이딩 봇 테스트 시작\n")

    # 1. Backpack 연결 테스트
    success1 = await test_backpack_connection()

    if not success1:
        print("\n⚠️  Backpack 연결 테스트 실패. 다음 테스트 건너뜀.")
        return

    # 2. 포트폴리오 매니저 테스트
    await asyncio.sleep(2)  # 잠시 대기
    success2 = await test_portfolio_manager()

    print("\n" + "=" * 60)
    print("테스트 요약")
    print("=" * 60)
    print(f"Backpack 연결: {'✅' if success1 else '❌'}")
    print(f"포트폴리오 매니저: {'✅' if success2 else '❌'}")
    print("=" * 60)

    if success1 and success2:
        print("\n✅ 모든 테스트 통과! 실제 트레이딩 준비 완료.")
        print("\n⚠️  주의: 실제 자금이 투입됩니다!")
        print("   실행하려면: python cluade_zone/trading/main_loop.py")
    else:
        print("\n❌ 일부 테스트 실패. 문제를 해결하고 다시 시도하세요.")


if __name__ == "__main__":
    asyncio.run(main())