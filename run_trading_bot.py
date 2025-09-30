#!/usr/bin/env python3
"""간소화된 델타 중립 트레이딩 봇 실행 스크립트"""

import asyncio
import os
import sys
from pathlib import Path

# 경로 추가
sys.path.insert(0, str(Path(__file__).parent / 'cluade_zone' / 'trading'))
sys.path.insert(0, str(Path(__file__).parent / 'cluade_zone' / 'exchanges'))
sys.path.insert(0, str(Path(__file__).parent / 'cluade_zone' / 'strategy'))
sys.path.insert(0, str(Path(__file__).parent / 'cluade_zone' / 'utils'))

from dotenv import load_dotenv
from main_loop import TradingBot

# 환경 변수 로드
load_dotenv()

# 클라이언트 import
try:
    from backpack_client import BackpackClient
    BACKPACK_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Backpack 클라이언트 로드 실패: {e}")
    BACKPACK_AVAILABLE = False

# GRVT SDK가 설치되지 않아 비활성화
GRVT_AVAILABLE = False


async def main():
    """메인 실행"""
    clients = []

    # Backpack 클라이언트 설정
    if BACKPACK_AVAILABLE:
        api_key = os.getenv("BACKPACK_PUBLIC_KEY")
        secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

        if api_key and secret_key:
            try:
                backpack = BackpackClient(api_key, secret_key)
                initialized = await backpack.initialize()

                if initialized:
                    clients.append(backpack)
                    print("✓ Backpack 클라이언트 준비 완료")
                else:
                    print("✗ Backpack 클라이언트 초기화 실패")
                    await backpack.close()
            except Exception as e:
                print(f"✗ Backpack 클라이언트 생성 실패: {e}")
        
    # GRVT는 SDK가 설치되지 않아 스킵

    if not clients:
        print("⚠️ 사용 가능한 거래소 클라이언트가 없습니다.")
        return

    print(f"\n준비된 거래소: {len(clients)}개")
    print("=" * 60)

    # 트레이딩 봇 초기화 (상관계수 비활성화)
    bot = TradingBot(
        clients=clients,
        profit_target=0.01,      # $0.01 이상
        capital_per_side=100.0,  # 한쪽당 $100
        wait_time=600,           # 10분
        use_correlation=False    # 상관계수 비활성화 (빠른 실행)
    )

    print("\n트레이딩 봇을 시작합니다...")
    print("중단하려면 Ctrl+C를 누르세요.\n")

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\n사용자 중단으로 봇을 종료합니다.")
    finally:
        # 클라이언트 정리
        for client in clients:
            try:
                await client.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
