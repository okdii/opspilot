"""All remaining relational models — created in migration but mostly used in later phases."""
import uuid
from datetime import datetime
from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey,
    Integer, String, Text, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ssl_warn_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    ssl_critical_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    ssl_expiry_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ssl_days_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ssl_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ssl_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ssl_last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_security_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_keyword: Mapped[str | None] = mapped_column(Text, nullable=True)
    forbidden_keywords_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    server: Mapped["Server"] = relationship(back_populates="services")
    incidents: Mapped[list["Incident"]] = relationship(back_populates="service", cascade="all, delete-orphan")
    security_scans: Mapped[list["ServiceSecurityScan"]] = relationship(back_populates="service", cascade="all, delete-orphan")
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
    security_grade: Mapped[str | None] = mapped_column(String(2), nullable=True)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    security_findings: Mapped[list | None] = mapped_column(JSONB(astext_type=Text()), nullable=True)

    domain: Mapped["Domain"] = relationship(back_populates="ssl_certs")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="ssl_cert")


class ServiceSecurityScan(Base):
    __tablename__ = "service_security_scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("service.id", ondelete="CASCADE"), nullable=False, index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grade: Mapped[str] = mapped_column(String(2), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    tls_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tls_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    cipher_suite: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cipher_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pfs_supported: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    key_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    key_size_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    self_signed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ocsp_stapling: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    https_redirect: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hsts: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    hsts_max_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    csp: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    x_frame_options: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    x_content_type: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    referrer_policy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    permissions_policy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    server_disclosure: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    x_powered_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    findings: Mapped[list] = mapped_column(JSONB(astext_type=Text()), nullable=False, default=list)

    service: Mapped["Service"] = relationship(back_populates="security_scans")


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="SET NULL"), nullable=True, index=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("service.id", ondelete="SET NULL"), nullable=True)
    domain_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("domain.id", ondelete="SET NULL"), nullable=True)
    ssl_cert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ssl_cert.id", ondelete="SET NULL"), nullable=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("monitored_job.id", ondelete="SET NULL"), nullable=True)
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
    job: Mapped["MonitoredJob"] = relationship(back_populates="alerts")


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


class MonitoredJob(Base):
    __tablename__ = "monitored_job"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schedule: Mapped[str] = mapped_column(String(120), nullable=False)
    grace_period_min: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    ping_token: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy")
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    start_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_size_formatted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    previous_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    server: Mapped["Server"] = relationship(back_populates="monitored_jobs")
    runs: Mapped[list["JobRun"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="job")


class JobRun(Base):
    __tablename__ = "job_run"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("monitored_job.id", ondelete="CASCADE"), nullable=False, index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped["MonitoredJob"] = relationship(back_populates="runs")


class DBCredential(Base):
    __tablename__ = "db_credential"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    server_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("server.id", ondelete="CASCADE"), nullable=False, index=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=3306)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_replica: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    db_type: Mapped[str] = mapped_column(String(16), nullable=False, default="mysql", server_default="mysql")
    last_deadlock_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str | None] = mapped_column(String(60), nullable=True)

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
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, server_default="UTC")
    smtp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    discord_webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    discord_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ai_provider: Mapped[str] = mapped_column(String(30), nullable=False, server_default="disabled")
    ai_model: Mapped[str] = mapped_column(String(80), nullable=False, server_default="claude-sonnet-4-6")
    ai_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
