from __future__ import annotations

from typing import Any

import httpx

from app.modules.ai.errors import AIUnavailableError
from app.modules.ai.provider import _parse_content

GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class GeminiProvider:
    """Google Gemini generateContent client. Uses the native v1beta API."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30,
        http_client: httpx.Client | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.api_key = api_key
        self.model = (model or "").strip() or GEMINI_DEFAULT_MODEL
        root = (base_url or "").strip().rstrip("/") or GEMINI_DEFAULT_BASE_URL
        self.base_url = root
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def _headers(self) -> dict[str, str]:
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _model_id(self) -> str:
        name = self.model
        if name.startswith("models/"):
            return name.split("/", 1)[1]
        return name

    def _model_path(self) -> str:
        return f"{self.base_url}/models/{self._model_id()}"

    def probe_health(self) -> None:
        response = self._send_http("GET", self._model_path())
        self._raise_http_status(response)

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        last_error: AIUnavailableError | None = None
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                return self._generate(payload)
            except AIUnavailableError as exc:
                last_error = exc
                if exc.reason not in {"timeout", "rate_limit", "provider_error"}:
                    raise
                if attempt >= self.max_retries:
                    raise
        assert last_error is not None
        raise last_error

    def _generate(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._send_http("POST", f"{self._model_path()}:generateContent", json_body=payload)
        self._raise_http_status(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise AIUnavailableError("invalid_response", "AI response was not JSON") from exc
        text = _candidate_text(body)
        return _parse_content(text)

    def _send_http(self, method: str, url: str, json_body: dict[str, Any] | None = None) -> httpx.Response:
        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        owns_client = self._http_client is None
        try:
            try:
                kwargs: dict[str, Any] = {
                    "headers": self._headers(),
                    "timeout": self.timeout_seconds,
                }
                if json_body is not None:
                    kwargs["json"] = json_body
                return client.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                raise AIUnavailableError("timeout", "AI request timed out") from exc
            except httpx.HTTPError as exc:
                raise AIUnavailableError("provider_error", "AI request failed") from exc
        finally:
            if owns_client:
                client.close()

    def _raise_http_status(self, response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise AIUnavailableError("auth", "AI authentication failed")
        if response.status_code in _TRANSIENT_STATUS:
            reason = "rate_limit" if response.status_code == 429 else "provider_error"
            message = "AI rate limit exceeded" if reason == "rate_limit" else "AI request failed"
            raise AIUnavailableError(reason, message)
        if 400 <= response.status_code < 500:
            raise AIUnavailableError("invalid_response", "AI request failed")
        if response.status_code >= 500:
            raise AIUnavailableError("provider_error", "AI request failed")


def _candidate_text(body: dict[str, Any]) -> str:
    try:
        parts = body["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIUnavailableError("invalid_response", "AI response missing content") from exc
    chunks: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text)
    joined = "\n".join(chunks).strip()
    if not joined:
        raise AIUnavailableError("invalid_response", "AI response missing content")
    return joined
