# HA-DongHang-Lottery

동행복권(로또6/45, 연금복권720+) 정보를 Home Assistant에서 조회/구매할 수 있는 커스텀 통합입니다.

> v0.4.1부터 **자동 프록시 IP 우회 기능**이 포함되어 이미 차단된 IP에서도 사용이 가능합니다.

---

## Features

- **계정 정보 조회**
  - 예치금 잔액, 미확인 게임 수, 미수령 당첨금
- **로또6/45 결과 조회**
  - 최신 회차 당첨번호, 1등 당첨금/당첨자 수
  - 내 번호 당첨 확인
- **연금복권720+ 결과 조회**
  - 최신 회차 당첨번호, 등위별 당첨금
  - 내 번호 당첨 확인
- **복권 구매** (주의: 실제 결제)
  - 로또6/45 자동/수동 구매
  - 연금복권720+ 자동 구매
- **주변 당첨 판매점 조회**
  - 위치 엔티티 기반 거리 필터링
- **나만의 번호 저장/관리**

---

## IP 차단 우회 - 자동 프록시 (v0.4.1+)

**이미 IP가 차단된 경우에도 이 컴포넌트를 설치하는 것만으로 우회가 가능합니다.**

| 기능 | 설명 |
|------|------|
| **무료 프록시 자동 수집** | 6개 이상의 프록시 소스에서 자동 수집 |
| **프록시 유효성 검증** | 동행복권 서버에 대해 프록시 검증 후 사용 |
| **성공률 기반 로테이션** | 성공률이 높은 프록시 우선 사용 |
| **자동 프록시 교체** | 403/429 에러 시 자동으로 다른 프록시로 전환 |
| **프록시 갱신** | 30분마다 프록시 목록 자동 갱신 |
| **직접 연결 폴백** | 프록시 실패 시 직접 연결로 자동 전환 |

### 프록시 설정

설정 → 기기 및 서비스 → 동행복권 → 옵션에서:
- **프록시 사용**: 기본 활성화 (이미 차단된 IP라면 반드시 ON)

---

## Anti-Bot Evasion (v0.4.0+)

동행복권 서버의 봇 탐지를 우회하기 위한 기능:

| 기능 | 설명 |
|------|------|
| **25개 User-Agent 풀** | Chrome, Firefox, Safari, Edge 등 다양한 브라우저/OS 조합 |
| **Chrome Client Hints** | `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform` 헤더 지원 |
| **Poisson 분포 딜레이** | 인간적인 요청 패턴 시뮬레이션 (4~10초 + 지수 분포 지터) |
| **프로액티브 UA 로테이션** | 5~15 요청마다 자동 User-Agent 변경 |
| **세마포어** | 동시 요청 1개로 제한 (버스트 방지) |
| **서킷 브레이커** | 연속 3회 실패 시 자동 중단, 60~300초 쿨다운 |
| **강화된 지수 백오프** | 403/429 시 15~180초 대기 |
| **세션 자동 갱신** | 1시간 또는 100 요청마다 새 세션 |
| **RSA 키 캐시** | 불필요한 키 요청 방지 (5분 캐시) |
| **랜덤 Keepalive** | 25~40분 간격으로 예측 불가능한 세션 유지 |

---

## Install (HACS)

