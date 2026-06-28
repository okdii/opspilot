"""Tests for Track A Task 2: detected_webroot exposed in ServerUpdate and ServerOut."""
import pytest
from pydantic import ValidationError
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


# --- Finding 1: path validation tests ----------------------------------------

def test_webroot_rejects_relative_path():
    with pytest.raises(ValidationError, match="absolute path"):
        ServerUpdate(detected_webroot="var/www/html")


def test_webroot_rejects_traversal():
    with pytest.raises(ValidationError, match="'\\.\\.'"):
        ServerUpdate(detected_webroot="/var/www/../etc")


def test_webroot_strips_trailing_slash():
    u = ServerUpdate(detected_webroot="/srv/www/")
    assert u.detected_webroot == "/srv/www"


def test_webroot_coerces_empty_string_to_none():
    u = ServerUpdate(detected_webroot="   ")
    assert u.detected_webroot is None
