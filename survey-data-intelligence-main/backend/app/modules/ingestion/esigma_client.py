from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from app.config import Settings, settings
from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.schemas import ESigmaPayload


def parse_esigma_payload(data: object) -> ESigmaPayload:
    if isinstance(data, list):
        payload: Any = {"records": data}
    elif isinstance(data, dict):
        payload = data
    else:
        raise IngestError("unsupported eSIGMA data structure", status_code=502)

    try:
        parsed = ESigmaPayload.model_validate(payload)
    except ValidationError as exc:
        raise IngestError("invalid eSIGMA API response", status_code=502) from exc

    if not all(isinstance(record, dict) for record in parsed.records):
        raise IngestError("unsupported eSIGMA data structure", status_code=502)
    return parsed


class ESigmaClient(Protocol):
    def fetch(self, path: str | None = None) -> ESigmaPayload: ...


class LiveESigmaClient:
    """Live eSIGMA adapter.

    Expected endpoint: ``ESIGMA_BASE_URL`` (optional path appended by ingest).
    Authentication: ``Authorization: Bearer <ESIGMA_API_KEY>`` and ``X-API-Key``.
    Request: HTTP GET, no request body. The official survey-office contract is not
    published in this repository; this adapter does not invent additional fields.
    Expected JSON: ``{"records": [ {survey fields...} ]}`` or a top-level list of
    record objects, then the existing standardizer → Parquet → SIRL pipeline.
    """
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        }

    def fetch(self, path: str | None = None) -> ESigmaPayload:
        if not self.base_url or not self.api_key:
            raise IngestError("eSIGMA is not configured", status_code=503)

        url = self.base_url
        if path:
            url = f"{self.base_url}/{path.lstrip('/')}"

        client = self._http_client or httpx.Client(timeout=self.timeout_seconds)
        owns_client = self._http_client is None
        try:
            response = client.get(url, headers=self._headers(), timeout=self.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise IngestError("eSIGMA request timed out", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise IngestError("eSIGMA request failed", status_code=502) from exc
        finally:
            if owns_client:
                client.close()

        if response.status_code in (401, 403):
            raise IngestError("eSIGMA authentication failed", status_code=401)
        if response.status_code >= 400:
            raise IngestError("eSIGMA request failed", status_code=502)

        try:
            data = response.json()
        except ValueError as exc:
            raise IngestError("malformed JSON from eSIGMA", status_code=502) from exc

        return parse_esigma_payload(data)


class MockESigmaClient:
    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def fetch(self, path: str | None = None) -> ESigmaPayload:
        if not self.fixture_path.is_file():
            raise IngestError("eSIGMA mock fixture is missing", status_code=500)
        try:
            data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise IngestError("malformed JSON from eSIGMA", status_code=502) from exc
        return parse_esigma_payload(data)


def build_esigma_client(app_settings: Settings | None = None) -> ESigmaClient:
    cfg = app_settings or settings
    if cfg.esigma_mock_mode:
        return MockESigmaClient(cfg.data_dir / "samples" / "esigma_sample.json")
    return LiveESigmaClient(
        base_url=cfg.esigma_base_url,
        api_key=cfg.esigma_api_key,
        timeout_seconds=cfg.esigma_timeout_seconds,
    )
