from app.services.onboarding import _discover_nginx_vhost_logs, _discover_webroot

NGINX_T_MPHTJ = """
server {
    server_name mphtj.gov.my;
    access_log /var/log/nginx/mphtj.access.log;
    root /home/mphtj/web;
    listen 443 ssl;
}
server {
    server_name _;
    access_log /var/log/nginx/access.log;
    root /var/www/html;
    listen 80;
}
"""

NGINX_T_MULTI = """
server {
    server_name site1.example.com;
    access_log /var/log/nginx/site1.access.log;
    root /home/site1/web;
}
server {
    server_name site2.example.com;
    access_log /var/log/nginx/site2.access.log;
    root /var/www/site2;
}
server {
    server_name _;
    access_log /var/log/nginx/access.log;
    root /var/www/html;
}
"""


def test_discovers_extra_vhost_log():
    result = _discover_nginx_vhost_logs(NGINX_T_MPHTJ)
    assert "/var/log/nginx/mphtj.access.log" in result


def test_excludes_default_access_log():
    result = _discover_nginx_vhost_logs(NGINX_T_MPHTJ)
    assert "/var/log/nginx/access.log" not in result


def test_multi_site_discovers_all_extra_logs():
    result = _discover_nginx_vhost_logs(NGINX_T_MULTI)
    assert "/var/log/nginx/site1.access.log" in result
    assert "/var/log/nginx/site2.access.log" in result
    assert "/var/log/nginx/access.log" not in result


def test_deduplicates_paths():
    doubled = NGINX_T_MPHTJ + "\naccess_log /var/log/nginx/mphtj.access.log;\n"
    result = _discover_nginx_vhost_logs(doubled)
    assert result.count("/var/log/nginx/mphtj.access.log") == 1


def test_empty_input_returns_empty_list():
    assert _discover_nginx_vhost_logs("") == []


def test_excludes_off_keyword():
    output = "access_log off;\naccess_log /var/log/nginx/real.log;\n"
    result = _discover_nginx_vhost_logs(output)
    assert "off" not in result
    assert "/var/log/nginx/real.log" in result


def test_webroot_returns_nonstandard_root():
    assert _discover_webroot(NGINX_T_MPHTJ) == "/home/mphtj/web"


def test_webroot_skips_standard_var_www():
    output = "root /var/www/html;\nroot /usr/share/nginx/html;\n"
    assert _discover_webroot(output) == "/var/www/html"


def test_webroot_fallback_on_empty():
    assert _discover_webroot("") == "/var/www/html"


def test_webroot_first_nonstandard_wins():
    assert _discover_webroot(NGINX_T_MULTI) == "/home/site1/web"
