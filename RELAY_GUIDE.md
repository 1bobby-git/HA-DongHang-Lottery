# IP 차단 우회 가이드 (릴레이 서버 설정)

동행복권 서버에서 IP가 차단된 경우, Cloudflare Worker를 릴레이 서버로 배포하여 우회할 수 있습니다.

---

## 차단 확인 방법

다음 증상이 나타나면 IP가 차단된 것입니다:

- HA 로그에 `초기 데이터 로드 타임아웃` 또는 `서버 연결 불가` 메시지
- HA 로그에 `403` 또는 `429` 응답 코드
- 동행복권 사이트에 HA 서버에서 직접 접속이 안 됨
- 통합 설정 시 "설정 실패" 반복

> **참고**: PC나 모바일에서는 정상 접속되지만 HA 서버(NAS, 라즈베리파이 등)에서만 접속이 안 되는 경우, 해당 서버의 IP만 차단된 것입니다.

---

## 릴레이 서버란?

릴레이 서버는 HA와 동행복권 사이트 사이에서 요청을 중계하는 프록시 역할을 합니다.

```
HA 서버 (차단된 IP) → Cloudflare Worker (릴레이) → 동행복권 서버
                    ↑ Cloudflare의 IP로 접속
```

Cloudflare Worker는 Cloudflare의 글로벌 네트워크를 통해 요청을 전달하므로, HA 서버의 IP가 차단되어 있어도 우회할 수 있습니다.

---

## Cloudflare Worker 배포 방법

### Step 1. Cloudflare 계정 생성

1. [Cloudflare 대시보드](https://dash.cloudflare.com/)에 접속
2. 무료 계정 생성 (신용카드 불필요)
3. 이메일 인증 완료

### Step 2. Worker 생성

1. 대시보드 좌측 메뉴에서 **Workers & Pages** 클릭
2. **Create** 버튼 클릭
3. Worker 이름 입력 (예: `dh-relay`)
4. **Deploy** 클릭

### Step 3. 코드 배포

1. 생성된 Worker 페이지에서 **Edit code** 클릭
2. 기존 코드를 모두 삭제
3. 이 저장소의 [`worker/dh-relay-worker.js`](worker/dh-relay-worker.js) 내용을 전체 복사하여 붙여넣기
4. **Deploy** 클릭
5. 생성된 URL 확인 (예: `https://dh-relay.your-id.workers.dev`)

### Step 4. HA 통합 설정

1. 설정 → 기기 및 서비스 → 통합 추가 → **동행복권**
2. 아이디/비밀번호 입력
3. **"IP 차단 우회 (릴레이 서버 사용)"** 체크
4. 다음 화면에서 Worker URL 입력 (예: `https://dh-relay.your-id.workers.dev`)
5. 완료

### 기존 설정에서 릴레이 추가

이미 설치된 통합에 릴레이를 추가하려면:

1. 설정 → 기기 및 서비스 → **동행복권** → **옵션**
2. **"IP 차단 우회 (릴레이 서버 사용)"** 체크
3. 다음 화면에서 Worker URL 입력
4. HA 재시작

---

## Cloudflare Workers 무료 한도

| 항목 | 무료 한도 | 이 통합의 예상 사용량 |
|------|----------|---------------------|
| 일일 요청 수 | **100,000건/일** | **~50~100건/일** |
| CPU 시간 | 10ms/요청 | ~0.8ms/요청 |
| 요청 크기 | 100MB | ~1KB |

### 예상 일일 요청 수

| 동작 | 요청 수 | 빈도 |
|------|---------|------|
| 데이터 갱신 (로그인+조회) | ~7건 | 추첨일 (주 2회) |
| 세션 유지 (Keepalive) | ~1건 | 25~40분마다 |
| **일 평균 총합** | **~50~70건** | 정상 운영 |

> 무료 한도 100,000건의 **0.1% 미만**을 사용하므로, 과금 걱정은 전혀 없습니다.
> 무료 플랜에서는 한도 초과 시 과금 없이 요청이 차단되므로 예기치 않은 과금도 발생하지 않습니다.

### 사용량 확인 방법

1. [Cloudflare 대시보드](https://dash.cloudflare.com/) 접속
2. 좌측 메뉴 → **Workers & Pages**
3. 생성한 Worker 클릭
4. **Metrics** 탭에서 요청 수 확인

---

## URL 매핑 구조

Worker는 요청 경로에 따라 동행복권의 서브도메인으로 자동 라우팅합니다:

| Worker 요청 경로 | 대상 서버 |
|-----------------|----------|
| `https://your-worker.workers.dev/path` | `https://www.dhlottery.co.kr/path` |
| `https://your-worker.workers.dev/ol/path` | `https://ol.dhlottery.co.kr/path` |
| `https://your-worker.workers.dev/el/path` | `https://el.dhlottery.co.kr/path` |

---

## 문제 해결

### 릴레이 설정 후에도 연결 실패

1. Worker URL이 올바른지 확인 (끝에 `/` 없이 입력)
2. Cloudflare 대시보드에서 Worker가 정상 배포되었는지 확인
3. 브라우저에서 `https://your-worker.workers.dev/` 접속 → 동행복권 메인 페이지가 보여야 함
4. HA 재시작 후 재시도

### Worker에서 에러 발생

- Cloudflare 대시보드 → Worker → **Metrics** 탭에서 에러율 확인
- **Logs** 탭에서 실시간 로그 확인 가능

### 릴레이 서버 URL 변경

설정 → 기기 및 서비스 → 동행복권 → 옵션에서 릴레이 URL을 변경할 수 있습니다.

---

## 보안 참고사항

- Worker를 통해 전달되는 데이터에는 로그인 정보가 포함됩니다
- **반드시 본인만 사용하는 Worker를 배포**하세요
- Worker URL을 타인과 공유하지 마세요
- Cloudflare는 HTTPS를 기본 제공하므로 전송 구간은 암호화됩니다
