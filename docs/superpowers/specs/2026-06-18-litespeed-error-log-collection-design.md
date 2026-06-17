# LiteSpeed (and generic web) error-log collection — Design

**Date:** 2026-06-18
**Status:** Approved

## Problem

OpsPilot's Fluent Bit config does not ship LiteSpeed error logs.

LiteSpeed **access** logs already ship: `_detect_web_access_log()` detects an active
`lsws` service and returns `/usr/local/lsws/logs/access.log`, which the template's
generic `web_access` INPUT tails. The gap is the **error** log: nginx gets both a
hardcoded `nginx_access` and `nginx_error` INPUT, but LiteSpeed/Apache only get
`web_access`. There is no `web_error` equivalent, so a LiteSpeed server never ships
`/usr/local/lsws/logs/error.log`.

## Goal

Add error-log collection that mirrors the existing generic `web_access` pattern,
covering LiteSpeed (and, as a free side-effect of the shared pattern, Apache).
nginx keeps its hardcoded `nginx_error` input.

## Design

### 1. Detection (`backend/app/services/onboarding.py`)

Reuse the single existing detection. `web_kind` is already derived from
`_detect_web_access_log()` via `_web_server_kind()`. Add a pure mapper — no second
SSH probe:

```python
def _web_error_log(web_kind: str) -> str:
    return {
        "litespeed":     "/usr/local/lsws/logs/error.log",
        "nginx":         "/var/log/nginx/error.log",
        "apache-debian": "/var/log/apache2/error.log",
        "apache-rhel":   "/var/log/httpd/error_log",
    }.get(web_kind, "")
```

Pass `web_error_log_path=_web_error_log(web_kind)` into the `fluent-bit.conf.j2`
render context alongside the existing `web_access_log_path`.

### 2. Template (`backend/app/services/templates/fluent-bit.conf.j2`)

New `web_error` INPUT, mirroring `web_access`, gated to skip nginx (already covered
by the hardcoded `nginx_error` input — tailing twice would double-count):

```jinja
{% if web_error_log_path and web_error_log_path != '/var/log/nginx/error.log' %}
[INPUT]
    Name              tail
    Path              {{ web_error_log_path }}
    Tag               web_error
    DB                /var/lib/fluent-bit/web_error.db
    Skip_Long_Lines   On
{% endif %}
```

## Consistency notes

- Same block shape as `web_access` (no `Refresh_Interval`, matching nginx/web_access).
- Existing `modify` + `lua set_source` filters stamp `server_id` and
  `source=web_error` automatically — no OUTPUT changes.
- Security rules match `source LIKE '%access%'`; `web_error` is not an access source
  and will not double-count.
- No parser changes — LiteSpeed/Apache error lines are single-line.

## Scope / rollout

Config-template + onboarding change only. Takes effect on the next onboarding or
Fluent Bit config re-deploy to a server.
