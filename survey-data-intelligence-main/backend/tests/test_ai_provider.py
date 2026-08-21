import json

import httpx
import pytest

from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.factory import build_ai_provider
from app.modules.ai.provider import ChatCompletionsProvider
from app.config import Settings


def test_factory_returns_none_without_config() -> None:
    cfg = Settings(
        ai_base_url="",
        ai_api_key="",
        ai_model="",
    )
    assert build_ai_provider(cfg) is None


def test_factory_builds_when_configured() -> None:
    cfg = Settings(
        ai_base_url="https://ai.example.test/v1",
        ai_api_key="secret-token",
        ai_model="mock-model",
    )
    provider = build_ai_provider(cfg)
    assert provider is not None
    assert getattr(provider, "model") == "mock-model"
    assert getattr(provider, "api_key") == "secret-token"



def test_openrouter_request_uses_max_tokens_20000() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"ok": True})}}]},
        )

    provider = ChatCompletionsProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="secret-token",
        model="deepseek/deepseek-v4-flash",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    provider.complete_json(system="sys", user="{}")
    assert captured["body"]["max_tokens"] == 20000
    assert "max_tokens" in captured["body"]
    assert captured["body"]["max_tokens"] != 65536
    assert captured["body"]["max_tokens"] != 2000


def test_health_probe_uses_auth_key_not_generation_budget() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(f"{request.method} {request.url.path}")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "deepseek/deepseek-v4-flash"}]})
        if request.url.path.endswith("/auth/key"):
            return httpx.Response(200, json={"data": {}})
        raise AssertionError("unexpected completion during health probe")

    provider = ChatCompletionsProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="secret-token",
        model="deepseek/deepseek-v4-flash",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
        retry_backoff_seconds=0,
    )
    provider.probe_health()
    assert any(item.endswith("/models") for item in methods)
    assert any(item.endswith("/auth/key") for item in methods)
    assert not any("chat/completions" in item for item in methods)


def test_provider_success_parses_json_object() -> None:
    payload = {
        "contextual_insights": ["Hours vary by enumerator."],
        "important_relationships": ["Cluster and district align."],
        "potential_data_quality_concerns": ["Age missingness."],
        "context_summary": "Small mixed employment sample.",
        "confidence": 0.7,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "secret-token" not in request.content.decode()
        body = json.loads(request.content)
        assert body["model"] == "mock-model"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.complete_json(system="sys", user='{"dataset_context": {}}')
    assert result["context_summary"] == payload["context_summary"]


def test_provider_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIUnavailableError) as exc:
        provider.complete_json(system="sys", user="{}")
    assert exc.value.reason == "timeout"
    assert "secret-token" not in exc.value.message


def test_provider_rate_limit() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIUnavailableError) as exc:
        provider.complete_json(system="sys", user="{}")
    assert exc.value.reason == "rate_limit"


def test_provider_malformed_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not-json"}}]},
        )

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIUnavailableError) as exc:
        provider.complete_json(system="sys", user="{}")
    assert exc.value.reason == "invalid_response"


def _counting_provider(statuses: list[int], success_payload: dict | None = None):
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        idx = min(calls["n"], len(statuses) - 1)
        status = statuses[idx]
        calls["n"] += 1
        if status == 200:
            body = success_payload or {"ok": True}
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(body)}}]},
            )
        return httpx.Response(status, json={"error": "fail"})

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=2,
        retry_backoff_seconds=0,
    )
    return provider, calls


def test_retries_on_429_then_succeeds() -> None:
    provider, calls = _counting_provider([429, 429, 200], {"ok": True})
    result = provider.complete_json(system="sys", user="{}")
    assert result["ok"] is True
    assert calls["n"] == 3


def test_retries_on_5xx_then_succeeds() -> None:
    provider, calls = _counting_provider([500, 200], {"ok": True})
    result = provider.complete_json(system="sys", user="{}")
    assert result["ok"] is True
    assert calls["n"] == 2


def test_does_not_retry_on_401() -> None:
    provider, calls = _counting_provider([401, 200], {"ok": True})
    with pytest.raises(AIUnavailableError) as exc:
        provider.complete_json(system="sys", user="{}")
    assert exc.value.reason == "auth"
    assert calls["n"] == 1
    assert "secret-token" not in exc.value.message


DEEPSEEK_EXPLANATION = {
    "summary": "High-risk record should be reviewed using the supplied evidence only.",
    "key_findings": ["Statistical and ML evidence both flag working hours."],
    "evidence_explanations": {
        "rule_evidence": "A configured rule contributed to review.",
        "statistical_evidence": "The statistical detector flagged working hours.",
        "ml_evidence": "The ML model assigned an elevated anomaly score.",
    },
    "recommended_action": "Review the original enumeration.",
    "limitations": ["Explanation quality depends on supplied evidence."],
    "explanation_confidence": 0.84,
}


