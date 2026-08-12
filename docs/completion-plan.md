# Reminiscence 개발 완성 계획

- 작성일: 2026-08-13
- 대상 저장소: `Reminiscence-BE`, `Reminiscence-FE`
- 기준 문서: `Reminiscence 프로젝트 확정 기획안 v1.4`
- 목표 서비스: `https://reminiscence.leehyowon14.dev`
- 배포 대상: `rpi5-server`
- 제품 전제: 서버 1대당 태블릿 1대인 교육용 단일 사용자 시스템

## 1. 완성 목표

두 저장소의 기능을 하나의 제품 흐름으로 통합하고, 확정 기획안 v1.4에 맞는 이상 탐지와 JSON 기반 영속성, 보호자 인증, 실환경 배포 및 검증을 완료한다.

완료 후 제품 등급은 다음과 같이 정의한다.

> 인터넷에서 접근 가능한 단일 서버·단일 태블릿용 교육용 appliance beta

다중 사용자, 다중 태블릿, 다중 보호자, 다중 API worker 및 데이터베이스 도입은 이번 범위에서 제외한다.

## 2. 확정 요구사항

- 이상 탐지는 확정 기획안 v1.4를 구현 기준으로 사용한다.
- 외부 서비스 주소는 `https://reminiscence.leehyowon14.dev` 하나로 통합한다.
- FE와 API는 same-origin으로 제공한다.
- 모든 애플리케이션 설정과 영속 데이터는 JSON으로 읽고 쓴다.
- DB, Redis, pickle 및 joblib 영속화를 사용하지 않는다.
- 보호자 비밀번호는 서버의 JSON 파일에 평문으로 저장한다.
- 비밀번호, API key와 SMTP 정보가 담긴 실제 JSON은 저장소와 container image에 포함하지 않는다.
- 사용자 WAV, 전사문과 TTS 결과는 메모리에서만 처리하고 파일로 보존하지 않는다.
- SMTP 실발송은 설정을 전달받은 뒤 최종 검증한다.
- `/care/*` 데모는 실제 제품 흐름과 분리해 보존한다.

JSON-only 조건은 영속 데이터와 런타임 설정에 적용한다. 오디오 요청과 응답은 불필요한 base64 오버헤드를 피하기 위해 기존 binary 전송을 유지하되 영속화하지 않는다.

## 3. 목표 시스템 구조

```text
Tablet / Guardian browser
        │ HTTPS
Cloudflare Tunnel
        │ HTTP, host-local
rpi5 host Nginx
        ├─ /api/* ──> FastAPI container
        └─ /*      ──> React static web container
                            │
FastAPI ──> versioned JSON configuration and state
```

### URL 구조

- `/`: 실제 가족사진 태블릿 홈
- `/tablet`: `/`로 이동하는 호환 경로
- `/conversation`: 실제 회상 대화
- `/dashboard/login`: 보호자 로그인
- `/dashboard`: 인증된 보호자 대시보드
- `/api/v1/*`: FastAPI
- `/api/health/live`: process 생존 확인
- `/api/health/ready`: 로컬 의존성 준비 상태 확인
- `/demo/*`: 운영 제품과 분리된 데모

### 런타임 제약

- Uvicorn worker와 API replica를 각각 1개로 고정한다.
- 동일 JSON data directory를 사용하는 두 번째 API process는 instance lock으로 차단한다.
- API와 web container port는 loopback에만 공개한다.
- 외부 요청은 host Nginx와 Cloudflare Tunnel을 통해서만 받는다.
- production CORS 의존을 제거하고 same-origin cookie를 사용한다.

## 4. JSON 저장 구조

```text
data/
  configuration.json
  activity_metrics.json
  anomaly_baseline.json
  personal_state.json
  notification_state.json
  auth_sessions.json
  auth_attempts.json
  .instance.lock
  .snapshot.lock

secrets/
  application-secrets.json
```

`application-secrets.json`은 다음 항목을 관리한다.

- 평문 보호자 비밀번호
- 태블릿 최초 pairing code
- codex-lb API key
- SMTP 정보

### 저장 안전성

