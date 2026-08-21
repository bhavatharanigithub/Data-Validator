from fastapi.testclient import TestClient

from app.modules.auth.router import DEMO_NOTICE


def test_valid_and_invalid_login(anon_client: TestClient) -> None:
    failed = anon_client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert failed.status_code == 401
    ok = anon_client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["success"] is True
    assert body["role"] == "SURVEY_ADMIN"
    assert body["username"] == "admin"
    assert "password" not in body
    assert "token" not in body
    cookie = ok.headers.get("set-cookie", "")
    assert "sv_access=" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "SURVEY_ADMIN"
    assert "password_hash" not in me.json()


def test_unauthenticated_protected_route(anon_client: TestClient) -> None:
    response = anon_client.get("/api/dashboard/overview")
    assert response.status_code == 401


def test_logout(anon_client: TestClient) -> None:
    anon_client.post("/api/auth/login", json={"username": "supervisor", "password": "supervisor"})
    assert anon_client.get("/api/auth/me").status_code == 200
    logged_out = anon_client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert anon_client.get("/api/auth/me").status_code == 401


def test_role_authorization_rules(supervisor_client: TestClient, client: TestClient) -> None:
    rules = client.get("/api/validation/rules").json()
    rule_id = rules[0]["id"]
    forbidden = supervisor_client.patch(f"/api/validation/rules/{rule_id}/disable")
    assert forbidden.status_code == 403
    allowed = client.patch(f"/api/validation/rules/{rule_id}/disable")
    assert allowed.status_code == 200
    client.patch(f"/api/validation/rules/{rule_id}/enable")


def test_demo_status_does_not_expose_secrets(anon_client: TestClient) -> None:
    status = anon_client.get("/api/auth/status")
    assert status.status_code == 200
    body = status.json()
    assert body["demo"] is True
    assert DEMO_NOTICE.split(".")[0] in body["notice"]
    dumped = str(body).lower()
    assert "jwt" not in dumped
    assert "password_hash" not in dumped
    assert "api_key" not in dumped
    usernames = {item["username"] for item in body["accounts"]}
    assert "admin" in usernames
    assert "supervisor" in usernames


def test_default_accounts_session_and_rejections(anon_client: TestClient) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import User
    from app.modules.auth.passwords import verify_password
    from app.config import settings

    db = SessionLocal()
    try:
        admin = db.scalars(select(User).where(User.username == "admin")).first()
        supervisor = db.scalars(select(User).where(User.username == "supervisor")).first()
        assert admin is not None and supervisor is not None
        assert admin.password_hash and supervisor.password_hash
        assert admin.password_hash.startswith("pbkdf2_sha256$")
        assert supervisor.password_hash.startswith("pbkdf2_sha256$")
        assert verify_password(settings.auth_admin_password, admin.password_hash)
        assert verify_password(settings.auth_supervisor_password, supervisor.password_hash)
        assert admin.role == "SURVEY_ADMIN"
        assert supervisor.role == "FIELD_SUPERVISOR"
    finally:
        db.close()

    supervisor_login = anon_client.post(
        "/api/auth/login", json={"username": "supervisor", "password": "supervisor"}
    )
    assert supervisor_login.status_code == 200
    assert supervisor_login.json()["role"] == "FIELD_SUPERVISOR"
    cookie = supervisor_login.headers.get("set-cookie", "")
    assert "sv_access=" in cookie
    assert "httponly" in cookie.lower()
    me = anon_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "supervisor"
    assert me.json()["role"] == "FIELD_SUPERVISOR"
    anon_client.post("/api/auth/logout")

    admin_login = anon_client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert admin_login.status_code == 200
    assert admin_login.json()["role"] == "SURVEY_ADMIN"
    assert anon_client.get("/api/auth/me").status_code == 200

    assert anon_client.post("/api/auth/login", json={"username": "nobody", "password": "supervisor"}).status_code == 401
    assert anon_client.post("/api/auth/login", json={"username": "supervisor", "password": "wrong"}).status_code == 401
    assert anon_client.post("/api/auth/login", json={"username": "", "password": "supervisor"}).status_code == 422
    assert anon_client.post("/api/auth/login", json={"username": "supervisor", "password": ""}).status_code == 422
