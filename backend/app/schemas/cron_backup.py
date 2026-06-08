"""Schemas for Phase 7 — Cron & Backup Job Monitoring (spec 09).

NOTE: the persisted models (app/models/other.py) differ from the spec text in a
few field names. We bind to the real models:
  * CronJob   has `schedule` (cron expr) + `grace_period_min`.
  * BackupJob has `expected_interval_hours` (no cron schedule) + `created_at`,
    and stores exit code inside `last_status_text`/run rows (BackupRun.exit_code).
The backup watchdog therefore derives its window from `expected_interval_hours`
+ a fixed grace, while cron uses the cron expression + per-job grace.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

# Grace period options per spec §5.2 (cron up to 2h).
_VALID_GRACE = {5, 10, 15, 30, 60, 120, 240}


def _is_valid_cron(expr: str) -> bool:
    from app.services.cron_schedule import is_valid_cron
    return is_valid_cron(expr)


# ── Cron Jobs ──────────────────────────────────────────────────────────────

class CronJobCreate(BaseModel):
    server_id: UUID
    name: str
    schedule: str = "0 * * * *"
    grace_period_min: int = 10

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Job name must be 2–100 characters")
        return v

    @field_validator("schedule")
    @classmethod
    def schedule_valid(cls, v: str) -> str:
        v = v.strip()
        if not _is_valid_cron(v):
            raise ValueError("Invalid cron expression")
        return v

    @field_validator("grace_period_min")
    @classmethod
    def grace_valid(cls, v: int) -> int:
        if v not in _VALID_GRACE:
            raise ValueError("Invalid grace period")
        return v


class CronJobUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    grace_period_min: int | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Job name must be 2–100 characters")
        return v

    @field_validator("schedule")
    @classmethod
    def schedule_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not _is_valid_cron(v):
            raise ValueError("Invalid cron expression")
        return v

    @field_validator("grace_period_min")
    @classmethod
    def grace_valid(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v not in _VALID_GRACE:
            raise ValueError("Invalid grace period")
        return v


class CronJobOut(BaseModel):
    id: str
    server_id: str
    server_name: str
    name: str
    schedule: str
    grace_period_min: int
    ping_url: str
    last_ping_at: datetime | None
    start_ping_at: datetime | None
    last_duration_sec: int | None
    status: str
    next_expected_at: datetime | None


class CronRunOut(BaseModel):
    id: str
    ran_at: datetime
    duration_sec: int | None
    outcome: str


# ── Backup Jobs ────────────────────────────────────────────────────────────

class BackupJobCreate(BaseModel):
    server_id: UUID
    name: str
    expected_interval_hours: int = 24
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Job name must be 2–100 characters")
        return v

    @field_validator("expected_interval_hours")
    @classmethod
    def interval_valid(cls, v: int) -> int:
        if not (1 <= v <= 24 * 30):
            raise ValueError("Expected interval must be 1–720 hours")
        return v


class BackupJobUpdate(BaseModel):
    name: str | None = None
    expected_interval_hours: int | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Job name must be 2–100 characters")
        return v

    @field_validator("expected_interval_hours")
    @classmethod
    def interval_valid(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not (1 <= v <= 24 * 30):
            raise ValueError("Expected interval must be 1–720 hours")
        return v


class BackupJobOut(BaseModel):
    id: str
    server_id: str
    server_name: str
    name: str
    description: str | None
    expected_interval_hours: int
    ping_url: str
    last_ping_at: datetime | None
    last_size_bytes: int | None
    last_size_formatted: str | None
    last_status_text: str | None
    previous_size_bytes: int | None
    last_files_count: int | None = None
    status: str
    next_expected_at: datetime | None


class BackupRunOut(BaseModel):
    id: str
    ran_at: datetime
    size_bytes: int | None
    size_formatted: str | None
    exit_code: int | None
    outcome: str
    files_count: int | None = None
