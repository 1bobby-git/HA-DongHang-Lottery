# HA-DongHang-Lottery

⚠️ 제작중입니다. 설치하지 마세요! ⚠️

동행복권(로또6/45, 연금복권720+)을 Home Assistant에서 조회/구매하는 커스텀 통합입니다.

## 주요 기능
- 아이디/비밀번호 로그인(RSA)
- 계정 요약 센서(잔액, 미확인 게임수, 고액 미수령 당첨)
- 로또6/45 결과 조회 및 상세 센서
- 연금복권720+ 결과 조회 및 상세 센서
- 당첨 판매점 조회(내 위치 엔티티 기준 거리 필터링)
- 구매 서비스(로또6/45 자동/수동, 연금복권720+ 자동)
- 로컬 “나만의 번호” 저장/조회
- 30분 간격 keepalive 유지

## 설치 (HACS)
1. HACS > Integrations > Custom repositories
2. Repository: `https://github.com/1bobby-git/HA-DongHang-Lottery`
3. Category: Integration
4. 설치 후 Home Assistant 재시작

## 설정
Home Assistant UI에서 통합 추가 후 아래 항목을 입력합니다.
- 아이디
- 비밀번호
- 내 위치 엔티티(선택): 주변 추천 기준 위치

## 센서/기기 구조
- 동행복권(아이디): 계정 요약 센서 + 업데이트 버튼
- 로또6/45: 로또 관련 센서
- 연금복권720+: 연금복권 관련 센서

## 서비스 예시
개발자도구 > 서비스에서 실행합니다.

```yaml
service: donghang_lottery.buy_lotto645
data:
  mode: manual
  numbers:
    - [1, 2, 3, 4, 5, 6]
```

```yaml
service: donghang_lottery.buy_pension720
data: {}
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

```yaml
service: donghang_lottery.set_my_numbers
data:
  lottery_type: lt645
  numbers:
    - [8, 12, 19, 28, 33, 41]
```

```yaml
service: donghang_lottery.check_lotto645_numbers
data:
  use_my_numbers: true
```

## 주의사항
- “나만의 번호”는 Home Assistant 로컬 스토리지에 저장됩니다.
- 동행복권 사이트 변경 시 동작이 중단될 수 있습니다.
- 자동 폴링 없이 서비스 호출/업데이트 버튼으로 갱신합니다.
