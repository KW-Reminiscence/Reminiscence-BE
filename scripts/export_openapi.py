"""Export or verify the deterministic Reminiscence OpenAPI snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from reminiscence.main import app
from reminiscence.openapi_contract import render_openapi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "openapi.json"


def main() -> int:
    """Write the snapshot or fail when the checked-in contract is stale."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()
    rendered = render_openapi(app.openapi())
    if arguments.check:
        if not arguments.output.exists():
            parser.error(f"OpenAPI snapshot is missing: {arguments.output}")
        if arguments.output.read_text(encoding="utf-8") != rendered:
            parser.error(
                "OpenAPI snapshot is stale; run "
                "`uv run python scripts/export_openapi.py`"
            )
        return 0
    arguments.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
