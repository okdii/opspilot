from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.database import get_db
from app.deps import AdminUser
from app.models.other import Settings
from app.schemas.settings import SettingsResponse, SettingsPatch, RotateWriterPassword
from app.services.email import send_email, parse_recipients, EmailNotConfigured
from app.services.retention import apply_retention
from app.services import rotation as rotation_service

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
        smtp_enabled=s.smtp_enabled,
        metrics_retention_days=s.metrics_retention_days,
        logs_retention_days=s.logs_retention_days,
        service_checks_retention_days=s.service_checks_retention_days,
        alerts_retention_days=s.alerts_retention_days,
        timezone=s.timezone,
        discord_webhook_url=s.discord_webhook_url,
        discord_enabled=s.discord_enabled,
        auto_response_enabled=s.auto_response_enabled,
        ai_provider=s.ai_provider,
        ai_model=s.ai_model,
        ai_has_key=s.ai_api_key_encrypted is not None,
        ai_base_url=s.ai_base_url,
        abuseipdb_enabled=s.abuseipdb_enabled,
        abuseipdb_has_key=s.abuseipdb_api_key_encrypted is not None,
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

    ai_key = data.pop("ai_api_key", None)
    if ai_key:
        s.ai_api_key_encrypted = crypto.encrypt(ai_key)

    abuseipdb_key = data.pop("abuseipdb_api_key", None)
    if abuseipdb_key:
        s.abuseipdb_api_key_encrypted = crypto.encrypt(abuseipdb_key)

    changed_retention = {}
    for key, value in data.items():
        setattr(s, key, value)
        if key in RETENTION_KEYS:
            changed_retention[key] = value

    await db.commit()
    await db.refresh(s)

    for key, value in changed_retention.items():
        await apply_retention(db, key, value)

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


@router.post("/discord/test", status_code=200)
async def discord_test(_: AdminUser, db: AsyncSession = Depends(get_db)):
    s = await _get_settings_row(db)
    if not s.discord_webhook_url:
        raise HTTPException(
            400,
            detail={"error": "not_configured", "message": "Configure a Discord webhook URL first."},
        )
    from datetime import datetime, timezone
    import httpx
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    payload = {
        "embeds": [
            {
                "title": "🔔 OpsPilot Test Notification",
                "description": "If you received this, your Discord webhook is configured correctly.",
                "color": 0x5865F2,
                "footer": {"text": f"{s.instance_name} · {ts}"},
            }
        ]
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(s.discord_webhook_url, json=payload)
        if resp.status_code not in (200, 204):
            raise HTTPException(
                502,
                detail={"error": "webhook_error", "message": resp.text[:400]},
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail={"error": "webhook_error", "message": str(e)})
    return {"ok": True}


@router.post("/rotate-writer-password")
async def rotate_writer_password(body: RotateWriterPassword, _: AdminUser):
    rotation_id, total = await rotation_service.start(body.new_password)
    return {"ok": True, "rotation_id": rotation_id, "total_servers": total}


@router.get("/rotation/{rotation_id}")
async def rotation_status(rotation_id: str, _: AdminUser):
    r = rotation_service.get(rotation_id)
    if not r:
        raise HTTPException(404, detail={"error": "not_found", "message": "Rotation not found."})
    return {
        "done": r.done,
        "servers": [
            {"server_id": p.server_id, "server_name": p.server_name, "status": p.status, "message": p.message}
            for p in r.servers.values()
        ],
    }


@router.post("/rotation/{rotation_id}/retry/{server_id}", status_code=204)
async def rotation_retry(rotation_id: str, server_id: str, _: AdminUser):
    await rotation_service.retry(rotation_id, server_id)


@router.post("/ai/test", status_code=200)
async def ai_test(_: AdminUser, db: AsyncSession = Depends(get_db)):
    from app.services.ai.provider import get_provider
    provider = await get_provider(db)
    if provider is None:
        raise HTTPException(
            400,
            detail={"error": "not_configured", "message": "Configure an AI provider and API key first."},
        )
    try:
        text_out, pt, ct = await provider.complete(
            system="You are a test assistant.",
            user="Reply with exactly: OK",
            max_tokens=10,
            timeout=30.0,
        )
    except Exception as exc:
        raise HTTPException(502, detail={"error": "ai_error", "message": str(exc)})
    return {"ok": True, "response": text_out.strip(), "prompt_tokens": pt, "completion_tokens": ct}


@router.post("/abuseipdb/test", status_code=200)
async def abuseipdb_test(_: AdminUser, db: AsyncSession = Depends(get_db)):
    s = await _get_settings_row(db)
    if not s.abuseipdb_api_key_encrypted:
        raise HTTPException(
            400,
            detail={"error": "not_configured", "message": "Add an AbuseIPDB API key first."},
        )
    import httpx
    key = crypto.decrypt(s.abuseipdb_api_key_encrypted)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.abuseipdb.com/api/v2/check",
                params={"ipAddress": "8.8.8.8", "maxAgeInDays": 90},
                headers={"Key": key, "Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise HTTPException(
                502, detail={"error": "abuseipdb_error", "message": resp.text[:400]})
        score = resp.json().get("data", {}).get("abuseConfidenceScore")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail={"error": "abuseipdb_error", "message": str(e)})
    return {"ok": True, "sample_score": score}
