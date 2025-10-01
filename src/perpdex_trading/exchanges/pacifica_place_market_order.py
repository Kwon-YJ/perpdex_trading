#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, time, uuid, argparse, sys
from decimal import Decimal, ROUND_DOWN, getcontext
import requests
import base58
from dotenv import load_dotenv
import re, base64

# solders: Ed25519 on Solana
from solders.keypair import Keypair

getcontext().prec = 40  # 안전한 고정소수 계산 정밀도

MAINNET_BASE = "https://api.pacifica.fi/api/v1"
TESTNET_BASE = "https://test-api.pacifica.fi/api/v1"

INFO_ENDPOINT = "/info"                # GET 심볼 스펙 (tick/lot/min_order_size 등)
PRICES_ENDPOINT = "/info/prices"       # GET 마크/미드 가격 등
CREATE_MKT_ENDPOINT = "/orders/create_market"  # POST 시장가 주문


def _extract_from_json_like(s: str) -> str | None:
    """
    문자열이 JSON 오브젝트라면 private key 후보를 뽑아 반환.
    예: {"privateKey":"0x..."} 또는 {"data":"[1,2,...]"} 등
    """
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        # 이미 [..] 배열이면 문자열로 다시 넘김
        return json.dumps(obj)
    if isinstance(obj, dict):
        # 흔한 키 후보들
        for k in ["privateKey", "private_key", "secret", "sk", "pk", "key", "data", "value"]:
            v = obj.get(k)
            if isinstance(v, (str, list)):
                return v if isinstance(v, str) else json.dumps(v)
        # 1단계 중첩 탐색
        for v in obj.values():
            if isinstance(v, (dict, list, str)):
                inner = _extract_from_json_like(json.dumps(v) if not isinstance(v, str) else v)
                if inner:
                    return inner
    return None



###############################################################################
# 키 유틸 (정규화/검증 통합)
###############################################################################

def _decode_any_to_bytes(raw: str) -> bytes:
    """
    JSON [..] / JSON 오브젝트 / solana:<...> / 0xHEX(+구분자 허용) / base64 / base58
    무엇이든 받아 32 또는 64바이트로 디코드하여 반환.
    """
    s = (raw or "").strip()

    # 1) 스킴 접두어 처리 (예: solana:xxxxx, key:xxxxx)
    if ":" in s and not s.startswith("[") and not s.startswith("{"):
        # 첫 콜론 뒤부터가 payload라고 가정
        prefix, payload = s.split(":", 1)
        # solana:, priv:, key:, pk: 등 흔한 접두어는 그냥 payload 사용
        if prefix.lower() in ("solana", "priv", "private", "key", "pk", "sk"):
            s = payload.strip()

    # 2) JSON 오브젝트 안에 들어있는 키 뽑기
    cand = _extract_from_json_like(s)
    if cand is not None:
        s = cand.strip()

    # 3) JSON 배열([1,2,...])이면 바로 처리
    if s.startswith("[") and s.endswith("]"):
        b = bytes(json.loads(s))
        return b

    # 4) base64 시도 (패딩 포함/불포함 모두 허용)
    try:
        b64 = s
        # URL-safe 변형 보정
        b64 = b64.replace("-", "+").replace("_", "/")
        # 패딩 부족 시 보정
        if len(b64) % 4 != 0:
            b64 += "=" * (4 - (len(b64) % 4))
        b = base64.b64decode(b64, validate=False)
        if len(b) in (32, 64):
            return b
    except Exception:
        pass

    # 5) HEX 시도: 0x 접두어 제거 + 구분자 제거(공백, 콜론, 하이픈, 언더스코어)
    s_hex = s
    if s_hex.lower().startswith("0x"):
        s_hex = s_hex[2:]
    s_hex = re.sub(r"[^0-9a-fA-F]", "", s_hex)
    if len(s_hex) in (64, 128):  # 32바이트 또는 64바이트 hex
        try:
            b = bytes.fromhex(s_hex)
            if len(b) in (32, 64):
                return b
        except Exception:
            pass

    # 6) Base58 최후 시도 (주의: Base58에는 문자 '0'이 없음)
    try:
        b = base58.b58decode(s)
        if len(b) in (32, 64):
            return b
    except Exception as e:
        # 마지막까지 실패
        raise ValueError(
            "인식 불가한 키 형식입니다. JSON/hex/base64/base58 중 하나여야 하며, 길이는 32 또는 64바이트여야 합니다. "
            f"(디코딩 에러: {e})"
        )

    # 안전망
    raise ValueError("인식 불가한 키 형식입니다. 32 또는 64바이트 길이의 Solana Ed25519 키만 허용됩니다.")

