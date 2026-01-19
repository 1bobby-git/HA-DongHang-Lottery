# HA-DongHang-Lottery

⚠️ 제작중입니다. 설치하지 마세요! ⚠️

동행복권(로또6/45, 연금복권720+) 정보를 Home Assistant에서 조회/구매할 수 있는 커스텀 통합입니다.

## 주요 기능
- 동행복권 계정 정보 조회 (예치금, 구매가능/구매불가, 미확인 게임수 등)
- 로또6/45 당첨 결과 조회 및 번호 확인
- 연금복권720+ 당첨 결과 조회 및 번호 확인
- 나만의 번호 저장/조회
- 주변 당첨 판매점 조회 (내 위치 엔티티 기준)
- 구매 서비스 호출 (로또/연금)

## 설치 (HACS)
1. HACS > Integrations > Custom repositories
2. Repository: `https://github.com/1bobby-git/HA-DongHang-Lottery`
3. Category: Integration
4. 통합 설치 후 Home Assistant 재시작

## Setup (Authentication)
Home Assistant UI > 설정 > 통합 > `동행복권` 추가:
- 아이디/비밀번호: `https://www.dhlottery.co.kr` 계정
- 내 위치 엔티티(선택): 주변 판매점 추천 기준 위치

재설정은 통합 옵션에서 동일 항목을 변경합니다.

## 엔티티
- 계정(동행복권): 예치금/구매가능/구매불가/미확인 게임수 등
- 로또6/45: 회차, 당첨번호, 1등 당첨금/당첨자 수 등
- 연금복권720+: 회차, 당첨번호, 1등 당첨금/당첨자 수 등
- 버튼: 수동 새로고침

## 서비스 예시
```yaml
service: donghang_lottery.buy_lotto645
data:
  mode: manual
  numbers:
    - [1, 2, 3, 4, 5, 6]
```

```yaml
service: donghang_lottery.fetch_winning_shops
data:
  lottery_type: lt645
  rank: "1"
  draw_no: "1206"
  location_entity: person.home
  max_distance_km: 10
  limit: 20
```

## 참고
- 동행복권 사이트 점검 시 로그인/조회가 실패할 수 있습니다.
- 구매 서비스는 실제 결제를 동반할 수 있으니 주의하세요.
