import os
import time
from dotenv import load_dotenv
import math
from hibachi_xyz import HibachiApiClient, Side


# Load environment variables from .env file
load_dotenv()

# --- Configuration from Environment Variables ---
API_ENDPOINT = os.environ.get('HIBACHI_API_ENDPOINT_PRODUCTION', 'https://api.hibachi.xyz')
DATA_API_ENDPOINT = os.environ.get('HIBACHI_DATA_API_ENDPOINT_PRODUCTION', 'https://data-api.hibachi.xyz')
API_KEY = os.getenv("HIBACHI_PUB_KEY")
ACCOUNT_ID = os.getenv("HIBACHI_ID")
PUBLIC_KEY = os.getenv("HIBACHI_PUB_KEY")
PRIVATE_KEY = os.getenv("HIBACHI_SEC_KEY")

# --- Initialize Hibachi API Client ---
if not all([API_KEY, ACCOUNT_ID, PRIVATE_KEY]):
    print("Error: Missing one or more required environment variables.")
    print("Please set HIBACHI_PUB_KEY, HIBACHI_ID, HIBACHI_SEC_KEY in your .env file.")
    exit(1)

try:
    hibachi_client = HibachiApiClient(
        api_url=API_ENDPOINT,
        data_api_url=DATA_API_ENDPOINT,
        api_key=API_KEY,
        account_id=ACCOUNT_ID,
        private_key=PRIVATE_KEY,
    )
    print("✓ HibachiApiClient initialized successfully.")
except Exception as e:
    print(f"✗ Error initializing HibachiApiClient: {e}")
    exit(1)

