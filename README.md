# Reminiscence-BE

Reminiscence 서비스의 백엔드 API 서버입니다.

## 기술 방향

Python과 [FastAPI](https://fastapi.tiangolo.com/)를 사용해 개발합니다.
FastAPI의 타입 기반 검증과 자동 OpenAPI 문서를 활용해 API 구현과 명세를
일관되게 관리합니다.

## 프로젝트 스펙

| 항목 | 스펙 |
| --- | --- |
| Language | Python |
| Web framework | FastAPI |
| API style | REST, JSON |
| API specification | OpenAPI 3.1 |
| Application interface | ASGI |
| Interactive API docs | Swagger UI(`/docs`), ReDoc(`/redoc`) |

| Python | 3.12 |
| Package manager | [uv](https://docs.astral.sh/uv/) |

MVP 데이터는 Raspberry Pi의 로컬 JSON 파일에 저장합니다. 태블릿 웹앱은
화면·마이크·스피커와 WAV 재생을 담당하고, 이 저장소의 FastAPI 서버는 루틴,
ASR, Supertonic 3 음성 합성, 대화 지표, 이상 탐지와 보호자 알림을 담당합니다.

## 로컬 실행

```bash
uv sync --all-groups
uv run uvicorn reminiscence.main:app --reload
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.
앱은 `.env`를 암묵적으로 읽지 않습니다. 로컬에서 환경 파일을 쓰려면
`deploy/runtime.env.example`을 바탕으로 Git에서 제외된 `.env`를 만든 뒤 다음처럼
명시합니다.

```bash
uv run uvicorn reminiscence.main:app --reload --env-file .env
```

### 로컬 데이터와 음성 설정

`deploy/configuration.example.json`을 `data/configuration.json`으로 복사하고
사진 URL과 루틴을 수정합니다. 다음 환경변수로 데이터 경로와 시간대를 바꿀 수
있습니다.

```bash
export REMINISCENCE_DATA_DIR=./data
export REMINISCENCE_TIMEZONE=Asia/Seoul
export REMINISCENCE_ROUTINE_TICK_SECONDS=5
export REMINISCENCE_EVALUATION_SECONDS=60
export REMINISCENCE_ANOMALY_CONFIRMATION_COUNT=3
```

`configuration.json`의 `conversation.suggestion_time`에는 매일 회상 대화를
권유할 서버 로컬 시각을 `HH:MM` 형식으로 설정합니다. 해당 시각 이후 같은 날
시작한 대화가 없을 때만 권유하며, 권유를 무시한 사실 자체는 저장하거나 이상으로
판정하지 않습니다.

각 routine의 `active`가 `false`이면 새 실행을 만들지 않습니다. 이미 시작된
실행은 시작 당시의 유예시간·재알림 간격·횟수를 저장하므로 설정을 바꾸거나
routine을 삭제해도 기존 응답 창은 변하지 않습니다. 같은 요일에 활성 routine의
응답 창이 겹치는 설정은 서버가 거부하며, 한 응답 창의 종료 시각과 다음 시작
시각이 같은 것은 허용합니다.

회상 대화 ASR을 사용하려면 `deploy/runtime.env.example`의 항목을 실제
환경변수로 설정합니다. 태블릿은 `audio/wav`를 전송해야 합니다. 서버는
codex-lb의 OpenAI 호환 `POST /v1/audio/transcriptions`에 정규화한 WAV와 고정
model `gpt-4o-transcribe`를 전송합니다. `CODEX_LB_BASE_URL`은 `/v1`까지 포함한
URL이고 `CODEX_LB_API_KEY`에는 codex-lb proxy key를 설정합니다.

codex-lb 응답의 `text`는 글자 수와 시간 지표로 즉시 축약하며,
음성·transcript·provider 원문 응답은 파일에 저장하지 않습니다. WAV 요청은
최대 10 MiB이며 초과한 본문은 FastAPI가 메모리에 적재하거나 codex-lb를
호출하기 전에 `413`으로 거부합니다. 기존 ETRI client와 baseline 도구는
오프라인 성능 비교용으로 유지하지만 Conversation API의 runtime provider로는
사용하지 않습니다.

서버는 질문마다 `display_text`와 `spoken_text`를 함께 반환합니다.
태블릿은 `spoken_text`를 `POST /api/v1/tts/speech`에 전송하고 응답받은
44.1kHz PCM WAV를 재생합니다. 음성은 Raspberry Pi에서 Supertonic 3 ONNX
모델로 생성하며 저장하거나 캐시하지 않습니다. 웹앱을 Raspberry Pi 정적 파일
또는 Vercel 중 어디에 배포해도 이 API 계약은 같습니다.

### Supertonic 3 TTS

로컬 개발에서는 첫 TTS 요청이 약 400MB의 모델을 기본 cache에 내려받습니다.
운영 배포는 `scripts/deploy.sh`가 모델을
`/home/ubuntu/apps/reminiscence/<environment>/supertonic3`에 먼저 내려받고,
컨테이너의 `/models/supertonic-3`에 영속 mount합니다. 이후 음성 합성에는
외부 TTS API나 인터넷 연결이 필요하지 않습니다.

기본 설정은 한국어, `F1` voice, 0.9배속, 8 inference steps이며
`deploy/runtime.env.example`의 `SUPERTONIC_*` 환경변수로 조정할 수 있습니다.
client가 voice나 inference parameter를 임의로 선택하지 못하도록 API에는
합성할 text만 받습니다. `SUPERTONIC_MAX_TEXT_CHARS`는 1~500 범위이고 API
절대 상한은 500자입니다.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tts/speech \
  -H 'Content-Type: application/json' \
  -d '{"text":"오늘 사진을 보며 이야기 나눠 보실래요?"}' \
  --output speech.wav
```

실제 model weights까지 포함한 한국어 합성 검증은 다음 명령으로 실행합니다.
`SUPERTONIC_MODEL_DIR` 등 `SUPERTONIC_*` 값이 먼저 설정되어 있어야 합니다.

```bash
RUN_SUPERTONIC_SMOKE=1 uv run pytest tests/tts/test_supertonic_smoke.py
```

`scripts/deploy.sh`도 새 image로 전환하기 전에 같은 한국어 문장을 메모리에서
합성하고 RIFF/WAVE header를 확인합니다. 실패하면 기존 container를 바꾸기 전에
배포가 중단됩니다.

Supertonic SDK 코드는 MIT, Supertonic 3 model weights는 사용 제한과 표시 의무가
있는 OpenRAIL-M입니다. 배포 전 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)의
공식 라이선스 링크를 확인해야 합니다.

### 태블릿 웹앱 연결

Raspberry Pi에서 웹앱과 API를 같은 origin으로 제공하면 CORS 설정이 필요하지
않습니다. Vercel처럼 다른 origin에서 웹앱을 제공하면 정확한 HTTPS origin을
쉼표로 구분해 설정합니다.

```bash
export REMINISCENCE_CORS_ORIGINS=https://your-tablet.vercel.app
```

태블릿에서 `file://`로 직접 연 HTML이 꼭 필요하면 브라우저가 보내는 `null`
origin을 명시할 수 있습니다. 다만 마이크 권한은 브라우저와 설치 방식에 따라
제한될 수 있으므로 실제 운영은 HTTPS 웹앱을 권장합니다.

```bash
export REMINISCENCE_CORS_ORIGINS=null
```

`*` wildcard는 허용하지 않습니다. HTTPS Vercel 화면에서 HTTP API를 호출하면
브라우저가 mixed content로 차단하므로 Raspberry Pi API도 HTTPS endpoint로
제공해야 합니다. CORS는 접근 인증이 아니므로 인터넷에 API를 공개할 때는
reverse proxy 또는 tunnel 계층의 접근 제어를 별도로 적용해야 합니다.

## 보호자 이메일 알림

이상 평가는 루틴과 회상 대화 모델을 분리하며, 현재 상태가 `ANOMALOUS`인 한
SMTP 발송은 한 번만 시도합니다. 발송 실패 자동 재시도와 과거 발송 이력은
MVP 범위에 포함하지 않습니다. 이메일에는 저장된 탐지 근거와 비의료 안내만
포함되며 API가 임의 제목이나 본문을 받지 않습니다.

`deploy/notification-config.example.json`을 저장소 밖의 안전한 위치에 복사한
뒤 보호자 이메일과 Gmail App Password를 입력합니다.

```bash
cp deploy/notification-config.example.json /tmp/notification-config.json
chmod 600 /tmp/notification-config.json
export NOTIFICATION_CONFIG_PATH=/tmp/notification-config.json
```

일반 Google 계정 비밀번호를 `app_password`에 넣으면 안 됩니다. Gmail 계정에
2단계 인증을 활성화하고 발급한 App Password만 사용합니다. 설정 파일이 없거나
잘못되어도 API 서버와 `/health`는 기동되지만, 알림 평가 요청은 `503`을
반환합니다.

주요 endpoint는 다음과 같습니다.

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/api/v1/routines/current` | 현재 진행 중인 루틴 문구와 TTS text 반환 |
| `POST` | `/api/v1/routines/{execution_id}/confirm` | 태블릿 버튼으로 루틴 완료 기록 |
| `GET` | `/api/v1/routines/history` | 루틴 수행 이력 반환 |
| `GET` | `/api/v1/conversations/suggestion` | 당일 정시 회상 대화 권유 상태 반환 |
| `POST` | `/api/v1/conversations/sessions` | 사진 회상 대화 시작과 TTS 질문 반환 |
| `POST` | `/api/v1/conversations/sessions/{session_id}/turns` | WAV 인식 후 지표만 저장 |
| `POST` | `/api/v1/conversations/sessions/{session_id}/complete` | 세션 완료와 요약 반환 |
| `POST` | `/api/v1/tts/speech` | `spoken_text`를 Supertonic 3 WAV로 합성 |
| `POST` | `/api/v1/anomaly/evaluate` | 개인별 루틴·대화 모델 평가 |
| `GET` | `/api/v1/anomaly/state` | 저장된 현재 상태와 근거 조회 |
| `POST` | `/api/v1/notifications/evaluate` | 평가 후 anomaly episode당 이메일 1회 시도 |

## Raspberry Pi 배포 파일

배포 환경별 디렉터리에 다음 파일을 미리 준비합니다.

```text
configuration.json은 data/configuration.json에 배치
notification-config.json은 mode 0600으로 배치
runtime.env는 mode 0600으로 배치
```

`runtime.env`에는 codex-lb proxy key가, `notification-config.json`에는 SMTP
App Password와 보호자 이메일이 있으므로 Git에 커밋하지 않습니다. 배포 시
`/data`와 Supertonic model directory만 쓰기 가능한 bind mount로 연결되고
나머지 컨테이너 파일 시스템은 읽기 전용으로 유지됩니다.

API 프로세스는 태블릿 polling 여부와 관계없이 루틴 상태를 기본 5초마다
전이하고 개인 이상 및 알림을 기본 60초마다 평가합니다. 두 간격은
`runtime.env`에서 조정할 수 있으며 0 이하·NaN·무한대는 기동 시 거부합니다.
candidate anomaly는 기본 3회 연속 관찰된 뒤 확정되며
`REMINISCENCE_ANOMALY_CONFIRMATION_COUNT`로 양의 정수 범위에서 조정합니다.

Nginx는 일반 요청 본문을 1 MiB로 제한하고 대화 WAV route만 10 MiB까지
허용합니다. Raspberry Pi의 Supertonic cold start를 고려해 upstream 응답
timeout은 300초입니다. production API는
`https://reminiscence-api.leehyowon14.dev`에서 제공합니다.

`.github/workflows/ci-cd.yml`은 `main` 대상 pull request에서 테스트, lint,
type check를 수행합니다. `main` push에서는 같은 검증을 통과한 ARM64 image를
GHCR에 게시한 뒤 production Docker Compose 배포를 수행합니다. 다른 branch의
push는 image build나 배포를 시작하지 않습니다.
