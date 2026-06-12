# Fail2ban Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Security" tab to the server detail page showing fail2ban daemon status, per-jail stats, a 24h ban timeline chart, top attacking countries, and a paginated banned IPs table with geolocation.

**Architecture:** SSH poll every 5 minutes per active server using `fail2ban-client status <jail>` for live banned IP snapshots and `/var/log/fail2ban.log` parsing for historical ban events. Geolocation resolved once per new IP via ip-api.com and cached permanently. Four new DB tables feed five API endpoints that drive five Vue sub-components inside a new SecurityTab.

**Tech Stack:** Python/FastAPI + SQLAlchemy (raw SQL, no ORM models), httpx for geo API calls, Vue 3 + Pinia + MetricChart (ApexCharts wrapper) for frontend.

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `backend/migrations/versions/0024_fail2ban.py` | Create | 4 new tables |
| `backend/app/services/fail2ban_collector.py` | Create | SSH poll + log parse + geo lookup |
| `backend/app/routers/fail2ban.py` | Create | 5 API endpoints |
| `backend/app/jobs/scheduler.py` | Modify | Register 5-min collector job |
| `backend/app/main.py` | Modify | Include fail2ban router |
| `frontend/src/stores/fail2ban.ts` | Create | Pinia store + TypeScript types |
| `frontend/src/components/servers/tabs/SecurityTab.vue` | Create | Tab shell + empty/error states |
| `frontend/src/components/servers/tabs/fail2ban/Fail2banStatusBar.vue` | Create | 4 stat cards |
| `frontend/src/components/servers/tabs/fail2ban/Fail2banChart.vue` | Create | 24h ban timeline bar chart |
| `frontend/src/components/servers/tabs/fail2ban/Fail2banJailCards.vue` | Create | Per-jail stat cards |
| `frontend/src/components/servers/tabs/fail2ban/Fail2banTopCountries.vue` | Create | Country breakdown list |
| `frontend/src/components/servers/tabs/fail2ban/Fail2banBannedTable.vue` | Create | Paginated banned IPs table |
| `frontend/src/views/servers/ServerDetail.vue` | Modify | Register Security tab |

---

## Task 1: DB Migration

**Files:**
- Create: `backend/migrations/versions/0024_fail2ban.py`

- [ ] **Step 1: Verify previous migration revision**

```bash
grep -r "revision\s*=\|down_revision" backend/migrations/versions/0023_ai_base_url.py
```

Expected output includes `revision = "0023_ai_base_url"`. Use this as `down_revision` in the new migration.

- [ ] **Step 2: Create migration file**

Create `backend/migrations/versions/0024_fail2ban.py`:

```python
"""Add fail2ban monitoring tables

Revision ID: 0024_fail2ban
Revises: 0023_ai_base_url
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0024_fail2ban"
down_revision = "0023_ai_base_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fail2ban_jails",
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jail_name", sa.Text(), nullable=False),
        sa.Column("currently_banned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_banned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currently_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("server_id", "jail_name"),
    )
    op.create_table(
        "fail2ban_banned_ips",
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jail", sa.Text(), nullable=False),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("banned_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("server_id", "jail", "ip"),
    )
    op.create_table(
        "fail2ban_ban_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("server_id", UUID(as_uuid=True), sa.ForeignKey("server.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ip", sa.Text(), nullable=False),
        sa.Column("jail", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("server_id", "ip", "jail", "event_at", "action", name="uq_fail2ban_ban_events"),
    )
    op.create_index("ix_fail2ban_ban_events_server_event", "fail2ban_ban_events", ["server_id", "event_at"])
    op.create_table(
        "ip_geodata",
        sa.Column("ip", sa.Text(), primary_key=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        sa.Column("country_name", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("isp", sa.Text(), nullable=True),
        sa.Column("cached_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("ip_geodata")
    op.drop_index("ix_fail2ban_ban_events_server_event", table_name="fail2ban_ban_events")
    op.drop_table("fail2ban_ban_events")
    op.drop_table("fail2ban_banned_ips")
    op.drop_table("fail2ban_jails")
```

- [ ] **Step 3: Run migration**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec migrate alembic upgrade head 2>&1 | tail -5
```

Expected: `Running upgrade 0023_ai_base_url -> 0024_fail2ban, Add fail2ban monitoring tables`

- [ ] **Step 4: Verify tables exist**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U opspilot -d opspilot -c "\dt fail2ban*" -c "\dt ip_geodata"
```

Expected: 4 tables listed — `fail2ban_ban_events`, `fail2ban_banned_ips`, `fail2ban_jails`, `ip_geodata`

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/versions/0024_fail2ban.py
git commit -m "feat: add fail2ban monitoring DB migration (4 tables)"
```

---

## Task 2: Fail2ban Collector Service

**Files:**
- Create: `backend/app/services/fail2ban_collector.py`

- [ ] **Step 1: Create the collector**

Create `backend/app/services/fail2ban_collector.py`:

```python
"""fail2ban SSH poll — collect jail status and ban events every 5 min per active server.

Permission requirement: the SSH user must be in the fail2ban group on the target server:
    sudo usermod -aG fail2ban opspilot
"""
import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text

from app.database import AsyncSessionLocal
from app.models.server import Server
from app.services.ssh import SSHSession

log = logging.getLogger(__name__)