# --- Get account balance ---
def get_account_balance():
    """계좌 잔액 조회"""
    try:
        balance = hibachi_client.get_account_balance()
        print("\n=== Account Balance ===")
        print(f"Account ID: {ACCOUNT_ID}")
        
        if hasattr(balance, '__dict__'):
            print("\nBalance Details:")
            for key, value in balance.__dict__.items():
                print(f"  {key}: {value}")
        else:
            print(f"Balance: {balance}")
        
        return balance
    except Exception as e:
        print(f"✗ Error getting account balance: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_exchange_info():
    try:
        exchange_info = hibachi_client.get_exchange_info()
        print("\n=== Exchange Info ===")
        print(f"Exchange Status: {exchange_info.status}")
        print(f"Maker Fee: {float(exchange_info.feeConfig.tradeMakerFeeRate) * 100}%")
        print(f"Taker Fee: {float(exchange_info.feeConfig.tradeTakerFeeRate) * 100}%")
        
        return exchange_info
    except Exception as e:
        print(f"✗ Error getting exchange info: {e}")
        import traceback
        traceback.print_exc()
        return None

# --- Helper function to find contract by symbol ---
def get_contract_by_symbol(exchange_info, symbol: str):
    for contract in exchange_info.futureContracts:
        if contract.symbol == symbol:
            return contract
    return None




# --- Get account balance ---
def get_capital_balance():
    """계좌 잔액 조회 (REST)"""
    try:
        bal = hibachi_client.get_capital_balance()  # ✅ 메서드명 수정
        print("\n=== Capital Balance ===")
        print(bal)
        return bal
    except Exception as e:
        print(f"✗ Error get_capital_balance: {e}")
        return None

def get_account_info():
    """계좌 요약(증거금, 총 포지션 명목 등)"""
    try:
        info = hibachi_client.get_account_info()  # ✅ 메서드명 수정
        print("\n=== Account Info ===")
        print(f"Balance: {getattr(info, 'balance', None)}")
        print(f"Total Position Notional: {getattr(info, 'totalPositionNotional', None)}")
        return info
    except Exception as e:
        print(f"✗ Error get_account_info: {e}")
        return None

# 참고: REST에 get_positions()는 없음. 포지션 상세는 계정 WS 클라이언트를 사용.
# (HibachiWSAccountClient 예제는 SDK 문서 참조)

# --- helpers ---
def floor_to_step(x: float, step: float) -> float:
    return math.floor(x / step) * step

def ceil_to_step(x: float, step: float) -> float:
    return math.ceil(x / step) * step

def quantize_price_qty(price: float, qty: float, tick: float, step: float):
    return floor_to_step(price, tick), floor_to_step(qty, step)

def min_qty_for_notional(min_notional: float, price: float, step: float) -> float:
    return ceil_to_step(min_notional / price, step)

# --- place LIMIT ---
def place_limit_order(symbol: str, side: str, quantity: float, price: float, max_fees_percent: float = 0.001):
    print(f"\n{'='*60}\nPlacing LIMIT {side} Order\nSymbol:{symbol} Qty:{quantity} Price:{price} MaxFees:{max_fees_percent}\n{'='*60}")
    try:
        # 계약 메타에서 제약 가져오기
        exch = hibachi_client.get_exchange_info()
        contract = next((c for c in exch.futureContracts if c.symbol == symbol), None)
        if not contract:
            raise ValueError(f"Unknown symbol {symbol}")

        tick = float(contract.tickSize)
        step = float(contract.stepSize)
        min_notional = float(contract.minNotional)

        # 유효한 tick/step & minNotional 맞추기
        price_q, qty_q = quantize_price_qty(price, quantity, tick, step)
        if price_q * qty_q < min_notional:
            needed = min_qty_for_notional(min_notional, price_q, step)
            qty_q = max(qty_q, needed)

        # enum 변환
        side_enum = Side.BID if side.upper() in ("BID", "BUY") else Side.ASK

        # ✅ 올바른 시그니처 사용 (nonce 전달 X, quantity/price는 float)
        nonce, order_id = hibachi_client.place_limit_order(
            symbol, qty_q, price_q, side_enum, max_fees_percent
        )
        print(f"✓ Limit placed. nonce={nonce}, order_id={order_id}")
        return order_id
    except Exception as e:
        print(f"✗ Error placing limit: {e}")
        return None

# --- place MARKET ---
def place_market_order(symbol: str, side: str, quantity: float, max_fees_percent: float = 0.001):
    print(f"\n{'='*60}\nPlacing MARKET {side} Order\nSymbol:{symbol} Qty:{quantity} MaxFees:{max_fees_percent}\n{'='*60}")
    try:
        # minNotional 체크(시장가이므로 대략 현재가 대신 mark를 쓰고 싶다면 get_inventory() 등 활용)
        exch = hibachi_client.get_exchange_info()
        contract = next((c for c in exch.futureContracts if c.symbol == symbol), None)
        if not contract:
            raise ValueError(f"Unknown symbol {symbol}")
        step = float(contract.stepSize)
        # 필요시 get_prices()/get_inventory()로 mark/last 받아 minNotional 검증 추가 가능

        qty_q = floor_to_step(quantity, step)
        side_enum = Side.BID if side.upper() in ("BID", "BUY") else Side.ASK

        nonce, order_id = hibachi_client.place_market_order(
            symbol, qty_q, side_enum, max_fees_percent
        )
        print(f"✓ Market placed. nonce={nonce}, order_id={order_id}")
        return order_id
    except Exception as e:
        print(f"✗ Error placing market: {e}")
        return None

# --- main ---
if __name__ == "__main__":
    # 1) 거래소 정보
    exchange_info = get_exchange_info()
    if not exchange_info:
        print("✗ Could not retrieve exchange information. Exiting.")
        exit(1)

    # 2) 잔액/계정
    get_capital_balance()
    get_account_info()

    # 3) 심볼 확인
    target_symbol = "BTC/USDT-P"
    contract = next((c for c in exchange_info.futureContracts if c.symbol == target_symbol), None)
    if not contract:
        print(f"✗ Symbol {target_symbol} not found."); exit(1)
    print(f"✓ Found {target_symbol} minNotional={contract.minNotional} step={contract.stepSize} tick={contract.tickSize}")

    # 4) 테스트 주문 (체결되지 않을 낮은 가격이지만 유효하게)
    test_price = 10_000.0
    # minNotional 충족 수량 계산
    min_qty = max(float(contract.minOrderSize), min_qty_for_notional(float(contract.minNotional), test_price, float(contract.stepSize)))
    place_limit_order(target_symbol, "BID", quantity=min_qty, price=test_price, max_fees_percent=0.001)