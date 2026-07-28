# Reminiscence 포스터 handoff

이 패키지는 학회형 A0 메인 포스터와 A1 기술·시연 포스터를 편집할 때 사용할 최종 원고, 정적 figure, 표 원본, 합성 데이터와 생성 source를 함께 제공한다. 본문은 Markdown과 DOCX 두 형식이며 DOCX에는 figure와 표를 배치해 편집자가 전체 맥락을 확인할 수 있도록 했다.

preview의 PDF는 DOCX를 검수용으로 렌더링한 결과다. MANIFEST.sha256은 압축 시점의 패키지 파일 해시를 기록하며 manifest 자체는 해시 대상에서 제외한다.

## 출력 배치

120×240 cm 백스크린의 상단에서 약 8 cm 아래에 A0 가로형을 배치하면 폭 118.9 cm가 스크린 폭 120 cm 안에 들어간다. A0 아래에 약 5 cm의 간격을 두고 A1 가로형을 가운데 정렬하면 두 장의 하단은 상단 기준 약 157 cm에 위치한다. 테이블 높이 74 cm로 인해 가려지는 하단 영역이 상단 기준 약 166 cm부터 시작하므로 두 포스터의 본문과 figure가 테이블 위에 남는다.

A0에는 프로젝트 소개, 연구 배경과 세 문제, 시스템 경계도, 사용자 시나리오, 개인 기준 평가, 구현 검증, 논의와 한계를 배치한다. Figure 1과 Figure 2에는 고정형 시작 문구 뒤 사용자 응답을 반영한 LLM 후속 질문이 이어지는 대화 구조를 표시한다.

A1에는 OpenAI API 기반 gpt-4o-transcribe 전사 경계, Supertonic 3 로컬 음성 출력, 루틴 타임라인, 합성 이상 탐지 plot, 데이터 보존 정책, 소프트웨어 검증과 실제 시연 화면을 배치한다. Figure 3과 Figure 4는 기술 설명과 인접하게 두고, 표는 exact lookup이 필요한 하단 또는 우측 영역에 배치한다.

## figure 사용

각 figure는 편집 가능한 SVG와 3200 px 폭의 PNG로 제공한다. PNG는 PowerPoint와 일반 편집 도구에 바로 삽입할 수 있고 SVG는 글자와 색, 간격을 수정할 때 사용한다. `figures/figma`에는 Figma 캔버스에 드래그해 가져올 수 있는 SVG 사본이 있다. 패널, 노드, 연결선, 라벨은 이름이 있는 group으로 구분했고 text element를 유지했으며 화살표는 marker 대신 편집 가능한 선과 삼각형으로 구성했다. 네 figure의 비중립 색상은 #8A1601을 중심으로 한 단일 계열이며 상태는 색상과 선, 마커, 직접 라벨을 함께 사용해 구분한다. Figure 4의 합성 자료 표시는 제목, plot 내부 주석과 캡션에서 유지해야 한다.

실제 사용자 UI와 실물 장치 사진은 현재 백엔드 저장소에 없다. assets의 FastAPI 화면은 실제 실행 화면이며, repository QR은 저장소 연결용이다. 프런트엔드 캡처나 실물 사진을 추가할 때에는 생성 시안과 실제 구현 화면을 구분해야 한다.

## 학술적 표기

Runtime 음성 전사는 OpenAI API의 /v1/audio/transcriptions를 사용하며 모델 식별자는 gpt-4o-transcribe이다. 회상 대화는 고정형 시작 문구로 시작하고 이후 문구는 직전 응답과 세션 맥락을 받은 OpenAI API 기반 LLM이 생성하도록 설계했다. 이 후속 질문 생성은 향후 구현과 검증 대상이다. WAV, 전사문, LLM 입력 맥락과 생성 text는 Reminiscence 로컬 저장소에 보존하지 않는 정책을 적용하며 OpenAI API의 서버 측 데이터 처리는 운영 시 별도로 확인한다.

합성 이상 탐지 plot은 handoff용 결정적 fixture를 현재 detector, anomaly service와 notification coordinator에 입력한 동작 예시이다. Figure 4는 다섯 개 대화 feature 중 세 개를 표시하고, 대화 domain 후보와 저장 상태를 구분한다. `evidence/synthetic_anomaly_result.json`에는 detector 결과와 60초 간격의 네 차례 service replay가 기록되어 있다. 기준 세션에는 요일 변화와 완만한 감소를 모사한 값이 포함되며 관측 자료로 해석할 수 없다. decision function은 위험 확률이 아니며 accuracy, sensitivity, specificity 또는 임상적 위험도로 표현할 수 없다. 회상요법 문헌은 설계 배경이며 이 프로토타입의 치매 예방·치료 효과를 입증하지 않는다.

## 편집 전 확인

최종 포스터에는 소속, 참여자 이름, 연락처와 실제 시연 QR의 목적지를 확정해야 한다. 인쇄 직전에는 실제 배치 크기에서 본문 글자, figure 축과 캡션을 확인하고 A0와 A1의 PDF를 100% 크기로 검수한다.
