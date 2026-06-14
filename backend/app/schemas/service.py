"""Pydantic schemas for Service Monitoring (spec 06)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

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
    ssl_warn_days: int = 30
    ssl_critical_days: int = 7
    expected_keyword: str | None = None
    forbidden_keywords_enabled: bool = True

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

    @model_validator(mode="after")
    def ssl_thresholds_valid(self) -> "ServiceCreate":
        if not (1 <= self.ssl_warn_days <= 365):
            raise ValueError("ssl_warn_days must be 1–365")
        if not (1 <= self.ssl_critical_days < self.ssl_warn_days):
            raise ValueError("ssl_critical_days must be ≥ 1 and less than ssl_warn_days")
        return self

    @field_validator("expected_keyword")
    @classmethod
    def expected_keyword_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) == 0:
            return None
        if len(v) > 200:
            raise ValueError("Expected keyword must be ≤ 200 characters")
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
    ssl_warn_days: int | None = None
    ssl_critical_days: int | None = None
    expected_keyword: str | None = None
    forbidden_keywords_enabled: bool | None = None

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

    @model_validator(mode="after")
    def ssl_thresholds_valid(self) -> "ServiceUpdate":
        warn = self.ssl_warn_days
        crit = self.ssl_critical_days
        if warn is not None and not (1 <= warn <= 365):
            raise ValueError("ssl_warn_days must be 1–365")
        if crit is not None and not (1 <= crit):
            raise ValueError("ssl_critical_days must be ≥ 1")
        if warn is not None and crit is not None and crit >= warn:
            raise ValueError("ssl_critical_days must be less than ssl_warn_days")
        return self

    @field_validator("expected_keyword")
    @classmethod
    def expected_keyword_valid(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) == 0:
            return None
        if len(v) > 200:
            raise ValueError("Expected keyword must be ≤ 200 characters")
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
    ssl_enabled: bool
    ssl_warn_days: int
    ssl_critical_days: int
    ssl_expiry_date: datetime | None
    ssl_days_remaining: int | None
    ssl_status: str | None
    ssl_issuer: str | None
    ssl_last_checked: datetime | None
    expected_keyword: str | None
    forbidden_keywords_enabled: bool
