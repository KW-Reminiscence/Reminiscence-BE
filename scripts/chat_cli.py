"""하드웨어 없이 회상 대화 흐름을 시험하는 개발용 CLI.

라즈베리파이도, 마이크도, 스피커도 없이 프롬프트를 반복 튜닝하기 위한 도구다.
시나리오 설계와 사용성 테스트 사이의 반복 루프를 여기서 돈다.

사용법::

    uv run python scripts/chat_cli.py
    uv run python scripts/chat_cli.py --photo "1998년 제주도, 본인과 딸, 여름"
    uv run python scripts/chat_cli.py --routine "점심 복약"

대화 중 명령어::

    /photo <설명>    표시 중인 사진 바꾸기
    /music <곡명>    음악 재생 상태로 바꾸기
    /routine <종류>  루틴 알림 걸기
    /alarm           액자가 먼저 말을 거는 루틴 알림 실행(기기 주도 턴)
    /state           현재 컨텍스트와 보호자 플래그 보기
    /quit            종료(세션 요약 출력)
"""

import argparse
from collections.abc import Generator

from reminiscence.dialogue import DialogueManager, SessionContext
from reminiscence.dialogue.manager import TurnResult
from reminiscence.dialogue.scenarios import LABELS, Scenario

DIM = "\033[2m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


def main() -> None:
    parser = argparse.ArgumentParser(description="회상 대화 흐름 테스트")
    parser.add_argument("--photo", help="표시 중인 사진 메타데이터")
    parser.add_argument("--music", help="재생 중인 음악")
    parser.add_argument("--routine", help="미이행 루틴 (예: 점심 복약)")
    parser.add_argument("--name", default="하늘이", help="기기 호칭")
    args = parser.parse_args()

    ctx = SessionContext(
        device_name=args.name,
        photo_meta=args.photo,
        music_meta=args.music,
        routine_type=args.routine,
        routine_pending=bool(args.routine),
    )
    manager = DialogueManager(ctx)

    print(f"{DIM}회상 대화 테스트. /quit 으로 종료.{RESET}\n")
    _print_state(ctx)

    while True:
        try:
            utterance = input(f"{CYAN}어르신 >{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not utterance:
            continue
        if utterance in {"/quit", "/exit"}:
            break
        if utterance == "/alarm":
            if not ctx.routine_pending:
                print(f"{DIM}걸린 루틴이 없습니다. /routine 점심 복약{RESET}\n")
                continue
            print(f"{YELLOW}{args.name} >{RESET} ", end="", flush=True)
            _print_trace(_speak_first(manager))
            continue

        if utterance.startswith("/"):
            _handle_command(utterance, ctx)
            continue

        print(f"{YELLOW}{args.name} >{RESET} ", end="", flush=True)
        _print_trace(_speak(manager, utterance))

    _print_summary(ctx)


def _speak(manager: DialogueManager, utterance: str) -> TurnResult:
    """문장을 받는 즉시 출력한다. 실제 기기에서는 이 자리가 TTS 큐다."""
    return _pump(manager.stream_turn(utterance))


def _speak_first(manager: DialogueManager) -> TurnResult:
    """액자가 먼저 말을 거는 턴(루틴 알림)."""
    return _pump(manager.stream_initiate(Scenario.S4_ROUTINE))


def _pump(stream: Generator[str, None, TurnResult]) -> TurnResult:
    while True:
        try:
            print(next(stream), end=" ", flush=True)
        except StopIteration as stop:
            print()
            result: TurnResult = stop.value
            return result


def _handle_command(cmd: str, ctx: SessionContext) -> None:
    head, _, rest = cmd.partition(" ")
    rest = rest.strip()

    if head == "/photo":
        ctx.photo_meta = rest or None
        ctx.music_meta = None
    elif head == "/music":
        ctx.music_meta = rest or None
    elif head == "/routine":
        ctx.routine_type = rest or None
        ctx.routine_pending = bool(rest)
    elif head == "/state":
        _print_state(ctx)
        return
    else:
        print(f"{DIM}알 수 없는 명령: {head}{RESET}")
        return

    _print_state(ctx)


def _print_state(ctx: SessionContext) -> None:
    routine = ctx.routine_type if ctx.routine_pending else "-"
    print(
        f"{DIM}[컨텍스트] 사진={ctx.photo_meta or '-'} | 음악={ctx.music_meta or '-'} | "
        f"루틴={routine} | 정서={ctx.affect_state} | "
        f"보호자플래그={len(ctx.guardian_flags)}건{RESET}\n"
    )


def _print_trace(result: TurnResult) -> None:
    label = LABELS[result.scenario]
    line = f"{DIM}  └ {result.scenario.value} {label}"
    if result.phase is not None:
        line += f" · {result.phase}"
    if result.guardian_flagged:
        line += f"{RESET}{RED} [보호자 플래그]{RESET}{DIM}"
    if result.violations:
        joined = ", ".join(result.violations)
        line += f"{RESET}{RED} 가드레일 위반: {joined}{RESET}{DIM}"
    print(line + RESET + "\n")


def _print_summary(ctx: SessionContext) -> None:
    """설계서 5장 사용성 테스트 체크리스트에 대응하는 세션 요약."""
    turns = [t for t in ctx.history if t.role == "assistant"]
    violations = sum(len(t.violations) for t in turns)

    print(f"\n{DIM}{'─' * 52}{RESET}")
    print("세션 요약")
    print(f"  대화 턴 수     : {len(turns)}")
    print(f"  가드레일 위반  : {violations}건  (목표 0건)")
    print(f"  보호자 알림 큐 : {len(ctx.guardian_flags)}건")

    used: dict[str, int] = {}
    for turn in turns:
        if turn.scenario is not None:
            used[turn.scenario] = used.get(turn.scenario, 0) + 1
    if used:
        breakdown = ", ".join(f"{k} {v}회" for k, v in sorted(used.items()))
        print(f"  시나리오 분포  : {breakdown}")

    if ctx.guardian_flags:
        print("\n  보호자 알림 큐 내용:")
        for flag in ctx.guardian_flags:
            print(f"    - [{flag.kind}] {flag.detail}")
    print()


if __name__ == "__main__":
    main()
