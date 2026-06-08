# Multi-DB Instance Monitoring per Server

**Date:** 2026-06-08  
**Status:** Approved  
**Scope:** Allow a single OpsPilot server to monitor multiple database instances (e.g. MySQL on :3306 and MySQL on :3307 on the same Linux box).

---

## Problem

`DBCredential` currently enforces one credential per server via `LIMIT 1` everywhere. A server running two MySQL instances on different ports cannot be monitored beyond the first one.

---

## Design

### 1. Data Layer

**Migration:** Add `label VARCHAR(60) NULL` to `db_credential`.

- If the user omits a label, the backend defaults it to `"{db_type}:{port}"` (e.g. `mysql:3306`, `postgres:5432`).
- No unique constraint. The label is a display name only.
- Existing rows get `label = NULL`; the API returns the auto-default for those.

### 2. Backend API

#### `GET /api/organizations/{org_id}/db-credentials`

Response shape changes from one flat entry per server to a grouped structure:

```json
[
  {
    "server_id": "...",
    "server_name": "lima-ubuntu",
    "instances": [
      {
        "credential_id": "...",
        "label": "Primary",
        "host": "127.0.0.1",
        "port": 3306,
        "username": "opspilot_monitor",
        "is_replica": false,
        "db_type": "mysql",
        "last_check_ok": true,
        "last_checked": "2026-06-08T07:39:10+00:00"
      },
      {
        "credential_id": "...",
        "label": "Analytics",
        "host": "127.0.0.1",
        "port": 3307,
        "username": "opspilot_monitor",
        "is_replica": false,
        "db_type": "mysql",
        "last_check_ok": null,
        "last_checked": null
      }
    ]
  }
]
```

`instances` is an empty array when no credentials are configured for that server. The outer entry always exists for every active server in the org.

#### Credential CRUD

| Old | New |
|-----|-----|
| `POST /api/servers/{server_id}/db-credentials` | Same path — remove the "already configured" guard; allow N credentials per server |
| `PATCH /api/servers/{server_id}/db-credentials` | `PATCH /api/servers/{server_id}/db-credentials/{credential_id}` |
| `DELETE /api/servers/{server_id}/db-credentials` | `DELETE /api/servers/{server_id}/db-credentials/{credential_id}` |
| `GET /api/servers/{server_id}/db-credentials/password` | `GET /api/servers/{server_id}/db-credentials/{credential_id}/password` |

`POST` body gains an optional `label` field (max 60 chars).  
`PATCH` body gains an optional `label` field.

#### `POST` request body (`DBCredentialIn`)
```json
{
  "host": "127.0.0.1",
  "port": 3307,
  "username": "opspilot_monitor",
  "password": "...",
  "is_replica": false,
  "db_type": "mysql",
  "label": "Analytics"
}
```

#### Metric query endpoints

`GET /api/servers/{server_id}/db-metrics/latest` and  
`GET /api/servers/{server_id}/db-metrics`  
both gain a required `credential_id` query parameter. The backend uses it to look up the credential's label and filters metrics by `labels->>'db_label' = :label`.

#### `_last_check` helper

Currently queries `metric_name LIKE 'mysql.%'` with no instance filter. New signature:

```python
async def _last_check(db, server_id, label: str, db_type: str) -> tuple[bool | None, datetime | None]
```

Filters: `metric_name LIKE '{db_type}.%' AND labels->>'db_label' = :label`

### 3. Telegraf

#### Onboarding service

Remove `_build_mysql_dsn` and `_build_pg_dsn`. Replace with:

```python
async def _build_db_instances(db, server) -> list[dict]:
    """Returns [{label, dsn, db_type}] for all credentials on this server."""
```

`_step_configure_telegraf` receives `db_instances: list[dict]` instead of two single DSN strings.

#### Template (`telegraf.conf.j2`)

Replace the two `{% if mysql_dsn %}` / `{% if pg_dsn %}` blocks with a loop:

