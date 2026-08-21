from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User
from app.modules.auth.deps import get_current_user
from app.modules.auth.passwords import hash_password, verify_password
from app.modules.auth.schemas import (
    AuthStatusResponse,
    AuthUserOut,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
)
from app.modules.auth.tokens import create_access_token


router = APIRouter(prefix="/auth", tags=["auth"])


DEMO_NOTICE = (
    "DEMO mode is enabled for offline judging. Passwords are hashed and roles come "
    "from the user record — this is hackathon authentication, not a production "
    "identity provider."
)

PROD_NOTICE = (
    "Sign in with a provisioned supervisor or administrator account."
)


def auth_status_payload() -> dict:
    accounts = [
        {
            "username": settings.auth_supervisor_user,
            "role": "FIELD_SUPERVISOR",
            "password_matches_username": (
                settings.auth_supervisor_password
                == settings.auth_supervisor_user
            ),
        },
        {
            "username": settings.auth_admin_user,
            "role": "SURVEY_ADMIN",
            "password_matches_username": (
                settings.auth_admin_password
                == settings.auth_admin_user
            ),
        },
    ]

    return {
        "demo": bool(settings.auth_demo_mode),
        "notice": (
            DEMO_NOTICE
            if settings.auth_demo_mode
            else PROD_NOTICE
        ),
        "default_username": (
            settings.auth_supervisor_user
            if not settings.auth_demo_mode
            else settings.supervisor_user
        ),
        "password_configured": True,
        "cookie_auth": True,
        "accounts": accounts,
    }


def _set_session_cookie(
    response: Response,
    token: str,
) -> None:
    """
    Store the JWT in an HttpOnly cookie.

    Vercel frontend and Render backend are different sites, so
    SameSite=None + Secure=True is required for cross-site
    cookie authentication over HTTPS.
    """

    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,

        # IMPORTANT:
        # Vercel and Render are different sites.
        samesite="none",

        # Production uses HTTPS.
        secure=True,

        max_age=int(settings.auth_token_minutes) * 60,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    """
    Remove the authentication cookie.
    """

    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
    )


def _user_out(user: User) -> AuthUserOut:
    return AuthUserOut(
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        demo=bool(settings.auth_demo_mode),
        district_scope=list(
            user.district_scope_json or []
        ),
        cluster_scope=list(
            user.cluster_scope_json or []
        ),
    )


@router.get(
    "/status",
    response_model=AuthStatusResponse,
)
@router.get(
    "/demo/status",
    response_model=AuthStatusResponse,
)
def read_auth_status() -> AuthStatusResponse:
    """
    Return authentication configuration/status.
    """

    return AuthStatusResponse(
        **auth_status_payload()
    )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=201,
)
def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
) -> RegisterResponse:
    """
    Create a new FIELD_SUPERVISOR account.

    Existing usernames are rejected with HTTP 409.
    """

    username = body.username.strip()

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Username is required",
        )

    password = body.password

    if not password:
        raise HTTPException(
            status_code=400,
            detail="Password is required",
        )

    display_name = body.display_name.strip()

    if not display_name:
        raise HTTPException(
            status_code=400,
            detail="Display name is required",
        )

    existing = db.scalars(
        select(User).where(
            User.username == username
        )
    ).first()

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Username already exists",
        )

    user = User(
        username=username,
        password_hash=hash_password(password),
        role="FIELD_SUPERVISOR",
        display_name=display_name,
        district_scope_json=[],
        cluster_scope_json=[],
        is_active=True,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return RegisterResponse(
        success=True,
        username=user.username,
        role=user.role,
        message=(
            "Account created successfully. "
            "You can now sign in."
        ),
    )


@router.post(
    "/login",
    response_model=LoginResponse,
)
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Authenticate a database user and create a JWT session cookie.
    """

    username = body.username.strip()

    if not username:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    user = db.scalars(
        select(User).where(
            User.username == username
        )
    ).first()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Account is inactive",
        )

    try:
        password_valid = verify_password(
            body.password,
            user.password_hash,
        )
    except Exception:
        password_valid = False

    if not password_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
        )

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )

    _set_session_cookie(
        response,
        token,
    )

    status = auth_status_payload()

    return LoginResponse(
        success=True,
        demo=status["demo"],
        notice=status["notice"],
        username=user.username,
        role=user.role,
    )


@router.post(
    "/demo/login",
    response_model=LoginResponse,
)
def demo_login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """
    Demo login uses the same database authentication flow.
    """

    if not settings.auth_demo_mode:
        raise HTTPException(
            status_code=404,
            detail="Demo login is disabled",
        )

    return login(
        body=body,
        response=response,
        db=db,
    )


@router.post("/logout")
def logout(response: Response) -> dict:
    """
    Clear the authentication session.
    """

    _clear_session_cookie(response)

    return {
        "success": True,
    }


@router.get(
    "/me",
    response_model=AuthUserOut,
)
def read_me(
    user: User = Depends(get_current_user),
) -> AuthUserOut:
    """
    Return the currently authenticated user.
    """

    return _user_out(user)
