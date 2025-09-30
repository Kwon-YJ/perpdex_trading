"""델타 중립 트레이딩 봇 실행 스크립트"""
import asyncio
import sys
import os
from datetime import datetime

# 경로 추가
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/trading')

from dotenv import load_dotenv
load_dotenv()

from backpack_client import BackpackClient
from main_loop import TradingBot


async def main():
    """메인 함수"""
    print("="* 60)
    print("델타 중립 거래량 증폭 봇 시작")
    print(f"시작 시간: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)

    # Backpack 클라이언트 설정
    backpack_api_key = os.getenv("BACKPACK_PUBLIC_KEY")
    backpack_secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

    if not backpack_api_key or not backpack_secret_key:
        print("❌ Backpack API 키가 설정되지 않았습니다")
        print("   .env 파일에 BACKPACK_PUBLIC_KEY와 BACKPACK_PRIVATE_KEY를 설정하세요")
        return

    # 클라이언트 생성
    clients = [
        BackpackClient(backpack_api_key, backpack_secret_key)
    ]

    # 봇 생성
    bot = TradingBot(
        clients=clients,
        profit_target=0.01,  # $0.01 이상 순이익 (매우 낮은 목표)
        wait_time=600,  # 10분 (초)
        use_correlation=False  # 상관계수 사용 안 함 (단일 거래소)
    )

    print("\n⚠️  주의: 현재 Backpack 단일 거래소로 운영 중")
    print("   롱/숏 포지션을 같은 거래소에서 거래합니다")
    print("   델타 중립 전략의 효율성이 제한될 수 있습니다\n")

    # 봇 실행 (무한 루프)
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\n봇 종료 요청 (Ctrl+C)")
        print("모든 포지션을 청산하는 중...")

        # 긴급 청산
        try:
            await bot.portfolio_manager.close_all_positions()
            print("✓ 모든 포지션 청산 완료")
        except Exception as e:
            print(f"✗ 청산 중 오류: {e}")

        # 클라이언트 종료
        for client in clients:
            try:
                await client.close()
            except:
                pass

        print("봇 종료 완료")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()