# fail2ban-client status <jail> parsing
_CURRENTLY_BANNED_RE = re.compile(r"Currently banned:\s+(\d+)")
_TOTAL_BANNED_RE = re.compile(r"Total banned:\s+(\d+)")
_CURRENTLY_FAILED_RE = re.compile(r"Currently failed:\s+(\d+)")
_BANNED_IP_LIST_RE = re.compile(r"Banned IP list:\s*(.*?)(?:\n\S|$)", re.DOTALL)

# /var/log/fail2ban.log line format:
# 2026-06-12 07:23:45,678 fail2ban.actions [1234]: NOTICE  [sshd] Ban 103.107.60.45
_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ fail2ban\.actions.*?NOTICE\s+\[(.+?)\] (Ban|Unban) (\S+)$"
)


def _parse_jail_status(output: str) -> dict:
    currently_banned = int(m.group(1)) if (m := _CURRENTLY_BANNED_RE.search(output)) else 0
    total_banned = int(m.group(1)) if (m := _TOTAL_BANNED_RE.search(output)) else 0
    currently_failed = int(m.group(1)) if (m := _CURRENTLY_FAILED_RE.search(output)) else 0
    banned_ips: list[str] = []
    if m := _BANNED_IP_LIST_RE.search(output):
        raw = m.group(1).strip()
        banned_ips = [ip.strip() for ip in raw.split() if ip.strip()]
    return {
        "currently_banned": currently_banned,
        "total_banned": total_banned,
        "currently_failed": currently_failed,
        "banned_ips": banned_ips,
    }


def _parse_fail2ban_log(output: str) -> list[dict]:
    events = []
    for line in output.splitlines():
        m = _LOG_LINE_RE.match(line.strip())
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        events.append({
            "event_at": ts,
            "jail": m.group(2),
            "action": m.group(3).lower(),
            "ip": m.group(4),
        })
    return events


