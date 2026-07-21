"""설계서 1장의 설계 원칙이 실제로 강제되는지 검증한다. API 키가 필요 없다."""

from reminiscence.dialogue import guardrails

# --- 입력 가드레일: 민감 소재 탐지 -------------------------------------


def test_scan_input_detects_an_explicit_death_mention() -> None:
    signal = guardrails.scan_input("우리 남편 돌아가신 지 오래됐지")

    assert signal.sensitive
    assert signal.keyword == "남편"


def test_scan_input_detects_asking_for_a_deceased_relative() -> None:
    # 설계서 S6의 대표 사례
    signal = guardrails.scan_input("우리 남편은 언제 와?")

    assert signal.sensitive
    assert signal.keyword == "남편"


def test_scan_input_leaves_ordinary_reminiscence_alone() -> None:
    signal = guardrails.scan_input("그때 참 좋았지, 딸이랑 바다 갔었어")

    assert not signal.sensitive
    assert not signal.distress


def test_scan_input_separates_distress_from_bereavement() -> None:
    signal = guardrails.scan_input("여기가 어디야, 집에 갈래")

    assert signal.distress
    assert not signal.sensitive


# --- 출력 가드레일: 응답 검증 -------------------------------------------


def test_check_output_replaces_a_death_notification() -> None:
    verdict = guardrails.check_output("남편분은 3년 전에 돌아가셨어요.")

    assert "돌아가셨" not in verdict.text
    assert verdict.violations
    assert verdict.text.endswith("?")


def test_check_output_blocks_fact_correction() -> None:
    verdict = guardrails.check_output("그건 아니에요, 따님이 아니라 조카분이세요.")

    assert "그건 아니" not in verdict.text
    assert verdict.violations


def test_check_output_strips_a_quiz_style_question() -> None:
    verdict = guardrails.check_output("이 사진 좋네요. 이분 누구예요?")

    assert "누구예요?" not in verdict.text
    assert any(v.startswith("시험형질문") for v in verdict.violations)


def test_check_output_truncates_beyond_two_sentences() -> None:
    three = "바다가 참 좋네요. 날씨도 맑았나 봐요. 그때 기분이 어떠셨어요?"

    verdict = guardrails.check_output(three)

    assert any(v.startswith("문장수") for v in verdict.violations)
    assert "그때 기분이" not in verdict.text


def test_check_output_keeps_only_one_question() -> None:
    verdict = guardrails.check_output("어디였어요? 기분이 어떠셨어요?")

    assert verdict.text.count("?") == 1


def test_check_output_passes_a_compliant_reply_through() -> None:
    good = "바다 앞에서 활짝 웃고 계시네요."

    verdict = guardrails.check_output(good)

    assert verdict.clean
    assert verdict.text == good


def test_check_output_records_length_without_truncating() -> None:
    # 문장 중간을 자르면 TTS가 어색해져 오히려 혼란을 준다
    verdict = guardrails.check_output("정말 " * 40 + "좋네요.")

    assert any(v.startswith("길이") for v in verdict.violations)
    assert verdict.text.endswith("좋네요.")


def test_has_forbidden_catches_a_banned_phrase() -> None:
    assert guardrails.has_forbidden("남편분은 돌아가셨어요")
    assert not guardrails.has_forbidden("바다 앞에서 웃고 계시네요")
