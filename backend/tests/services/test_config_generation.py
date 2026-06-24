import os
from jinja2 import Environment, FileSystemLoader
from app.services.onboarding import _build_auditd_setup, _build_action_script

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../../app/services/templates")


def _render_fb(extra_nginx_log_paths=None):
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    tmpl = env.get_template("fluent-bit.conf.j2")
    return tmpl.render(
        server_id="test-id", server_name="test",
        ingest_host="backend", ingest_port=8000, ingest_tls="Off",
        ingestion_token="tok",
        php_fpm_log_path="/var/log/php8.2-fpm.log", php_app_log_path="",
        web_access_log_path="/var/log/nginx/access.log", web_error_log_path="",
        auditd_enabled=False, mariadb_general_enabled=False,
        syslog_path="/var/log/syslog", auth_log_path="/var/log/auth.log",
        mariadb_error_path="/var/log/mysql/error.log",
        mariadb_slow_path="/var/log/mysql/slow.log",
        extra_nginx_log_paths=extra_nginx_log_paths or [],
    )


def test_no_extra_logs_no_extra_input_block():
    conf = _render_fb([])
    # mphtj log should not appear
    assert "/var/log/nginx/mphtj.access.log" not in conf


def test_extra_log_renders_additional_input():
    conf = _render_fb(["/var/log/nginx/mphtj.access.log"])
    assert "/var/log/nginx/mphtj.access.log" in conf


def test_extra_log_tagged_nginx_access():
    conf = _render_fb(["/var/log/nginx/mphtj.access.log"])
    # Find the block and confirm it has nginx_access tag
    idx = conf.index("/var/log/nginx/mphtj.access.log")
    block = conf[idx - 200:idx + 200]
    assert "nginx_access" in block


def test_extra_log_unique_db_path():
    conf = _render_fb(["/var/log/nginx/mphtj.access.log"])
    assert "_var_log_nginx_mphtj_access_log" in conf


def test_two_extra_logs_both_rendered():
    conf = _render_fb(["/var/log/nginx/site1.access.log", "/var/log/nginx/site2.access.log"])
    assert "/var/log/nginx/site1.access.log" in conf
    assert "/var/log/nginx/site2.access.log" in conf


# auditd builder
def test_build_auditd_setup_injects_webroot():
    script = _build_auditd_setup("/home/mphtj/web")
    assert "-w /home/mphtj/web -p wa -k webroot_write" in script


def test_build_auditd_setup_preserves_dollar_vars():
    script = _build_auditd_setup("/home/mphtj/web")
    assert "$WEBUID" in script
    assert "WEBUID=$(id -u" in script


def test_build_auditd_setup_default_path():
    script = _build_auditd_setup("/var/www/html")
    assert "-w /var/www/html -p wa -k webroot_write" in script


# action script builder
def test_build_action_script_adds_nonstandard_root():
    script = _build_action_script("/opt/custom/web")
    assert "/opt/custom/web" in script


def test_build_action_script_home_subdir_added_explicitly():
    script = _build_action_script("/home/mphtj/web")
    assert "/home/mphtj/web" in script


def test_build_action_script_none_produces_standard_roots():
    script = _build_action_script(None)
    assert "for root in /var/www /usr/share/nginx /srv/www /home" in script
    assert "{extra_roots_entry}" not in script
