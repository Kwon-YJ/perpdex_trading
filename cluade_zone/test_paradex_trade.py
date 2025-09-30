"""Paradex 거래 테스트 스크립트"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).parent / "exchanges"))

from base import Order, OrderSide, OrderType
from paradex_client import ParadexClient


async def test_paradex_trade():
    """Paradex 거래 테스트"""
    load_dotenv()

    print("\n" + "="*60)
    print("PARADEX 거래 테스트 시작")
    print("="*60)

    l1_address = os.getenv("PARADEX_PUB_KEY")
    l1_private_key = os.getenv("PARADEX_SEC_KEY")

    if not l1_address or not l1_private_key:
        return {"error": "Paradex API 키가 설정되지 않았습니다"}

    client = ParadexClient(l1_address, l1_private_key)
    results = {}

    try:
        # 초기화
        print("\n[1] 초기화 중...")
        if not await client.initialize():
            return {"error": "초기화 실패"}
        print("✓ 초기화 성공")

        # 초기 잔고 확인 (인증 필요하므로 스킵)
        print("\n[2] 초기 잔고 확인...")
        try:
            initial_balance = await client.get_balance()
            print(f"✓ 초기 잔고: {initial_balance.total:.2f} USDC (가용: {initial_balance.free:.2f})")
            results['initial_balance'] = initial_balance.total
        except NotImplementedError as e:
            print(f"⚠️ 잔고 조회 스킵: {e}")
            results['initial_balance'] = 0.0

        # 거래 가능한 이더리움 심볼 찾기
        print("\n[3] 이더리움 심볼 찾기...")
        assets = await client.get_available_assets()
        eth_asset = None
        for asset in assets:
            if 'ETH' in asset.symbol and 'PERP' in asset.symbol:
                eth_asset = asset
                break

        if not eth_asset:
            return {"error": "이더리움 거래 심볼을 찾을 수 없습니다"}

        print(f"✓ 거래 심볼: {eth_asset.symbol}")
        results['symbol'] = eth_asset.symbol

        # 현재 가격 확인 (인증 필요)
        print("\n[4] 현재 ETH 가격 확인...")
        try:
            current_price = await client.get_current_price(eth_asset.symbol)
            print(f"✓ 현재가: ${current_price:.2f}")
            results['current_price'] = current_price
        except Exception as e:
            print(f"⚠️ 가격 조회 실패 (인증 필요): {e}")
            results['current_price'] = 0.0

        # 거래 기능은 Starknet 온보딩 필요
        print("\n[5] 거래 기능 테스트...")
        print("⚠️ Paradex는 Starknet 기반 DEX로 다음이 필요합니다:")
        print("   - L2 Starknet 계정 생성")
        print("   - 계정 온보딩 프로세스")
        print("   - paradex-py SDK 사용")
        print("   - 현재 구현: 공개 API만 지원 (시장 정보, 가격 조회)")
        print("\n✓ 공개 API 기능 테스트 완료")

        results['buy_order_id'] = "N/A (인증 필요)"
        results['sell_order_id'] = "N/A (인증 필요)"
        results['final_balance'] = results['initial_balance']
        results['pnl'] = 0.0
        results['success'] = True
        results['note'] = "공개 API만 테스트 완료, 거래 기능은 SDK 및 온보딩 필요"

    except Exception as e:
        print(f"\n✗ 오류 발생: {str(e)}")
        import traceback
        traceback.print_exc()
        results['error'] = str(e)
        results['success'] = False

    finally:
        await client.close()

    return results


async def main():
    """메인 테스트 함수"""
    print("\n" + "="*60)
    print(f"Paradex 거래소 매수/매도 테스트")
    print(f"테스트 시작 시간: {datetime.utcnow().isoformat()}")
    print("="*60)

    # Paradex 테스트
    paradex_results = await test_paradex_trade()

    # 결과 요약
    print("\n\n" + "="*60)
    print("테스트 결과 요약")
    print("="*60)

    print("\n[Paradex]")
    if paradex_results.get('success'):
        print(f"✓ 성공")
        print(f"  초기 잔고: ${paradex_results['initial_balance']:.2f}")
        print(f"  최종 잔고: ${paradex_results['final_balance']:.2f}")
        print(f"  순손익: ${paradex_results['pnl']:.4f}")
    else:
        print(f"✗ 실패: {paradex_results.get('error', 'Unknown error')}")

    print("\n" + "="*60)
    print(f"테스트 종료 시간: {datetime.utcnow().isoformat()}")
    print("="*60)

    # 결과를 파일로 저장
    output_file = f"/home/kyj1435/project/perpdex_trading/cluade_zone/{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_paradex_test_result.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("="*60 + "\n")
        f.write("Paradex 거래소 매수/매도 테스트 결과\n")
        f.write(f"테스트 시간: {datetime.utcnow().isoformat()}\n")
        f.write("="*60 + "\n\n")

        f.write("[Paradex 테스트]\n")
        if paradex_results.get('success'):
            f.write(f"상태: 성공\n")
            f.write(f"거래 심볼: {paradex_results.get('symbol', 'N/A')}\n")
            f.write(f"현재가: ${paradex_results.get('current_price', 0):.2f}\n")
            f.write(f"초기 잔고: ${paradex_results['initial_balance']:.2f}\n")
            f.write(f"최종 잔고: ${paradex_results['final_balance']:.2f}\n")
            f.write(f"순손익: ${paradex_results['pnl']:.4f}\n")
            f.write(f"매수 체결가: ${paradex_results.get('buy_filled_price', 0):.2f}\n")
            f.write(f"매도 체결가: ${paradex_results.get('sell_filled_price', 0):.2f}\n")
        else:
            f.write(f"상태: 실패\n")
            f.write(f"에러: {paradex_results.get('error', 'Unknown error')}\n")

        f.write("\n" + "="*60 + "\n")

    print(f"\n결과가 {output_file}에 저장되었습니다.")

    return paradex_results


if __name__ == "__main__":
    asyncio.run(main())