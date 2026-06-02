from datetime import datetime

from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    instance_name: str
    base_url: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_encryption: str
    smtp_username: str | None
    smtp_from_address: str | None
    smtp_recipients: str | None
    smtp_has_password: bool
    metrics_retention_days: int
    logs_retention_days: int
    service_checks_retention_days: int
    alerts_retention_days: int


class SettingsPatch(BaseModel):
    instance_name: str | None = None
    base_url: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_encryption: str | None = None  # none | tls | ssl
    smtp_username: str | None = None
    smtp_password: str | None = None  # plaintext in; encrypted at rest; blank/None keeps existing
    smtp_from_address: str | None = None
    smtp_recipients: str | None = None
    metrics_retention_days: int | None = Field(default=None, ge=7, le=365)
    logs_retention_days: int | None = Field(default=None, ge=7, le=365)
    service_checks_retention_days: int | None = Field(default=None, ge=30, le=365)
    alerts_retention_days: int | None = Field(default=None, ge=30, le=730)


class SessionResponse(BaseModel):
    jti: str
    is_current: bool
    ip_address: str | None
    user_agent: str | None
    issued_at: datetime
    expires_at: datetime
