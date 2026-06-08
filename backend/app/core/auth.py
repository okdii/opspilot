from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import jwt

from app.config import settings

_ALGORITHM = "HS256"
_TTL = timedelta(hours=24)


def create_token(user_id: str) -> tuple[str, str, datetime]:
    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    expires_at = now + _TTL
    payload = {"sub": user_id, "jti": jti, "iat": now, "exp": expires_at}
    token = jwt.encode(payload, settings.opspilot_jwt_secret, algorithm=_ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.opspilot_jwt_secret, algorithms=[_ALGORITHM])
