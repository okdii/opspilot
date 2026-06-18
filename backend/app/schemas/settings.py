from datetime import datetime

from pydantic import BaseModel, Field, field_validator


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
    smtp_enabled: bool
    metrics_retention_days: int
    logs_retention_days: int
    service_checks_retention_days: int
    alerts_retention_days: int
    timezone: str
    discord_webhook_url: str | None
    discord_enabled: bool
    auto_response_enabled: bool
    ai_provider: str
    ai_model: str
    ai_has_key: bool
    ai_base_url: str | None
    abuseipdb_enabled: bool
    abuseipdb_has_key: bool


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
    smtp_enabled: bool | None = None
    metrics_retention_days: int | None = Field(default=None, ge=7, le=365)
    logs_retention_days: int | None = Field(default=None, ge=7, le=365)
    service_checks_retention_days: int | None = Field(default=None, ge=30, le=365)
    alerts_retention_days: int | None = Field(default=None, ge=30, le=730)
    timezone: str | None = None
    discord_webhook_url: str | None = None
    discord_enabled: bool | None = None
    auto_response_enabled: bool | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key: str | None = None  # plaintext in; encrypted at rest; blank/None keeps existing
    ai_base_url: str | None = None
    abuseipdb_enabled: bool | None = None
    abuseipdb_api_key: str | None = None  # plaintext in; encrypted at rest; blank/None keeps existing

    @field_validator("timezone")
    @classmethod
    def valid_iana_tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            raise ValueError(f"'{v}' is not a valid IANA timezone name")
        return v


class SessionResponse(BaseModel):
    jti: str
    is_current: bool
    ip_address: str | None
    user_agent: str | None
    issued_at: datetime
    expires_at: datetime


class InviteCreate(BaseModel):
    email: str
    org_id: str
    role: str  # operator | viewer


class OrgAssignmentCreate(BaseModel):
    org_id: str
    role: str  # operator | viewer


class RotateWriterPassword(BaseModel):
    new_password: str = Field(min_length=16)

    @field_validator("new_password")
    @classmethod
    def no_spaces(cls, v: str) -> str:
        if " " in v:
            raise ValueError("Password must not contain spaces.")
        return v