def test_provider_parses_openrouter_deepseek_v4_message() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "gen-test",
                "provider": "openrouter",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(DEEPSEEK_EXPLANATION),
                            "refusal": None,
                            "reasoning": "internal reasoning text",
                            "reasoning_details": [{"type": "reasoning.text", "text": "internal"}],
                        },
                    }
                ],
            },
        )

    provider = ChatCompletionsProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key="secret-token",
        model="deepseek/deepseek-v4-flash",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.complete_json(system="sys", user="{}")
    assert result["summary"] == DEEPSEEK_EXPLANATION["summary"]
    assert isinstance(result["evidence_explanations"], dict)


def test_provider_parses_json_code_fence() -> None:
    fenced = "```json\n" + json.dumps({"ok": True, "summary": "fenced"}) + "\n```"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.complete_json(system="sys", user="{}")
    assert result["ok"] is True


def test_provider_rejects_empty_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "", "reasoning": "{}"}}]},
        )

    provider = ChatCompletionsProvider(
        base_url="https://ai.example.test/v1",
        api_key="secret-token",
        model="mock-model",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AIUnavailableError) as exc:
        provider.complete_json(system="sys", user="{}")
    assert exc.value.reason == "invalid_response"
    assert "secret-token" not in exc.value.message


def test_factory_selects_openrouter_provider() -> None:
    cfg = Settings(
        ai_provider="openrouter",
        ai_base_url="https://openrouter.ai/api/v1",
        ai_api_key="secret-token",
        ai_model="deepseek/deepseek-v4-flash",
    )
    provider = build_ai_provider(cfg)
    assert isinstance(provider, ChatCompletionsProvider)
    assert provider.model == "deepseek/deepseek-v4-flash"


def test_factory_selects_gemini_provider_with_default_model() -> None:
    from app.modules.ai.gemini import GEMINI_DEFAULT_MODEL, GeminiProvider

    cfg = Settings(
        ai_provider="gemini",
        ai_base_url="",
        ai_api_key="secret-token",
        ai_model="",
    )
    provider = build_ai_provider(cfg)
    assert isinstance(provider, GeminiProvider)
    assert provider.model == GEMINI_DEFAULT_MODEL
    assert provider.model == "gemini-3.6-flash"
    assert "secret-token" not in provider.base_url


def test_factory_rejects_unknown_provider() -> None:
    cfg = Settings(
        ai_provider="unknown-vendor",
        ai_base_url="https://example.test",
        ai_api_key="secret-token",
        ai_model="x",
    )
    with pytest.raises(AIUnavailableError) as exc:
        build_ai_provider(cfg)
    assert exc.value.reason == "provider_error"
    assert "secret-token" not in exc.value.message


def test_gemini_complete_json_parses_native_candidates() -> None:
    from app.modules.ai.gemini import GeminiProvider

    payload = {"summary": "ok", "primary_reason": "hours look unusual"}
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header_has_key"] = "x-goog-api-key" in request.headers
        captured["authorization"] = request.headers.get("authorization")
        body = json.loads(request.content)
        captured["mime"] = body.get("generationConfig", {}).get("responseMimeType")
        assert "secret-token" not in request.content.decode()
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
        )

    provider = GeminiProvider(
        api_key="secret-token",
        model="gemini-3.6-flash",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    result = provider.complete_json(system="sys", user='{"ping": true}')
    assert result == payload
    assert captured["header_has_key"] is True
    assert captured["authorization"] is None
    assert captured["mime"] == "application/json"
    assert ":generateContent" in captured["url"]
    assert "secret-token" not in captured["url"]


def test_gemini_health_is_lightweight_model_lookup() -> None:
    from app.modules.ai.gemini import GeminiProvider

    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(f"{request.method} {request.url.path}")
        assert request.headers.get("x-goog-api-key") == "secret-token"
        if request.method == "GET" and "/models/gemini-3.6-flash" in request.url.path:
            return httpx.Response(200, json={"name": "models/gemini-3.6-flash"})
        raise AssertionError("gemini health must not call generateContent")

    provider = GeminiProvider(
        api_key="secret-token",
        timeout_seconds=5,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    provider.probe_health()
    assert any(item.startswith("GET ") and "generateContent" not in item for item in methods)
    assert not any("generateContent" in item for item in methods)
