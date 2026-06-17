import uuid
from datetime import datetime
from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Server(Base):
    __tablename__ = "server"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    ssh_port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    ssh_user: Mapped[str] = mapped_column(String(80), nullable=False)
    ssh_auth_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'key' | 'password'
    ssh_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    os_distro: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kernel_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String(30)), nullable=True, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    auto_response_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false")
    block_ttl_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=24, server_default="24")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    ingestion_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4, index=True
    )

    organization: Mapped["Organization"] = relationship(back_populates="servers")
    onboarding_logs: Mapped[list["OnboardingLog"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    services: Mapped[list["Service"]] = relationship(back_populates="server")
    alert_rules: Mapped[list["AlertRule"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    log_alert_rules: Mapped[list["LogAlertRule"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    maintenance_windows: Mapped[list["MaintenanceWindow"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    monitored_jobs: Mapped[list["MonitoredJob"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    db_credentials: Mapped[list["DBCredential"]] = relationship(back_populates="server", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="server")


class OnboardingLog(Base):
    __tablename__ = "onboarding_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    step: Mapped[str] = mapped_column(String(80), nullable=False)
    step_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # 'running' | 'done' | 'failed' | 'skipped'
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    server: Mapped["Server"] = relationship(back_populates="onboarding_logs")
