"""델타 중립 트레이딩 봇 실행 스크립트."""

import asyncio
import os
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from dotenv import load_dotenv

from main_loop import TradingBot
from base import ExchangeClient
from exchange_guide_updater import ExchangeGuideUpdater

TRADING_DIR = Path(__file__).resolve().parent
CLUADE_ZONE_DIR = TRADING_DIR.parent
PROJECT_ROOT = CLUADE_ZONE_DIR.parent

IMPORT_WARNINGS: List[str] = []

try:
    from backpack_client import BackpackClient  # type: ignore
except Exception as exc:  # pragma: no cover - 로컬 환경에 따라 달라짐
    BackpackClient = None  # type: ignore
    IMPORT_WARNINGS.append(f"Backpack 클라이언트 모듈 로드 실패: {exc}")

try:
    from grvt_client import GrvtClient  # type: ignore
except Exception as exc:  # pragma: no cover - 로컬 환경에 따라 달라짐
    GrvtClient = None  # type: ignore
    IMPORT_WARNINGS.append(f"GRVT 클라이언트 모듈 로드 실패: {exc}")

ClientBuilder = Callable[[], ExchangeClient]
CLIENT_BUILDERS: Dict[str, ClientBuilder] = {}


if 'BackpackClient' in globals() and BackpackClient is not None:
    def build_backpack() -> ExchangeClient:
        api_key = os.getenv("BACKPACK_PUBLIC_KEY")
        secret_key = os.getenv("BACKPACK_PRIVATE_KEY")

        if not api_key or not secret_key:
            raise ValueError("Backpack API 키 또는 시크릿이 설정되지 않았습니다.")

        return BackpackClient(api_key, secret_key)

    CLIENT_BUILDERS["backpack"] = build_backpack


if 'GrvtClient' in globals() and GrvtClient is not None:
    def build_grvt() -> ExchangeClient:
        api_key = os.getenv("GRVT_PUB_KEY")
        private_key = os.getenv("GRVT_SEC_KEY")
        trading_account = os.getenv("GRVT_TRADING_ACCOUNT_ID")

        if not api_key or not private_key:
            raise ValueError("GRVT API 키 또는 시크릿이 설정되지 않았습니다.")

        return GrvtClient(api_key, private_key, trading_account)

    CLIENT_BUILDERS["grvt"] = build_grvt


def load_environment() -> List[str]:
    """환경 변수를 로드하고 결과 메시지를 반환합니다."""
    messages: List[str] = []
    env_path = PROJECT_ROOT / ".env"

    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path))
        messages.append(".env 파일을 불러왔습니다.")
    else:
        load_dotenv()
        messages.append(".env 파일을 찾지 못해 시스템 환경변수를 사용합니다.")

    return messages


def find_exchange_guide() -> Path:
    """exchange_guide.txt 경로를 탐색합니다."""
    candidates = [
        CLUADE_ZONE_DIR / "exchange_guide.txt",
        PROJECT_ROOT / "exchange_guide.txt",
    ]

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError("exchange_guide.txt 파일을 찾을 수 없습니다.")


def load_exchange_names(file_path: Path) -> List[str]:
    """exchange_guide.txt에서 거래소 이름을 로드합니다."""
    updater = ExchangeGuideUpdater(str(file_path))
    rows = updater.read_exchange_guide()

    exchange_names: List[str] = []
    for row in rows:
        name = (row.get('거래소명') or '').strip()
        if name:
            exchange_names.append(name)

    return exchange_names


def prepare_clients(exchange_names: List[str]) -> Tuple[List[ExchangeClient], List[str]]:
    """거래소 이름 목록을 기반으로 클라이언트를 준비합니다."""
    clients: List[ExchangeClient] = []
    logs: List[str] = []

    for name in exchange_names:
        key = name.strip().lower()
        builder = CLIENT_BUILDERS.get(key)

        if builder is None:
            logs.append(f"{name} 거래소는 아직 자동화 대상에 포함되지 않았습니다.")
            continue

        try:
            client = builder()
        except ValueError as exc:
            logs.append(f"{name} 클라이언트 준비 실패: {exc}")
        except ImportError as exc:
            logs.append(f"{name} 클라이언트 준비 실패 (라이브러리 누락): {exc}")
        except Exception as exc:
            logs.append(f"{name} 클라이언트 준비 중 예기치 않은 오류: {exc}")
        else:
            clients.append(client)
            logs.append(f"{name} 클라이언트를 성공적으로 준비했습니다.")

    return clients, logs


async def run_bot() -> None:
    """트레이딩 봇 실행."""
    info_messages = load_environment()

    exchange_names: List[str] = []
    try:
        exchange_file = find_exchange_guide()
        info_messages.append(f"거래소 가이드 파일 경로: {exchange_file}")
        exchange_names = load_exchange_names(exchange_file)
    except FileNotFoundError:
        info_messages.append("exchange_guide.txt 파일을 찾지 못했습니다.")

    clients, client_logs = prepare_clients(exchange_names)
    info_messages.extend(client_logs)

    bot = TradingBot(
        clients,
        profit_target=0.01,
        capital_per_side=100.0,
        wait_time=600,
        use_correlation=True,
    )

    for warning in IMPORT_WARNINGS:
        bot.log(f"⚠️ {warning}")

    for message in info_messages:
        bot.log(message)

    if not exchange_names:
        bot.log("⚠️ 거래소 목록이 비어 있어 봇 실행을 종료합니다.")
        return

    if not clients:
        bot.log("⚠️ 사용 가능한 거래소 클라이언트가 없어 봇 실행을 종료합니다.")
        return

    bot.log(f"준비 완료: {len(clients)}개 거래소를 대상으로 사이클을 시작합니다.")

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.log("사용자 중단 신호로 인해 봇을 종료합니다.")
    finally:
        for client in clients:
            try:
                await client.close()
            except Exception as exc:
                bot.log(f"{client.name} 클라이언트 종료 과정에서 오류 발생: {exc}")


def main() -> None:
    """엔트리 포인트."""
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
