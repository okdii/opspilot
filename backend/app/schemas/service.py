"""Pydantic schemas for Service Monitoring (spec 06)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator

_VALID_TYPES = {"http", "tcp", "db"}
_VALID_INTERVALS = {30, 60, 120, 300, 600}
_VALID_TIMEOUTS = {3, 5, 10, 30}


class ServiceCreate(BaseModel):
    server_id: UUID
    name: str
    type: str
    url: str | None = None
    port: int | None = None
    expected_status: int | None = None
    interval_sec: int = 60
    timeout_sec: int = 5
    is_active: bool = True
    is_public: bool = False
    ignore_ssl_errors: bool = False

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Service name must be 2–100 characters")
        return v

    @field_validator("type")
    @classmethod
    def type_valid(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _VALID_TYPES:
            raise ValueError("Type must be one of: http, tcp, db")
        return v

    @field_validator("interval_sec")
    @classmethod
    def interval_valid(cls, v: int) -> int:
        if v not in _VALID_INTERVALS:
            raise ValueError("Interval must be one of: 30, 60, 120, 300, 600 seconds")
        return v

    @field_validator("timeout_sec")
    @classmethod
    def timeout_valid(cls, v: int) -> int:
        if v not in _VALID_TIMEOUTS:
            raise ValueError("Timeout must be one of: 3, 5, 10, 30 seconds")
        return v

    @field_validator("port")
    @classmethod
    def port_valid(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (1 <= v <= 65535):
            raise ValueError("Port must be 1–65535")
        return v

    @field_validator("expected_status")
    @classmethod
    def expected_status_valid(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (100 <= v <= 599):
            raise ValueError("Expected status must be 100–599")
        return v


class ServiceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    port: int | None = None
    expected_status: int | None = None
    interval_sec: int | None = None
    timeout_sec: int | None = None
    is_active: bool | None = None
    is_public: bool | None = None
    ignore_ssl_errors: bool | None = None

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not (2 <= len(v) <= 100):
            raise ValueError("Service name must be 2–100 characters")
        return v

    @field_validator("interval_sec")
    @classmethod
    def interval_valid(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v not in _VALID_INTERVALS:
            raise ValueError("Interval must be one of: 30, 60, 120, 300, 600 seconds")
        return v

    @field_validator("timeout_sec")
    @classmethod
    def timeout_valid(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v not in _VALID_TIMEOUTS:
            raise ValueError("Timeout must be one of: 3, 5, 10, 30 seconds")
        return v

    @field_validator("port")
    @classmethod
    def port_valid(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (1 <= v <= 65535):
            raise ValueError("Port must be 1–65535")
        return v

    @field_validator("expected_status")
    @classmethod
    def expected_status_valid(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if not (100 <= v <= 599):
            raise ValueError("Expected status must be 100–599")
        return v


class ServiceOut(BaseModel):
    id: str
    server_id: str
    server_name: str
    name: str
    type: str
    url: str | None
    port: int | None
    expected_status: int | None
    interval_sec: int
    timeout_sec: int
    is_active: bool
    is_public: bool
    ignore_ssl_errors: bool
    last_status: str | None
    last_checked: datetime | None
    consecutive_failures: int
    uptime_24h: float | None
    uptime_7d: float | None
    avg_response_ms_24h: int | None
    open_incident_id: str | None
