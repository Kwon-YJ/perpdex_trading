# 델타 중립 거래량 증폭 봇 마스터 플랜

## 목표
델타 리스크 없이 거래량만 증폭하는 자동 트레이딩 시스템 구축

## 핵심 전략
1. **롱 바스켓**: 임의 절반 거래소에서 거래소별 3~5개 자산으로 시장가 롱 포지션 구성
2. **숏 바스켓**: 나머지 절반 거래소에서 롱 바스켓과 높은 상관계수를 가진 다른 자산들로 시장가 숏 포지션 구성 (델타 기반)
3. **청산 조건**:
   - 순이익(수수료 제외) 1원 이상 시 즉시 청산
   - 강제 청산 발생 시 모든 포지션 즉시 정리 및 현금화
4. **사이클**: 10분 대기 → 청산 → 10분 대기 → 반복

## 아키텍처 설계

### 모듈 구조
```
src/perpdex_trading/
├── exchanges/          # 거래소 API 클라이언트
│   ├── base.py        # 공통 인터페이스
│   ├── paradex.py     # Paradex 클라이언트
│   ├── hibachi.py     # Hibachi 클라이언트
│   ├── extended.py    # Extended 클라이언트
│   ├── tanx.py        # TanX 클라이언트
│   ├── backpack.py    # Backpack 클라이언트
│   ├── grvt.py        # GRVT 클라이언트
│   ├── lighter.py     # Lighter 클라이언트
│   ├── edgex.py       # Edgex 클라이언트
│   └── aster.py       # Aster 클라이언트
├── strategy/          # 전략 로직
│   ├── correlation.py # 상관계수 계산
│   ├── portfolio.py   # 델타 중립 포트폴리오 생성
│   └── liquidation.py # 청산 조건 모니터링
├── trading/           # 거래 실행
│   ├── executor.py    # 주문 실행
│   └── monitor.py     # 포지션 모니터링
├── utils/             # 유틸리티
│   ├── logger.py      # 로깅
│   └── config.py      # 설정 관리
└── main.py            # 메인 루프
```

## 현재 상태
- 거래소 가이드 확인 완료
- API 키 확인 완료
- 프로젝트 구조 설계 완료

## 다음 단계
1. 공통 거래소 인터페이스 정의
2. 주요 거래소 API 클라이언트 구현
3. 상관계수 계산 로직
4. 델타 중립 포트폴리오 생성
