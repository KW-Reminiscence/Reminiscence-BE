"""Static validation for the Raspberry Pi Nginx ingress."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _nginx() -> str:
    return (PROJECT_ROOT / "deploy/nginx/reminiscence").read_text(encoding="utf-8")


def test_nginx_routes_one_origin_to_api_and_web_loopback_ports() -> None:
    nginx = _nginx()

    assert "server_name reminiscence.leehyowon14.dev;" in nginx
    assert "reminiscence-api.leehyowon14.dev" not in nginx
    assert "    location /api/ {" in nginx
    assert "proxy_pass http://127.0.0.1:3010;" in nginx
    assert "    location / {" in nginx
    assert "proxy_pass http://127.0.0.1:3011;" in nginx


def test_nginx_allows_only_bounded_audio_and_slow_local_inference() -> None:
    nginx = _nginx()

    assert nginx.count("client_max_body_size 1m;") == 1
    assert nginx.count("client_max_body_size 10m;") == 1
    assert nginx.count("client_body_timeout 30s;") == 1
    assert nginx.count("proxy_read_timeout 300s;") == 3
    assert nginx.count(
        r"location ~ ^/api/v1/conversations/sessions/[^/]+/turns$"
    ) == 1


def test_nginx_disables_api_cache_and_applies_browser_security_headers() -> None:
    nginx = _nginx()

    assert '~^/api/ "no-store";' in nginx
    assert "add_header Cache-Control $reminiscence_cache_control always;" in nginx
    assert "Content-Security-Policy" in nginx
    assert "Permissions-Policy" in nginx
    assert "microphone=(self)" in nginx
    assert "Referrer-Policy" in nginx
    assert "X-Content-Type-Options" in nginx


def test_nginx_rate_limits_abuse_prone_public_and_media_routes() -> None:
    nginx = _nginx()

    assert "zone=reminiscence_auth:10m rate=10r/m;" in nginx
    assert "zone=reminiscence_turn:10m rate=30r/m;" in nginx
    assert "zone=reminiscence_tts:10m rate=60r/m;" in nginx
    assert "limit_req zone=reminiscence_auth" in nginx
    assert "limit_req zone=reminiscence_turn" in nginx
    assert "limit_req zone=reminiscence_tts" in nginx
    assert "limit_req_status 429;" in nginx


def test_nginx_uses_a_host_flag_for_atomic_maintenance_entry() -> None:
    nginx = _nginx()

    assert (
        "if (-f /home/ubuntu/apps/reminiscence/production/maintenance.flag)"
        in nginx
    )
    assert "error_page 503 @maintenance;" in nginx
    assert "location @maintenance" in nginx
    assert "잠시 점검 중입니다" in nginx
