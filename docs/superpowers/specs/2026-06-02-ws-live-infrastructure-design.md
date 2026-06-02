# WebSocket Live Infrastructure — Design

**Date:** 2026-06-02
**Phase:** 2 — Live Dashboard & Charts (slice 1 of 3)
**Status:** Approved (design), pending implementation plan
**Related:** PRD §5.4.8, spec 04 §4 (WebSocket Data Flow), spec 01 (WS tickets)

---

## 1. Purpose & scope

Deliver the **live data pipeline** that pushes new metric rows from the ingest
endpoint to subscribed browser clients over the existing WebSocket connection.
This is the backend foundation that the Global Dashboard and Server Detail
slices consume.

**In scope**
- In-process live bus + 500ms batched flush
- `write_metrics()` → live bus hook
- WS manager fan-out to **server** and **org** subscribers
- `subscribe_org` / `unsubscribe_org` / `subscribe` / `unsubscribe` actions with
  **server-side authorization** (closes the Phase-1 "full check in Phase 2" TODO)

**Out of scope (later slices)**
- Dashboard UI and server-card grid
- REST initial-state endpoints (`/servers/summary`, `/servers/:id/metrics`)
- Log live tail (`server_logs:{server_id}`) — same pattern, wired when the Log
  Viewer (Phase 3) needs it
- Alert events (`alert_fired`, …) — Phase 8

## 2. Architecture & data flow

The backend and ingest endpoint run in the **same process**, so fan-out is
in-process — no PostgreSQL `LISTEN/NOTIFY` (see PRD §5.4.8 for the rationale and
the multi-process upgrade path).

```
Telegraf POST ──► /api/ingest/metrics ──► write_metrics()
                                              │ (writes DB rows, unchanged)
                                              ▼
                                   live_bus.publish(server_id, org_id, rows)
                                              │  buffers rows per server_id
                                              ▼
                        ┌──── 500ms flush task (one asyncio loop) ────┐
                        │  for each server with buffered rows:        │
                        │     ws_manager.broadcast_metrics(           │
                        │         server_id, org_id, batch)           │
                        └─────────────────────────────────────────────┘
                                              ▼
        connections where  server_id ∈ subscribed_servers
                       OR  org_id    ∈ subscribed_orgs
```

## 3. Components

### 3.1 `app/ws/live_bus.py` (new) — the seam
- Holds `buffer: dict[str, list[dict]]` (server_id → pending rows) and
  `server_org: dict[str, str]` (server_id → org_id cache).
- `publish(server_id, org_id, rows)`: appends rows to the buffer and records the
  server→org mapping. Cheap, called from `write_metrics`.
- `flush_loop()`: every 500ms, atomically swap out the buffer, and for each
  server with rows call `ws_manager.broadcast_metrics(...)`. Skips empty servers
  (no empty pushes).
- Started/stopped in the FastAPI lifespan as a single background task.
- **This is the only module to change** if we ever move to multi-process
  (`LISTEN/NOTIFY`).

### 3.2 `WSManager.broadcast_metrics(server_id, org_id, payload)` (new)
- Targets a connection if `server_id ∈ subscribed_servers` **or**
  `org_id ∈ subscribed_orgs` — one message per connection regardless.
- Payload matches spec 04 §4.3:
  ```json
  { "channel": "server_metrics:<server_id>", "rows": [ { "metric_name", "value", "labels", "time" }, ... ] }
  ```
- Reuses the existing dead-connection cleanup pattern.

### 3.3 `write_metrics()` hook (`app/services/ingestion.py`)
- After the existing DB insert + commit, call
  `live_bus.publish(server_id, org_id, parsed_rows)`. No change to parsing or
  persistence; the live path is additive and must never block/break ingestion.
- `org_id` is **not** re-queried: the ingest endpoint already holds the
  authenticated `Server` (with `org_id`), so `write_metrics` takes `org_id` as a
  parameter (signature becomes `write_metrics(server_id, org_id, body, db)`) and
  the endpoint passes `server.org_id`. No extra DB hit per POST.

### 3.4 WS endpoint authorization (`app/main.py`)
Replace the Phase-1 simplified subscribe handling with authorized handling:

| Action | Authorization | Effect |
|---|---|---|
| `subscribe_org {org_id}` | `admin` OR `UserOrganization` membership for org | add to `subscribed_orgs` |
| `unsubscribe_org {org_id}` | — | remove from `subscribed_orgs` |
| `subscribe {server_id}` | resolve server→org, then same check | add to `subscribed_servers` |
| `unsubscribe {server_id}` | — | remove from `subscribed_servers` |

- Unauthorized subscribe → ignored, plus a `{ "error": "forbidden", "channel": ... }`
  frame for client debuggability.
- Authorization DB lookups use a short-lived `AsyncSessionLocal()` inside the
  handler, consistent with the existing user load.

## 4. Error handling & edge cases

- **Dead connections** — handled by existing `broadcast_*` cleanup; reused.
- **Org switch** — client sends `unsubscribe_org` then `subscribe_org`; set mutation only.
- **No subscribers for a server** — buffer fills, flush finds no targets, drops cheaply.
- **Large batches / `top_processes`** — fine; no NOTIFY 8KB limit (in-process).
- **Flush loop lifecycle** — one task, started/stopped in the app lifespan.
- **Empty ticks** — servers with no new rows are skipped (no empty pushes).
- **Ingestion safety** — `live_bus.publish` failures must not affect the ingest
  response; the publish call is wrapped so a live-path error never breaks writes.

## 5. Verification

`lima-ubuntu` is live, so this slice is verified end-to-end against real data
(raw WS client, mirroring the Phase-1 onboarding capture):

1. `subscribe {lima server_id}` → a `server_metrics:{id}` batch arrives within
   ~10s (next Telegraf flush), coalesced into one message.
2. `subscribe_org {org_id}` → the same server's metrics arrive via the org channel.
3. **Authorization** — a member-role user with no membership subscribing to a
   foreign org/server → no data + a `forbidden` frame.
4. **Batching** — one WS message carries the full ~117-row batch, not 117 messages.
5. `unsubscribe` → pushes stop.

## 6. PRD alignment

PRD §5.4.8 originally specified PostgreSQL `LISTEN/NOTIFY`. It has been updated
(this change set) to document the in-process live bus as the real architecture,
with `LISTEN/NOTIFY` retained as the multi-process upgrade path. Spec 03 §6
(onboarding) was likewise corrected to reflect the already-shipped in-process
broadcast. The PRD remains the source of truth.
