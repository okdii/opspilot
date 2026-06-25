"""Daily Report endpoints.

GET  /api/servers/{server_id}/daily-report          — fetch or auto-generate for yesterday
POST /api/servers/{server_id}/daily-report/regenerate — force-regenerate (admin only)
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser, CurrentUser
from app.models.daily_report import DailyReport
from app.models.other import Alert, Settings
from app.schemas.daily_report import DailyReportFinding, DailyReportResponse, RegenerateRequest
from app.services.ai.provider import get_provider

router = APIRouter(prefix="/api/servers", tags=["daily-report"])


def _yesterday() -> date:
    return (datetime.now(timezone.utc) - timedelta(days=1)).date()


def _to_response(r: DailyReport) -> DailyReportResponse:
    return DailyReportResponse(
        status="ok",
        report_date=r.report_date,
        score=r.score,
        band=r.band,
        narrative=r.narrative,
        findings=[DailyReportFinding(**f) for f in (r.findings or [])],
        data_snapshot=r.data_snapshot or {},
        ai_provider=r.ai_provider,
        ai_model=r.ai_model,
        generated_at=r.generated_at,
        prompt_tokens=r.prompt_tokens,
        completion_tokens=r.completion_tokens,
    )


@router.get("/{server_id}/daily-report", response_model=DailyReportResponse)
async def get_daily_report(
    server_id: str,
    user: CurrentUser,
    report_date: date | None = None,
    db: AsyncSession = Depends(get_db),
) -> DailyReportResponse:
    from app.routers.servers import _assert_server_access
    await _assert_server_access(server_id, user, db)

    target = report_date or _yesterday()

    cached = await db.scalar(
        select(DailyReport).where(
            DailyReport.server_id == uuid.UUID(server_id),
            DailyReport.report_date == target,
        )
    )
    if cached:
        return _to_response(cached)

    provider = await get_provider(db)
    if provider is None:
        return DailyReportResponse(status="ai_not_configured")

    if target != _yesterday():
        return DailyReportResponse(status="not_generated")

    s = await db.scalar(select(Settings).where(Settings.id == 1))
    from app.services.daily_report_generator import generate_and_store
    try:
        report = await generate_and_store(
            db=db,
            server_id=uuid.UUID(server_id),
            report_date=target,
            provider=provider,
            provider_name=s.ai_provider,
            model_name=s.ai_model,
        )
    except Exception as exc:
        raise HTTPException(502, detail={"error": "ai_error", "message": str(exc)})

    return _to_response(report)


@router.get("/{server_id}/daily-report/alerts")
async def list_daily_report_alerts(
    server_id: str,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    report_date: date = Query(...),
    page: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=100),
):
    from app.routers.servers import _assert_server_access
    await _assert_server_access(server_id, user, db)

    day_start = datetime(report_date.year, report_date.month, report_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    sid = uuid.UUID(server_id)

    base = select(Alert).where(
        Alert.server_id == sid,
        Alert.sent_at >= day_start,
        Alert.sent_at < day_end,
    )
    total: int = (await db.scalar(select(func.count()).select_from(base.subquery()))) or 0
    rows = (
        await db.execute(
            base.order_by(Alert.sent_at.desc())
            .offset(page * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    def _dur(a: Alert) -> int | None:
        if a.resolved_at and a.sent_at:
            return int((a.resolved_at - a.sent_at).total_seconds() // 60)
        return None

    items = [
        {
            "id": str(a.id),
            "severity": a.severity,
            "type": a.type,
            "message": a.message,
            "state": a.state,
            "fired_at": a.sent_at.strftime("%H:%M") if a.sent_at else None,
            "resolved_at": a.resolved_at.strftime("%H:%M") if a.resolved_at else None,
            "duration_min": _dur(a),
        }
        for a in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/{server_id}/daily-report/regenerate", response_model=DailyReportResponse)
async def regenerate_daily_report(
    server_id: str,
    body: RegenerateRequest,
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> DailyReportResponse:
    provider = await get_provider(db)
    if provider is None:
        raise HTTPException(
            400,
            detail={"error": "ai_not_configured", "message": "Configure an AI provider in Settings first."},
        )

    s = await db.scalar(select(Settings).where(Settings.id == 1))
    from app.services.daily_report_generator import generate_and_store
    try:
        report = await generate_and_store(
            db=db,
            server_id=uuid.UUID(server_id),
            report_date=body.date,
            provider=provider,
            provider_name=s.ai_provider,
            model_name=s.ai_model,
        )
    except Exception as exc:
        raise HTTPException(502, detail={"error": "ai_error", "message": str(exc)})

    return _to_response(report)
