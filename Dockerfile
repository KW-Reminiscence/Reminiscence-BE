FROM ghcr.io/astral-sh/uv:0.10.4 AS uv

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN uv sync --locked --no-dev

RUN useradd --create-home --shell /usr/sbin/nologin app
USER app

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "from urllib.request import urlopen; assert urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200"

CMD ["uvicorn", "reminiscence.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
