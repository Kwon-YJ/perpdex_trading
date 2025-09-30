"""델타 중립 트레이딩 봇 실행 스크립트"""
import asyncio
import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

# 로컬 모듈 경로 추가
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/exchanges')
sys.path.append('/home/kyj1435/project/perpdex_trading/cluade_zone/trading')

from dotenv import load_dotenv

from base import ExchangeClient
from backpack_client import BackpackClient
from grvt_client import GrvtClient
from main_loop import TradingBot

PROJECT_ROOT = Path('/home/kyj1435/project/perpdex_trading')
CLUADE_ZONE = PROJECT_ROOT / 'cluade_zone'
TRADING_RESULT_PATH = CLUADE_ZONE / 'trading_result.txt'


def _now_stamp() -> str:
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')


def _write_bootstrap_log(messages: List[str]) -> None:
    """봇 시작 전 로그를 파일로 남긴다."""
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    session_log = CLUADE_ZONE / f'{timestamp}.txt'
    session_log.touch(exist_ok=True)

    for message in messages:
        line = f"[{_now_stamp()}] {message}\n"
        for path in (TRADING_RESULT_PATH, session_log):
            try:
                with path.open('a', encoding='utf-8') as fp:
                    fp.write(line)
            except Exception:
                # 파일 쓰기 실패 시 다른 경로라도 계속 시도
                continue


def _locate_exchange_guide() -> Path:
    """exchange_guide 파일 경로를 탐색"""
    candidates = [
        PROJECT_ROOT / 'exchange_guide.txt',
        CLUADE_ZONE / 'exchange_guide.txt'
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError('exchange_guide.txt 파일을 찾지 못했습니다')


def _load_exchange_names(guide_path: Path) -> List[str]:
    exchanges: List[str] = []
    with guide_path.open('r', encoding='utf-8') as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            name = (row.get('거래소명') or '').strip()
            if name and name not in exchanges:
                exchanges.append(name)
    return exchanges


def _build_backpack_client() -> Tuple[Optional[ExchangeClient], str]:
    api_key = os.getenv('BACKPACK_PUBLIC_KEY')
    secret_key = os.getenv('BACKPACK_PRIVATE_KEY')

    if not api_key or not secret_key:
        return None, 'Backpack: API 키가 설정되지 않아 제외합니다'

    try:
        client = BackpackClient(api_key, secret_key)
        return client, 'Backpack: 클라이언트를 준비했습니다'
    except Exception as exc:  # pragma: no cover - 초기화 예외 기록 목적
        return None, f'Backpack: 클라이언트 생성 실패 {exc}'


def _build_grvt_client() -> Tuple[Optional[ExchangeClient], str]:
    api_key = os.getenv('GRVT_PUB_KEY')
    secret_key = os.getenv('GRVT_SEC_KEY')
    trading_account = os.getenv('GRVT_TRADING_ACCOUNT_ID')

    if not api_key or not secret_key:
        return None, 'GRVT: API 키가 없어 제외합니다'

    try:
        client = GrvtClient(api_key, secret_key, trading_account_id=trading_account)
        return client, 'GRVT: 클라이언트를 준비했습니다'
    except Exception as exc:  # pragma: no cover - 초기화 예외 기록 목적
        return None, f'GRVT: 클라이언트 생성 실패 {exc}'


CLIENT_BUILDERS: Dict[str, Callable[[], Tuple[Optional[ExchangeClient], str]]] = {
    'Backpack': _build_backpack_client,
    'GRVT': _build_grvt_client,
}


async def main() -> None:
    load_dotenv()

    bootstrap_logs: List[str] = []
    try:
        guide_path = _locate_exchange_guide()
        exchanges = _load_exchange_names(guide_path)
        bootstrap_logs.append(
            f'exchange_guide에서 {len(exchanges)}개 거래소를 불러왔습니다 ({guide_path.name})'
        )
    except Exception as exc:
        bootstrap_logs.append(f'거래소 목록을 불러오지 못했습니다: {exc}')
        _write_bootstrap_log(bootstrap_logs)
        return

    clients: List[ExchangeClient] = []

    for exchange_name in exchanges:
        builder = CLIENT_BUILDERS.get(exchange_name)
        if not builder:
            bootstrap_logs.append(f'{exchange_name}: 지원되는 자동화 클라이언트가 없어 건너뜁니다')
            continue

        client, message = builder()
        bootstrap_logs.append(message)
        if client:
            clients.append(client)

    if not clients:
        bootstrap_logs.append('활성화할 수 있는 거래소가 없어 봇을 시작하지 않습니다')
        _write_bootstrap_log(bootstrap_logs)
        return

    bot = TradingBot(
        clients=clients,
        capital_per_side=200.0,
        wait_time=600,
        use_correlation=len(clients) > 1
    )

    for message in bootstrap_logs:
        bot.log(message)

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.log('사용자 중단 감지: 모든 포지션을 정리합니다')
    except Exception as exc:  # pragma: no cover - 실행 중 예외 기록 목적
        import traceback
        bot.log(f'치명적 오류 발생: {exc}')
        bot.log(traceback.format_exc())
    finally:
        bot.log('종료 루틴 실행: 포지션 청산 및 세션 종료')
        try:
            await bot.portfolio_manager.close_all_positions()
        except Exception as cleanup_error:
            bot.log(f'포지션 청산 중 오류: {cleanup_error}')

        for client in clients:
            try:
                await client.close()
            except Exception as exc:
                bot.log(f'{client.name} 세션 종료 실패: {exc}')


if __name__ == '__main__':
    asyncio.run(main())