def _keypair_from_any(raw: str) -> Keypair:
    """
    JSON/HEX/Base58 무엇이든 받아 Keypair 생성.
    길이에 따라 from_bytes(64) 또는 from_seed(32)를 선택.
    """
    b = _decode_any_to_bytes(raw)
    if len(b) == 64:
        return Keypair.from_bytes(b)
    if len(b) == 32:
        return Keypair.from_seed(b)
    raise ValueError(f"키 길이가 {len(b)}바이트입니다. Solana Ed25519는 32 또는 64바이트만 허용합니다.")

def _normalized_key_strings(kp: Keypair) -> tuple[str, str]:
    """
    Keypair를 표준 포맷 두 가지로 출력용 변환:
    - Base58-64byte (secret+public)
    - JSON-64byte   (secret+public)
    """
    b64 = bytes(kp)  # 64 bytes: secret(32)+public(32)
    base58_sk = base58.b58encode(b64).decode("ascii")
    json_sk = json.dumps(list(b64))
    return base58_sk, json_sk

def load_signing_keypair():
    """
    에이전트키가 있으면 그것으로 서명, 없으면 PRIVATE_KEY로 서명.
    이때 해당 공개키와 환경변수(AGENT_WALLET / ACCOUNT)가 불일치하면 즉시 에러.
    """
    agent_priv = os.getenv("PACIFICA_AGENT_PRIVATE_KEY")
    owner_priv = os.getenv("PACIFICA_PRIVATE_KEY")

    if agent_priv:
        kp = _keypair_from_any(agent_priv)
        agent_wallet_env = os.getenv("PACIFICA_AGENT_WALLET")
        if agent_wallet_env and agent_wallet_env != str(kp.pubkey()):
            raise RuntimeError(
                f"PACIFICA_AGENT_WALLET({agent_wallet_env}) ≠ 에이전트 서명키의 공개키({kp.pubkey()})."
            )
        return kp, "agent"

    if owner_priv:
        kp = _keypair_from_any(owner_priv)
        account_env = os.getenv("PACIFICA_ACCOUNT")
        if account_env and account_env != str(kp.pubkey()):
            raise RuntimeError(
                f"PACIFICA_ACCOUNT({account_env}) ≠ 오너 서명키의 공개키({kp.pubkey()})."
            )
        return kp, "owner"

    raise RuntimeError("에이전트키(PACIFICA_AGENT_PRIVATE_KEY) 또는 원본키(PACIFICA_PRIVATE_KEY)가 필요합니다.")

def get_account_pubkey(signing_mode: str, kp: Keypair) -> str:
    """
    account(원본 지갑 퍼블릭키)를 결정.
    - 에이전트 서명: 반드시 PACIFICA_ACCOUNT를 사용 (문서 규정)
    - 원본키 서명: PACIFICA_ACCOUNT 없으면 서명키에서 유도
    """
    account = os.getenv("PACIFICA_ACCOUNT")
    if signing_mode == "agent":
        if not account:
            raise RuntimeError("에이전트 사용 시 PACIFICA_ACCOUNT(원본 지갑 주소)가 반드시 필요합니다.")
        return account
    # owner mode
    return account or str(kp.pubkey())

def get_agent_wallet_pubkey() -> str | None:
    return os.getenv("PACIFICA_AGENT_WALLET") or None

