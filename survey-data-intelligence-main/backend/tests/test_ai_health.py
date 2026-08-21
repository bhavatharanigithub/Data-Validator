import json
import logging
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from app.config import BACKEND_DIR, PROJECT_ROOT, Settings, _settings_env_files
from app.modules.ai.config_status import ai_is_configured, ai_model_configured
from app.modules.ai.health import check_ai_health
from app.modules.ai.provider import ChatCompletionsProvider
from app.modules.ingestion.logging_utils import log_event, log_failure


def test_settings_env_files_are_absolute_and_include_backend_dotenv() -> None:
    files = _settings_env_files()
    assert files == (
        str((PROJECT_ROOT / ".env").resolve()),
        str((BACKEND_DIR / ".env").resolve()),
    )
    assert Path(files[0]).is_absolute()
    assert Path(files[1]).is_absolute()
    assert Path(files[1]).name == ".env"
    assert Path(files[1]).parent == BACKEND_DIR.resolve()
    configured = Settings.model_config.get("env_file")
    assert configured == files


def test_backend_dotenv_declares_ai_configuration_without_exposing_secrets() -> None:
    path = BACKEND_DIR / ".env"
    assert path.is_file(), "backend/.env is required for local AI configuration"
    parsed: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip().strip("'").strip('"')
    base = parsed.get("AI_BASE_URL", "")
    model = parsed.get("AI_MODEL", "")
    key = parsed.get("AI_API_KEY", "")
    assert bool(base), "AI_BASE_URL missing from backend/.env"
    assert bool(model), "AI_MODEL missing from backend/.env"
    assert bool(key), "AI_API_KEY missing from backend/.env"
    dumped = json.dumps({"AI_BASE_URL_set": True, "AI_MODEL_set": True, "AI_API_KEY_set": True})
    assert key not in dumped
    assert "sk-" not in dumped


def test_settings_loads_backend_dotenv_when_process_env_unsets_ai(monkeypatch) -> None:
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("AI_MODEL", raising=False)
    cfg = Settings(_env_file=_settings_env_files())
    assert bool((cfg.ai_base_url or "").strip())
    assert bool((cfg.ai_model or "").strip())
    assert bool((cfg.ai_api_key or "").strip())
    assert ai_is_configured(cfg) is True
    assert ai_model_configured(cfg) is True
    blob = json.dumps({"configured": True, "model": bool(cfg.ai_model)})
    assert cfg.ai_api_key not in blob


def test_live_configuration_detection() -> None:
    empty = Settings(ai_base_url="", ai_api_key="", ai_model="")
    assert ai_is_configured(empty) is False
    assert ai_model_configured(empty) is False
    full = Settings(
        ai_base_url="https://ai.example.test/v1",
        ai_api_key="secret-token",
        ai_model="mock-model",
    )
    assert ai_is_configured(full) is True
    assert ai_model_configured(full) is True
    missing_key = Settings(
        ai_base_url="https://ai.example.test/v1",
        ai_api_key="",
        ai_model="mock-model",
    )
    assert ai_is_configured(missing_key) is False
    assert ai_model_configured(missing_key) is True


def test_app_health_does_not_call_ai(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "configured" not in response.json()


def test_ai_health_not_configured(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.modules.ai.router.check_ai_health",
        lambda: {
            "configured": False,
            "provider_reachable": False,
            "model_configured": False,
            "status": "not_configured",
        },
    )
    response = client.get("/api/ai/health")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["provider_reachable"] is False
    assert body["status"] == "not_configured"
    assert "secret" not in json.dumps(body).lower()
    assert "authorization" not in json.dumps(body).lower()
    assert "api_key" not in json.dumps(body).lower()


def test_ai_health_ready_with_mock(monkeypatch) -> None:
    cfg = Settings(
        ai_base_url="https://ai.example.test/v1",
        ai_api_key="secret-token",
        ai_model="mock-model",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        assert "secret-token" not in _request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"ok": True})}}]},
        )

    provider = ChatCompletionsProvider(
        base_url=cfg.ai_base_url,
        api_key=cfg.ai_api_key,
        model=cfg.ai_model,
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
        retry_backoff_seconds=0,
    )
    result = check_ai_health(cfg, provider=provider)
    assert result["configured"] is True
    assert result["model_configured"] is True
    assert result["provider_reachable"] is True
    assert result["status"] == "ready"
    assert "secret-token" not in json.dumps(result)


