from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.database import get_db
from app.deps import AdminUser
from app.models.other import Settings
from app.schemas.settings import SettingsResponse, SettingsPatch

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