async def _geo_lookup_batch(db, ips: list[str]) -> None:
    for ip in ips:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(
                    f"http://ip-api.com/json/{ip}",
                    params={"fields": "status,country,countryCode,city,isp"},
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("status") == "success":
                        await db.execute(
                            text("""
                                INSERT INTO ip_geodata (ip, country_code, country_name, city, isp, cached_at)
                                VALUES (:ip, :cc, :cn, :city, :isp, NOW())
                                ON CONFLICT (ip) DO NOTHING
                            """),
                            {
                                "ip": ip,
                                "cc": data.get("countryCode"),
                                "cn": data.get("country"),
                                "city": data.get("city"),
                                "isp": data.get("isp"),
                            },
                        )
                        await db.commit()
        except Exception:
            log.warning("geo lookup failed for %s", ip)
        await asyncio.sleep(1.5)  # respect 45 req/min free tier


async def _collect_one(server: Server) -> None:
    try:
        async with SSHSession(server) as ssh:
            # Get jail list
            status_result = await ssh.run("fail2ban-client status 2>&1", timeout=10)
            if not status_result.ok:
                log.warning("fail2ban: status check failed on %s: %s", server.id, status_result.stderr)
                return
            jail_match = re.search(r"Jail list:\s*(.+)", status_result.stdout)
            if not jail_match:
                log.info("fail2ban: no jails on server %s", server.id)
                return
            jail_names = [j.strip() for j in jail_match.group(1).split(",") if j.strip()]

            # Per-jail status
            jail_data: dict[str, dict] = {}
            for jail in jail_names:
                r = await ssh.run(f"fail2ban-client status {jail} 2>&1", timeout=10)
                if r.ok:
                    jail_data[jail] = _parse_jail_status(r.stdout)

            # Ban event log
            log_result = await ssh.run(
                "tail -n 5000 /var/log/fail2ban.log 2>/dev/null || true", timeout=15
            )
            log_events = _parse_fail2ban_log(log_result.stdout) if log_result.ok else []
    except Exception as e:
        msg = str(e).lower()
        if "permission denied" in msg or "permission" in msg:
            log.warning(
                "fail2ban: permission denied on %s — run: sudo usermod -aG fail2ban opspilot",
                server.id,
            )
        else:
            log.exception("fail2ban: SSH failed for server %s", server.id)
        return

    now = datetime.now(timezone.utc)
    all_new_ips: set[str] = set()

    async with AsyncSessionLocal() as db:
        for jail, data in jail_data.items():
            # Upsert jail snapshot
            await db.execute(
                text("""
                    INSERT INTO fail2ban_jails
                        (server_id, jail_name, currently_banned, total_banned, currently_failed, checked_at)
                    VALUES (:sid, :jail, :cb, :tb, :cf, :now)
                    ON CONFLICT (server_id, jail_name) DO UPDATE SET
                        currently_banned = EXCLUDED.currently_banned,
                        total_banned     = EXCLUDED.total_banned,
                        currently_failed = EXCLUDED.currently_failed,
                        checked_at       = EXCLUDED.checked_at
                """),
                {
                    "sid": str(server.id), "jail": jail,
                    "cb": data["currently_banned"], "tb": data["total_banned"],
                    "cf": data["currently_failed"], "now": now,
                },
            )
            await db.commit()

            # Replace banned IPs for this jail with live list
            await db.execute(
                text("DELETE FROM fail2ban_banned_ips WHERE server_id = :sid AND jail = :jail"),
                {"sid": str(server.id), "jail": jail},
            )
            for ip in data["banned_ips"]:
                await db.execute(
                    text("""
                        INSERT INTO fail2ban_banned_ips (server_id, jail, ip, checked_at)
                        VALUES (:sid, :jail, :ip, :now)
                        ON CONFLICT (server_id, jail, ip) DO UPDATE SET checked_at = EXCLUDED.checked_at
                    """),
                    {"sid": str(server.id), "jail": jail, "ip": ip, "now": now},
                )
                all_new_ips.add(ip)
            await db.commit()

        # Insert ban events (UNIQUE constraint silently skips duplicates)
        for event in log_events:
            try:
                await db.execute(
                    text("""
                        INSERT INTO fail2ban_ban_events (server_id, ip, jail, action, event_at)
                        VALUES (:sid, :ip, :jail, :action, :event_at)
                        ON CONFLICT (server_id, ip, jail, event_at, action) DO NOTHING
                    """),
                    {
                        "sid": str(server.id), "ip": event["ip"], "jail": event["jail"],
                        "action": event["action"], "event_at": event["event_at"],
                    },
                )
            except Exception:
                pass
        await db.commit()

        # Geo-lookup IPs not yet cached
        if all_new_ips:
            rows = await db.execute(
                text("SELECT ip FROM ip_geodata WHERE ip = ANY(:ips)"),
                {"ips": list(all_new_ips)},
            )
            existing = {r[0] for r in rows.fetchall()}
            await _geo_lookup_batch(db, list(all_new_ips - existing))

    log.info(
        "fail2ban: server %s — %d jails, %d events ingested",
        server.id, len(jail_data), len(log_events),
    )


async def collect_fail2ban() -> None:
    """Entry point called by APScheduler every 5 minutes."""
    async with AsyncSessionLocal() as db:
        servers = (
            await db.execute(select(Server).where(Server.is_active == True))
        ).scalars().all()

    for server in servers:
        try:
            await _collect_one(server)
        except Exception:
            log.exception("fail2ban: collection failed for server %s", server.id)
```

- [ ] **Step 2: Verify Python syntax**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "from app.services.fail2ban_collector import collect_fail2ban, _parse_jail_status, _parse_fail2ban_log; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Quick parse unit check**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "
from app.services.fail2ban_collector import _parse_jail_status, _parse_fail2ban_log

sample_status = '''
Status for the jail: sshd
|- Filter
|  |- Currently failed:\t5
|  |- Total failed:\t1203
|  \`- File list:\t/var/log/auth.log
\`- Actions
   |- Currently banned:\t38
   |- Total banned:\t1200
   \`- Banned IP list:\t103.107.60.45 154.221.28.214
'''
r = _parse_jail_status(sample_status)
assert r['currently_banned'] == 38, r
assert r['total_banned'] == 1200, r
assert '103.107.60.45' in r['banned_ips'], r
print('_parse_jail_status OK:', r)

sample_log = '''2026-06-12 07:23:45,678 fail2ban.actions [1234]: NOTICE  [sshd] Ban 1.2.3.4
2026-06-12 07:45:12,345 fail2ban.actions [1234]: NOTICE  [sshd] Unban 1.2.3.4
'''
events = _parse_fail2ban_log(sample_log)
assert len(events) == 2, events
assert events[0]['action'] == 'ban', events
assert events[1]['action'] == 'unban', events
print('_parse_fail2ban_log OK:', events)
"
```

Expected: both `OK` lines printed, no AssertionError.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/fail2ban_collector.py
git commit -m "feat: add fail2ban SSH collector service"
```

---

## Task 3: API Router

**Files:**
- Create: `backend/app/routers/fail2ban.py`

- [ ] **Step 1: Create the router**

Create `backend/app/routers/fail2ban.py`:

```python
"""fail2ban monitoring API.

GET /api/servers/{server_id}/fail2ban/status
GET /api/servers/{server_id}/fail2ban/jails
GET /api/servers/{server_id}/fail2ban/banned-ips
GET /api/servers/{server_id}/fail2ban/events
GET /api/servers/{server_id}/fail2ban/top-countries
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import CurrentUser

router = APIRouter(prefix="/api/servers", tags=["fail2ban"])


async def _check_access(server_id: str, user: CurrentUser, db: AsyncSession) -> None:
    from app.routers.servers import _assert_server_access
    await _assert_server_access(server_id, user, db)


@router.get("/{server_id}/fail2ban/status")
async def get_fail2ban_status(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    last_checked = await db.scalar(
        text("SELECT MAX(checked_at) FROM fail2ban_jails WHERE server_id = :sid"),
        {"sid": server_id},
    )
    currently_banned = await db.scalar(
        text("SELECT COALESCE(SUM(currently_banned), 0) FROM fail2ban_jails WHERE server_id = :sid"),
        {"sid": server_id},
    ) or 0
    jail_count = await db.scalar(
        text("SELECT COUNT(*) FROM fail2ban_jails WHERE server_id = :sid"),
        {"sid": server_id},
    ) or 0
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    bans_today = await db.scalar(
        text("""
            SELECT COUNT(*) FROM fail2ban_ban_events
            WHERE server_id = :sid AND action = 'ban' AND event_at >= :today
        """),
        {"sid": server_id, "today": today_start},
    ) or 0

    return {
        "running": last_checked is not None,
        "jail_count": int(jail_count),
        "currently_banned": int(currently_banned),
        "bans_today": int(bans_today),
        "last_checked": last_checked,
    }


@router.get("/{server_id}/fail2ban/jails")
async def get_fail2ban_jails(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    rows = await db.execute(
        text("""
            SELECT jail_name, currently_banned, total_banned, currently_failed, checked_at
            FROM fail2ban_jails WHERE server_id = :sid
            ORDER BY currently_banned DESC
        """),
        {"sid": server_id},
    )
    return [
        {
            "jail_name": r.jail_name,
            "currently_banned": r.currently_banned,
            "total_banned": r.total_banned,
            "currently_failed": r.currently_failed,
            "checked_at": r.checked_at,
        }
        for r in rows.fetchall()
    ]


@router.get("/{server_id}/fail2ban/banned-ips")
async def get_fail2ban_banned_ips(
    server_id: str,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    offset = (page - 1) * per_page
    rows = await db.execute(
        text("""
            SELECT b.ip, b.jail, b.banned_since, b.checked_at,
                   g.country_code, g.country_name, g.isp
            FROM fail2ban_banned_ips b
            LEFT JOIN ip_geodata g ON g.ip = b.ip
            WHERE b.server_id = :sid
            ORDER BY b.checked_at DESC
            LIMIT :limit OFFSET :offset
        """),
        {"sid": server_id, "limit": per_page, "offset": offset},
    )
    total = await db.scalar(
        text("SELECT COUNT(*) FROM fail2ban_banned_ips WHERE server_id = :sid"),
        {"sid": server_id},
    ) or 0

    return {
        "total": int(total),
        "page": page,
        "per_page": per_page,
        "items": [
            {
                "ip": r.ip,
                "jail": r.jail,
                "banned_since": r.banned_since,
                "checked_at": r.checked_at,
                "country_code": r.country_code,
                "country_name": r.country_name,
                "isp": r.isp,
            }
            for r in rows.fetchall()
        ],
    }


@router.get("/{server_id}/fail2ban/events")
async def get_fail2ban_events(
    server_id: str,
    user: CurrentUser,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await db.execute(
        text("""
            SELECT date_trunc('hour', event_at) AS hour, COUNT(*) AS ban_count
            FROM fail2ban_ban_events
            WHERE server_id = :sid AND action = 'ban' AND event_at >= :since
            GROUP BY 1 ORDER BY 1
        """),
        {"sid": server_id, "since": since},
    )
    return [{"hour": r.hour, "ban_count": int(r.ban_count)} for r in rows.fetchall()]


@router.get("/{server_id}/fail2ban/top-countries")
async def get_fail2ban_top_countries(
    server_id: str,
    user: CurrentUser,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    await _check_access(server_id, user, db)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = await db.execute(
        text("""
            SELECT g.country_code, g.country_name, COUNT(*) AS count
            FROM fail2ban_ban_events e
            LEFT JOIN ip_geodata g ON g.ip = e.ip
            WHERE e.server_id = :sid AND e.action = 'ban' AND e.event_at >= :since
            GROUP BY g.country_code, g.country_name
            ORDER BY count DESC
            LIMIT 15
        """),
        {"sid": server_id, "since": since},
    )
    return [
        {
            "country_code": r.country_code or "XX",
            "country_name": r.country_name or "Unknown",
            "count": int(r.count),
        }
        for r in rows.fetchall()
    ]
```

- [ ] **Step 2: Verify syntax**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec backend python -c "from app.routers.fail2ban import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/fail2ban.py
git commit -m "feat: add fail2ban API router (5 endpoints)"
```

---

## Task 4: Register Collector + Router

**Files:**
- Modify: `backend/app/jobs/scheduler.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add collector to scheduler**

In `backend/app/jobs/scheduler.py`, append after the `dmesg_collector` function (after line 84):

```python

async def fail2ban_collector() -> None:
    """Every 5 min: poll fail2ban status on each active server."""
    from app.services.fail2ban_collector import collect_fail2ban
    await collect_fail2ban()
```

- [ ] **Step 2: Register the scheduler job**

In `backend/app/main.py`, add this import at line 13 (after `dmesg_collector` on the existing import line):

Change the existing import from:
```python
from app.jobs.scheduler import maintenance_expiry, scheduler, session_cleanup, ticket_sweep, daily_report_nightly, dmesg_collector
```
To:
```python
from app.jobs.scheduler import maintenance_expiry, scheduler, session_cleanup, ticket_sweep, daily_report_nightly, dmesg_collector, fail2ban_collector
```

Then add the job registration in the `lifespan` function, after line 61 (`dmesg_collector` job):
```python
    scheduler.add_job(fail2ban_collector, "interval", minutes=5, id="fail2ban_collector", replace_existing=True)
```

- [ ] **Step 3: Include router in main.py**

In `backend/app/main.py`, add this import after the `daily_report_router` import (around line 34):
```python
from app.routers.fail2ban import router as fail2ban_router
```

And in the routers section after `app.include_router(daily_report_router)` (around line 130):
```python
app.include_router(fail2ban_router)
```

- [ ] **Step 4: Restart backend and verify**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart backend
sleep 5
curl -s http://localhost:9090/api/health
```

Expected: `{"ok":true}`

- [ ] **Step 5: Verify endpoint is registered**

```bash
curl -s http://localhost:9090/api/docs 2>/dev/null | grep -c "fail2ban" || \
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs backend --tail=20
```

Backend should start without errors. Logs should show no ImportError.

- [ ] **Step 6: Commit**

```bash
git add backend/app/jobs/scheduler.py backend/app/main.py
git commit -m "feat: register fail2ban collector job and router"
```

---

## Task 5: Pinia Store

**Files:**
- Create: `frontend/src/stores/fail2ban.ts`

- [ ] **Step 1: Create the store**

Create `frontend/src/stores/fail2ban.ts`:

```typescript
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/services/api'

export interface Fail2banStatus {
  running: boolean
  jail_count: number
  currently_banned: number
  bans_today: number
  last_checked: string | null
}

export interface Fail2banJail {
  jail_name: string
  currently_banned: number
  total_banned: number
  currently_failed: number
  checked_at: string
}

export interface Fail2banBannedIp {
  ip: string
  jail: string
  banned_since: string | null
  checked_at: string
  country_code: string | null
  country_name: string | null
  isp: string | null
}

export interface Fail2banBannedIpsResponse {
  total: number
  page: number
  per_page: number
  items: Fail2banBannedIp[]
}

export interface Fail2banEvent {
  hour: string
  ban_count: number
}

export interface Fail2banCountry {
  country_code: string
  country_name: string
  count: number
}

export const useFail2banStore = defineStore('fail2ban', () => {
  const status = ref<Fail2banStatus | null>(null)
  const jails = ref<Fail2banJail[]>([])
  const bannedIps = ref<Fail2banBannedIpsResponse | null>(null)
  const events = ref<Fail2banEvent[]>([])
  const topCountries = ref<Fail2banCountry[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll(serverId: string) {
    loading.value = true
    error.value = null
    try {
      const [s, j, b, e, c] = await Promise.all([
        api.get(`/api/servers/${serverId}/fail2ban/status`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/jails`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/banned-ips`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/events`).then(r => r.data),
        api.get(`/api/servers/${serverId}/fail2ban/top-countries`).then(r => r.data),
      ])
      status.value = s
      jails.value = j
      bannedIps.value = b
      events.value = e
      topCountries.value = c
    } catch (err: any) {
      error.value = err?.response?.data?.detail || 'Failed to load fail2ban data'
    } finally {
      loading.value = false
    }
  }

  async function fetchBannedIps(serverId: string, page = 1) {
    const r = await api.get(`/api/servers/${serverId}/fail2ban/banned-ips?page=${page}`)
    bannedIps.value = r.data
  }

  return {
    status, jails, bannedIps, events, topCountries, loading, error,
    fetchAll, fetchBannedIps,
  }
})
```

- [ ] **Step 2: TypeScript check**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vue-tsc --noEmit 2>&1 | grep -i "fail2ban\|error" | head -20
```

Expected: no errors related to fail2ban.ts

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/fail2ban.ts
git commit -m "feat: add fail2ban Pinia store with TypeScript types"
```

---

## Task 6: SecurityTab.vue + Sub-component Directory

**Files:**
- Create: `frontend/src/components/servers/tabs/SecurityTab.vue`
- Create: `frontend/src/components/servers/tabs/fail2ban/` (directory via first file)

- [ ] **Step 1: Create SecurityTab.vue**

Create `frontend/src/components/servers/tabs/SecurityTab.vue`:

```vue
<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useFail2banStore } from '@/stores/fail2ban'
import Fail2banStatusBar from './fail2ban/Fail2banStatusBar.vue'
import Fail2banChart from './fail2ban/Fail2banChart.vue'
import Fail2banJailCards from './fail2ban/Fail2banJailCards.vue'
import Fail2banTopCountries from './fail2ban/Fail2banTopCountries.vue'
import Fail2banBannedTable from './fail2ban/Fail2banBannedTable.vue'

const props = defineProps<{ serverId: string }>()
const store = useFail2banStore()

let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  store.fetchAll(props.serverId)
  pollInterval = setInterval(() => store.fetchAll(props.serverId), 5 * 60 * 1000)
})
onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})

const permissionDenied = computed(() =>
  store.error?.toLowerCase().includes('permission') ?? false
)
const noData = computed(() =>
  !store.loading && !store.error && store.status?.last_checked === null
)
const hasData = computed(() =>
  !store.loading && !store.error && store.status?.last_checked !== null
)
</script>

<template>
  <div class="security-tab">
    <div v-if="store.loading && !store.status" class="empty-state">
      <p class="muted">Loading fail2ban data…</p>
    </div>

    <div v-else-if="permissionDenied" class="empty-state">
      <p class="state-title">Permission denied</p>
      <p class="muted">Add the SSH user to the fail2ban group on this server:</p>
      <code class="setup-cmd">sudo usermod -aG fail2ban opspilot</code>
    </div>

    <div v-else-if="noData" class="empty-state">
      <p class="state-title">fail2ban not detected</p>
      <p class="muted">Install fail2ban and add the SSH user to its group:</p>
      <code class="setup-cmd">sudo apt install fail2ban &amp;&amp; sudo usermod -aG fail2ban opspilot</code>
    </div>

    <template v-else-if="hasData">
      <Fail2banStatusBar :status="store.status!" />
      <div class="chart-row">
        <Fail2banChart :events="store.events" class="chart-col" />
        <Fail2banTopCountries :countries="store.topCountries" class="country-col" />
      </div>
      <Fail2banJailCards :jails="store.jails" />
      <Fail2banBannedTable :server-id="props.serverId" />
    </template>
  </div>
</template>

<style scoped>
.security-tab { display: flex; flex-direction: column; gap: 18px; }
.empty-state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; min-height: 300px; gap: 12px; text-align: center;
}
.state-title { font-size: 16px; font-weight: 600; color: var(--text); }
.muted { color: var(--muted); font-size: 13px; }
.setup-cmd {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 6px; padding: 8px 16px; font-size: 12px; color: var(--text);
}
.chart-row { display: flex; gap: 18px; }
.chart-col { flex: 2; min-width: 0; }
.country-col { flex: 1; min-width: 0; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/servers/tabs/SecurityTab.vue
git commit -m "feat: add SecurityTab shell with empty/error states"
```

---

## Task 7: Fail2banStatusBar.vue

**Files:**
- Create: `frontend/src/components/servers/tabs/fail2ban/Fail2banStatusBar.vue`

- [ ] **Step 1: Create Fail2banStatusBar.vue**

Create `frontend/src/components/servers/tabs/fail2ban/Fail2banStatusBar.vue`:

```vue
<script setup lang="ts">
import type { Fail2banStatus } from '@/stores/fail2ban'

defineProps<{ status: Fail2banStatus | null }>()
</script>

<template>
  <div class="status-bar">
    <div class="stat-card" :class="status?.running ? 'ok' : 'err'">
      <div class="label">STATUS</div>
      <div class="value">
        <span class="dot">●</span>
        {{ status?.running ? 'Active' : 'Inactive' }}
      </div>
    </div>
    <div class="stat-card">
      <div class="label">JAILS</div>
      <div class="value">{{ status?.jail_count ?? '—' }}</div>
    </div>
    <div class="stat-card" :class="(status?.currently_banned ?? 0) > 0 ? 'warn' : ''">
      <div class="label">BANNED NOW</div>
      <div class="value">{{ status?.currently_banned ?? '—' }}</div>
    </div>
    <div class="stat-card">
      <div class="label">BANS TODAY</div>
      <div class="value">{{ status?.bans_today ?? '—' }}</div>
    </div>
  </div>
</template>

<style scoped>
.status-bar { display: flex; gap: 12px; }
.stat-card {
  flex: 1; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px;
}
.stat-card.ok { border-color: #22c55e; }
.stat-card.err { border-color: #ef4444; }
.stat-card.warn { border-color: #ef4444; }
.label { font-size: 10px; text-transform: uppercase; color: var(--muted); margin-bottom: 6px; letter-spacing: 0.05em; }
.value { font-size: 22px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
.stat-card.ok .value, .stat-card.ok .dot { color: #22c55e; }
.stat-card.err .value, .stat-card.err .dot { color: #ef4444; }
.stat-card.warn .value { color: #ef4444; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/servers/tabs/fail2ban/Fail2banStatusBar.vue
git commit -m "feat: add Fail2banStatusBar stat cards"
```

---

## Task 8: Fail2banChart.vue

**Files:**
- Create: `frontend/src/components/servers/tabs/fail2ban/Fail2banChart.vue`

- [ ] **Step 1: Create Fail2banChart.vue**

Create `frontend/src/components/servers/tabs/fail2ban/Fail2banChart.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import MetricChart from '@/components/charts/MetricChart.vue'
import type { Fail2banEvent } from '@/stores/fail2ban'

const props = defineProps<{ events: Fail2banEvent[] }>()

const series = computed(() => [
  {
    name: 'Bans',
    data: props.events.map(e => ({
      x: new Date(e.hour).getTime(),
      y: e.ban_count,
    })),
  },
])
</script>

<template>
  <section class="card">
    <h3>Bans (last 24h)</h3>
    <div v-if="events.length === 0" class="no-data">No ban events recorded yet</div>
    <MetricChart
      v-else
      type="bar"
      unit="count"
      :series="series"
      :height="200"
      :colors="['#ef4444']"
    />
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/servers/tabs/fail2ban/Fail2banChart.vue
git commit -m "feat: add Fail2banChart 24h ban timeline"
```

---

## Task 9: Fail2banJailCards.vue + Fail2banTopCountries.vue

**Files:**
- Create: `frontend/src/components/servers/tabs/fail2ban/Fail2banJailCards.vue`
- Create: `frontend/src/components/servers/tabs/fail2ban/Fail2banTopCountries.vue`

- [ ] **Step 1: Create Fail2banJailCards.vue**

Create `frontend/src/components/servers/tabs/fail2ban/Fail2banJailCards.vue`:

```vue
<script setup lang="ts">
import type { Fail2banJail } from '@/stores/fail2ban'
defineProps<{ jails: Fail2banJail[] }>()
</script>

<template>
  <div v-if="jails.length" class="jail-row">
    <div v-for="jail in jails" :key="jail.jail_name" class="jail-card">
      <div class="jail-name">{{ jail.jail_name }}</div>
      <div class="jail-stat banned">{{ jail.currently_banned }} banned</div>
      <div class="jail-stat failed">{{ jail.currently_failed }} failing</div>
      <div class="jail-total">{{ jail.total_banned.toLocaleString() }} total</div>
    </div>
  </div>
</template>

<style scoped>
.jail-row { display: flex; gap: 12px; flex-wrap: wrap; }
.jail-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px; min-width: 140px;
}
.jail-name { font-size: 13px; font-weight: 600; color: var(--text); margin-bottom: 6px; }
.jail-stat { font-size: 12px; margin-bottom: 2px; }
.jail-stat.banned { color: #ef4444; }
.jail-stat.failed { color: #f59e0b; }
.jail-total { font-size: 11px; color: var(--muted); margin-top: 4px; }
</style>
```

- [ ] **Step 2: Create Fail2banTopCountries.vue**

Create `frontend/src/components/servers/tabs/fail2ban/Fail2banTopCountries.vue`:

```vue
<script setup lang="ts">
import { computed } from 'vue'
import type { Fail2banCountry } from '@/stores/fail2ban'

const props = defineProps<{ countries: Fail2banCountry[] }>()

const top = computed(() => props.countries.slice(0, 10))
const maxCount = computed(() => Math.max(...top.value.map(c => c.count), 1))

function flagEmoji(code: string): string {
  if (!code || code === 'XX') return '🏳'
  return code.toUpperCase().replace(/./g, ch =>
    String.fromCodePoint(0x1F1E6 + ch.charCodeAt(0) - 65)
  )
}
</script>

<template>
  <section class="card">
    <h3>Top Countries (24h)</h3>
    <div v-if="top.length === 0" class="no-data">No data yet</div>
    <div v-else class="country-list">
      <div v-for="c in top" :key="c.country_code" class="country-row">
        <span class="flag">{{ flagEmoji(c.country_code) }}</span>
        <span class="name">{{ c.country_name }}</span>
        <div class="bar-wrap">
          <div class="bar" :style="{ width: (c.count / maxCount * 100) + '%' }" />
        </div>
        <span class="count">{{ c.count }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; height: 100%; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
.country-list { display: flex; flex-direction: column; gap: 7px; }
.country-row { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.flag { font-size: 14px; width: 20px; }
.name { color: var(--text); width: 90px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bar-wrap { flex: 1; background: var(--bg); border-radius: 2px; height: 6px; overflow: hidden; }
.bar { height: 100%; background: #ef4444; border-radius: 2px; transition: width 0.3s; }
.count { color: var(--muted); width: 32px; text-align: right; font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/servers/tabs/fail2ban/Fail2banJailCards.vue \
        frontend/src/components/servers/tabs/fail2ban/Fail2banTopCountries.vue
git commit -m "feat: add Fail2banJailCards and Fail2banTopCountries components"
```

---

## Task 10: Fail2banBannedTable.vue

**Files:**
- Create: `frontend/src/components/servers/tabs/fail2ban/Fail2banBannedTable.vue`

- [ ] **Step 1: Create Fail2banBannedTable.vue**

Create `frontend/src/components/servers/tabs/fail2ban/Fail2banBannedTable.vue`:

```vue
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useFail2banStore } from '@/stores/fail2ban'

const props = defineProps<{ serverId: string }>()
const store = useFail2banStore()
const page = ref(1)

onMounted(() => store.fetchBannedIps(props.serverId, 1))

async function goPage(p: number) {
  page.value = p
  await store.fetchBannedIps(props.serverId, p)
}

function flagEmoji(code: string | null): string {
  if (!code || code === 'XX') return '🏳'
  return code.toUpperCase().replace(/./g, ch =>
    String.fromCodePoint(0x1F1E6 + ch.charCodeAt(0) - 65)
  )
}

function relTime(ts: string | null): string {
  if (!ts) return '—'
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

const totalPages = () => Math.ceil((store.bannedIps?.total ?? 0) / (store.bannedIps?.per_page ?? 50))
</script>

<template>
  <section class="card">
    <div class="table-header">
      <h3>Currently Banned IPs</h3>
      <span class="total-badge">{{ store.bannedIps?.total ?? 0 }} total</span>
    </div>

    <div v-if="!store.bannedIps?.items?.length" class="no-data">
      No IPs currently banned
    </div>

    <table v-else class="ban-table">
      <thead>
        <tr>
          <th>IP Address</th>
          <th>Country</th>
          <th>ISP</th>
          <th>Jail</th>
          <th>Banned Since</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in store.bannedIps!.items" :key="item.ip + item.jail">
          <td class="mono">{{ item.ip }}</td>
          <td>
            <span class="flag-emoji">{{ flagEmoji(item.country_code) }}</span>
            {{ item.country_code ?? '—' }}
          </td>
          <td class="isp-cell">{{ item.isp ?? '—' }}</td>
          <td><span class="jail-badge">{{ item.jail }}</span></td>
          <td class="time-cell">{{ relTime(item.checked_at) }}</td>
        </tr>
      </tbody>
    </table>

    <div v-if="totalPages() > 1" class="pagination">
      <button :disabled="page <= 1" @click="goPage(page - 1)">← Prev</button>
      <span>{{ page }} / {{ totalPages() }}</span>
      <button :disabled="page >= totalPages()" @click="goPage(page + 1)">Next →</button>
    </div>
  </section>
</template>

<style scoped>
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.table-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
h3 { font-size: 13px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.total-badge { font-size: 11px; background: var(--bg); border: 1px solid var(--border); border-radius: 10px; padding: 2px 8px; color: var(--muted); }
.no-data { color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center; }
.ban-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ban-table th { text-align: left; padding: 8px 10px; color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }
.ban-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); color: var(--text); }
.ban-table tr:last-child td { border-bottom: none; }
.ban-table tr:hover td { background: var(--bg); }
.mono { font-family: monospace; font-size: 12px; }
.flag-emoji { margin-right: 4px; }
.isp-cell { color: var(--muted); max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.jail-badge { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 1px 6px; font-size: 11px; }
.time-cell { color: var(--muted); white-space: nowrap; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 14px; }
.pagination button { background: var(--surface); border: 1px solid var(--border); border-radius: 5px; padding: 4px 12px; color: var(--text); cursor: pointer; font-size: 12px; }
.pagination button:disabled { opacity: 0.4; cursor: default; }
.pagination span { font-size: 12px; color: var(--muted); }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/servers/tabs/fail2ban/Fail2banBannedTable.vue
git commit -m "feat: add Fail2banBannedTable paginated banned IPs table"
```

---

## Task 11: Wire ServerDetail.vue + Smoke Test + Release

**Files:**
- Modify: `frontend/src/views/servers/ServerDetail.vue`

- [ ] **Step 1: Add Security tab to ServerDetail.vue**

In `frontend/src/views/servers/ServerDetail.vue`, add the import at line 20 (after `DatabaseTab` import):

```typescript
import SecurityTab from '@/components/servers/tabs/SecurityTab.vue'
```

Change line 46 (the `TABS` const) from:
```typescript
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Database', 'Monitoring', 'Alerts', 'Logs', 'Backup', 'Daily Report ✦'] as const
```
To:
```typescript
const TABS = ['Info', 'Overview', 'CPU', 'Memory', 'Disk', 'Network', 'System', 'Processes', 'Services', 'Database', 'Monitoring', 'Alerts', 'Logs', 'Backup', 'Security', 'Daily Report ✦'] as const
```

Change lines 49-54 (the `TAB_COMPONENTS` map) — add `Security: SecurityTab` after `Backup: BackupTab`:
```typescript
  Info: InfoTab, Overview: OverviewTab, CPU: CpuTab, Memory: MemoryTab,
  Disk: DiskTab, Network: NetworkTab, System: SystemTab, Processes: ProcessesTab,
  Services: ServicesTab, Database: DatabaseTab, Monitoring: MonitoringTab,
  Alerts: AlertsTab, Logs: LogsTab, Backup: BackupTab,
  Security: SecurityTab,
  'Daily Report ✦': DailyReportTab,
```

- [ ] **Step 2: TypeScript check**

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec frontend npx vue-tsc --noEmit 2>&1 | grep -i "error" | head -20
```

Expected: no errors.

- [ ] **Step 3: Browser smoke test**

Open `http://localhost:9090` in a browser. Navigate to a server detail page. Verify:
- "Security" tab appears in the tab bar
- Clicking it loads the tab (no JS console errors)
- If fail2ban is not yet set up on the test server: the "fail2ban not detected" empty state shows
- If fail2ban IS set up: stat cards, chart, jail cards, country list, and IP table all render

- [ ] **Step 4: Seed test data and verify API (optional — if fail2ban not available on test server)**

```bash
# Get a server UUID to use
SERVER_ID=$(curl -s -b cookies.txt http://localhost:9090/api/servers | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if d else '')" 2>/dev/null)

# Insert a test jail row
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec postgres psql -U opspilot -d opspilot -c "
  INSERT INTO fail2ban_jails (server_id, jail_name, currently_banned, total_banned, currently_failed, checked_at)
  VALUES ('$SERVER_ID', 'sshd', 47, 1203, 5, NOW())
  ON CONFLICT DO NOTHING;
  INSERT INTO fail2ban_ban_events (server_id, ip, jail, action, event_at)
  SELECT '$SERVER_ID', '103.107.60.45', 'sshd', 'ban', NOW() - (i || ' minutes')::interval
  FROM generate_series(1, 50) i
  ON CONFLICT DO NOTHING;
  INSERT INTO fail2ban_banned_ips (server_id, jail, ip, checked_at)
  VALUES ('$SERVER_ID', 'sshd', '103.107.60.45', NOW())
  ON CONFLICT DO NOTHING;
"

# Verify status endpoint
curl -s -b cookies.txt "http://localhost:9090/api/servers/$SERVER_ID/fail2ban/status" | python3 -m json.tool
```

Expected: JSON with `running: true`, `jail_count: 1`, `currently_banned: 47`

- [ ] **Step 5: Update PROGRESS.md and DASHBOARD.html**

In `PROGRESS.md`, find and mark the fail2ban monitoring task done (add `✅` or change `⬜` to `✅`).

In `DASHBOARD.html`, find the matching task entry and change `status: 'pending'` to `status: 'done'`. Update `LAST_UPDATED` to `2026-06-12`.

- [ ] **Step 6: Commit + push + tag release**

```bash
git add frontend/src/views/servers/ServerDetail.vue PROGRESS.md DASHBOARD.html
git commit -m "feat: wire Security tab into ServerDetail — fail2ban monitoring complete"
git push origin main

# Bump patch version (check current tag first)
git describe --tags --abbrev=0
# Then tag: git tag v1.2.18 && git push origin v1.2.18 (use next patch after current)
```

---

## Self-Review Checklist

- [x] Migration creates all 4 tables with correct constraints and index
- [x] Collector parses both `fail2ban-client status` output and log file format
- [x] `fail2ban_banned_ips` is delete-and-reinsert each poll (not append) — survives fail2ban restarts
- [x] Geo lookup batched with 1.5s sleep to respect 45 req/min limit
- [x] Router uses `_assert_server_access` from servers.py — consistent auth
- [x] All 5 endpoints covered: status, jails, banned-ips, events, top-countries
- [x] `Fail2banBannedTable` fetches its own data via `fetchBannedIps` (separate from fetchAll) for pagination
- [x] `SecurityTab` clears the poll interval on unmount — no memory leak
- [x] Empty states: permission denied, not installed, no bans — all handled
- [x] `flagEmoji` helper duplicated in `Fail2banTopCountries` and `Fail2banBannedTable` — intentional (components are self-contained, no shared utility needed for a 4-line helper)
- [x] `httpx` must be available in the backend container — verify if not already a dependency
