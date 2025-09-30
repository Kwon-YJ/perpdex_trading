# 💡 목표: 델타 리스크 없이 거래량만 증폭

## 주요 동작
1. 거래소 목록에서 임의로 절반을 선택 후 **거래소별로 3~5개 자산**을 임의로 선정하여 시장가로 롱 포지션 바스켓 구성.
2. 나머지 절반 거래소에 **롱 바스켓 상관계수가 매우 높은, 다른 자산들로 시장가 숏 바스켓**을 구성하여 롱 바스켓과 숏 바스켓의 포트폴리오의 이론적 델타를 0으로 상쇄. 롱/숏 바스켓은 **명목가치가 아닌 델타 기반**으로 구성
3. **10분 대기**  
4. 청산조건 1: **총 포지션의 순이익(수수료, 슬리피지, 트랜잭션 비용 제외)이 1원 이상이 되는 즉시 모든 포지션을 청산**
5. 청산조건 2: 롱 숏 바스켓 중 **하나라도 강제 청산 시 즉시 모든 포지션을 정리**하고 모든 거래소의 자산을 현금화
6. 트레이딩 로그를 ./cluade_zone/trading_result.txt에, 현재자본을 조회하여 ./cluade_zone/exchange_guide.txt의 현재자본 column을 업데이트
7. **10분 대기** 후 1번으로 돌아감

- 거래소 목록 정보 조회는 ./exchange_guide.txt
- 거래소 별 order 기능 구현을 위한 가이드 문서 또한 ./exchange_guide.txt
- order 서명을 위한 api 키 조회는 ./.env
- python 사용시 "source /project/arbitrage_bot/.venv/bin/activate" 실행
- python 패키지 추가 시 "source /project/arbitrage_bot/.venv/bin/activate; rye add {package_name}" 실행
- 코드 구현에 80% 자원을, 테스트에 20%의 자원을 할애.
- 작업용 임시 공간으로 ./cluade_zone 폴더 활용, **장기 계획**과 **할 일 목록** 또한 여기에 저장.
- 작업 결과를 **출력하지 말고 ./cluade_zone에 {UTC_current_time}.txt 파일을 만들어 작성**
- 작업에 개시하기 전에 claude_zone 폴더의 내용을 한번 체크 할 것.
