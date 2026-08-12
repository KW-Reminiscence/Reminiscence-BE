"""Strict container preflight before executing the API process."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Sequence
from pathlib import Path

from reminiscence.auth.secrets import load_auth_secrets
from reminiscence.notification.config import load_notification_config
from reminiscence.storage.migration import validate_data_directory

CommandExecutor = Callable[[str, list[str]], object]


def validate_runtime_configuration(data_directory: Path | None = None) -> None:
    """Validate versioned domain JSON and both mode-restricted secret JSON files."""

    validate_data_directory(
        data_directory
        or Path(os.environ.get("REMINISCENCE_DATA_DIR", "data"))
    )
    load_auth_secrets()
    load_notification_config()


def run_preflight(
    command: Sequence[str],
    *,
    executor: CommandExecutor = os.execvp,
) -> int:
    """Validate configuration, then replace this process with the command."""

    validate_runtime_configuration()
    if not command:
        return 0
    executable = command[0]
    if not executable.strip():
        raise ValueError("command must not be blank")
    executor(executable, list(command))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the optional command executed after a successful preflight."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    arguments = parser.parse_args(argv)
    return run_preflight(arguments.command)


if __name__ == "__main__":
    raise SystemExit(main())
