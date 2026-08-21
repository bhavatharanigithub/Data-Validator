from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.modules.auth.tokens import decode_access_token

ROLES = {"FIELD_SUPERVISOR", "SURVEY_ADMIN"}


def _token_from_request(request: Request) -> str | None:
    cookie = request.cookies.get(settings.auth_cookie_name)
    if cookie:
        return cookie
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.scalars(select(User).where(User.username == payload["sub"])).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.role not in ROLES:
        raise HTTPException(status_code=403, detail="Unknown role")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "SURVEY_ADMIN":
        raise HTTPException(status_code=403, detail="Survey administrator role required")
    return user


def district_scope(user: User) -> list[str] | None:
    """None means unrestricted. A non-empty list is an allowlist enforced server-side."""
    if user.role == "SURVEY_ADMIN":
        return None
    scoped = [str(item) for item in (user.district_scope_json or []) if str(item)]
    return scoped or None


def cluster_scope(user: User) -> list[str] | None:
    if user.role == "SURVEY_ADMIN":
        return None
    scoped = [str(item) for item in (user.cluster_scope_json or []) if str(item)]
    return scoped or None


def allowed_for_record(user: User, *, district_id: str | None, cluster_id: str | None) -> bool:
    districts = district_scope(user)
    clusters = cluster_scope(user)
    if districts is not None and (district_id or "") not in districts:
        return False
    if clusters is not None and (cluster_id or "") not in clusters:
        return False
    return True
