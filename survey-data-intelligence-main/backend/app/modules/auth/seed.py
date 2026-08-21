from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.modules.auth.passwords import hash_password, verify_password


def _hash_scheme_supported(stored: str | None) -> bool:
    if not stored:
        return False
    return stored.startswith("pbkdf2_sha256$")


def _upsert(
    db: Session, username: str, password: str, role: str, display_name: str, districts: list[str] | None
) -> None:
    row = db.scalars(select(User).where(User.username == username)).first()
    if row is None:
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                display_name=display_name,
                district_scope_json=districts or [],
                cluster_scope_json=[],
                is_active=True,
            )
        )
        return
    stale_hash = not _hash_scheme_supported(row.password_hash)
    demo_mismatch = settings.auth_demo_mode and not verify_password(password, row.password_hash or "")
    if stale_hash or demo_mismatch:
        row.password_hash = hash_password(password)
    if not row.role:
        row.role = role
    row.is_active = True
    if not row.display_name:
        row.display_name = display_name


def seed_users(db: Session) -> None:
    _upsert(
        db,
        settings.auth_admin_user,
        settings.auth_admin_password,
        "SURVEY_ADMIN",
        "Survey administrator",
        [],
    )
    _upsert(
        db,
        settings.auth_supervisor_user,
        settings.auth_supervisor_password,
        "FIELD_SUPERVISOR",
        "Field supervisor",
        [],
    )
    if settings.auth_demo_mode:
        _upsert(
            db,
            settings.supervisor_user,
            settings.supervisor_pass or "demo",
            "FIELD_SUPERVISOR",
            "Demo supervisor",
            [],
        )
    db.commit()