```jinja2
{% for inst in db_instances %}
{% if inst.db_type == 'mysql' %}
# ── MySQL input: {{ inst.label }} ──────────────────────────────────────────
[[inputs.mysql]]
  servers = ["{{ inst.dsn }}"]
  perf_events_statements_digest_text_limit = 120
  perf_events_statements_limit            = 250
  perf_events_statements_time_limit       = 86400
  table_schema_databases                  = []
  gather_slave_status                     = true
  gather_table_io_waits                   = false
  gather_table_lock_waits                 = false
  gather_index_io_waits                   = false
  gather_event_waits                      = false
  gather_file_events_stats                = false
  gather_perf_events_statements           = false
  [inputs.mysql.tags]
    db_label = "{{ inst.label }}"

{% elif inst.db_type == 'postgres' %}
# ── PostgreSQL input: {{ inst.label }} ─────────────────────────────────────
[[inputs.postgresql]]
  address = "{{ inst.dsn }}"
  [inputs.postgresql.tags]
    db_label = "{{ inst.label }}"

{% endif %}
{% endfor %}
```

The `db_label` tag lands in `server_metrics.labels` as `{"db_label": "Primary", "server": "127.0.0.1:3306", ...}`, allowing per-instance metric isolation.

### 4. Frontend Store (`stores/databases.ts`)

#### New types

```typescript
export interface DbInstanceStatus {
  credential_id: string
  label: string
  host: string
  port: number
  username: string
  is_replica: boolean
  db_type: DbType
  last_check_ok: boolean | null
  last_checked: string | null
}

export interface DbServerStatus {
  server_id: string
  server_name: string
  instances: DbInstanceStatus[]
}
```

`DbCredentialStatus` is replaced by `DbServerStatus` + `DbInstanceStatus`. The `has_credentials` boolean is derived as `instances.length > 0`.

#### Updated `DbCredentialPayload`

```typescript
export interface DbCredentialPayload {
  host: string
  port: number
  username: string
  password?: string
  is_replica: boolean
  db_type: DbType
  label?: string
}
```

#### Store action signatures

```typescript
saveCredentials(serverId, payload, credentialId: string | null): Promise<void>
// credentialId=null → POST (create); string → PATCH (edit)

deleteCredentials(serverId, credentialId: string): Promise<void>

fetchLatest(serverId, credentialId: string): Promise<void>

fetchSeries(serverId, metric, range, credentialId: string): Promise<DbSeriesResponse>

fetchPassword(serverId, credentialId: string): Promise<string>
```

### 5. Frontend Components

#### `DatabasesView.vue`

- `servers` computed from `store.servers` (renamed from `store.credentials`).
- `selectedInstanceId: ref<string | null>` — active instance within the selected server.
- When a server tab is selected, auto-select its first instance (prefer connected over pending over first).
- Between the server tab strip and the dashboard, render an **instance pill bar** when `instances.length > 0`:

```
[ ● Primary ]  [ Analytics ]  [ + Add Instance ]
```

  - Active pill: accent background. Connected dot: green `●`, pending: `◐`, error: `⚠`.
  - `[+ Add Instance]` pill always appears at the end; opens `DbCredentialModal` in create mode.
- `DbNoCredentials` renders when `instances.length === 0`.
- `DbHealthDashboard` renders for the selected instance, receives `credentialId` and the `DbInstanceStatus`.

#### `DbCredentialModal.vue`

- New `Label` text field (optional, max 60 chars, placeholder "e.g. Primary, Analytics, Port 3307").
- `db_type` selector is always enabled on create (each instance is independent).
- Prop `existingCredential: DbInstanceStatus | null` — null = create, non-null = edit.
- Title: "Add DB Instance — {serverName}" on create, "Edit DB Instance — {label}" on edit.

#### `DbHealthDashboard.vue`

- New required prop: `credentialId: string`.
- All calls to `store.fetchLatest`, `store.fetchSeries`, `store.fetchPassword` pass `credentialId`.
- "Edit Credentials" and "Remove" act on `credentialId`.
- No visual changes to the dashboard itself.

#### `DbNoCredentials.vue`

- No changes. Continues to render the SQL setup card for the first credential.
- After first credential is saved, the pill bar appears and the `[+ Add Instance]` pill handles additional ones.

---

## Migration Path for Existing Data

Existing `db_credential` rows have `label = NULL`. The API treats `NULL` label as `"{db_type}:{port}"` when returning responses. No data loss; existing monitoring continues uninterrupted. The Telegraf redeploy injects the `db_label` tag; metrics collected before the redeploy have no `db_label` in labels — the metric queries fall back gracefully (show `—` for historical data before the migration, live data is correct immediately after redeploy).

---

## Out of Scope

- Alert rules per DB instance (existing alert rules remain at server level).
- Replication lag per instance (existing `is_replica` flag stays, applied to each instance independently).
- Bulk credential import.