def test_ai_health_probe_does_not_request_generation_max_tokens() -> None:
    captured: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        captured.append((request.method, str(request.url), body))
        path = str(request.url)
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "mock-model"}]})
        if path.endswith("/auth/key"):
            return httpx.Response(200, json={"data": {"label": "sk-or-test"}})
        raise AssertionError("health probe must not call chat completions when auth/key succeeds")

    cfg = Settings(
        ai_base_url="https://openrouter.ai/api/v1",
        ai_api_key="secret-token",
        ai_model="deepseek/deepseek-v4-flash",
    )
    provider = ChatCompletionsProvider(
        base_url=cfg.ai_base_url,
        api_key=cfg.ai_api_key,
        model=cfg.ai_model,
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
        retry_backoff_seconds=0,
    )
    result = check_ai_health(cfg, provider=provider)
    assert result["status"] == "ready"
    assert result["provider_reachable"] is True
    assert all(item[2] is None or item[2].get("max_tokens") != 20000 for item in captured)
    assert not any("/chat/completions" in item[1] for item in captured)


def test_ai_health_auth_failure_is_not_ready() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = str(request.url)
        if path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        if path.endswith("/auth/key"):
            return httpx.Response(401, json={"error": {"message": "invalid"}})
        return httpx.Response(500)

    cfg = Settings(
        ai_base_url="https://openrouter.ai/api/v1",
        ai_api_key="secret-token",
        ai_model="deepseek/deepseek-v4-flash",
    )
    provider = ChatCompletionsProvider(
        base_url=cfg.ai_base_url,
        api_key=cfg.ai_api_key,
        model=cfg.ai_model,
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
        retry_backoff_seconds=0,
    )
    result = check_ai_health(cfg, provider=provider)
    assert result["configured"] is True
    assert result["status"] == "auth"
    assert result["status"] != "ready"


def test_secret_redaction_in_logs(caplog) -> None:
    with caplog.at_level(logging.INFO):
        log_event(
            "probe",
            batch_id="BATCH_SAFE",
            record_id="R1",
            api_key="secret-token",
            authorization="Bearer secret-token",
            prompt="FULL SURVEY PROMPT",
            response="FULL AI RESPONSE",
            provider_status="success",
            latency_ms=12,
        )
        log_failure("probe_fail", authorization="Bearer secret-token", batch_id="BATCH_SAFE")
    assert "secret-token" not in caplog.text
    assert "FULL SURVEY PROMPT" not in caplog.text
    assert "FULL AI RESPONSE" not in caplog.text
    assert "BATCH_SAFE" in caplog.text
    assert "success" in caplog.text


def test_gemini_health_ready_without_generation() -> None:
    from app.modules.ai.gemini import GeminiProvider

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "generateContent" not in str(request.url)
        return httpx.Response(200, json={"name": "models/gemini-3.6-flash"})

    cfg = Settings(ai_provider="gemini", ai_api_key="secret-token", ai_model="")
    provider = GeminiProvider(
        api_key="secret-token",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    result = check_ai_health(cfg, provider=provider)
    assert result["configured"] is True
    assert result["model_configured"] is True
    assert result["status"] == "ready"
    assert "secret-token" not in json.dumps(result)


def test_invalid_provider_health_is_not_ready() -> None:
    cfg = Settings(
        ai_provider="not-a-vendor",
        ai_api_key="secret-token",
        ai_base_url="https://example.test",
        ai_model="x",
    )
    result = check_ai_health(cfg)
    assert result["status"] != "ready"
    assert result["status"] == "provider_error"
    assert result["provider_reachable"] is False
