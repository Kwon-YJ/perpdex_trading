# 델타 중립 트레이딩 봇 구현 로그
시작 시간: 2025-09-30 08:50:45 UTC

## 현황 분석
1. **프로젝트 구조**
   - 프로젝트 루트: `/home/kyj1435/project/perpdex_trading`
   - 소스 디렉토리: `src/perpdex_trading/` (현재 비어있음)
   - 작업 공간: `cluade_zone/` (root 소유, 쓰기 권한 없음)
   - Python 가상환경: `.venv/` 활성화됨 (Python 3.12.9)
   - 패키지 관리: Rye 사용

2. **거래소 정보** (exchange_guide.txt에서 확인)
   - Paradex: 1000 USDC (API 지원, Python SDK)
   - Hibachi: 1000 USDT (ARB)
   - Extended: 1000 USDC
   - TanX: 1000 USDC
   - Backpack: 1000 USDT (SOL)
   - GRVT: 1000 USDT (BSC)
   - Lighter: 1008 USDC (ARB)
   - Edgex: 990 USDT (ARB)
   - Aster: 1001 USDT (ARB)

3. **API 키 확인 완료** (.env 파일 존재)

4. **권한 문제**
   - src/ 및 cluade_zone/ 폴더가 root 소유
   - 임시 작업 공간 /tmp/perpdex_work 사용

## 구현 전략

### Phase 1: 간소화된 프로토타입 (80% 구현, 20% 테스트)
주요 거래소 3개만 우선 구현:
1. **Paradex** - Python SDK 지원, 문서 양호
2. **Backpack** - Python SDK 지원
3. **GRVT** - Python SDK 지원

간소화된 전략:
- 상관계수 계산 대신 **동일 자산(예: BTC, ETH)으로 롱/숏** 구성
- 이렇게 하면 상관계수 ≈ 1.0으로 완벽한 델타 헤지 가능
- 거래소 간 가격 차이로 인한 소액 차익 기대

### 구현 계획

#### 1단계: 핵심 인프라 (완료)
- [x] 공통 거래소 인터페이스 정의 (base.py)
- [x] 데이터 클래스 정의 (Asset, Position, Order, etc.)

#### 2단계: 거래소 클라이언트 (진행 중)
- [ ] Paradex 클라이언트 구현
  - paradex-py SDK 설치
  - 잔고 조회
  - 자산 목록 조회
  - 시장가 주문
  - 포지션 조회/청산

- [ ] Backpack 클라이언트 구현
- [ ] GRVT 클라이언트 구현

#### 3단계: 거래 로직
- [ ] 포트폴리오 관리자
  - 거래소 그룹 분할 (롱/숏)
  - 동일 자산 선택 로직
  - 델타 계산 및 균형 맞추기

- [ ] 청산 모니터
  - 총 손익 계산
  - 강제 청산 감지
  - 자동 청산 실행

#### 4단계: 메인 루프
- [ ] 트레이딩 사이클 구현
  - 포지션 생성
  - 10분 대기
  - 청산 조건 모니터링
  - 포지션 청산
  - 로깅 및 자본 업데이트

#### 5단계: 테스트 (20%)
- [ ] 단위 테스트
- [ ] 통합 테스트
- [ ] Dry-run 모드 실행

## 현재 작업
Paradex API 클라이언트 구현 중

## 참고사항
- 실제 자금 사용 전 충분한 테스트 필요
- 각 거래소의 최소 주문 크기, 수수료 구조 확인 필요
- API rate limit 고려
- 네트워크 지연 및 슬리피지 고려