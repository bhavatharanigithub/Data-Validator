import httpx
import pytest

from app.modules.ingestion.errors import IngestError
from app.modules.ingestion.esigma_client import LiveESigmaClient, MockESigmaClient
from tests.conftest import SAMPLES


def test_mock_client_reads_fixture() -> None:
    payload = MockESigmaClient(SAMPLES / "esigma_sample.json").fetch()
    assert len(payload.records) == 4
    assert payload.records[0]["respondent_id"] == "R001"


def test_live_client_timeout() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = LiveESigmaClient(
        base_url="https://esigma.example.test/api",
        api_key="secret-token",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(IngestError) as exc:
        client.fetch()
    assert exc.value.status_code == 504
    assert "secret-token" not in exc.value.message


def test_live_client_authentication_failure() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "denied"})

    client = LiveESigmaClient(
        base_url="https://esigma.example.test/api",
        api_key="secret-token",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(IngestError) as exc:
        client.fetch()
    assert exc.value.status_code == 401
    assert "secret-token" not in exc.value.message


def test_live_client_malformed_json() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{not-json")

    client = LiveESigmaClient(
        base_url="https://esigma.example.test/api",
        api_key="secret-token",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(IngestError) as exc:
        client.fetch()
    assert exc.value.status_code == 502


def test_live_client_missing_configuration() -> None:
    client = LiveESigmaClient(base_url="", api_key="", timeout_seconds=1)
    with pytest.raises(IngestError) as exc:
        client.fetch()
    assert exc.value.status_code == 503


def test_live_client_success_parses_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "secret-token"
        return httpx.Response(200, json={"records": [{"respondent_id": "R001", "age": 34}]})

    client = LiveESigmaClient(
        base_url="https://esigma.example.test/api",
        api_key="secret-token",
        timeout_seconds=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    payload = client.fetch()
    assert payload.records[0]["respondent_id"] == "R001"
