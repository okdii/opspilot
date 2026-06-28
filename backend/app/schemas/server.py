from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, field_validator


class ServerCreate(BaseModel):
    name: str
    host: str
    ssh_port: int = 22
    ssh_user: str
    ssh_auth_type: str
    ssh_key: str | None = None
    ssh_password: str | None = None
    tags: list[str] = []

    @field_validator("name")
    @classmethod
    def name_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Server name is required")
        if len(v) > 80:
            raise ValueError("Name is too long")
        return v

    @field_validator("host")
    @classmethod
    def host_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("IP address or hostname is required")
        if " " in v:
            raise ValueError("Enter a valid IP address or hostname")
        return v

    @field_validator("ssh_port")
    @classmethod
    def port_valid(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError("Enter a valid port number")
        return v

    @field_validator("ssh_user")
    @classmethod
    def ssh_user_valid(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("SSH username is required")
        return v

    @field_validator("ssh_auth_type")
    @classmethod
    def auth_type_valid(cls, v: str) -> str:
        if v not in ("key", "password"):
            raise ValueError("SSH auth type must be 'key' or 'password'")
        return v

    @field_validator("tags")
    @classmethod
    def tags_valid(cls, v: list[str]) -> list[str]:
        if len(v) > 10:
            raise ValueError("Maximum 10 tags allowed")
        return [t.strip()[:30] for t in v if t.strip()]


class ServerUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    ssh_port: int | None = None
    ssh_user: str | None = None
    ssh_auth_type: str | None = None
    ssh_key: str | None = None
    ssh_password: str | None = None
    tags: list[str] | None = None
    detected_webroot: str | None = None


class ReconfigureResult(BaseModel):
    extra_logs_added: list[str]
    webroot: str
    rules_added: int
    warnings: list[str]


class ServerOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    host: str
    ssh_port: int
    ssh_user: str
    ssh_auth_type: str
    os_distro: str | None
    kernel_version: str | None
    tags: list[str] | None
    is_active: bool
    status: str
    last_seen_at: datetime | None
    active_alert_count: int
    logs_supported: bool
    detected_webroot: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
