# HA-DongHang-Lottery

동행복권(로또6/45, 연금복권720+) 정보를 Home Assistant에서 조회/구매할 수 있는 커스텀 통합입니다.

> **주의**: 이 통합은 동행복권 사이트에 자동으로 접속합니다. 사용 빈도에 따라 동행복권 서버로부터 **IP 차단**을 받을 수 있습니다. 차단된 경우 [릴레이 서버 설정 가이드](RELAY_GUIDE.md)를 참조하여 우회할 수 있습니다.

---

## Features

- **계정 정보 조회**
  - 예치금 잔액, 미확인 게임 수, 미수령 당첨금
- **로또6/45 결과 조회**
  - 최신 회차 당첨번호, 보너스 번호, 1등 당첨금/당첨자 수
  - 2등/3등/전체 당첨자 수, 판매금
  - 내 번호 당첨 확인
- **연금복권720+ 결과 조회**
  - 최신 회차 1등 당첨 조/번호, 보너스 조/번호
  - 1등 당첨금/당첨자 수
  - 내 번호 당첨 확인
- **내 주변 당첨 판매점**
  - 위치 엔티티 기반 가장 가까운 당첨 판매점 자동 검색
  - 로또6/45 / 연금복권720+ 각각의 당첨 판매점 표시
  - 판매점명, 주소, 전화번호, 거리, 당첨종류/방식, 판매 복권 종류
  - 온라인 판매점 자동 제외 (물리 매장만 표시)
- **복권 구매** (주의: 실제 결제)
  - 로또6/45 자동/수동 구매
  - 연금복권720+ 자동 구매
- **서비스 호출**
  - 당첨 판매점 조회, 복권 판매점 검색
  - 구매 내역 조회, 다음 회차 정보 조회
- **나만의 번호 저장/관리**
- **자동 업데이트**
  - 로또6/45: 매주 토요일 21:10
  - 연금복권720+: 매주 목요일 19:30
  - 결과 미반영 시 10분 간격 자동 재시도
- **Anti-Bot Evasion**
  - User-Agent 로테이션 (25개), Poisson 분포 딜레이, 서킷 브레이커
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
3. (선택) 위치 엔티티 설정 - 내 주변 당첨 판매점 기능에 사용됩니다
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
| `location_entity` | 위치 엔티티 (내 주변 판매점 거리 계산용) | (선택) |
| `use_relay` | IP 차단 우회 (릴레이 서버 사용) | False |
| `relay_url` | 릴레이 서버 URL | (선택) |

> 당첨결과 자동 업데이트: 로또6/45는 매주 토요일 21:10, 연금복권720+는 매주 목요일 19:30에 자동 확인됩니다. 결과가 아직 반영되지 않은 경우 10분 간격으로 재시도합니다.

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

### 내 주변 판매점 센서가 표시되지 않을 때
- 설정에서 위치 엔티티가 올바르게 지정되어 있는지 확인
- 위치 엔티티에 latitude/longitude 속성이 있는지 확인
- 당첨 판매점 API 응답에 물리 매장이 없는 경우 (모두 온라인 판매점) 센서가 비어있을 수 있습니다

---

## Dependencies

- `beautifulsoup4>=4.13.0` - HTML 파싱
- `html5lib>=1.1` - HTML5 파서
- `pycryptodome>=3.20.0` - RSA/AES 암호화

---

## License

MIT License
