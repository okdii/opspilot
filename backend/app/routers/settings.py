from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.database import get_db
from app.deps import AdminUser
from app.models.other import Settings
from app.schemas.settings import SettingsResponse, SettingsPatch
from app.services.email import send_email, parse_recipients, EmailNotConfigured

router = APIRouter(prefix="/api/settings", tags=["settings"])

RETENTION_KEYS = {
    "metrics_retention_days",
    "logs_retention_days",
    "service_checks_retention_days",
    "alerts_retention_days",
}


async def _get_settings_row(db: AsyncSession) -> Settings:
    row = await db.scalar(select(Settings).where(Settings.id == 1))
    if row is None:
        row = Settings(id=1)
        db.add(row)
        await db.flush()
    return row


def _to_response(s: Settings) -> SettingsResponse:
    return SettingsResponse(
        instance_name=s.instance_name,
        base_url=s.base_url,
        smtp_host=s.smtp_host,
        smtp_port=s.smtp_port,
        smtp_encryption=s.smtp_encryption,
        smtp_username=s.smtp_username,
        smtp_from_address=s.smtp_from_address,
        smtp_recipients=s.smtp_recipients,
        smtp_has_password=s.smtp_password_encrypted is not None,
        metrics_retention_days=s.metrics_retention_days,
        logs_retention_days=s.logs_retention_days,
        service_checks_retention_days=s.service_checks_retention_days,
        alerts_retention_days=s.alerts_retention_days,
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(_: AdminUser, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    s = await _get_settings_row(db)
    return _to_response(s)


@router.patch("", response_model=SettingsResponse)
async def patch_settings(body: SettingsPatch, _: AdminUser, db: AsyncSession = Depends(get_db)) -> SettingsResponse:
    s = await _get_settings_row(db)
    data = body.model_dump(exclude_unset=True)

    pw = data.pop("smtp_password", None)
    if pw:
        s.smtp_password_encrypted = crypto.encrypt(pw)

    changed_retention = {}
    for key, value in data.items():
        setattr(s, key, value)
        if key in RETENTION_KEYS:
            changed_retention[key] = value

    await db.commit()
    await db.refresh(s)

    # Task 8 wires changed_retention -> retention service here.

    return _to_response(s)


@router.post("/smtp/test", status_code=200)
async def smtp_test(_: AdminUser, db: AsyncSession = Depends(get_db)):
    s = await _get_settings_row(db)
    recipients = parse_recipients(s.smtp_recipients)
    if not recipients:
        raise HTTPException(
            400,
            detail={"error": "no_recipients", "message": "Add at least one alert recipient first."},
        )
    subject = f"[OpsPilot] Test Email — {s.instance_name}"
    base = s.base_url or "your OpsPilot instance"
    body = (
        "This is a test email from OpsPilot.\n"
        "If you received this, your SMTP configuration is working correctly.\n\n"
        f"Sent by: {s.instance_name} ({base})\n"
    )
    try:
        send_email(s, subject, body, [recipients[0]])
    except EmailNotConfigured as e:
        raise HTTPException(400, detail={"error": "not_configured", "message": str(e)})
    except Exception as e:  # SMTP errors surfaced verbatim to the admin
        raise HTTPException(502, detail={"error": "smtp_error", "message": str(e)})
    return {"ok": True, "sent_to": recipients[0]}
