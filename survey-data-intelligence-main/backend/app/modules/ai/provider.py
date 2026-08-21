from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.modules.ai.errors import AIUnavailableError

_JSON_FENCE = "```"
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_HEALTH_MAX_TOKENS = 16
_HEALTH_SKIP_COMPLETION = {404, 405, 501}


def _extract_json_text(content: str) -> str:
    text = content.strip()
    if not text.startswith(_JSON_FENCE):
        return text
    newline = text.find("\n")
    body = text[newline + 1 :] if newline != -1 else text.lstrip("`")
    if body.lstrip().startswith("json"):
        body = body.lstrip()[4:]
    fence_end = body.rfind(_JSON_FENCE)
    if fence_end != -1:
        body = body[:fence_end]
    return body.strip()


def _parse_content(content: str) -> dict[str, Any]:
    text = _extract_json_text(content)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIUnavailableError("invalid_response", "AI response was not JSON") from exc
    if not isinstance(parsed, dict):
        raise AIUnavailableError("invalid_response", "AI response was not a JSON object")
    return parsed


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        joined = "\n".join(parts).strip()
        if joined:
            return joined
    raise AIUnavailableError("invalid_response", "AI response missing content")


class ChatCompletionsProvider:
    """OpenAI-compatible chat completions client. Vendor-neutral."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.1,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def _api_root(self) -> str:
        root = self.base_url.rstrip("/")
        if root.endswith("/chat/completions"):
            return root[: -len("/chat/completions")].rstrip("/")
        return root

    def _endpoint(self) -> str:
        if self.base_url.rstrip("/").endswith("/chat/completions"):
            return self.base_url.rstrip("/")
        return f"{self._api_root()}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _sleep(self, attempt: int) -> None:
        if self.retry_backoff_seconds <= 0:
            return
        time.sleep(self.retry_backoff_seconds * (attempt + 1))

    def probe_health(self) -> None:
        """Lightweight authenticated availability check. Does not call complete_json."""
        models = self._send_http("GET", f"{self._api_root()}/models")
        if models.status_code in (401, 403):
            raise AIUnavailableError("auth", "AI authentication failed")
        auth_key = self._send_http("GET", f"{self._api_root()}/auth/key")
        if auth_key.status_code in (401, 403):
            raise AIUnavailableError("auth", "AI authentication failed")
        if auth_key.status_code == 200:
            return
        if models.status_code == 200 and auth_key.status_code in _HEALTH_SKIP_COMPLETION:
            return
        if models.status_code == 200:
            self._health_completion()
            return
        self._raise_http_status(models, allow_format_retry=False)

    def _health_completion(self) -> None:
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": _HEALTH_MAX_TOKENS,
            "messages": [{"role": "user", "content": "ping"}],
        }
        self._request(payload, allow_format_retry=False, parse_json_object=False)

    def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 20000,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        return self._request(payload, allow_format_retry=True)

    def _request(
        self,
        payload: dict[str, Any],
        allow_format_retry: bool,
        parse_json_object: bool = True,
    ) -> dict[str, Any]:
        last_error: AIUnavailableError | None = None
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                return self._send(
                    payload,
                    allow_format_retry=allow_format_retry,
                    parse_json_object=parse_json_object,
                )
            except AIUnavailableError as exc:
                last_error = exc
                if exc.reason not in {"timeout", "rate_limit", "provider_error"}:
                    raise
                if attempt >= self.max_retries:
                    raise
                self._sleep(attempt)
        assert last_error is not None
        raise last_error

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

    def _raise_http_status(self, response: httpx.Response, *, allow_format_retry: bool, payload: dict[str, Any] | None = None) -> None:
        if response.status_code in (401, 403):
            raise AIUnavailableError("auth", "AI authentication failed")
        if response.status_code in _TRANSIENT_STATUS:
            reason = "rate_limit" if response.status_code == 429 else "provider_error"
            message = "AI rate limit exceeded" if reason == "rate_limit" else "AI request failed"
            raise AIUnavailableError(reason, message)
        if (
            response.status_code == 400
            and allow_format_retry
            and payload is not None
            and "response_format" in payload
        ):
            return
        if 400 <= response.status_code < 500:
            raise AIUnavailableError("invalid_response", "AI request failed")
        if response.status_code >= 500:
            raise AIUnavailableError("provider_error", "AI request failed")

    def _send(
        self,
        payload: dict[str, Any],
        allow_format_retry: bool,
        parse_json_object: bool = True,
    ) -> dict[str, Any]:
        response = self._send_http("POST", self._endpoint(), json_body=payload)
        if (
            response.status_code == 400
            and allow_format_retry
            and "response_format" in payload
        ):
            retry_payload = dict(payload)
            retry_payload.pop("response_format", None)
            return self._send(retry_payload, allow_format_retry=False, parse_json_object=parse_json_object)
        self._raise_http_status(response, allow_format_retry=False, payload=payload)

        try:
            body = response.json()
        except ValueError as exc:
            raise AIUnavailableError("invalid_response", "AI response was not JSON") from exc
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailableError("invalid_response", "AI response missing content") from exc
        if not isinstance(message, dict):
            raise AIUnavailableError("invalid_response", "AI response missing content")
        if not parse_json_object:
            _message_content(message)
            return {}
        return _parse_content(_message_content(message))
