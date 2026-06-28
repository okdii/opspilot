"""Tests for Track A Task 2: detected_webroot exposed in ServerUpdate and ServerOut."""
from app.schemas.server import ServerOut, ServerUpdate


def test_server_update_has_detected_webroot_field():
    u = ServerUpdate(detected_webroot="/srv/www")
    assert u.detected_webroot == "/srv/www"


def test_server_update_detected_webroot_defaults_none():
    u = ServerUpdate()
    assert u.detected_webroot is None


def test_server_out_has_detected_webroot_field():
    """ServerOut must include detected_webroot so frontend can read it."""
    fields = ServerOut.model_fields
    assert "detected_webroot" in fields
