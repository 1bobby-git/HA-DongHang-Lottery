# HA-DongHang-Lottery

동행복권(로또6/45, 연금복권720+) 정보를 Home Assistant에서 조회/구매할 수 있는 커스텀 통합입니다.

> ⚠️ **주의**: 이 통합은 동행복권 사이트에 자동으로 접속합니다. 사용 빈도에 따라 동행복권 서버로부터 **IP 차단**을 받을 수 있습니다. 차단된 경우 [릴레이 서버 설정 가이드](RELAY_GUIDE.md)를 참조하여 우회할 수 있습니다.

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
- **Anti-Bot Evasion**
  - User-Agent 로테이션, Poisson 분포 딜레이, 서킷 브레이커
- **릴레이 서버 우회** (IP 차단 시)
  - Cloudflare Worker를 통한 릴레이 연결 지원

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
2. 동행복권 계정 정보 입력 (아이디/비밀번호)
3. (선택) 위치 엔티티, 업데이트 시간 설정
4. **IP 차단 우회가 필요한 경우**: "IP 차단 우회 (릴레이 서버 사용)" 체크
5. 체크한 경우 다음 화면에서 릴레이 서버 URL 입력
6. 완료

### 일반 사용자 (차단되지 않은 경우)
아이디/비밀번호만 입력하면 바로 설정이 완료됩니다.

### 차단된 사용자 (릴레이 서버 사용)
1. Cloudflare Worker 배포 (아래 "릴레이 서버 설정" 참조)
2. 설정 시 "IP 차단 우회" 체크
3. 다음 화면에서 릴레이 URL 입력

---

## IP 차단 우회

동행복권 서버에서 IP가 차단된 경우, Cloudflare Worker를 릴레이로 배포하여 우회할 수 있습니다.

**[IP 차단 우회 상세 가이드 →](RELAY_GUIDE.md)**

설정 시 "IP 차단 우회 (릴레이 서버 사용)" 체크박스를 선택하면 릴레이 URL을 입력할 수 있습니다.

---

## Options

설정 → 기기 및 서비스 → 동행복권 → 옵션에서 변경 가능:

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `username` | 동행복권 아이디 | (필수) |
| `password` | 동행복권 비밀번호 | (필수) |
| `location_entity` | 위치 엔티티 (판매점 거리 계산용) | (선택) |
| `lotto_update_hour` | 로또 발표 확인 시간 (시, 0~23) | 0 |
| `pension_update_hour` | 연금복권 발표 확인 시간 (시, 0~23) | 0 |
| `use_relay` | IP 차단 우회 (릴레이 서버 사용) | False |
| `relay_url` | 릴레이 서버 URL | (선택) |

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

### IP 차단 시
- 상세한 우회 방법은 [IP 차단 우회 가이드](RELAY_GUIDE.md)를 참조하세요
- 설정에서 "IP 차단 우회" 옵션을 활성화하고 릴레이 URL을 입력하세요

### 403/429 에러 발생 시
- 서킷 브레이커가 자동으로 작동하여 60~300초간 요청을 중단합니다
- 자동으로 복구되며, 로그에서 상태를 확인할 수 있습니다

### 로그인 실패 시
- 동행복권 사이트에서 직접 로그인하여 계정 상태 확인
- 비밀번호 변경 후 통합 재설정
- 동행복권 사이트 점검 시간 확인 (매주 일요일 새벽)

---

## Dependencies

- `beautifulsoup4>=4.13.0` - HTML 파싱
- `html5lib>=1.1` - HTML5 파서
- `pycryptodome>=3.20.0` - RSA/AES 암호화

---

## License

MIT License
