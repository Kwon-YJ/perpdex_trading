"""Aster 거래 테스트 스크립트"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).parent / "exchanges"))

from base import Order, OrderSide, OrderType
from aster_client import AsterClient


async def test_aster_trade():
    """Aster 거래 테스트"""
    load_dotenv()

    print("\n" + "="*60)
    print("ASTER 거래 테스트 시작")
    print("="*60)

    private_key = os.getenv("ASTER_SEC_KEY")

    if not private_key:
        return {"error": "Aster API 키가 설정되지 않았습니다"}

    # 0x 접두사 추가
    if not private_key.startswith('0x'):
        private_key = '0x' + private_key

    # Private key로부터 주소 생성
    from eth_account import Account
    account = Account.from_key(private_key)
    user_address = account.address
    signer_address = account.address

    client = AsterClient(user_address, signer_address, private_key)
    results = {}

    try:
        # 초기화
        print("\n[1] 초기화 중...")
        if not await client.initialize():
            return {"error": "초기화 실패"}
        print("✓ 초기화 성공")

        # 초기 잔고 확인
        print("\n[2] 초기 잔고 확인...")
        initial_balance = await client.get_balance()
        print(f"✓ 초기 잔고: {initial_balance.total:.2f} USDT (가용: {initial_balance.free:.2f})")
        results['initial_balance'] = initial_balance.total

        # 거래 가능한 이더리움 심볼 찾기
        print("\n[3] 이더리움 심볼 찾기...")
        assets = await client.get_available_assets()
        eth_asset = None
        for asset in assets:
            if 'ETH' in asset.symbol and 'USDT' in asset.symbol:
                eth_asset = asset
                break

        if not eth_asset:
            return {"error": "이더리움 거래 심볼을 찾을 수 없습니다"}

        print(f"✓ 거래 심볼: {eth_asset.symbol}")
        results['symbol'] = eth_asset.symbol

        # 현재 가격 확인
        print("\n[4] 현재 ETH 가격 확인...")
        current_price = await client.get_current_price(eth_asset.symbol)
        print(f"✓ 현재가: ${current_price:.2f}")
        results['current_price'] = current_price

        # 매수 주문 (최소 수량)
        print("\n[5] ETH 매수 주문 실행...")
        buy_size = max(eth_asset.min_size, 0.001)  # 최소 주문 수량
        print(f"   매수 수량: {buy_size} ETH")

        buy_order = Order(
            symbol=eth_asset.symbol,
            side=OrderSide.LONG,
            order_type=OrderType.MARKET,
            size=buy_size
        )

        buy_result = await client.place_order(buy_order)
        print(f"✓ 매수 완료")
        print(f"   주문 ID: {buy_result.order_id}")
        print(f"   체결가: ${buy_result.filled_price:.2f}")
        print(f"   상태: {buy_result.status}")
        results['buy_order_id'] = buy_result.order_id
        results['buy_filled_price'] = buy_result.filled_price

        # 잠시 대기
        await asyncio.sleep(2)

        # 포지션 확인
        print("\n[6] 포지션 확인...")
        positions = await client.get_positions()
        print(f"✓ 현재 포지션: {len(positions)}개")
        for pos in positions:
            print(f"   - {pos.symbol} {pos.side.value} {pos.size} @ ${pos.entry_price:.2f}")

        # 매도 주문 (동일 수량)
        print("\n[7] ETH 매도 주문 실행...")
        sell_order = Order(
            symbol=eth_asset.symbol,
            side=OrderSide.SHORT,
            order_type=OrderType.MARKET,
            size=buy_size
        )

        sell_result = await client.place_order(sell_order)
        print(f"✓ 매도 완료")
        print(f"   주문 ID: {sell_result.order_id}")
        print(f"   체결가: ${sell_result.filled_price:.2f}")
        print(f"   상태: {sell_result.status}")
        results['sell_order_id'] = sell_result.order_id
        results['sell_filled_price'] = sell_result.filled_price

        # 잠시 대기
        await asyncio.sleep(2)

        # 최종 잔고 확인
        print("\n[8] 최종 잔고 확인...")
        final_balance = await client.get_balance()
        print(f"✓ 최종 잔고: {final_balance.total:.2f} USDT (가용: {final_balance.free:.2f})")
        results['final_balance'] = final_balance.total

        # 손익 계산
        pnl = final_balance.total - initial_balance.total
        print(f"\n{'='*60}")
        print(f"순손익: ${pnl:.4f} USDT")
        print(f"{'='*60}")
        results['pnl'] = pnl
        results['success'] = True

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
    print(f"Aster 거래소 매수/매도 테스트")
    print(f"테스트 시작 시간: {datetime.utcnow().isoformat()}")
    print("="*60)

    # Aster 테스트
    aster_results = await test_aster_trade()

    # 결과 요약
    print("\n\n" + "="*60)
    print("테스트 결과 요약")
    print("="*60)

    print("\n[Aster]")
    if aster_results.get('success'):
        print(f"✓ 성공")
        print(f"  초기 잔고: ${aster_results['initial_balance']:.2f}")
        print(f"  최종 잔고: ${aster_results['final_balance']:.2f}")
        print(f"  순손익: ${aster_results['pnl']:.4f}")
    else:
        print(f"✗ 실패: {aster_results.get('error', 'Unknown error')}")

    print("\n" + "="*60)
    print(f"테스트 종료 시간: {datetime.utcnow().isoformat()}")
    print("="*60)

    # 결과를 파일로 저장
    output_file = f"/home/kyj1435/project/perpdex_trading/cluade_zone/{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_aster_test_result.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("="*60 + "\n")
        f.write("Aster 거래소 매수/매도 테스트 결과\n")
        f.write(f"테스트 시간: {datetime.utcnow().isoformat()}\n")
        f.write("="*60 + "\n\n")

        f.write("[Aster 테스트]\n")
        if aster_results.get('success'):
            f.write(f"상태: 성공\n")
            f.write(f"거래 심볼: {aster_results.get('symbol', 'N/A')}\n")
            f.write(f"현재가: ${aster_results.get('current_price', 0):.2f}\n")
            f.write(f"초기 잔고: ${aster_results['initial_balance']:.2f}\n")
            f.write(f"최종 잔고: ${aster_results['final_balance']:.2f}\n")
            f.write(f"순손익: ${aster_results['pnl']:.4f}\n")
            f.write(f"매수 체결가: ${aster_results.get('buy_filled_price', 0):.2f}\n")
            f.write(f"매도 체결가: ${aster_results.get('sell_filled_price', 0):.2f}\n")
        else:
            f.write(f"상태: 실패\n")
            f.write(f"에러: {aster_results.get('error', 'Unknown error')}\n")

        f.write("\n" + "="*60 + "\n")

    print(f"\n결과가 {output_file}에 저장되었습니다.")

    return aster_results


if __name__ == "__main__":
    asyncio.run(main())