[![Open your Home Assistant instance and show the HACS repository.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=1bobby-git&repository=HA-DongHang-Lottery&category=integration)

1. HACS → Integrations → 우측 상단 ⋮ → Custom repositories
2. Repository: `https://github.com/1bobby-git/HA-DongHang-Lottery`
3. Category: Integration
4. 설치 후 Home Assistant 재시작

---

## Setup

[![Open your Home Assistant instance and start setting up the integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=donghang_lottery)

1. 설정 → 기기 및 서비스 → 통합 추가 → **동행복권**
2. 동행복권 계정 정보 입력 (https://www.dhlottery.co.kr)
3. (선택) 내 위치 엔티티 선택 (주변 판매점 조회용)
4. 완료

---

## Options

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `username` | 동행복권 아이디 | (필수) |
| `password` | 동행복권 비밀번호 | (필수) |
| `location_entity` | 위치 엔티티 (판매점 거리 계산용) | (선택) |
| `min_request_interval` | 최소 요청 간격 (초) | 4.0 |
| `max_request_interval` | 최대 요청 간격 (초) | 10.0 |
| `use_proxy` | 프록시 사용 (IP 차단 우회) | True |

---

## Entities

### 계정 (Account)
| 센서 | 설명 |
|------|------|
| `sensor.donghang_lottery_total_amount` | 총 예치금 |
| `sensor.donghang_lottery_unconfirmed_count` | 미확인 게임 수 |
| `sensor.donghang_lottery_unclaimed_high_value_count` | 미수령 고액 당첨금 |

### 로또6/45 (Lotto645)
| 센서 | 설명 |
|------|------|
| `sensor.donghang_lottery_lotto645_round` | 회차 |
| `sensor.donghang_lottery_lotto645_numbers` | 당첨번호 |
| `sensor.donghang_lottery_lotto645_bonus` | 보너스 번호 |
| `sensor.donghang_lottery_lotto645_first_prize` | 1등 당첨금 |
| `sensor.donghang_lottery_lotto645_first_winners` | 1등 당첨자 수 |

### 연금복권720+ (Pension720)
| 센서 | 설명 |
|------|------|
| `sensor.donghang_lottery_pension720_round` | 회차 |
| `sensor.donghang_lottery_pension720_draw_date` | 추첨일 |

### 버튼
| 버튼 | 설명 |
|------|------|
| `button.donghang_lottery_refresh` | 수동 새로고침 |

---

## Services

### `donghang_lottery.buy_lotto645`
로또6/45 구매

```yaml
service: donghang_lottery.buy_lotto645
data:
  mode: auto  # auto 또는 manual
  count: 5    # 1~5 게임
```

```yaml
service: donghang_lottery.buy_lotto645
data:
  mode: manual
  numbers:
    - [1, 2, 3, 4, 5, 6]
    - [7, 8, 9, 10, 11, 12]
```

### `donghang_lottery.buy_pension720`
연금복권720+ 자동 구매

```yaml
service: donghang_lottery.buy_pension720
```

### `donghang_lottery.fetch_lotto645_result`
로또6/45 결과 조회

```yaml
service: donghang_lottery.fetch_lotto645_result
data:
  draw_no: 1150  # 선택: 특정 회차 (미지정 시 최신)
```

### `donghang_lottery.fetch_winning_shops`
당첨 판매점 조회

```yaml
service: donghang_lottery.fetch_winning_shops
data:
  lottery_type: lt645  # lt645, pt720
  rank: "1"
  draw_no: "1150"
  location_entity: person.home
  max_distance_km: 10
  limit: 20
```

### `donghang_lottery.check_lotto645_numbers`
로또 번호 당첨 확인

```yaml
service: donghang_lottery.check_lotto645_numbers
data:
  draw_no: 1150
  numbers:
    - [1, 2, 3, 4, 5, 6]
```

### `donghang_lottery.set_my_numbers` / `get_my_numbers`
나만의 번호 저장/조회

```yaml
service: donghang_lottery.set_my_numbers
data:
  lottery_type: lt645
  numbers:
    - [1, 2, 3, 4, 5, 6]
    - [7, 8, 9, 10, 11, 12]
```

---

## Debug (Logs)

`configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.donghang_lottery: debug
```

---

## Troubleshooting

### 403/429 에러 발생 시
- 서킷 브레이커가 자동으로 작동하여 60~300초간 요청을 중단합니다
- 로그에서 `[DHLottery] 서킷 브레이커 OPEN` 메시지를 확인하세요
- 자동으로 복구되며, 복구 후 `CLOSED 상태로 복구` 메시지가 출력됩니다

### 로그인 실패 시
- 동행복권 사이트에서 직접 로그인하여 계정 상태 확인
- 비밀번호 변경 후 통합 재설정
- 동행복권 사이트 점검 시간 확인 (매주 일요일 새벽)

### 차단된 경우
- **v0.4.1+**: 프록시 사용 옵션을 켜면 자동으로 IP 차단을 우회합니다
- 설정 → 기기 및 서비스 → 동행복권 → 옵션 → "프록시 사용" 활성화
- 로그에서 `[DHLottery] 프록시 사용:` 또는 `[ProxyMgr]` 메시지로 프록시 동작 확인
- 프록시 초기화에 실패하면 직접 연결로 자동 전환됩니다

---

## Dependencies

- `beautifulsoup4==4.12.3` - HTML 파싱
- `html5lib==1.1` - HTML5 파서
- `pycryptodome==3.20.0` - RSA/AES 암호화

---

## License

MIT License