- 모든 JSON root에 `schema_version`을 둔다.
- startup에서 각 파일을 strict validation한다.
- write는 같은 directory의 임시 파일 작성, file `fsync`, `os.replace`, directory `fsync` 순서로 수행한다.
- process 간 write에는 `fcntl.flock`을 적용한다.
- snapshot 중에는 전체 데이터에 exclusive lock을 사용한다.
- 손상된 JSON을 빈 기본값으로 덮어쓰지 않고 readiness를 `503`으로 만든다.
- schema migration은 애플리케이션 기동 중 자동 수행하지 않고 명시적 CLI로 수행한다.
- 실제 secret 파일은 mode `0600`, data directory는 `0750`을 사용한다.
- web container에는 data 및 secret volume을 mount하지 않는다.

### Backup과 복구

- 배포 직전에 predeploy snapshot을 생성한다.
- 매일 한 번 모든 domain JSON의 일관된 snapshot을 만든다.
- staging directory에서 SHA-256 manifest를 만든 뒤 완성본을 atomic rename한다.
- 권장 보존 기간은 daily 7개, weekly 4개, monthly 6개다.
- secret과 auth session은 일반 snapshot에서 제외한다.
- 월 1회 임시 directory에 복구한 뒤 preflight를 실행한다.

## 5. 기획안 기준 이상 탐지

현재의 반복 polling 기반 확정 방식을 제거한다. 날짜 또는 세션처럼 새로운 관측 단위가 생성될 때만 후보와 지속성 상태를 변경한다.

Isolation Forest 모델 객체 자체는 저장하지 않는다. 고정 기준 벡터와 모델 설정을 JSON으로 저장하고 `random_state=42`로 모델을 재구성한다.

### 5.1 루틴 관측

하루의 모든 예정 루틴이 종료된 뒤 다음 6개 특징으로 불변 일별 관측값을 만든다.

1. 식사 미응답률
2. 복약 미응답률
3. 식사 평균 확인 지연
4. 복약 평균 확인 지연
5. 전체 완료율
6. 동일 루틴 최대 연속 미응답

판정 정책은 다음과 같다.

- 초기 28개의 완성된 관측일을 고정 기준선으로 저장한다.
- 초기 구간에는 동일 루틴 3회 연속 `NOT_ANSWERED` 규칙을 사용한다.
- 중간에 `CONFIRMED`가 발생하면 해당 연속 횟수를 초기화한다.
- 29번째 완성된 관측일부터 Isolation Forest를 적용한다.
- 낮 시간의 불완전한 하루를 과거의 완성된 하루와 비교하지 않는다.
- 동일 날짜와 동일 관측값의 재평가로 지속성 횟수를 증가시키지 않는다.

### 5.2 대화 품질 관측

완료된 세션마다 다음 특징을 계산한다.

1. 사용자 턴 수
2. 총 글자 수
3. 평균 글자 수
4. 평균 턴 입력 시간
5. 무응답 횟수

판정 정책은 다음과 같다.

- 최초 완료 세션 20개를 고정 기준으로 저장한다.
- 21번째 완료 세션부터 Isolation Forest를 적용한다.
- 최근 3개 세션 중 2개 이상이 비정상이면 지속성 신호를 활성화한다.
- 새로운 세션이 완료될 때만 품질 상태를 갱신한다.

### 5.3 대화 참여량

- 초기 28일을 네 개의 7일 구간으로 나누어 사용자 턴 수 평균을 기준으로 저장한다.
- 현재 날짜를 기준으로 최근 7일 사용자 턴 수를 계산한다.
- 대화가 전혀 없는 날짜도 0으로 관측한다.
- 기준보다 50% 이상이면서 10턴 이상 감소해야 감소 규칙을 충족한다.
- 감소 상태가 2개의 연속 관측일 동안 유지되어야 지속성 신호를 충족한다.

### 5.4 최종 판정

각 영역은 다음 세 신호를 별도로 계산하고 JSON에 근거와 함께 저장한다.

1. 규칙 기반 신호
2. Isolation Forest 신호
3. 지속성 신호

세 신호 중 2개 이상이 충족되면 해당 영역을 `ANOMALOUS`로 확정한다. 루틴 또는 대화 중 한 영역만 확정되어도 개인 상태를 `ANOMALOUS`로 전환한다.

필수 경계 테스트에는 다음을 포함한다.

