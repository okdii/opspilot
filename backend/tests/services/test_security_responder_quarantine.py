"""Tests for Track A: HTTP 200 gate and server-webroot in quarantine."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.security_responder import _resolve_target, _extract_file


def _alert(message: str):
    a = MagicMock()
    a.message = message
    a.sent_at = None
    a.server_id = "test-server"
    return a


def _server(webroot: str | None = None):
    s = MagicMock()
    s.detected_webroot = webroot
    return s


def test_quarantine_skipped_when_no_200_in_message():
    """HTTP 200 gate: alert without ' 200 ' must return None without touching DB."""
    alert = _alert("5 log line(s) matched '%/media/%.php%' on %access% in the last 300s (threshold 1)")
    result = asyncio.run(_resolve_target(None, alert, "quarantine_file", _server()))
    assert result is None


def test_quarantine_not_skipped_when_200_in_message():
    """HTTP 200 gate: alert with ' 200 ' must proceed to _extract_file."""
    alert = _alert("3 lines matched '%POST%.php% 200 %'")
    server = _server("/srv/www")
    with patch("app.services.security_responder._recent_log_lines", new_callable=AsyncMock) as mock:
        mock.return_value = []  # _extract_file returns None but gate is passed
        asyncio.run(_resolve_target(None, alert, "quarantine_file", server))
    mock.assert_called()  # gate was passed, _extract_file ran


def test_extract_file_uses_server_detected_webroot():
    """`_extract_file` must prefix paths with server.detected_webroot."""
    alert = _alert("matched")
    server = _server("/srv/www")
    log_line = '1.2.3.4 - - [25/Jun/2026] "POST /media/evil.php HTTP/1.1" 200 100 "-" "-"'
    with patch("app.services.security_responder._recent_log_lines", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [log_line]]  # webroot_write empty, fallback hits
        result = asyncio.run(_extract_file(None, alert, server))
    assert result == "/srv/www/media/evil.php"


def test_extract_file_falls_back_to_default_webroot_when_none():
    """`_extract_file` must use '/var/www/html' when detected_webroot is None."""
    alert = _alert("matched")
    server = _server(None)
    log_line = '1.2.3.4 - - [25/Jun/2026] "POST /media/evil.php HTTP/1.1" 200 100 "-" "-"'
    with patch("app.services.security_responder._recent_log_lines", new_callable=AsyncMock) as mock:
        mock.side_effect = [[], [log_line]]
        result = asyncio.run(_extract_file(None, alert, server))
    assert result == "/var/www/html/media/evil.php"