###############################################################################
# API 호출
###############################################################################
def get_market_info(base_url: str) -> list[dict]:
    r = requests.get(base_url + INFO_ENDPOINT, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("data", [])

def get_prices(base_url: str) -> list[dict]:
    r = requests.get(base_url + PRICES_ENDPOINT, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("data", [])

def find_symbol_info(symbol: str, info_list: list[dict]) -> dict:
    for it in info_list:
        if it.get("symbol", "").upper() == symbol.upper():
            return it
    raise ValueError(f"심볼 스펙을 찾지 못했습니다: {symbol}")

def find_symbol_price(symbol: str, prices_list: list[dict]) -> dict:
    for it in prices_list:
        if it.get("symbol", "").upper() == symbol.upper():
            return it
    raise ValueError(f"심볼 가격을 찾지 못했습니다: {symbol}")

def quantize_amount(amount: Decimal, lot_size: Decimal) -> Decimal:
    return (amount // lot_size) * lot_size  # 내림

def ceil_to_lot(min_amount: Decimal, lot_size: Decimal) -> Decimal:
    q = (min_amount / lot_size).to_integral_value(rounding=ROUND_DOWN)
    if q * lot_size < min_amount:
        q += 1
    return q * lot_size

###############################################################################
# Pacifica 서명 (deterministic JSON + Ed25519 base58)
###############################################################################
def recursive_sort(obj):
    if isinstance(obj, dict):
        return {k: recursive_sort(obj[k]) for k in sorted(obj.keys())}
    if isinstance(obj, list):
        return [recursive_sort(x) for x in obj]
    return obj

def sign_operation(kp: Keypair, op_type: str, op_data: dict, expiry_ms: int) -> dict:
    ts = int(time.time() * 1000)
    sig_header = {
        "timestamp": ts,
        "expiry_window": expiry_ms,
        "type": op_type,
    }
    to_sign = {**sig_header, "data": op_data}
    sorted_msg = recursive_sort(to_sign)
    compact = json.dumps(sorted_msg, separators=(",", ":")).encode("utf-8")
    sig = kp.sign_message(compact)
    sig_b58 = base58.b58encode(bytes(sig)).decode("ascii")
    return {"signature": sig_b58, **sig_header}

###############################################################################
# 주문
###############################################################################
def place_market_order(
    base_url: str,
    account_pubkey: str,
    agent_wallet: str | None,
    kp: Keypair,
    symbol: str,
    side: str,
    amount: Decimal | None,
    notional_usd: Decimal | None,
    slippage_percent: Decimal,
    reduce_only: bool,
    expiry_ms: int = 5000,
    auto_pad_min: bool = True,
):
    # 1) 기초 정보/가격
    info = get_market_info(base_url)
    prices = get_prices(base_url)
    sym_info = find_symbol_info(symbol, info)
    sym_px = find_symbol_price(symbol, prices)

    lot_size = Decimal(sym_info["lot_size"])
    min_order_usd = Decimal(sym_info["min_order_size"])
    mark = Decimal(sym_px["mark"])

    # 2) 수량 산출
    if amount is None and notional_usd is None:
        raise ValueError("amount 또는 notional_usd 중 하나는 지정해야 합니다.")
    if amount is None:
        # USD 명목가 → 베이스 수량
        amount = (notional_usd / mark)

    # 3) lot 반올림(내림)
    qty = quantize_amount(amount, lot_size)
    if qty <= 0:
        qty = lot_size

    # 4) 최소 주문 USD 충족 보정
    usd_notional = qty * mark
    if usd_notional < min_order_usd and auto_pad_min:
        need = min_order_usd / mark
        qty = ceil_to_lot(need, lot_size)
        usd_notional = qty * mark

    # 5) 요청 바디 구성 (문서 규격)
    op_data = {
        "symbol": symbol.upper(),
        "amount": str(qty),
        "side": "bid" if side.lower() in ("buy", "bid", "long") else "ask",
        "slippage_percent": str(slippage_percent),
        "reduce_only": bool(reduce_only),
        "client_order_id": str(uuid.uuid4()),
    }

    # 6) 서명
    signed = sign_operation(kp, "create_market_order", op_data, expiry_ms)

    # 7) 최종 요청(JSON)
    body = {
        "account": account_pubkey,
        "agent_wallet": agent_wallet,
        **signed,
        **op_data,  # data 래퍼 없이 병합 (문서 규정)
    }

    # 8) 전송
    resp = requests.post(
        base_url + CREATE_MKT_ENDPOINT,
        json=body,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    # 9) 결과 처리
    try:
        data = resp.json()
    except Exception:
        resp.raise_for_status()
        raise

    if resp.status_code != 200:
        raise RuntimeError(f"Order rejected (HTTP {resp.status_code}): {data}")

    return {
        "symbol": symbol.upper(),
        "side": op_data["side"],
        "qty": str(qty),
        "usd_notional": str(usd_notional.quantize(Decimal("0.0001"))),
        "slippage_percent": str(slippage_percent),
        "order_response": data,
        "endpoint": base_url + CREATE_MKT_ENDPOINT,
    }

###############################################################################
# CLI
###############################################################################
def main():
    load_dotenv()

    p = argparse.ArgumentParser(
        description="Place Pacifica market order (buy/sell) via REST"
    )
    p.add_argument("symbol", help="e.g., BTC / ETH ...")
    p.add_argument("side", help="BUY|SELL (또는 bid/ask/long/short)")
    p.add_argument("amount", nargs="?", type=str, help="베이스 수량 (옵션, --notional-usd 사용 시 생략)")
    p.add_argument("--notional-usd", type=str, help="USD 명목가 (베이스 수량 대신)")
    p.add_argument("--slip", type=str, default="0.5", help="슬리피지 %, 기본 0.5")
    p.add_argument("--reduce-only", action="store_true", help="Reduce-only 주문")
    p.add_argument("--expiry-ms", type=int, default=5000, help="서명 유효기간 ms (기본 5000)")
    p.add_argument("--testnet", action="store_true", help="테스트넷 사용")
    p.add_argument("--key-check", action="store_true", help="환경변수 키를 정규화(Base58/JSON)해 출력하고 종료")

    args = p.parse_args()

    base_url = TESTNET_BASE if args.testnet else MAINNET_BASE

    # 키 로딩 및 모드 결정(+일관성 검증)
    kp, mode = load_signing_keypair()

    # 키 정규화 출력만 원하는 경우
    if args.key_check:
        base58_sk, json_sk = _normalized_key_strings(kp)
        print("Mode          :", mode)
        print("Signer Pubkey :", str(kp.pubkey()))
        print("Base58-64byte :", base58_sk)
        print("JSON-64byte   :", json_sk)
        sys.exit(0)

    account = get_account_pubkey(mode, kp)
    agent_wallet = get_agent_wallet_pubkey() if mode == "agent" else None

    # agent 모드는 agent_wallet 필수 & 서명키와 일치 검사
    if mode == "agent":
        if not agent_wallet:
            raise RuntimeError("agent 모드: PACIFICA_AGENT_WALLET 환경변수가 필요합니다.")
        if agent_wallet != str(kp.pubkey()):
            raise RuntimeError(
                f"agent 모드: PACIFICA_AGENT_WALLET({agent_wallet}) ≠ 서명키 공개키({kp.pubkey()})."
            )

    amount = Decimal(args.amount) if args.amount is not None else None
    notional = Decimal(args.notional_usd) if args.notional_usd else None
    slip = Decimal(args.slip)

    if args.side.lower() not in ("buy", "sell", "bid", "ask", "long", "short"):
        print("side는 BUY/SELL(bid/ask/long/short) 중 하나여야 합니다.", file=sys.stderr)
        sys.exit(2)

    res = place_market_order(
        base_url=base_url,
        account_pubkey=account,
        agent_wallet=agent_wallet,
        kp=kp,
        symbol=args.symbol.upper(),
        side=args.side,
        amount=amount,
        notional_usd=notional,
        slippage_percent=slip,
        reduce_only=args.reduce_only,
        expiry_ms=args.expiry_ms,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
