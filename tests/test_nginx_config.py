"""Static validation for the Raspberry Pi Nginx ingress."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_nginx_allows_bounded_audio_and_slow_local_inference() -> None:
    nginx = (PROJECT_ROOT / "deploy/nginx/reminiscence").read_text(encoding="utf-8")

    assert nginx.count("client_max_body_size 1m;") == 2
    assert nginx.count("client_max_body_size 10m;") == 2
    assert nginx.count("client_body_timeout 30s;") == 2
    assert nginx.count("proxy_read_timeout 300s;") == 2
    assert nginx.count(
        r"location ~ ^/api/v1/conversations/sessions/[^/]+/turns$"
    ) == 2
