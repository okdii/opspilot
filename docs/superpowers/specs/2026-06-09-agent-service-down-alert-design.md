# Agent Service Down Alert — Design Spec

**Date:** 2026-06-09
**Status:** Approved

## Problem

The probe system (Services tab) fires `service_down` alerts via external TCP checks. This cannot reach services bound to `localhost` (e.g. MySQL on `127.0.0.1:3306`). The OpsPilot agent already detects local service status via systemd and reports it in the heartbeat, but the heartbeat ingest only stores data — it never fires alerts.

## Solution

Add alert-firing logic inline in the `ingest_heartbeat` handler. After storing rows, evaluate each service status and fire or resolve alerts accordingly.

## Alert Type Encoding

Use `agent_service_down:{service_name}` as the alert type string (e.g. `agent_service_down:mysql`).

This leverages the existing `(type, server_id)` dedup logic in `fire_alert` — since the service name is embedded in the type, each `(service, server)` pair gets independent dedup and cooldown. No schema changes required.

## Status Mapping

| Agent status     | Action                                       |
|------------------|----------------------------------------------|
| `stopped`        | `fire_alert(type=f"agent_service_down:{name}", server_id=..., severity="critical")` |
| `running`        | Query open alert of that type on that server → `resolve_alert(...)` if found |
| `not_installed`  | No action                                    |

## Alert Properties

- **Type:** `agent_service_down:{service_name}`
- **Severity:** `critical`
- **Message:** `"Service {name} is down (reported by OpsPilot agent)"`
- **FK:** `server_id` (no `service_id` — these are agent-local services, not Service model entries)
- **Cooldown:** 60 min
- **Dedup key:** `(type, server_id)` — unique per `(service_name, server)`

## Resolve Logic

On a `running` heartbeat for service `name`:
```sql
SELECT * FROM alert
WHERE type = 'agent_service_down:{name}'
  AND server_id = :server_id
  AND state IN ('firing', 'acked', 'snoozed')
LIMIT 1
```
If found, call `resolve_alert(db, alert)`.

## File Changed

`backend/app/routers/ingest.py` — `ingest_heartbeat` function only. No migrations, no new models, no scheduler changes.

## Out of Scope

- No UI changes (alert appears in the existing Alerts feed)
- No new alert rule configuration (always-on for agent-monitored services)
- No `_FK_BY_TYPE` registration needed (falls back to `server_id` for unknown types)
