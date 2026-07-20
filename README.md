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

Python 버전, 패키지 관리 도구, 데이터베이스, ORM, 인증 및 배포 구성은 관련
이슈에서 결정한 뒤 이 문서에 반영합니다.

## 문서

- [개발 및 협업 규칙](./TBD.md)