- 28일과 29일 경계
- 20세션과 21세션 경계
- 정확히 50% 및 10턴 감소
- 최근 3세션 중 정확히 2세션 이상
- `CONFIRMED`에 의한 연속 미응답 초기화
- 대화가 전혀 없는 최근 7일
- 같은 관측값의 반복 평가
- 불완전한 현재 날짜 제외
- timezone 경계와 날짜 역행 입력 거부

## 6. 인증과 권한

### 보호자 인증

요구사항대로 보호자 비밀번호를 JSON에 평문 저장하되 다음 제한을 적용한다.

- API 응답, 애플리케이션 로그와 backup manifest에 비밀번호를 노출하지 않는다.
- `hmac.compare_digest`로 비교한다.
- 최소 길이와 빈 문자열을 검증한다.
- 로그인 실패 횟수와 잠금 시각을 `auth_attempts.json`에 기록한다.
- 로그인 성공 시 `HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/` cookie를 발급한다.
- session token 원문은 cookie에만 두고 SHA-256 값만 `auth_sessions.json`에 저장한다.
- session 만료, 로그아웃과 보호자 비밀번호 변경 시 session revoke를 검증한다.

평문 비밀번호는 host 또는 파일 유출 시 즉시 노출되는 위험을 수용한 설계다. 실제 파일은 저장소와 image에 포함하지 않고 API 전용 read-only volume으로 제공한다.

### 단일 태블릿 인증

- 최초 한 번 pairing code를 입력해 tablet session을 발급한다.
- 한 서버에는 유효한 tablet session을 하나만 유지한다.
- 새 pairing이 성공하면 이전 tablet session을 revoke한다.
- tablet cookie도 server-side JSON session과 strict cookie로 관리한다.

### 역할별 API

| 역할 | 접근 범위 |
| --- | --- |
| Public | live/ready, 보호자 로그인, 태블릿 pairing |
| Tablet | 통합 홈, 루틴 조회·확인, 회상 대화, TTS |
| Guardian | 루틴·대화 이력, 대시보드, 이상 상태 |
| Internal | 이상 평가, 이메일 평가 |

상태 변경 요청에는 cookie 외에도 `Origin == https://reminiscence.leehyowon14.dev` 검증을 적용한다. 로그인, pairing, ASR과 TTS에는 Nginx 및 애플리케이션 rate limit을 적용한다.

## 7. 백엔드 완성 작업

- `GET /api/v1/tablet/state`로 루틴, 대화 권유와 가족사진 상태를 통합한다.
- 대화 완료 API가 이미 완료된 세션에 기존 summary를 반환하도록 멱등화한다.
- turn에 client-generated ID를 받아 중복 지표 저장을 차단한다.
- 태블릿 하나당 active conversation session 하나만 허용한다.
- FE recorder의 `hasSpeech`와 종료 이유를 BE까지 전달해 무응답 판정에 반영한다.
- 이메일 상태를 `PENDING`, `SENT`, `FAILED`로 구분하고 실패 재시도를 지원한다.
- notification과 anomaly 수동 평가 endpoint는 internal-only로 제한한다.
- `/api/health/live`와 `/api/health/ready`를 분리한다.
- readiness에서 JSON parse, atomic write 가능 여부, model assets, TTS 초기화, background task와 instance lock을 확인한다.
- OpenAPI JSON snapshot을 생성하고 CI에서 코드와의 차이를 검사한다.

## 8. 프런트엔드 완성 작업

태블릿 홈은 다음 우선순위로 화면을 결정한다.

1. 활성 루틴
2. 정시 대화 권유
3. 가족사진과 자발적 대화 버튼
4. 통신 장애 또는 stale 안내

추가 작업은 다음과 같다.

- 루틴과 대화 완료 후 가족사진 홈으로 복귀한다.
- polling 실패 시 오래된 루틴을 정상 화면처럼 계속 표시하지 않는다.
- API timeout, content type과 runtime 응답 형식을 검증한다.
- 업로드 중 대화 종료가 complete를 중복 호출하지 않도록 수정한다.
- 보호자 로그인과 session guard를 추가한다.
- 대시보드는 Asia/Seoul 기준 월별 이력을 조회한다.
- 내부 routine ID 대신 사용자용 이름을 표시한다.
- 이상 영역, 관찰 근거와 평가 시각을 표시한다.
- production route와 demo route를 분리한다.
- production bundle에서 개인정보 가족사진을 제거한다.
- OpenAPI 생성 타입을 사용해 FE와 BE 계약을 일치시킨다.

