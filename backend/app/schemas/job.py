"""Schemas for Phase 9 — Unified Job Monitoring (spec 06).

The MonitoredJob system unifies cron jobs and backup jobs under a single
model with a flexible schedule field (cron expression) and a shared grace
period mechanism.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

# Grace period options per spec §5.2 (up to 2h).
_VALID_GRACE = {5, 10, 15, 30, 60, 120, 240}


def _is_valid_cron(expr: str) -> bool:
    from app.services.cron_schedule import is_valid_cron
    return is_valid_cron(expr)


# ── Job Create ──────────────────────────────────────────────────────────────


class JobCreate(BaseModel):
    server_id: UUID
    name: str
    schedule: str = "0 2 * * *"
    grace_period_min: int = 10
    description: str | None = None

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


# ── Job Update ──────────────────────────────────────────────────────────────


class JobUpdate(BaseModel):
    name: str | None = None
    schedule: str | None = None
    grace_period_min: int | None = None
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


# ── Job Response ────────────────────────────────────────────────────────────


class JobOut(BaseModel):
    id: str
    server_id: str
    server_name: str
    name: str
    description: str | None
    schedule: str
    grace_period_min: int
    ping_url: str
    status: str
    last_ping_at: datetime | None
    start_ping_at: datetime | None
    last_duration_sec: int | None
    last_size_bytes: int | None
    last_size_formatted: str | None
    last_files_count: int | None
    last_exit_code: int | None
    last_label: str | None
    next_expected_at: datetime | None


# ── Job Run Response ────────────────────────────────────────────────────────


class JobRunOut(BaseModel):
    id: str
    ran_at: datetime
    outcome: str
    duration_sec: int | None
    size_bytes: int | None
    size_formatted: str | None
    files_count: int | None
    exit_code: int | None
    label: str | None = None
    started_at: datetime | None = None


class TodayRunOut(JobRunOut):
    job_id: str
    job_name: str
    server_name: str
