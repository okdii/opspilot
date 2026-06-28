"""Alert-rule CRUD (metric + log) and default-rule auto-creation (spec 10 §9, §14)."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.organization import Organization
from app.models.other import AlertRule, LogAlertRule
from app.models.server import Server
from app.models.user import UserOrganization

router = APIRouter(prefix="/api", tags=["alert-rules"])


# ---------------------------------------------------------------------------
# Defaults (spec 10 §9.2/§9.3 — auto-created at server create / onboarding)
# ---------------------------------------------------------------------------

# 4 metric rules: (metric, threshold). window 5 min, cooldown 60 min.
DEFAULT_METRIC_RULES: list[tuple[str, float]] = [
    ("cpu", 85.0),
    ("ram", 90.0),
    ("disk", 85.0),
    ("disk_inode", 90.0),
]

# 7-tuple log rules: (source, pattern, severity, threshold, window_sec, match_field, exclude_pattern).
DEFAULT_LOG_RULES: list[tuple[str, str, str, int, int, str | None, str | None]] = [
    ("php_app",         "%Fatal error%",                        "critical",  1,  300, None, None),
    ("nginx_access",    '%" 5__ %',                             "warning",  10,  300, None, None),
    ("auth",            "%Failed password%",                    "critical",  5,  300, None, None),
    ("mariadb_error",   "%ERROR%",                              "critical",  1,  300, None, None),
    ("mariadb_slow",    "%Query_time%",                         "warning",   5,  300, None, None),
    # ── Security detection (Part 1) ──────────────────────────────────────
    ("%access%",        "%com_jce%profiles.import%",            "critical",  1,  300, None, None),
    ("%access%",        "%POST%.php% 200 %",                    "critical", 10,  300, None, "%jsvisit_counter%"),
    ("%access%",        "%/images/%.php% 200 %",                "critical",  1,  300, None, None),
    ("%access%",        "%/media/%.php% 200 %",                 "critical",  1,  300, None, None),
    ("%access%",        "%/uploads/%.php% 200 %",               "critical",  1,  300, None, None),
    ("%access%",        "%/files/%.php% 200 %",                 "critical",  1,  300, None, None),
    ("%access%",        "%/tmp/%.php% 200 %",                   "critical",  1,  300, None, None),
    ("%access%",        "%/cache/%.php% 200 %",                 "critical",  1,  300, None, None),
    ("%access%",        "% 404 %",                              "warning",  20,  300, None, None),
    ("auditd",          "%webroot_write%",                      "critical",  1,  300, None, None),
    ("auditd",          "%webshell_exec%",                      "critical",  1,  300, None, None),
    ("auditd",          "%ssh_key_change%",                     "critical",  1,  300, None, None),
    ("auditd",          "%log_tamper%",                         "critical",  1,  300, None, None),
    ("mariadb_general", "%CREATE USER%",                        "critical",  1,  300, None, None),
    ("mariadb_general", "%GRANT ALL%",                          "critical",  1,  300, None, None),
    ("auth",            "%Accepted publickey%",                 "warning",   1,  300, None, None),
    # ── SP Page Builder CVE-2026-48908 ───────────────────────────────────
    ("%access%",        "%com_sppagebuilder%uploadCustomIcon%", "critical",  1,  300, None, "%/administrator/%"),
    ("%access%",        "%POST%index.php% 200 %",               "warning",  10,   60, None, None),
    # ── Field-scoped rules ────────────────────────────────────────────────
    # %/media/%.PHP% and %/media/%.pHp% removed: they match Referer index.php
    # on every Joomla asset load. This rule replaces them by scoping to raw->>'url'.
    ("%access%",        "%/media/%.php%",                       "critical",  1,  300, "url", None),
]


async def create_default_rules(db: AsyncSession, server) -> tuple[int, int]:
    """Insert the default AlertRules and LogAlertRules for a new server.

    Idempotent: skips creation if the server already has any rule of that kind.
    Does NOT commit — the caller owns the transaction. Returns (metric_count,
    log_count) of rows actually added.
    """
    server_id = server.id if hasattr(server, "id") else server

    existing_metric = await db.scalar(
        select(AlertRule.id).where(AlertRule.server_id == server_id).limit(1)
    )
    metric_added = 0
    if existing_metric is None:
        for metric, threshold in DEFAULT_METRIC_RULES:
            db.add(
                AlertRule(
                    server_id=server_id,
                    metric=metric,
                    threshold=threshold,
                    rolling_window_min=5,
                    cooldown_min=60,
                    enabled=True,
                )
            )
            metric_added += 1

    log_added = 0
    for source, pattern, severity, threshold, window_sec, match_field, exclude_pattern in DEFAULT_LOG_RULES:
        exists = await db.scalar(
            select(LogAlertRule.id)
            .where(
                LogAlertRule.server_id == server_id,
                LogAlertRule.source == source,
                LogAlertRule.pattern == pattern,
            )
            .limit(1)
        )
        if exists:
            continue
        db.add(
            LogAlertRule(
                server_id=server_id,
                source=source,
                pattern=pattern,
                severity=severity,
                threshold=threshold,
                window_sec=window_sec,
                cooldown_min=60,
                enabled=True,
                match_field=match_field,
                exclude_pattern=exclude_pattern,
            )
        )
        log_added += 1

    return metric_added, log_added


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

_WINDOW_MIN_ALLOWED = {1, 3, 5, 10, 15}
_COOLDOWN_ALLOWED = {15, 30, 60, 120, 240}


class MetricRuleIn(BaseModel):
    server_id: str
    metric: str = Field(min_length=1, max_length=50)
    threshold: float = Field(gt=0)
    rolling_window_min: int = 5
    cooldown_min: int = 60
    enabled: bool = True


class MetricRulePatch(BaseModel):
    threshold: float | None = Field(default=None, gt=0)
    rolling_window_min: int | None = None
    cooldown_min: int | None = None
    enabled: bool | None = None


class MetricRuleOut(BaseModel):
    id: str
    server_id: str
    server_name: str | None = None
    metric: str
    threshold: float
    rolling_window_min: int
    cooldown_min: int
    enabled: bool
    last_fired_at: datetime | None = None
    is_auto: bool = False


class LogRuleIn(BaseModel):
    server_id: str
    source: str = Field(min_length=1, max_length=80)
    pattern: str = Field(min_length=1, max_length=500)
    severity: str = Field(pattern="^(warning|critical)$")
    threshold: int = Field(ge=1)
    window_sec: int = Field(ge=10, le=3600)
    cooldown_min: int = 60
    enabled: bool = True
    exclude_pattern: str | None = Field(default=None, max_length=255)


class LogRulePatch(BaseModel):
    source: str | None = Field(default=None, min_length=1, max_length=80)
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    severity: str | None = Field(default=None, pattern="^(warning|critical)$")
    threshold: int | None = Field(default=None, ge=1)
    window_sec: int | None = Field(default=None, ge=10, le=3600)
    cooldown_min: int | None = None
    enabled: bool | None = None
    exclude_pattern: str | None = Field(default=None, max_length=255)


class LogRuleOut(BaseModel):
    id: str
    server_id: str
    server_name: str | None = None
    source: str
    pattern: str
    severity: str
    threshold: int
    window_sec: int
    cooldown_min: int
    enabled: bool
    last_fired_at: datetime | None = None
    exclude_pattern: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_auto(rule: AlertRule) -> bool:
    for metric, threshold in DEFAULT_METRIC_RULES:
        if rule.metric == metric and rule.threshold == threshold:
            return True
    return False


def _metric_out(rule: AlertRule, server_name: str | None = None) -> MetricRuleOut:
    return MetricRuleOut(
        id=str(rule.id),
        server_id=str(rule.server_id),
        server_name=server_name,
        metric=rule.metric,
        threshold=rule.threshold,
        rolling_window_min=rule.rolling_window_min,
        cooldown_min=rule.cooldown_min,
        enabled=rule.enabled,
        last_fired_at=rule.last_fired_at,
        is_auto=_is_auto(rule),
    )


def _log_out(rule: LogAlertRule, server_name: str | None = None) -> LogRuleOut:
    return LogRuleOut(
        id=str(rule.id),
        server_id=str(rule.server_id),
        server_name=server_name,
        source=rule.source,
        pattern=rule.pattern,
        severity=rule.severity,
        threshold=rule.threshold,
        window_sec=rule.window_sec,
        cooldown_min=rule.cooldown_min,
        enabled=rule.enabled,
        last_fired_at=rule.last_fired_at,
        exclude_pattern=rule.exclude_pattern,
    )


async def _assert_org_access(org_id: str, user, db: AsyncSession) -> None:
    org = await db.scalar(select(Organization).where(Organization.id == org_id))
    if not org:
        raise HTTPException(404, detail={"error": "not_found", "message": "Organization not found."})
    if user.role != "admin":
        membership = await db.scalar(
            select(UserOrganization).where(
                UserOrganization.user_id == user.id,
                UserOrganization.org_id == org_id,
            )
        )
        if not membership:
            raise HTTPException(403, detail={"error": "forbidden", "message": "Access denied."})


async def _get_server(server_id: str, db: AsyncSession) -> Server:
    server = await db.scalar(select(Server).where(Server.id == server_id, Server.is_active == True))
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})
    return server


# ---------------------------------------------------------------------------
# Combined list (org-scoped, read)
# ---------------------------------------------------------------------------

@router.get("/organizations/{org_id}/alert-rules")
async def list_alert_rules(org_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)):
    await _assert_org_access(org_id, user, db)

    servers = (
        await db.execute(
            select(Server).where(Server.org_id == org_id, Server.is_active == True)
        )
    ).scalars().all()
    name_by_id = {str(s.id): s.name for s in servers}
    server_ids = list(name_by_id.keys())

    if not server_ids:
        return {"metric_rules": [], "log_rules": []}

    metric_rows = (
        await db.execute(
            select(AlertRule).where(AlertRule.server_id.in_(server_ids)).order_by(AlertRule.metric)
        )
    ).scalars().all()
    log_rows = (
        await db.execute(
            select(LogAlertRule).where(LogAlertRule.server_id.in_(server_ids)).order_by(LogAlertRule.source)
        )
    ).scalars().all()

    return {
        "metric_rules": [_metric_out(r, name_by_id.get(str(r.server_id))) for r in metric_rows],
        "log_rules": [_log_out(r, name_by_id.get(str(r.server_id))) for r in log_rows],
    }


# ---------------------------------------------------------------------------
# Metric rule CRUD (Admin)
# ---------------------------------------------------------------------------

@router.post("/alert-rules", status_code=201)
async def create_metric_rule(body: MetricRuleIn, user: AdminUser, db: AsyncSession = Depends(get_db)):
    if body.rolling_window_min not in _WINDOW_MIN_ALLOWED:
        raise HTTPException(422, detail={"error": "validation_error", "message": "Rolling window must be one of 1/3/5/10/15 minutes."})
    if body.cooldown_min not in _COOLDOWN_ALLOWED:
        raise HTTPException(422, detail={"error": "validation_error", "message": "Cooldown must be one of 15/30/60/120/240 minutes."})

    server = await _get_server(body.server_id, db)

    dup = await db.scalar(
        select(AlertRule.id).where(
            AlertRule.server_id == body.server_id, AlertRule.metric == body.metric
        )
    )
    if dup is not None:
        raise HTTPException(
            409,
            detail={"error": "duplicate_rule", "message": f"A rule for {body.metric} on {server.name} already exists."},
        )

    rule = AlertRule(
        server_id=body.server_id,
        metric=body.metric,
        threshold=body.threshold,
        rolling_window_min=body.rolling_window_min,
        cooldown_min=body.cooldown_min,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _metric_out(rule, server.name)


@router.patch("/alert-rules/{rule_id}")
async def update_metric_rule(rule_id: str, body: MetricRulePatch, user: AdminUser, db: AsyncSession = Depends(get_db)):
    rule = await db.scalar(select(AlertRule).where(AlertRule.id == rule_id))
    if not rule:
        raise HTTPException(404, detail={"error": "not_found", "message": "Alert rule not found."})

    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.rolling_window_min is not None:
        if body.rolling_window_min not in _WINDOW_MIN_ALLOWED:
            raise HTTPException(422, detail={"error": "validation_error", "message": "Rolling window must be one of 1/3/5/10/15 minutes."})
        rule.rolling_window_min = body.rolling_window_min
    if body.cooldown_min is not None:
        if body.cooldown_min not in _COOLDOWN_ALLOWED:
            raise HTTPException(422, detail={"error": "validation_error", "message": "Cooldown must be one of 15/30/60/120/240 minutes."})
        rule.cooldown_min = body.cooldown_min
    if body.enabled is not None:
        rule.enabled = body.enabled

    await db.commit()
    await db.refresh(rule)
    server = await db.scalar(select(Server).where(Server.id == rule.server_id))
    return _metric_out(rule, server.name if server else None)


@router.delete("/alert-rules/{rule_id}", status_code=204)
async def delete_metric_rule(rule_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    rule = await db.scalar(select(AlertRule).where(AlertRule.id == rule_id))
    if not rule:
        raise HTTPException(404, detail={"error": "not_found", "message": "Alert rule not found."})
    await db.delete(rule)
    await db.commit()
    return None


# ---------------------------------------------------------------------------
# Log rule CRUD (Admin)
# ---------------------------------------------------------------------------

@router.post("/log-alert-rules", status_code=201)
async def create_log_rule(body: LogRuleIn, user: AdminUser, db: AsyncSession = Depends(get_db)):
    if body.cooldown_min not in _COOLDOWN_ALLOWED:
        raise HTTPException(422, detail={"error": "validation_error", "message": "Cooldown must be one of 15/30/60/120/240 minutes."})

    server = await _get_server(body.server_id, db)

    rule = LogAlertRule(
        server_id=body.server_id,
        source=body.source,
        pattern=body.pattern,
        severity=body.severity,
        threshold=body.threshold,
        window_sec=body.window_sec,
        cooldown_min=body.cooldown_min,
        enabled=body.enabled,
        exclude_pattern=body.exclude_pattern,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return _log_out(rule, server.name)


@router.patch("/log-alert-rules/{rule_id}")
async def update_log_rule(rule_id: str, body: LogRulePatch, user: AdminUser, db: AsyncSession = Depends(get_db)):
    rule = await db.scalar(select(LogAlertRule).where(LogAlertRule.id == rule_id))
    if not rule:
        raise HTTPException(404, detail={"error": "not_found", "message": "Log alert rule not found."})

    if body.cooldown_min is not None and body.cooldown_min not in _COOLDOWN_ALLOWED:
        raise HTTPException(422, detail={"error": "validation_error", "message": "Cooldown must be one of 15/30/60/120/240 minutes."})

    if body.source is not None:
        rule.source = body.source
    if body.pattern is not None:
        rule.pattern = body.pattern
    if body.severity is not None:
        rule.severity = body.severity
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.window_sec is not None:
        rule.window_sec = body.window_sec
    if body.cooldown_min is not None:
        rule.cooldown_min = body.cooldown_min
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.exclude_pattern is not None:
        rule.exclude_pattern = body.exclude_pattern or None  # empty string → NULL

    await db.commit()
    await db.refresh(rule)
    server = await db.scalar(select(Server).where(Server.id == rule.server_id))
    return _log_out(rule, server.name if server else None)


@router.delete("/log-alert-rules/{rule_id}", status_code=204)
async def delete_log_rule(rule_id: str, user: AdminUser, db: AsyncSession = Depends(get_db)):
    rule = await db.scalar(select(LogAlertRule).where(LogAlertRule.id == rule_id))
    if not rule:
        raise HTTPException(404, detail={"error": "not_found", "message": "Log alert rule not found."})
    await db.delete(rule)
    await db.commit()
    return None
