from unittest.mock import MagicMock
from app.services.log_evaluator import _derive_type


def _rule(pattern: str, source: str = "%access%", match_field=None):
    r = MagicMock()
    r.source = source
    r.pattern = pattern
    r.match_field = match_field
    return r


def test_derive_type_sppb_sppagebuilder():
    assert _derive_type(_rule("%com_sppagebuilder%uploadCustomIcon%")) == "sppb_exploit"


def test_derive_type_sppb_uploadcustomicon_only():
    assert _derive_type(_rule("%uploadCustomIcon%")) == "sppb_exploit"


def test_derive_type_field_scoped_php_is_webshell_execution():
    assert _derive_type(_rule("%/media/%.php%", match_field="url")) == "webshell_execution"


def test_derive_type_field_scoped_any_php_is_webshell_execution():
    """match_field set + .php in pattern always returns webshell_execution."""
    assert _derive_type(_rule("%.php%", match_field="url")) == "webshell_execution"


def test_derive_type_full_message_post_php_still_webshell_upload():
    """Existing %POST%.php% 200 % rule (no match_field) must stay webshell_upload."""
    assert _derive_type(_rule("%POST%.php% 200 %")) == "webshell_upload"


def test_derive_type_full_message_media_php_200_still_webshell_execution():
    """Existing %/media/%.php% 200 % rule (no match_field) must stay webshell_execution."""
    assert _derive_type(_rule("%/media/%.php% 200 %")) == "webshell_execution"


def test_derive_type_jce_unchanged():
    assert _derive_type(_rule("%com_jce%profiles.import%")) == "jce_exploit_attempt"


def test_derive_type_probe_scan_unchanged():
    assert _derive_type(_rule("% 404 %")) == "probe_scan"
