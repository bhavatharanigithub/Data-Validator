from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from app.config import settings

ALGORITHM = "HS256"


def create_access_token(*, user_id: int, username: str, role: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": username,
        "uid": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=int(settings.auth_token_minutes))).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if not payload.get("sub") or payload.get("role") not in {"FIELD_SUPERVISOR", "SURVEY_ADMIN"}:
        return None
    return payload
