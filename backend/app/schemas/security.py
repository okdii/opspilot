"""Pydantic schemas for the HTTP security audit endpoint."""
from datetime import datetime

from pydantic import BaseModel


class TLSSummary(BaseModel):
    version: str | None
    ok: bool | None
    cipher_suite: str | None
    cipher_ok: bool | None
    pfs: bool | None
    key_size: int | None
    key_size_ok: bool | None
    self_signed: bool | None
    ocsp: bool | None


class HeaderSummary(BaseModel):
    https_redirect: bool | None
    hsts: bool | None
    hsts_max_age: int | None
    csp: bool | None
    x_frame_options: bool | None
    x_content_type: bool | None
    referrer_policy: bool | None
    permissions_policy: bool | None
    server_disclosure: bool | None
    x_powered_by: str | None


class SecurityFinding(BaseModel):
    check: str
    severity: str
    passed: bool
    detail: str


class ServiceSecurityOut(BaseModel):
    grade: str
    score: int
    scanned_at: datetime
    tls: TLSSummary
    headers: HeaderSummary
    findings: list[SecurityFinding]
