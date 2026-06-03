"""All remaining relational models — created in migration but mostly used in later phases."""
import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Service(Base):
    __tablename__ = "service"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'http' | 'tcp' | 'db'
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    ignore_ssl_errors: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    server: Mapped["Server"] = relationship(back_populates="services")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="service")


class Incident(Base):
    __tablename__ = "incident"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("service.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    service: Mapped["Service"] = relationship(back_populates="incidents")


class Domain(Base):
    __tablename__ = "domain"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    registrar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warn_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="domains")
    ssl_certs: Mapped[list["SSLCert"]] = relationship(back_populates="domain", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="domain")


class SSLCert(Base):
    __tablename__ = "ssl_cert"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("domain.id", ondelete="CASCADE"), nullable=False, index=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=443)
    issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warn_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    domain: Mapped["Domain"] = relationship(back_populates="ssl_certs")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="ssl_cert")


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="SET NULL"), nullable=True, index=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("service.id", ondelete="SET NULL"), nullable=True)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("domain.id", ondelete="SET NULL"), nullable=True)
    ssl_cert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ssl_cert.id", ondelete="SET NULL"), nullable=True)
    cron_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cron_job.id", ondelete="SET NULL"), nullable=True)
    backup_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("backup_job.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="firing", index=True)
    consecutive_clear_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    server: Mapped["Server"] = relationship(back_populates="alerts")
    service: Mapped["Service"] = relationship(back_populates="alerts")
    domain: Mapped["Domain"] = relationship(back_populates="alerts")
    ssl_cert: Mapped["SSLCert"] = relationship(back_populates="alerts")
    cron_job: Mapped["CronJob"] = relationship(back_populates="alerts")
    backup_job: Mapped["BackupJob"] = relationship(back_populates="alerts")


class AlertRule(Base):
    __tablename__ = "alert_rule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(50), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    rolling_window_min: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    cooldown_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    server: Mapped["Server"] = relationship(back_populates="alert_rules")


class LogAlertRule(Base):
    __tablename__ = "log_alert_rule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    window_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    cooldown_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    server: Mapped["Server"] = relationship(back_populates="log_alert_rules")


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_window"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True)

    server: Mapped["Server"] = relationship(back_populates="maintenance_windows")


class CronJob(Base):
    __tablename__ = "cron_job"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    schedule: Mapped[str] = mapped_column(String(80), nullable=False)
    grace_period_min: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    ping_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    server: Mapped["Server"] = relationship(back_populates="cron_jobs")
    runs: Mapped[list["CronJobRun"]] = relationship(back_populates="cron_job", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="cron_job")


class CronJobRun(Base):
    __tablename__ = "cron_job_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cron_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cron_job.id", ondelete="CASCADE"), nullable=False, index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # 'success' | 'missed'

    cron_job: Mapped["CronJob"] = relationship(back_populates="runs")


class BackupJob(Base):
    __tablename__ = "backup_job"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    ping_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_status_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    previous_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    server: Mapped["Server"] = relationship(back_populates="backup_jobs")
    runs: Mapped[list["BackupRun"]] = relationship(back_populates="backup_job", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="backup_job")


class BackupRun(Base):
    __tablename__ = "backup_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backup_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backup_job.id", ondelete="CASCADE"), nullable=False, index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # 'success' | 'missed' | 'failed'

    backup_job: Mapped["BackupJob"] = relationship(back_populates="runs")


class DBCredential(Base):
    __tablename__ = "db_credential"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=3306)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_replica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    last_deadlock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    server: Mapped["Server"] = relationship(back_populates="db_credentials")


class Settings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    instance_name: Mapped[str] = mapped_column(String(255), nullable=False, server_default="OpsPilot")
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_encryption: Mapped[str] = mapped_column(String(10), nullable=False, server_default="tls")
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    smtp_from_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_recipients: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    logs_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    service_checks_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    alerts_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    writer_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