## 9. 테스트와 완료 조건

### 백엔드 품질 게이트

```text
pytest 통과
Ruff clean
mypy clean
OpenAPI contract clean
실제 Supertonic model smoke 통과
```

### 프런트엔드 품질 게이트

```text
pnpm test 통과
ESLint clean
TypeScript typecheck clean
production build 성공
Playwright E2E 통과
```

### 핵심 브라우저 E2E

- 사진 홈 → 루틴 확인 → 사진 홈
- 사진 홈 → 정시 대화 → 사진 홈
- 사진 홈 → 자발적 대화 → 사진 홈
- 대화 upload 중 종료 시 complete 요청 1회 보장
- offline, stale 상태와 reconnect
- 보호자 비밀번호 오입력, 로그인, 새로고침, 로그아웃과 session 만료
- `/dashboard` 직접 진입과 SPA fallback
- 태블릿 viewport와 fake microphone media

### 통합 인수 조건

- FE와 BE OpenAPI 계약 차이 0
- 재시작 후 모든 JSON 상태 유지
- 동시 write에서 JSON 손상 없음
- 손상된 JSON에서 fail-closed 및 readiness `503`
- backup checksum과 임시 directory 복구 검증 통과
- public API port 직접 노출 없음
- 인증되지 않은 이력과 이상 상태 접근 차단
- 실제 HTTPS에서 same-origin 동작
- Cloudflare 경유 마이크, 대화, 루틴과 대시보드 smoke 통과
- SMTP 설정 전달 후 실발송 검증 통과

## 10. CI/CD와 rpi5 배포

구현 시작 시 `rpi5-server`에서 다음을 읽기 전용으로 조사하고 사용 중이거나 중지된 container와 겹치지 않는 port를 선택한다.

- `docker ps -a`
- 모든 Docker Compose project
- `docker inspect`
- `ss -ltnp`
- host Nginx 설정
- Cloudflare Tunnel ingress

### CI/CD 원칙

- FE와 BE는 GitHub-hosted runner에서 검증하고 ARM64 image를 build한다.
- 검증된 image는 GHCR에 digest로 게시한다.
- rpi5 runner에서는 `docker build`, `pnpm`과 `uv sync`를 실행하지 않는다.
- rpi5에서는 image pull, backup, 명시적 migration, Docker Compose와 smoke만 수행한다.
- production concurrency는 하나로 제한한다.
- PR 및 fork job은 self-hosted runner에서 실행하지 않는다.
- FE와 BE digest를 하나의 release manifest로 관리한다.

### Nginx와 Cloudflare

- `server_name reminiscence.leehyowon14.dev`
- `/api/`는 API loopback port로 URI를 보존해 proxy한다.
- 나머지 경로는 FE container로 전달하고 SPA fallback을 지원한다.
- `/api/*`는 `no-store`, hash asset은 1년 immutable cache를 적용한다.
- `index.html`은 no-cache로 제공한다.
- turn upload route만 10 MiB를 허용하고 나머지는 1 MiB로 제한한다.
- CSP, `X-Content-Type-Options`, `Referrer-Policy`와 microphone `Permissions-Policy`를 적용한다.
- Cloudflare는 `/api/*` cache를 우회하고 HTTPS를 강제한다.
- domain 전체 Cloudflare Access는 무인 태블릿을 차단하므로 적용하지 않는다.

### 배포와 rollback

1. FE와 BE candidate image pull
2. image digest와 manifest 검증
3. web `nginx -t`, API preflight와 TTS smoke
4. maintenance 진입
5. API 중지
6. JSON predeploy snapshot
7. 필요한 경우 명시적 migration
8. candidate API와 web 기동
9. readiness 대기
10. host loopback smoke
11. public URL smoke
12. current release 전환 및 previous release 보존

실패하면 candidate를 중지하고 FE와 BE를 함께 previous digest로 되돌린다. schema migration이 수행됐다면 predeploy snapshot을 복구한 뒤 previous readiness를 확인한다. 사용자 traffic을 받은 뒤에는 신규 기록 유실 위험 때문에 data snapshot을 자동 복구하지 않고 수동 판단한다.

