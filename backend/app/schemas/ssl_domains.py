"""Schemas for SSL & Domain Monitoring (spec 07)."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator


def _normalize_domain(v: str) -> str:
    v = v.strip().lower()
    for prefix in ("https://", "http://"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    if v.startswith("www."):
        v = v[len("www."):]
    v = v.split("/")[0].strip()
    if not v:
        raise ValueError("Domain name is required")
    if len(v) > 253:
        raise ValueError("Domain name is too long")
    if " " in v or "." not in v:
        raise ValueError("Enter a valid domain (e.g. example.com)")
    return v


def _validate_thresholds(warn: int, crit: int) -> None:
    if not (1 <= warn <= 365):
        raise ValueError("Warning threshold must be between 1 and 365 days")
    if not (1 <= crit <= 365):
        raise ValueError("Critical threshold must be between 1 and 365 days")
    if crit >= warn:
        raise ValueError("Critical threshold must be lower than warning threshold")


# ── Domain ──────────────────────────────────────────────────────────────────

class DomainCreate(BaseModel):
    org_id: UUID
    domain: str
    warn_days: int = 60
    critical_days: int = 30

    @field_validator("domain")
    @classmethod
    def _domain(cls, v: str) -> str:
        return _normalize_domain(v)

    @model_validator(mode="after")
    def _thresholds(self):
        _validate_thresholds(self.warn_days, self.critical_days)
        return self


class DomainUpdate(BaseModel):
    warn_days: int | None = None
    critical_days: int | None = None


class DomainOut(BaseModel):
    id: UUID
    domain: str
    registrar: str | None
    expiry_date: datetime | None
    days_remaining: int | None
    warn_days: int
    critical_days: int
    last_checked: datetime | None
    status: str | None

    model_config = {"from_attributes": True}


# ── SSL Cert ──────────────────────────────────────────────────────────────────

class SSLCertCreate(BaseModel):
    domain_id: UUID
    port: int = 443
    warn_days: int = 30
    critical_days: int = 7

    @field_validator("port")
    @classmethod
    def _port(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("Enter a valid port number")
        return v

    @model_validator(mode="after")
    def _thresholds(self):
        _validate_thresholds(self.warn_days, self.critical_days)
        return self


class SSLCertUpdate(BaseModel):
    port: int | None = None
    warn_days: int | None = None
    critical_days: int | None = None


class SSLCertOut(BaseModel):
    id: UUID
    domain_id: UUID
    domain: str | None = None
    port: int
    issuer: str | None
    expiry_date: datetime | None
    days_remaining: int | None
    warn_days: int
    critical_days: int
    last_checked: datetime | None
    status: str | None

    model_config = {"from_attributes": True}


class ServiceSslOut(BaseModel):
    id: UUID
    name: str
    url: str | None
    ssl_status: str | None
    ssl_expiry_date: datetime | None
    ssl_days_remaining: int | None
    ssl_issuer: str | None
    ssl_last_checked: datetime | None
    ssl_warn_days: int
    ssl_critical_days: int

    model_config = {"from_attributes": True}


class SSLDomainsResponse(BaseModel):
    domains: list[DomainOut]
    ssl_certs: list[SSLCertOut]
    service_ssl: list[ServiceSslOut]
