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

보호자 알림은 교육용 소규모 운영을 전제로 데이터베이스 없이 로컬 JSON 파일에
피보호자 1명과 보호자 1명의 연결 정보를 저장합니다.

## 로컬 실행

```bash
uv sync --all-groups
uv run uvicorn reminiscence.main:app --reload
```

API 문서는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다.

## 보호자 이메일 알림

이상 탐지 모듈이나 태블릿은 `POST /guardian-alerts`를 호출해 보호자 1명에게
이메일을 보낼 수 있습니다. 요청은 설정 파일의 `api_password`와
`X-API-Key` header가 일치할 때만 처리됩니다.

메일은 Gmail SMTP의 STARTTLS 연결로 즉시 한 번 전송합니다. 데이터베이스,
발송 queue, 자동 재시도, 발송 이력은 사용하지 않습니다.

### Gmail과 설정 파일 준비

Google 계정에서 2단계 인증을 활성화한 뒤
[Google App Password](https://support.google.com/accounts/answer/185833?hl=ko)를
발급합니다. Google 계정 유형이나 보안 정책에 따라 App Password 메뉴가 제공되지
않을 수 있으며, 일반 Google 계정 비밀번호를 `app_password`에 저장하면 안 됩니다.

`deploy/notification-config.example.json`을 저장소 밖의 안전한 위치에 복사한 뒤
다음 값을 변경합니다.

| 항목 | 설명 |
| --- | --- |
| `api_password` | 태블릿이 `X-API-Key`로 보낼 사용자 지정 비밀번호. 출력 가능한 ASCII 문자만 허용 |
| `care_recipient.name` | 알림 본문에 표시할 피보호자 이름 |
| `guardian.email` | 알림을 받을 보호자 이메일 주소 |
| `smtp.username` | 메일을 발송할 Gmail 주소 |
| `smtp.app_password` | 해당 Gmail 계정에서 발급한 App Password |
| `smtp.from_name` | 메일 발신자 표시 이름 |

실제 설정 파일에는 비밀번호와 개인정보가 있으므로 Git에 commit하지 않습니다.
로컬 개발에서는 파일 권한을 제한하고 경로를 환경 변수로 전달합니다.

```bash
cp deploy/notification-config.example.json /tmp/notification-config.json
chmod 600 /tmp/notification-config.json
export NOTIFICATION_CONFIG_PATH=/tmp/notification-config.json
uv run uvicorn reminiscence.main:app --reload
```

설정 파일이 없거나 올바르지 않아도 API server와 `/health`는 기동됩니다.
이 경우 `/guardian-alerts`만 `503 Service Unavailable`을 반환합니다.

### API 호출

`detected_at`은 UTC offset을 포함한 ISO 8601 시각이어야 합니다.

```bash
curl --request POST http://127.0.0.1:8000/guardian-alerts \
  --header "Content-Type: application/json" \
  --header "X-API-Key: change-this-tablet-password" \
  --data '{
    "alert_type": "루틴 이탈",
    "description": "약 복용 확인에 연속으로 응답하지 않았습니다.",
    "detected_at": "2026-07-24T10:30:00+09:00"
  }'
```

정상 전송 응답은 `{"status":"sent"}`입니다. 인증 실패는 `401`, Gmail 연결이나
전송 실패는 `502`, 설정 오류는 `503`을 반환합니다.

### Raspberry Pi 배포 전 준비

현재 Raspberry Pi가 offline인 동안 실제 배포와 Gmail 실발송 검증은 수행하지
않습니다. 장비가 online이 되면 배포 환경별로 다음 경로에 실제 설정을 먼저
준비해야 합니다.

- 개발: `/home/ubuntu/apps/reminiscence/development/notification-config.json`
- 운영: `/home/ubuntu/apps/reminiscence/production/notification-config.json`

두 파일 모두 소유자만 읽고 쓸 수 있도록 mode를 `0600`으로 설정합니다.
배포 시 이 파일은 container의 `/run/secrets/notification-config.json`에
read-only로 mount됩니다. 파일이 없으면 배포 script가 실행을 중단합니다.

## 문서

- [개발 및 협업 규칙](./TBD.md)
