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
화면·마이크·스피커를 담당하고, 이 저장소의 FastAPI 서버는 루틴, ASR,
대화 지표, 이상 탐지와 보호자 알림을 담당합니다.

## 로컬 실행

```bash
uv sync --all-groups
uv run uvicorn reminiscence.main:app --reload
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

### 로컬 데이터와 음성 설정

`deploy/configuration.example.json`을 `data/configuration.json`으로 복사하고
사진 URL과 루틴을 수정합니다. 다음 환경변수로 데이터 경로와 시간대를 바꿀 수
있습니다.

```bash
export REMINISCENCE_DATA_DIR=./data
export REMINISCENCE_TIMEZONE=Asia/Seoul
export REMINISCENCE_ROUTINE_TICK_SECONDS=5
export REMINISCENCE_EVALUATION_SECONDS=60
```

`configuration.json`의 `conversation.suggestion_time`에는 매일 회상 대화를
권유할 서버 로컬 시각을 `HH:MM` 형식으로 설정합니다. 해당 시각 이후 같은 날
시작한 대화가 없을 때만 권유하며, 권유를 무시한 사실 자체는 저장하거나 이상으로
판정하지 않습니다.

회상 대화 ASR을 사용하려면 `deploy/runtime.env.example`의 항목을 실제
환경변수로 설정합니다. 태블릿은 `audio/wav`를 전송해야 합니다. 서버는
ETRI 응답의 transcript를 글자 수와 시간 지표로 즉시 축약하며, 음성·transcript·
provider 원문 응답은 파일에 저장하지 않습니다.

서버는 질문마다 `display_text`와 `spoken_text`를 함께 반환합니다.
`spoken_text`는 태블릿 브라우저의 Web Speech API로 읽는 계약이며, 서버에서
음성 파일을 합성하지 않습니다. 웹앱을 Raspberry Pi 정적 파일 또는 Vercel 중
어디에 배포해도 이 API 계약은 같습니다.

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

`runtime.env`에는 ETRI API key가, `notification-config.json`에는 SMTP App
Password와 보호자 이메일이 있으므로 Git에 커밋하지 않습니다. 배포 시
`/data`만 쓰기 가능한 bind mount로 연결되고 나머지 컨테이너 파일 시스템은
읽기 전용으로 유지됩니다.

API 프로세스는 태블릿 polling 여부와 관계없이 루틴 상태를 기본 5초마다
전이하고 개인 이상 및 알림을 기본 60초마다 평가합니다. 두 간격은
`runtime.env`에서 조정할 수 있으며 0 이하 값은 기동 시 거부합니다.

## 문서

- [개발 및 협업 규칙](./TBD.md)