## 11. 원자 커밋 계획

각 커밋에는 해당 변경을 검증하는 테스트를 함께 포함한다. 기능, 설정, 인프라와 문서를 한 커밋에 섞지 않는다.

### BE

1. `docs(spec): 확정 기획안 구현 기준 명문화`
2. `feat(storage): JSON schema version과 원자 저장 추가`
3. `feat(storage): JSON migration과 snapshot 추가`
4. `feat(anomaly): 루틴 28일 고정 기준선 적용`
5. `feat(anomaly): 대화 품질 기준선과 지속성 적용`
6. `feat(anomaly): 대화 참여량 감소 판정 적용`
7. `feat(anomaly): 세 신호 합의 판정 적용`
8. `feat(auth): 보호자 JSON session 인증 추가`
9. `feat(auth): 단일 Tablet pairing 인증 추가`
10. `fix(api): same-origin 요청 검증 추가`
11. `feat(routine): role 기반 접근 제어 적용`
12. `feat(conversation): role 기반 접근 제어 적용`
13. `feat(tts): Tablet 접근 제어 적용`
14. `feat(anomaly): Guardian 접근 제어 적용`
15. `fix(notification): 평가 API를 internal 전용으로 제한`
16. `fix(conversation): session과 turn 멱등성 보장`
17. `feat(tablet): 통합 홈 상태 API 추가`
18. `fix(notification): 알림 전달 상태와 재시도 추가`
19. `feat(health): liveness와 readiness 분리`
20. `chore(api): OpenAPI 계약 검증 추가`
21. `build(api): non-root runtime과 preflight 강화`
22. `chore(deploy): FE와 API Compose release 통합`
23. `chore(ingress): same-origin Nginx routing 적용`
24. `ci(deploy): rpi5 release 배포와 rollback 추가`
25. `docs(operations): 배포·backup·복구 절차 추가`

### FE

1. `chore(test): React 컴포넌트 테스트 기반 추가`
2. `refactor(api): OpenAPI 생성 계약 적용`
3. `fix(api): timeout과 응답 검증 적용`
4. `fix(conversation): 대화 종료 경쟁 조건 제거`
5. `fix(routine): stale polling 상태 처리`
6. `feat(auth): 보호자 로그인과 session guard 추가`
7. `feat(auth): Tablet pairing 흐름 추가`
8. `feat(home): 사진·루틴·대화 통합 홈 추가`
9. `fix(conversation): 완료 후 사진 홈 복귀 적용`
10. `feat(dashboard): 월별 기록과 이상 근거 표시`
11. `refactor(demo): production과 demo route 분리`
12. `fix(privacy): production 가족사진 asset 제거`
13. `test(e2e): Tablet·Guardian 핵심 흐름 추가`
14. `build(web): ARM64 정적 웹 image 추가`
15. `ci(web): 검증과 GHCR 게시 workflow 추가`
16. `docs(web): 실행과 배포 절차 문서화`

## 12. 일정 및 Git 이력 원칙

보고서에는 다음 기간을 구분해 기록한다.

- 프로젝트 수행 기간: 2026-06-24~2026-07-28
- 위 기간의 활동: 기존 문서와 실제 Git 기록으로 확인 가능한 내용만 기술
- 후속 완성 작업: 2026-08-13 이후

새 커밋은 실제 작업자와 실제 작성 시각으로 남긴다. 과거부터 여러 사람이 작업한 것처럼 저자, 시각 또는 기여 기록을 조작하지 않는다. 여러 사람이 실제로 참여하는 경우 각자의 실제 기여 단위로 커밋한다.

## 13. 남은 외부 입력

개발은 추가 정보 없이 시작할 수 있다. 배포 및 최종 인수 단계에는 다음이 필요하다.

- 실제 보호자 비밀번호
- 실제 Tablet pairing code
- SMTP host, port, 계정, 발신자와 수신자 정보
- 최종 가족사진과 설명
- 실사용 식사·복약 일정

비밀번호, pairing code, API key와 SMTP 비밀값은 채팅이나 Git에 기록하지 않고 `rpi5-server`의 권한 제한 JSON에 직접 배치한다.
