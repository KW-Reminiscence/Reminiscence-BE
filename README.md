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

| 모듈 | 역할 |
| --- | --- |
| `prompts.py` | 마스터 시스템 프롬프트와 시나리오별 템플릿. 프롬프트 수정은 여기서만 합니다. |
| `router.py` | 트리거로 시나리오를 고릅니다(규칙 기반). |
| `guardrails.py` | 사실 정정 금지, 시험형 질문 회피 등 설계 원칙을 코드로 강제합니다. |
| `context.py` | 세션 상태, 대화 이력, 보호자 알림 큐 |
| `llm_client.py` | Anthropic Messages API 스트리밍 래퍼 |
| `manager.py` | 위를 엮는 오케스트레이터 |

아직 HTTP 라우터에 연결되어 있지 않습니다. 하드웨어 없이 대화를 시험하려면
개발용 CLI를 사용합니다.

```bash
uv run python scripts/chat_cli.py --photo "1998년 제주도, 본인과 딸, 여름"
```

### 환경 변수

`ANTHROPIC_API_KEY`만 필수이고 나머지는 기본값으로 동작합니다.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | (없음) | 필수. Anthropic API 키 |
| `DIALOGUE_MODEL` | `claude-opus-4-8` | 사용할 모델 |
| `DIALOGUE_EFFORT` | `low` | `low`/`medium`/`high`/`xhigh`/`max` |
| `DIALOGUE_FAST_MODE` | `0` | `1`이면 fast mode(응답 속도 향상, 프리미엄 과금) |
| `DIALOGUE_MAX_TOKENS` | `300` | 응답 최대 토큰 |
| `DIALOGUE_HISTORY_TURNS` | `8` | LLM에 넘길 최근 대화 턴 수 |

## 문서

- [개발 및 협업 규칙](./TBD.md)
