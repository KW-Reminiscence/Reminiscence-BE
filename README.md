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

데이터베이스, ORM, 인증 및 배포 구성은 관련 이슈에서 결정한 뒤 이 문서에
반영합니다.

## 로컬 실행

```bash
uv sync --all-groups
uv run uvicorn reminiscence.main:app --reload
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

## 회상 대화 엔진

`src/reminiscence/dialogue/`는 회상치료 대화 시나리오(S1~S6)와 프롬프트,
그리고 치매 케어 원칙을 강제하는 가드레일을 담고 있습니다.

액자는 브라우저로 구현합니다. 음성 인식과 음성 합성은 프론트엔드가
Web Speech API로 처리하고, 이 서버는 그 사이의 대화 흐름만 담당합니다.

```
브라우저 마이크 ─ASR─> POST /dialogue/sessions/{id}/turns
                              │
                        (문장 스트림)
                              v
        브라우저 speechSynthesis ─> 스피커
```

LLM은 OpenAI 호환 Chat Completions API를 사용합니다. 팀 게이트웨이
(`chat-api.leehyowon14.dev`)를 `OPENAI_BASE_URL`로 지정하며, 제공 모델은
`gpt-5.6-luna`입니다. API 키는 서버에만 두고 브라우저로 내보내지 않습니다.

> 게이트웨이 앞의 Cloudflare가 OpenAI SDK 기본 User-Agent를 403으로 막아,
> 클라이언트가 브라우저 형태의 User-Agent를 보냅니다(`DIALOGUE_USER_AGENT`).
> 게이트웨이에서 SDK를 정상 허용하도록 고치면 이 우회는 필요 없습니다.

| 모듈 | 역할 |
| --- | --- |
| `api.py` | HTTP 엔드포인트와 NDJSON 스트리밍 |
| `prompts.py` | 마스터 시스템 프롬프트와 시나리오별 템플릿. 프롬프트 수정은 여기서만 합니다. |
| `router.py` | 트리거로 시나리오를 고릅니다(규칙 기반). |
| `guardrails.py` | 사실 정정 금지, 시험형 질문 회피 등 설계 원칙을 코드로 강제합니다. |
| `fallbacks.py` | LLM 응답이 없을 때 대신 내보낼 문구 |
| `context.py` | 세션 상태, 대화 이력, 보호자 알림 큐 |
| `store.py` | 세션 저장소(메모리) |
| `messages.py` | 제공자에 묶이지 않는 대화 메시지 타입 |
| `llm_client.py` | OpenAI Chat Completions 스트리밍 래퍼 |
| `manager.py` | 위를 엮는 오케스트레이터 |

대화 엔진은 `ReplyStreamer` 프로토콜에만 의존하므로, 다른 LLM으로 바꾸려면
`llm_client.py`만 교체하면 됩니다.

### API

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/dialogue/sessions` | 세션 시작 |
| `GET` | `/dialogue/sessions/{id}` | 현재 상태 조회 |
| `PATCH` | `/dialogue/sessions/{id}` | 표시 중인 사진·음악·루틴 변경 |
| `POST` | `/dialogue/sessions/{id}/turns` | 한 턴 실행(문장 스트리밍) |
| `GET` | `/dialogue/sessions/{id}/summary` | 사용성 테스트 지표 |
| `DELETE` | `/dialogue/sessions/{id}` | 세션 종료 |

턴 요청은 두 가지입니다. `utterance`를 보내면 어르신이 말을 건 것이고,
`scenario`만 보내면 액자가 먼저 말을 겁니다(복약 알림 등).

```json
{"utterance": "이거 뭐야"}
{"scenario": "S4"}
```

응답은 `application/x-ndjson` 스트림입니다. 문장이 완성되는 즉시 한 줄씩
내려오므로, 받는 대로 `speechSynthesis`에 넣으면 됩니다.

```
{"type":"sentence","text":"바다 앞에서 활짝 웃고 계시네요."}
{"type":"sentence","text":"그때 기분이 어떠셨어요?"}
{"type":"result","scenario":"S1","scenario_label":"사진 기반 회상 대화",
 "reply":"...","violations":[],"guardian_flagged":false,"degraded":false}
```

`EventSource`(SSE)를 쓰지 않은 이유는 GET만 지원하기 때문입니다. 발화를
쿼리 파라미터에 실으면 nginx 접근 로그에 어르신의 발화가 그대로 남습니다.

`degraded`가 `true`면 LLM 응답을 받지 못해 대체 문구를 내보낸 것입니다.
복약 알림은 이 경우에도 반드시 전달됩니다.

### 실행과 시험

```bash
uv run uvicorn reminiscence.main:app --reload
```

브라우저에서 `scripts/frame_demo.html`을 열면 액자 형태로 동작을 확인할 수
있습니다(음성 인식은 Chrome·Edge에서 동작). 터미널에서 대화만 시험하려면
개발용 CLI를 씁니다.

```bash
uv run python scripts/chat_cli.py --photo "1998년 제주도, 본인과 딸, 여름"
```

### 환경 변수

`OPENAI_API_KEY`만 필수이고 나머지는 기본값으로 동작합니다. 값은 `.env`에
두면 됩니다(`.env.example` 참고). `.env`는 커밋되지 않습니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `OPENAI_API_KEY` | (없음) | 필수. API 키 |
| `OPENAI_BASE_URL` | OpenAI 기본 | OpenAI 호환 프록시·게이트웨이 엔드포인트 |
| `DIALOGUE_CORS_ORIGINS` | `*` | 허용할 프론트엔드 오리진. 쉼표로 구분 |
| `DIALOGUE_MODEL` | `gpt-5.6-luna` | 사용할 모델(`/v1/models`로 확인) |
| `DIALOGUE_USER_AGENT` | 브라우저 형태 | 요청 User-Agent(게이트웨이 WAF 우회용) |
| `DIALOGUE_TEMPERATURE` | `0.7` | 표현 다양성(0에 가까울수록 딱딱함) |
| `DIALOGUE_MAX_TOKENS` | `300` | 응답 최대 토큰 |
| `DIALOGUE_HISTORY_TURNS` | `8` | LLM에 넘길 최근 대화 턴 수 |
| `DIALOGUE_TIMEOUT_SECONDS` | `15` | 요청 제한 시간 |
| `DIALOGUE_MAX_RETRIES` | `1` | 재시도 횟수 |

## 문서

- [개발 및 협업 규칙](./TBD.md)
